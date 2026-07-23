# Query Service

FastAPI service for querying **and** ingesting BrainKB knowledge graphs in the
graph database (Oxigraph), with W3C PROV-O provenance and team-owned
private/public spaces.

## Features

- [x] Structured logging (with correlation IDs)
- [x] JWT auth with per-endpoint scopes (`read` / `write` / `admin`)
- [x] SPARQL query endpoints (registered graphs, taxonomy, arbitrary query — admin only)
- [x] Bulk RDF ingestion into named graphs (file + raw), run as background jobs
- [x] Job tracking: live status, processing history, progress, crash recovery
- [x] Native **PROV-O provenance** in Oxigraph (ingestion / recovery activities)
- [x] **Triple-level delta tracking** — per-job delta graphs + query/compare endpoints
- [x] **Spaces** — owner-controlled, private/public containers of named graphs
- [x] **Search** — hybrid Postgres-locator + Oxigraph-data, access-filtered by space

## Auth & scopes

Tokens are issued by the JWT/token manager and validated here. Scope policy:

- **GET (reads)** → `read`
- **Mutations** (ingest, register/attach graph, recover, create/modify space) → `write`
- **Arbitrary SPARQL** (`/query/sparql/`) → `admin`
- **Public-space reads** → no token required (anonymous), see Spaces below
- `/register`, `/token` → public

Users may only act on their own `user_id` (enforced), and job-scoped endpoints are
owner-only.

## Endpoints (prefix `/api`)

### Query
- `GET /query/registered-named-graphs` — registry/catalog of graphs (visibility-filtered)
- `GET /query/taxonomy` — taxonomy view
- `GET /query/sparql/` — arbitrary SPARQL (**admin**)

### Ingestion & jobs
- `POST /insert/raw/knowledge-graph-triples` — ingest raw triples (background job)
- `POST /insert/files/knowledge-graph-triples` — ingest uploaded RDF files
- `POST /register-named-graph` — register a named graph
- `GET  /insert/jobs`, `GET /insert/user/jobs/detail` — job listing / detail
- `GET  /insert/jobs/check-recoverable`, `POST /insert/jobs/recover` — crash recovery

### Provenance (PROV-O, JSON-LD)
- `GET /provenance/job` — full bundle for one job
- `GET /provenance/named-graph` — ingestion/activity history of a graph
- `GET /provenance/delta` — exact triples a job added
- `GET /provenance/delta/history` — a graph's change history
- `GET /provenance/delta/compare` — diff two jobs' deltas

See [PROVENANCE_MODEL.md](PROVENANCE_MODEL.md).

### Spaces (private/public)
- `POST /spaces`, `GET /spaces`, `GET /spaces/{slug}`
- `PATCH /spaces/{slug}/visibility` — flip private/public (owner)
- `POST/DELETE /spaces/{slug}/members[/{member}]` — membership (owner)
- `POST /spaces/{slug}/graphs` — register + bind a graph to a space (owner/editor)
- `GET /spaces/{slug}/data` — read space RDF (public = anonymous)

**public** = readable by anyone, including unauthenticated clients; **private** =
members only; **write/ingest** = space owner/editor only. See
[SPACES_MODEL.md](SPACES_MODEL.md).

### Search
- `GET /search?q=…[&space={slug}][&limit&offset]` — full-text search, access-filtered.

Hybrid design: **Postgres** holds a full-text **locator index** (`graph_search_index`:
subject + text + named graph + owning space), populated at ingest. A search runs in
Postgres (fast, filtered by space visibility/membership), then the matched subjects'
triples are fetched from **Oxigraph** (the source of truth). Anonymous → public
spaces only; authenticated → public + own/member spaces (+ legacy). Pass `space` to
scope to one workspace, omit for a full search. Private data is never returned to
non-members — the filter is enforced in the locator query.

## Architecture notes

- **Postgres** holds identity/teams/enforcement (JWT users, jobs, spaces/members/graphs).
- **Oxigraph** holds all knowledge-graph data, PROV-O provenance, per-job delta
  graphs, and a mirror of each space manifest — the graph database is the source of
  truth for graph data and provenance.

### Acknowledgements
Special thanks to the authors of the resources below who helped with some best practices.
- Building Python Microservices with FastAPI
- Mastering-REST-APIs-with-FastAPI
- FastAPI official documentation

### License
[MIT](https://github.com/git/git-scm.com/blob/main/MIT-LICENSE.txt)
