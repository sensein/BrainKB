
# BrainKB

BrainKB is a cutting-edge knowledge base platform designed to empower scientists worldwide by providing tools for searching, exploring, and visualizing Neuroscience knowledge through knowledge graphs (KGs). Additionally, BrainKB offers advanced tools that enable scientists to contribute new information to the platform, ensuring it remains the premier destination for neuroscience research.


BrainKB serves as a knowledge base platform that provides scientists worldwide with tools for searching, exploring, and visualizing Neuroscience knowledge represented by knowledge graphs (KGs). Moreover, BrainKB provides cutting-edge tools that enable scientists to contribute new information (or knowledge) to the platform, ensuring it remains the go-to destination for all neuroscience-related research needs.


## Organization 
- [Ingest Service](ingest_service) Provides the service related to data ingestion and consumption using RabbitMQ. Not used currently.
- [GraphDB](graphdb) The docker compose configuration of GraphDB.
- [JWT User & Scope Manager](APItokenmanager) A toolkit to manage JWT users and their permissions for API endpoint access.
- [Query Service](query_service) Provides the functionalities for querying (and updating) the knowledge graphs from the graph database.
- [SPARQL Queries](sparql_queries) List of SPARQL queries tested or used in BrainKB.

## Running

### Quick Start

#### 1. Setup Environment variables

**Important**: Change default passwords in `.env` for security.

```bash
# Copy the environment template
cp env.template .env

# Edit .env with your configuration (make sure to change passwords!)
nano .env  # or use your preferred editor
```

#### 2. Start Services

**Recommended: Use the wrapper script (includes Ollama setup + pgAdmin config):**
```bash
chmod +x start_services.sh
./start_services.sh
```

#### 3. Access Services

Once started, services are accessible at:

- **API Token Manager (Django)**: `http://localhost:8000/`
  - Once you register JWT user you need to activate it using token manager. You can also assign permission.
- **Query Service (FastAPI)**: `http://localhost:8010/`
  - Supports querying **and** ingestion of the knowledge graphs.
  - Native W3C PROV-O provenance in the graph database, with triple-level delta
    tracking (per-job delta graphs + query/compare endpoints).
  - **Spaces**: team-owned, private/public containers of named graphs — keep data
    private to members or publish it publicly (anonymous read). Per-endpoint JWT
    scopes (`read`/`write`/`admin`); role-based authorization (see
    `query_service/RBAC_MODEL.md`). Accepts both SSO (RS256/JWKS) and legacy
    HS256 tokens.
  - **Search**: hybrid full-text search — Postgres locator index (aware of
    workspace + visibility) finds subjects, data is fetched from Oxigraph. Results
    are access-filtered (anonymous sees public only).
  - See `query_service/README.md`, `query_service/PROVENANCE_MODEL.md`, and
    `query_service/SPACES_MODEL.md` for details.
- **ML Service (FastAPI)**: `http://localhost:8007/`
  - Integrates StructSense (multi-agent NER + structured-resource extraction).
  - Hosts **SynthScholar** at `/api/synth-scholar/*` — PRISMA-guided literature
    review pipeline (search → screening → critical appraisal → synthesis,
    with SSE progress streaming and markdown / JSON / RDF exports). Reuses
    the unified `brainkb` Postgres database. See `env.template` for the
    optional API keys (OpenRouter, NCBI, Semantic Scholar, CORE).
- **Oxigraph SPARQL**: `http://localhost:7878/` (password protected) graph database
- **pgAdmin**: `http://localhost:5051/`
- **User management service (FastAPI)**: `http://localhost:8004`
  - Canonical **identity** service: user profiles, roles/RBAC, and OAuth sign-in
    (Globus / ORCID / GitHub). One canonical user; the credential row is linked to
    the profile (identity unification).
  - **Single sign-on** issuer (RS256 + JWKS): one login mints a refresh token,
    exchanged for narrow per-service access tokens (`aud=<service>`) that each
    service verifies via `/.well-known/jwks.json`. A token for one service can't
    be replayed against another. Legacy per-service HS256 tokens still work.
  - Admins can activate users and assign roles/groups. See
    `query_service/AUTH_UNIFICATION.md` and `usermanagement_service/README.md`.

## Authentication

BrainKB is moving to a single sign-on model — usermanagement is the sole token
issuer and each service verifies audience-scoped RS256 tokens against its JWKS,
while legacy per-service HS256 tokens remain accepted during migration. Web
sign-in returns both an access and a refresh token so the UI renews silently
(`USERMANAGEMENT_WEB_SESSION_TTL_MIN` / `USERMANAGEMENT_WEB_REFRESH_TTL_MIN`).
The full design, phases, and deployment env are in
[query_service/AUTH_UNIFICATION.md](query_service/AUTH_UNIFICATION.md).

**Please note:** for the Query Service and ML Service, you won’t see anything at their base URLs. To verify they are running, open their API docs at `http://localhost:8010/docs` and `http://localhost:8007/docs` respectively.

### Troubleshooting

If you encounter Docker mount errors or issues with file sharing, please refer to the [Troubleshooting section in LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md#troubleshooting).



## Documentation
Please refer to the BrainKB documentation below for additional information regarding BrainKB, its rationale, deployment instructions, and lessons learned.
- [https://sensein.group/brainkbdocs/](https://sensein.group/brainkbdocs/)

## Contact
- Tek Raj Chhetri <tekraj@mit.edu>

## License

This project is licensed under the [Apache License 2.0](https://opensource.org/license/apache-2-0).

**Copyright © 2024–Present Senseable Intelligence Group**

You may obtain a copy of the license at: [Apache License, Version 2.0](https://opensource.org/license/apache-2-0)


