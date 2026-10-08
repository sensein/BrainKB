# Ingestion integration tests

These tests exercise the real raw-RDF route, background ingestion worker,
PostgreSQL job records, Oxigraph registry/domain/delta graphs, SPARQL retrieval,
and PROV-O provenance writes. The fixture is entirely synthetic.

JWT signature and scope checks execute normally. User lookup and global-role
lookup are fixtures for the separate identity service; this suite does not test
password login, SSO, or global RBAC. Private-space membership filtering uses
real PostgreSQL tables. Search indexing is replaced with a test double.

The worker runs in the application event loop; no broker is required. A small
FastAPI app mounts the production insert/query routers without unrelated startup
services. The test reads literal job/space DDL from `core/main.py`'s startup
function and executes it in a unique schema. This avoids maintaining a second
copy of those tables. It is not a full-server startup or migration test.

## Reproduce on Linux or macOS

Requires Docker Compose, Python 3.12, and available local ports 55432/17878.
Run from `query_service` in a fresh virtual environment:

```sh
python -m pip install -r requirements.txt
python -m pip install pytest PyYAML requests python-dotenv
set -a
. integration_tests/test.env
set +a
docker compose -p brainkb-integration -f integration_tests/compose.yml up -d --wait
python -m pytest integration_tests -q --junitxml=integration-results.xml
docker compose -p brainkb-integration -f integration_tests/compose.yml down -v
```

On Windows use the same Compose commands and import `test.env` entries into the
PowerShell process environment before running pytest. Docker is required for
the real-service tests. Ordinary `core/tests` remains service-free.

Always run the final Compose cleanup command, including after a test failure.
The database name and loopback endpoints are checked before schema creation.
Never redirect this suite to production. Committed credentials are exclusively
for these disposable containers. Each test creates its own schema and graph,
then removes its own jobs, graph, registry entry, and job provenance. Generic
agent provenance can remain until the disposable container is removed.

## Assertions and failure diagnosis

- Successful ingestion preserves RDF terms, including typed/language literals.
- The domain graph and per-job delta match the fixture exactly.
- Provenance links the job activity to its user ID, target graph, and status.
- Malformed RDF results in an effective failed status and no domain triples.
- Unregistered graphs and a different submitted user ID create no job.
- A private graph appears for its owner but is hidden from a non-member.

Job polling has a 30-second deadline; provenance polling has a separate
10-second deadline because provenance is best-effort and follows job completion.
Tests assert it is present in this healthy environment, not that every successful
production job guarantees provenance. Individual HTTP requests have deadlines.
Pytest reports job/graph/status details and captures application logging on
failure. CI uploads JUnit results and container logs, and repeats the suite to
check isolation. The runner destroys the service containers afterward.

CI also performs three controlled fault experiments on the successful test:
disable the delta merge, redirect the merge to another test graph, and disable
the provenance write. Each must produce an assertion failure. Run one locally
with `BRAINKB_INTEGRATION_FAULT=skip-merge python -m pytest integration_tests -q -k round_trip`.
Fault patches exist only in the test process and never modify production code.

This does not assert rollback of partially ingested multi-file jobs, recovery
after crashes, concurrent-ingestion behavior, or scientific truth of RDF claims.
Those require separate contracts. For a small synthetic fixture, startup and
dependency installation should dominate runtime; see the workflow for measured
timings rather than treating a fixed estimate as a guarantee.
