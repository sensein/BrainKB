"""Small, service-free checks for the ingestion and graph-listing API contract."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("QUERY_SERVICE_JWT_SECRET_KEY", "brainkb-local-test-secret")

import httpx
from fastapi import FastAPI
from jose import jwt

from core import security
from core.routers import insert, query


USER = {"id": 7, "email": "researcher@example.org"}
GRAPH = "https://example.org/graphs/synthetic-brain"
TRIPLES = (
    "@prefix ex: <https://example.org/brain/> .\n"
    'ex:region a ex:BrainRegion ; ex:label "Synthetic region"@en ; '
    'ex:count "2"^^<http://www.w3.org/2001/XMLSchema#integer> .\n'
)


class IngestionQueryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.app = FastAPI()
        self.app.include_router(insert.router, prefix="/api")
        self.app.include_router(query.router, prefix="/api")
        self.transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.token = jwt.encode(
            {"sub": USER["email"], "scopes": ["read", "write"]},
            security.SECRET_KEY,
            algorithm=security.ALGORITHM,
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    async def test_raw_ingestion_records_job_and_preserves_payload(self):
        with (
            patch.object(insert, "JOB_BASE_DIR", self.temp_dir.name),
            patch.object(security, "get_user", new_callable=AsyncMock, return_value=USER),
            patch.object(insert, "check_named_graph_exists", new_callable=AsyncMock, return_value=True),
            patch.object(insert.rbac, "has_capability", new_callable=AsyncMock, return_value=True),
            patch.object(insert._spaces, "get_space_for_graph", new_callable=AsyncMock, return_value=None),
            patch.object(insert, "get_oxigraph_endpoint", return_value="http://unused.test/store"),
            patch.object(insert, "create_job", new_callable=AsyncMock) as create_job,
            patch.object(insert, "run_ingest_job", new_callable=AsyncMock) as run_ingest_job,
        ):
            response = await self.client.post(
                "/api/insert/raw/knowledge-graph-triples",
                params={"user_id": str(USER["id"]), "named_graph_iri": GRAPH},
                content=TRIPLES,
                headers={**self.headers, "Content-Type": "text/plain"},
            )
            await asyncio.sleep(0)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["detected_format"], "ttl")
        self.assertEqual(body["named_graph_iri"], GRAPH)
        self.assertEqual(body["size_bytes"], len(TRIPLES.encode("utf-8")))
        self.assertEqual(body["status_url"], f"/api/query/jobs?job_id={body['job_id']}&user_id=7")
        saved = Path(self.temp_dir.name, str(USER["id"]), f"job_{body['job_id']}", "raw_payload.ttl")
        self.assertEqual(saved.read_text(encoding="utf-8"), TRIPLES)
        self.assertEqual(create_job.await_args.kwargs["graph"], GRAPH)
        self.assertEqual(create_job.await_args.kwargs["status"], "pending")
        run_ingest_job.assert_awaited_once_with(body["job_id"], 1, str(USER["id"]), False)

    async def test_unregistered_graph_is_rejected_before_job_creation(self):
        with (
            patch.object(security, "get_user", new_callable=AsyncMock, return_value=USER),
            patch.object(insert, "check_named_graph_exists", new_callable=AsyncMock, return_value=False),
            patch.object(insert, "create_job", new_callable=AsyncMock) as create_job,
        ):
            response = await self.client.post(
                "/api/insert/raw/knowledge-graph-triples",
                params={"user_id": str(USER["id"]), "named_graph_iri": GRAPH},
                content=TRIPLES,
                headers={**self.headers, "Content-Type": "text/plain"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["named_graph_iri"], GRAPH)
        create_job.assert_not_awaited()
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [])

    async def test_user_cannot_submit_under_another_identity(self):
        with (
            patch.object(security, "get_user", new_callable=AsyncMock, return_value=USER),
            patch.object(insert, "check_named_graph_exists", new_callable=AsyncMock) as graph_exists,
        ):
            response = await self.client.post(
                "/api/insert/raw/knowledge-graph-triples",
                params={"user_id": "someone-else", "named_graph_iri": GRAPH},
                content=TRIPLES,
                headers={**self.headers, "Content-Type": "text/plain"},
            )

        self.assertEqual(response.status_code, 403)
        graph_exists.assert_not_awaited()

    async def test_private_graph_is_hidden_from_another_user(self):
        bindings = [
            {
                "graph": {"value": graph},
                "description": {"value": "Synthetic test graph"},
                "registered_at": {"value": "2026-01-01T00:00:00Z"},
            }
            for graph in (GRAPH, "https://example.org/graphs/private")
        ]
        with (
            patch.object(security, "get_user", new_callable=AsyncMock, return_value=USER),
            patch.object(
                query,
                "fetch_data_gdb_async",
                new_callable=AsyncMock,
                return_value={"status": "success", "message": {"results": {"bindings": bindings}}},
            ),
            patch("core.spaces.hidden_graphs_for", new_callable=AsyncMock, return_value={"https://example.org/graphs/private"}) as hidden,
        ):
            response = await self.client.get("/api/query/registered-named-graphs", headers=self.headers)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {GRAPH})
        hidden.assert_awaited_once_with(USER["email"])
