"""Real PostgreSQL/Oxigraph tests; identity and global roles are test fixtures."""

import ast
import asyncio
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BRAINKB_INTEGRATION") != "1", reason="requires disposable services"
)

os.environ.setdefault("QUERY_SERVICE_JWT_SECRET_KEY", "brainkb-local-test-secret")

import asyncpg
import httpx
from fastapi import FastAPI
from jose import jwt
from rdflib import Graph, Literal, RDF, URIRef
from rdflib.compare import isomorphic

from core import database, security, spaces
from core.provenance import (
    BRAINKB, PROV, PROVENANCE_GRAPH, activity_ref, agent_ref, delta_graph_for,
)
from core.routers import insert, query
from core.shared import get_oxigraph_endpoint

FIXTURE = '''@prefix ex: <https://example.org/brainkb-test/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:region a ex:BrainRegion ; ex:label "Synthetic region"@en .
ex:cell a ex:CellType ; ex:locatedIn ex:region ; ex:count "2"^^xsd:integer .
'''


def job_schema_statements():
    """Use the application's literal startup DDL without importing its server.

    Only the tables exercised here are initialized. There is no separate copy
    of the job schema to drift from the application.
    """
    source = Path(__file__).parents[1] / "core" / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    startup = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                   and n.name == "startup_event")
    tables = {"jobs", "job_results", "job_processing_log", "spaces",
              "space_members", "space_graphs"}
    statements = []
    for node in ast.walk(startup):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "execute" or not node.args:
            continue
        arg = node.args[0]
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            continue
        words = arg.value.split()
        if words[:5] == ["CREATE", "TABLE", "IF", "NOT", "EXISTS"] and words[5] in tables:
            statements.append((node.lineno, arg.value))
        elif words[:2] == ["ALTER", "TABLE"] and words[2] in tables:
            statements.append((node.lineno, arg.value))
    assert sum("CREATE TABLE" in sql for _, sql in statements) == len(tables)
    return [sql for _, sql in sorted(statements)]


class IngestionRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIn(database.DB_SETTINGS["host"], ("127.0.0.1", "localhost"))
        self.assertEqual(database.DB_SETTINGS["database"], "brainkb_integration")
        self.assertIn(get_oxigraph_endpoint(), ("http://127.0.0.1:17878/store",
                                              "http://localhost:17878/store"))
        # Dedicated schema confines relational cleanup to this run.
        self.schema = "integration_" + uuid.uuid4().hex
        self.graph = "https://example.org/brainkb-test/graphs/" + uuid.uuid4().hex + "/"
        self.jobs = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pool = await asyncpg.create_pool(
            min_size=1, max_size=4, **database.DB_SETTINGS,
            server_settings={"search_path": self.schema},
        )
        self.addAsyncCleanup(self.cleanup_services)
        async with self.pool.acquire() as conn:
            await conn.execute(f'CREATE SCHEMA "{self.schema}"')
            for sql in job_schema_statements():
                await conn.execute(sql)
        self.pool_patch = patch.object(database, "pool", self.pool)
        self.pool_patch.start()
        self.addCleanup(self.pool_patch.stop)
        self.dir_patch = patch.object(insert, "JOB_BASE_DIR", self.temp.name)
        self.dir_patch.start()
        self.addCleanup(self.dir_patch.stop)
        # JWT parsing/scope enforcement stays real. User lookup and global-role
        # lookup stand in for the separate Django identity service.
        self.user = {"id": 7, "email": "researcher@example.org"}
        self.identity = patch.object(security, "get_user", new_callable=AsyncMock,
                                     return_value=self.user)
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.role = patch.object(insert.rbac, "has_capability", new_callable=AsyncMock,
                                 return_value=True)
        self.role.start()
        self.addCleanup(self.role.stop)
        # Search indexing is outside this test's persistence/provenance scope.
        self.index = patch("core.indexing.enqueue_ingest", new_callable=AsyncMock)
        self.index.start()
        self.addCleanup(self.index.stop)
        # Opt-in fault experiments prove the round-trip assertions detect missing
        # writes. These overrides affect only this test process.
        fault = os.getenv("BRAINKB_INTEGRATION_FAULT")
        if fault == "skip-merge":
            fault_patch = patch.object(insert, "merge_delta_into_target", new_callable=AsyncMock)
        elif fault == "skip-provenance":
            fault_patch = patch.object(insert, "write_provenance", new_callable=AsyncMock)
        elif fault == "wrong-graph":
            merge = insert.merge_delta_into_target
            async def wrong_graph(delta, target):
                return await merge(delta, target + "wrong/")
            fault_patch = patch.object(insert, "merge_delta_into_target", side_effect=wrong_graph)
        elif fault:
            raise ValueError(f"Unknown test fault: {fault}")
        else:
            fault_patch = None
        if fault_patch:
            fault_patch.start()
            self.addCleanup(fault_patch.stop)
        insert._ingest_semaphore = None
        self.app = FastAPI()
        self.app.include_router(insert.router, prefix="/api")
        self.app.include_router(query.router, prefix="/api")
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                        base_url="http://test", timeout=10)
        self.addAsyncCleanup(self.client.aclose)
        token = jwt.encode({"sub": self.user["email"], "scopes": ["read", "write", "admin"]},
                           security.SECRET_KEY, algorithm=security.ALGORITHM)
        self.headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=10) as client:
            ready = await client.get(get_oxigraph_endpoint().replace("/store", "/query"),
                                     params={"query": "ASK {}"})
            ready.raise_for_status()
        response = await self.client.post("/api/register-named-graph", headers=self.headers,
            json={"named_graph_url": self.graph, "description": "Synthetic integration fixture"})
        self.assertEqual(response.status_code, 200, response.text)

    async def cleanup_services(self):
        # Cancel only this test's outstanding jobs before removing their schema.
        for job in self.jobs:
            task = insert._running_job_tasks.get(job)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        async with httpx.AsyncClient(timeout=10) as client:
            for graph in [self.graph, self.graph + "wrong/"] + [delta_graph_for(job) for job in self.jobs]:
                response = await client.delete(get_oxigraph_endpoint(), params={"graph": graph})
                if response.status_code not in (200, 204, 404):
                    response.raise_for_status()
            # Delete only the registry entry and provenance minted for this run.
            prefixes = [f"https://brainkb.org/prov/{kind}/{job}"
                        for job in self.jobs for kind in ("activity", "bundle", "file", "delta")]
            update = f"DELETE WHERE {{ GRAPH <https://brainkb.org/metadata/named-graph> {{ <{self.graph}> ?p ?o }} }};"
            for prefix in prefixes:
                update += f'''DELETE {{ GRAPH <{PROVENANCE_GRAPH}> {{ ?s ?p ?o }} }}
WHERE {{ GRAPH <{PROVENANCE_GRAPH}> {{ ?s ?p ?o FILTER(STRSTARTS(STR(?s), "{prefix}")) }} }};'''
            response = await client.post(get_oxigraph_endpoint().replace("/store", "/update"),
                content=update, headers={"Content-Type": "application/sparql-update"})
            response.raise_for_status()
        async with self.pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        await self.pool.close()

    async def submit(self, payload=FIXTURE, graph=None, user_id="7"):
        response = await self.client.post("/api/insert/raw/knowledge-graph-triples",
            params={"user_id": user_id, "named_graph_iri": graph or self.graph},
            content=payload, headers={**self.headers, "Content-Type": "text/plain"})
        if response.status_code == 200:
            self.jobs.append(response.json()["job_id"])
        return response

    async def wait_for_job(self, job_id):
        deadline = time.monotonic() + 30
        last = None
        while time.monotonic() < deadline:
            response = await self.client.get("/api/insert/user/jobs/detail",
                params={"job_id": job_id, "user_id": "7"}, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            last = response.json()
            if last["status"] in ("done", "failed", "partial", "error"):
                return last
            await asyncio.sleep(0.1)
        self.fail(f"Job {job_id} timed out for graph {self.graph}: {last}")

    async def stored_graph(self, graph):
        # Retrieval passes through the real query route and SPARQL client.
        response = await self.client.get("/api/query/sparql/", headers=self.headers,
            params={"sparql_query": f"SELECT ?s ?p ?o WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "success", body)
        result = Graph()
        for row in body["message"]["results"]["bindings"]:
            terms = []
            for key in ("s", "p", "o"):
                item = row[key]
                if item["type"] == "uri":
                    terms.append(URIRef(item["value"]))
                else:
                    terms.append(Literal(item["value"], lang=item.get("xml:lang"),
                                         datatype=item.get("datatype")))
            result.add(tuple(terms))
        return result

    async def test_round_trip_preserves_rdf_and_records_provenance(self):
        response = await self.submit()
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()["job_id"]
        status = await self.wait_for_job(job)
        self.assertEqual(status["status"], "done", status)
        self.assertEqual((status["success_count"], status["fail_count"]), (1, 0))
        expected = Graph().parse(data=FIXTURE, format="turtle")
        deadline = time.monotonic() + 10
        while True:
            actual = await self.stored_graph(self.graph)
            provenance = await self.stored_graph(PROVENANCE_GRAPH)
            if (activity_ref(job), PROV.wasAssociatedWith, agent_ref("7")) in provenance:
                break
            if time.monotonic() >= deadline:
                self.fail(f"Missing provenance for job {job}, graph {self.graph}")
            await asyncio.sleep(0.1)
        self.assertTrue(isomorphic(actual, expected), actual.serialize(format="turtle"))
        self.assertIn((activity_ref(job), RDF.type, BRAINKB.IngestionActivity), provenance)
        self.assertIn((activity_ref(job), BRAINKB.targetGraph, URIRef(self.graph)), provenance)
        self.assertIn((activity_ref(job), BRAINKB.jobStatus, Literal("done")), provenance)
        self.assertTrue(isomorphic(await self.stored_graph(delta_graph_for(job)), expected))

    async def test_malformed_rdf_reports_failure_without_domain_triples(self):
        response = await self.submit("@prefix ex: <https://example.org/> . ex:a ex:b [")
        self.assertEqual(response.status_code, 200, response.text)
        status = await self.wait_for_job(response.json()["job_id"])
        self.assertEqual(status["status"], "failed", status)
        self.assertEqual(status["fail_count"], 1)
        self.assertEqual(len(await self.stored_graph(self.graph)), 0)

    async def test_unregistered_graph_and_wrong_identity_do_not_create_jobs(self):
        response = await self.submit(graph=self.graph + "unregistered/")
        self.assertEqual(response.status_code, 400, response.text)
        response = await self.submit(user_id="8")
        self.assertEqual(response.status_code, 403, response.text)
        async with self.pool.acquire() as conn:
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM jobs"), 0)

    async def test_private_graph_is_hidden_with_real_space_membership(self):
        space = await spaces.create_space(slug=self.schema, name="Synthetic private space",
                                          description="Synthetic fixture", owner=self.user["email"])
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO space_graphs(space_id,named_graph_iri) VALUES($1,$2)",
                               space["space_id"], self.graph)
        response = await self.client.get("/api/query/registered-named-graphs", headers=self.headers)
        self.assertIn(self.graph, response.json())
        with patch.object(security, "get_user", new_callable=AsyncMock,
                          return_value={"id": 8, "email": "other@example.org"}):
            response = await self.client.get("/api/query/registered-named-graphs", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(self.graph, response.json())
