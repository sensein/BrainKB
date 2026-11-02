"""Stored queries: only declared, validated parameters reach the SPARQL; the graph
must belong to a space the caller may read; anonymous results are cached only for
spaces anyone may read. Offline fakes for the space store and Oxigraph."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from ..routers import spaces as router
from ..stored_queries import STORED_QUERIES, MAX_IRI_LIST

G = "https://brainkb.org/graph/bican-basal-ganglia/"
T = "urn:bkbit:abc123"
PUB = {"space_id": "p", "slug": "bg", "visibility": "public", "space_type": "team"}
PRIV = {"space_id": "q", "slug": "lab", "visibility": "private", "space_type": "team"}
PRIV_G = "https://brainkb.org/graph/lab/"


def run(coro):
    return asyncio.run(coro)


class Req:
    def __init__(self, **params):
        self.query_params = params


def patched(fn, member_role=None, rules_ok=True, private_cap=True):
    calls = {"sparql": []}

    async def space_for_graph(g):
        return {G: dict(PUB), PRIV_G: dict(PRIV)}.get(g)

    async def role(_sid, member):
        return member_role if member else None

    async def permitted(_space, _action, _member):
        return rules_ok

    async def has_cap(member, _cap):
        return bool(member) and private_cap

    async def fetch(sparql):
        calls["sparql"].append(sparql)
        return {"status": "success", "message": {"head": {"vars": ["x"]}, "results": {"bindings": [{"x": {"value": "1"}}]}}}

    router._stored_cache.clear()
    with patch.object(router.sp, "get_space_for_graph", space_for_graph), \
            patch.object(router.sp, "member_role", role), \
            patch.object(router.sp, "space_action_permitted", permitted), \
            patch.object(router.rbac, "has_capability", has_cap), \
            patch.object(router, "fetch_data_gdb_async", fetch):
        out = run(fn())
    return out, calls


class StoredQuerySparqlTests(unittest.TestCase):
    def test_every_query_is_capped_and_declares_its_params(self):
        for name, q in STORED_QUERIES.items():
            self.assertTrue(q["query"].rstrip().endswith(f"LIMIT {q['limit']}"), name)
            self.assertIn("<{{graph}}>", q["query"], name)
            for p, kind in q["params"].items():
                if kind == "iri":  # never bare, so a validated IRI can't end a pattern early
                    self.assertEqual(q["query"].count("{{%s}}" % p), q["query"].count("<{{%s}}>" % p), (name, p))

    def test_fills_graph_and_iri(self):
        graph, sparql, limit = router._stored_sparql("taxonomy.cells", {"graph": G, "taxon": T})
        self.assertEqual(graph, G)
        self.assertIn(f"GRAPH <{G}>", sparql)
        self.assertIn(f"epi:about <{T}>", sparql)
        self.assertNotIn("{{", sparql)
        self.assertEqual(limit, STORED_QUERIES["taxonomy.cells"]["limit"])

    def test_iri_list(self):
        _, sparql, _ = router._stored_sparql("taxonomy.epigenome_tracks", {"graph": G, "summaries": f"{T} urn:bkbit:def,urn:bkbit:ghi"})
        self.assertIn(f"VALUES ?summary {{ <{T}> <urn:bkbit:def> <urn:bkbit:ghi> }}", sparql)

    def test_rejects_breaking_out_of_an_iri(self):
        for bad in [T + "> } DELETE WHERE { ?s ?p ?o } #", "urn:a b", 'urn:a"', "urn:a{x}", "no-scheme", "", "urn:a\\x"]:
            with self.assertRaises(HTTPException) as e:
                router._stored_sparql("taxonomy.cells", {"graph": G, "taxon": bad})
            self.assertEqual(e.exception.status_code, 400, bad)
        with self.assertRaises(HTTPException):
            router._stored_sparql("taxonomy.taxa", {"graph": "https://x/> } SELECT * {"})

    def test_rejects_unknown_missing_and_too_many(self):
        cases = [("nope", {"graph": G}, 404), ("taxonomy.taxa", {"graph": G, "taxon": T}, 400),
                 ("taxonomy.cells", {"graph": G}, 400), ("taxonomy.taxa", {}, 400),
                 ("taxonomy.epigenome_tracks", {"graph": G, "summaries": " ".join([T] * (MAX_IRI_LIST + 1))}, 400)]
        for name, args, code in cases:
            with self.assertRaises(HTTPException) as e:
                router._stored_sparql(name, args)
            self.assertEqual(e.exception.status_code, code, (name, args))


class StoredQueryAccessTests(unittest.TestCase):
    def test_anonymous_reads_a_public_space_and_is_cached(self):
        async def go():
            a = await router.run_stored_query("taxonomy.taxa", Req(graph=G), None)
            b = await router.run_stored_query("taxonomy.taxa", Req(graph=G), None)
            return a, b
        (a, b), calls = patched(go)
        self.assertEqual(a["status"], "success")
        self.assertFalse(a["capped"])
        self.assertIs(a, b)
        self.assertEqual(len(calls["sparql"]), 1)

    def test_anonymous_cannot_read_a_private_space(self):
        async def go():
            await router.run_stored_query("taxonomy.taxa", Req(graph=PRIV_G), None)
        with self.assertRaises(HTTPException) as e:
            patched(go)
        self.assertEqual(e.exception.status_code, 403)

    def test_member_reads_a_private_space_without_caching(self):
        user = {"email": "m@x.org"}
        async def go():
            await router.run_stored_query("taxonomy.taxa", Req(graph=PRIV_G), user)
            await router.run_stored_query("taxonomy.taxa", Req(graph=PRIV_G), user)
        _, calls = patched(go, member_role="viewer")
        self.assertEqual(len(calls["sparql"]), 2)
        self.assertEqual(router._stored_cache, {})

    def test_space_read_rule_applies(self):
        async def go():
            await router.run_stored_query("taxonomy.taxa", Req(graph=G), None)
        with self.assertRaises(HTTPException) as e:
            patched(go, rules_ok=False)
        self.assertEqual(e.exception.status_code, 403)

    def test_graph_outside_any_space(self):
        async def go():
            await router.run_stored_query("taxonomy.taxa", Req(graph="https://brainkb.org/graph/other/"), None)
        with self.assertRaises(HTTPException) as e:
            patched(go)
        self.assertEqual(e.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
