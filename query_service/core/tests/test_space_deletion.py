"""Space deletion (SuperAdmin only). Offline: the triplestore, Postgres and the
provenance writer are fakes; the tests check what would be sent to each and in
which order."""
import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi import HTTPException
from rdflib import URIRef
from rdflib.namespace import PROV

from .. import spaces as sp
from ..routers import spaces as router

SPACE = {
    "space_id": "sp-1", "slug": "test-resource-acticity", "name": "Test resource acticity",
    "owner": "owner@example.org", "visibility": "public",
    "iri": sp.space_iri("test-resource-acticity"),
    "members": [{"member": "owner@example.org", "role": "owner"}],
    "graphs": ["https://brainkb.org/graph/test-resource-acticity/"],
}
DELTA = "https://brainkb.org/provenance/delta/job-42"


class FakeConn:
    def __init__(self, log):
        self.log = log

    @asynccontextmanager
    async def transaction(self):
        self.log.append(("begin",))
        yield
        self.log.append(("commit",))

    async def fetchval(self, sql, *args):
        self.log.append(("fetchval", sql, args))
        return 7

    async def execute(self, sql, *args):
        self.log.append(("execute", sql, args))


def fake_db(log):
    @asynccontextmanager
    async def conn():
        yield FakeConn(log)
    return conn


def run(coro):
    return asyncio.run(coro)


class DeleteSpaceTests(unittest.TestCase):
    def setUp(self):
        self.log, self.updates, self.prov = [], [], []

        async def fetch(_query):
            return {"status": "success", "message": {"results": {"bindings": [{"delta": {"value": DELTA}}]}}}

        async def update(text):
            self.log.append(("sparql",))
            self.updates.append(text)

        async def write(graph):
            self.prov.append(graph)
            return True
        self.patches = [
            patch("core.graph_database_connection_manager.fetch_data_gdb_async", fetch),
            patch.object(sp, "_sparql_update", update),
            patch.object(sp, "get_db_connection", fake_db(self.log)),
            patch("core.provenance.write_provenance", write),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_triplestore_first_then_postgres_then_provenance(self):
        result = run(sp.delete_space(dict(SPACE), "admin@example.org"))
        [update] = self.updates
        graph = SPACE["graphs"][0]
        self.assertIn(f"DROP SILENT GRAPH <{graph}>", update)
        self.assertIn(f"DROP SILENT GRAPH <{DELTA}>", update)
        self.assertIn(f"GRAPH <{sp.NAMED_GRAPH_REGISTRY}> {{ <{graph}> ?p ?o }}", update)
        self.assertIn(f"GRAPH <{sp.SPACES_METADATA_GRAPH}> {{ <{SPACE['iri']}> ?p ?o }}", update)
        kinds = [entry[0] for entry in self.log]
        self.assertEqual(kinds, ["sparql", "begin", "fetchval", "execute", "commit"])
        self.assertIn("graph_search_index", self.log[2][1])
        self.assertEqual(self.log[3][1], "DELETE FROM spaces WHERE space_id = $1")
        self.assertEqual(result["dropped_graphs"], SPACE["graphs"])
        self.assertEqual(result["dropped_delta_graphs"], [DELTA])
        self.assertEqual(result["search_index_rows_removed"], 7)
        self.assertTrue(result["provenance_recorded"])
        [g] = self.prov
        invalidated = set(g.objects(None, PROV.invalidated))
        self.assertEqual(invalidated, {URIRef(SPACE["iri"]), URIRef(graph), URIRef(DELTA)})
        self.assertTrue(list(g.subjects(PROV.wasAssociatedWith, None)))

    def test_triplestore_failure_leaves_postgres_untouched(self):
        async def failing(_text):
            raise sp.SpaceDeletionError("SPARQL update failed (HTTP 500)")
        with patch.object(sp, "_sparql_update", failing):
            with self.assertRaises(sp.SpaceDeletionError):
                run(sp.delete_space(dict(SPACE), "admin@example.org"))
        self.assertEqual(self.log, [])
        self.assertEqual(self.prov, [])

    def test_failed_delta_lookup_aborts_before_anything_is_deleted(self):
        async def broken(_query):
            return {"status": "fail", "message": "timeout"}
        with patch("core.graph_database_connection_manager.fetch_data_gdb_async", broken):
            with self.assertRaises(sp.SpaceDeletionError):
                run(sp.delete_space(dict(SPACE), "admin@example.org"))
        self.assertEqual((self.updates, self.log), ([], []))

    def test_unsafe_graph_iri_is_refused(self):
        bad = dict(SPACE, graphs=["https://x.org/g> } ; DROP ALL ; { <a"])
        with self.assertRaises(sp.SpaceDeletionError):
            run(sp.delete_space(bad, "admin@example.org"))
        self.assertEqual((self.updates, self.log), ([], []))


class EndpointTests(unittest.TestCase):
    USER = {"email": "someone@example.org", "id": 1}

    def call(self, *, superadmin, confirm, space=SPACE):
        async def is_superadmin(_email):
            return superadmin

        async def get_space(_slug):
            return dict(space) if space else None

        async def delete(space_, by):
            return {"deleted": True, "slug": space_["slug"], "deleted_by": by,
                    "dropped_graphs": space_["graphs"], "dropped_delta_graphs": []}
        with patch.object(router.rbac, "is_superadmin", is_superadmin), \
                patch.object(router.sp, "get_space", get_space), \
                patch.object(router.sp, "delete_space", delete):
            return run(router.delete_space(SPACE["slug"], self.USER, confirm))

    def test_only_superadmin(self):
        with self.assertRaises(HTTPException) as e:
            self.call(superadmin=False, confirm=SPACE["slug"])
        self.assertEqual(e.exception.status_code, 403)

    def test_confirm_must_equal_slug(self):
        with self.assertRaises(HTTPException) as e:
            self.call(superadmin=True, confirm="something-else")
        self.assertEqual(e.exception.status_code, 400)

    def test_missing_space_is_404(self):
        resp = self.call(superadmin=True, confirm=SPACE["slug"], space=None)
        self.assertEqual(resp.status_code, 404)

    def test_superadmin_deletes(self):
        out = self.call(superadmin=True, confirm=SPACE["slug"])
        self.assertTrue(out["deleted"])
        self.assertEqual(out["deleted_by"], "someone@example.org")

    def test_triplestore_failure_is_502_and_says_retry_is_safe(self):
        async def failing(_s, _by):
            raise sp.SpaceDeletionError("SPARQL update failed (HTTP 500)")

        async def yes(_e):
            return True

        async def get_space(_slug):
            return dict(SPACE)
        with patch.object(router.rbac, "is_superadmin", yes), \
                patch.object(router.sp, "get_space", get_space), \
                patch.object(router.sp, "delete_space", failing):
            with self.assertRaises(HTTPException) as e:
                run(router.delete_space(SPACE["slug"], self.USER, SPACE["slug"]))
        self.assertEqual(e.exception.status_code, 502)
        self.assertIn("safe to retry", e.exception.detail)


if __name__ == "__main__":
    unittest.main()
