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

Two token schemes are accepted (see `AUTH_UNIFICATION.md`):

- **Single sign-on (RS256)** — access tokens minted by usermanagement (the single
  issuer) and verified here against its published **JWKS**; the token's `aud` must
  equal `query_service`, so a token minted for another service is rejected
  (containment). Configure with `QUERY_SERVICE_SSO_JWKS_URL` /
  `QUERY_SERVICE_SSO_ISSUER` / `QUERY_SERVICE_SSO_AUDIENCE`.
- **Legacy HS256** — this service's own password login at **`/api/login`**
  (`/api/token` is a deprecated alias), signed with its own secret. Still accepted
  during migration; both schemes work side by side.

Scope policy (same for either scheme):

- **GET (reads)** → `read`
- **Mutations** (ingest, register/attach graph, recover, create/modify space) → `write`
- **Arbitrary SPARQL** (`/query/sparql/`) → `admin`
- **Public-space reads** → no token required (anonymous), see Spaces below
- `/login` (and deprecated alias `/token`) → public

**Onboarding is via Globus/ORCID/GitHub sign-in — there is no self-registration.**
`POST /register` is **disabled** (returns 405). A user's profile + default role are
auto-created/linked on first OAuth login (usermanagement). Authorization is
role-based (see `RBAC_MODEL.md`) and read from the DB, not just the token.

Users may only act on their own `user_id` (enforced), and job-scoped endpoints are
owner-only.

## Capabilities & roles (RBAC)

Two independent layers apply to every mutating call:

1. **JWT scope** (`read`/`write`/`admin`) — API-access gate at the endpoint.
2. **Capability** — *who is allowed to do what*, derived from the user's **role(s)**
   (read from the DB, not just the token) plus any admin-delegated grants.

### Capabilities — what each one means

| Capability | Meaning |
|---|---|
| `create_private_space` | Create your own individual/private space |
| `create_team_space` | Create a **team** (shared) space |
| `manage_team_space` | Manage a team space's members/visibility/graphs/rules — **only for team spaces you own or are assigned to** (a member of), *not* all team spaces (Admin/SuperAdmin manage all) |
| `ingest` | Ingest data into a graph — **also** needs per-space write (owner/editor membership **or** a space write access rule; see below) |
| `recover` | Recover stuck/errored ingest jobs |
| `read_private` | Read non-public content you're a member of |
| `sparql_admin` | Run arbitrary SPARQL (`/query/sparql/`) |
| `grant` | Grant/revoke capabilities to other users |

### Which roles get which capabilities

| Role tier | Capabilities |
|---|---|
| **SuperAdmin / Admin** | **all** of the above |
| **Write roles** — Curator, Lab Member, Submitter, Annotator, Mapper, Knowledge Contributor | `create_private_space`, `ingest`, `recover`, `read_private` |
| **Any other active role** (Reviewer, Validator, Moderator, …) | `read_private` |
| **No role** | public reads only — no create/ingest/private read |

**Delegation (Admin/SuperAdmin only):** the *grantable* capabilities —
`create_private_space`, `create_team_space`, `manage_team_space`, `ingest`,
`recover`, `read_private` — can be granted to either:

- **an individual** — `POST /admin/capabilities/grant` `{member, capability}`
  (revoke: `/admin/capabilities/revoke`); or
- **a whole role/group** — `POST /admin/capabilities/grant-role`
  `{role, capability}` (revoke: `/admin/capabilities/revoke-role`; inspect:
  `GET /admin/capabilities/role?role=`). This gives every member of a role/group
  (including a custom group like `uk_collaborator`) the capability.

`GET /admin/capabilities/available` lists the full catalog and which are
delegatable. `grant` and `sparql_admin` are **not** delegatable (they come only
from an Admin/SuperAdmin role), so grants can't escalate a non-admin into an admin.
Effective capabilities = role-derived ∪ role/group grants ∪ per-user grants.

**SuperAdmin vs Admin — who they are and who creates them:**
- **SuperAdmin** is the top authority, **bootstrapped at deployment** from
  `USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS` (seeded on that user's first login).
  It's a protected marker — can't be banned, deleted, or role-stripped. Only a
  **SuperAdmin** can grant the `Admin` (or `SuperAdmin`) role to others.
- **Admin** is created by a **SuperAdmin** assigning the `Admin` role
  (`brainkb_assign_role(email, "Admin")` — SuperAdmin-only). Admins have the same
  KG capabilities but are themselves manageable (a SuperAdmin can demote/ban them).
- **Scope of "manage all":** only Admin/SuperAdmin manage *every* team space.
  A non-admin (even with `manage_team_space`) manages **only** the team spaces they
  **created (own)** or were **assigned to** (a member, or matched by a per-space
  `manage` rule). Role *assignment* itself is owned by usermanagement, not
  query_service.

### Giving a whole group ingest access to a team space

Ingesting into a space-mapped graph needs the `ingest` capability **and** write
authorization on the space. Write is granted by any of: global Admin, owner/editor
membership, **or a per-space write access rule**. So to let a whole group ingest
without adding each person as a member, an admin (or space manager) adds a rule:

```
action=write, subject_type=global_role, subject_value="<group/role>"   # e.g. "Lab Member"
```

Every user in that group can then ingest into the space's graphs (they still need
a write-capable role for the `ingest` capability). Rules can also target a single
`member` (email) or a `space_role`. Remove the rule to revoke. See
`RBAC_MODEL.md` and `SPACES_MODEL.md` for the full model.

### Creating a custom group and giving it powers

Creating a group and assigning it always works; a **brand-new custom role starts
with no powers** (only `read_private`) — you then **grant** it capabilities. Full
flow (Admin/SuperAdmin):

```
# 1. create the group/category (usermanagement)
POST /api/admin/roles                      {name: "uk_collaborator", category, description}
# 2. give the group a power (query_service) — global capability
POST /api/admin/capabilities/grant-role    {role: "uk_collaborator", capability: "ingest"}
# 3. put a user in the group (usermanagement)
POST /api/admin/users/{profile_id}/roles   {role: "uk_collaborator"}
# → every uk_collaborator can now ingest
```

**Global vs per-space** — two ways to let a group ingest:
- **Global** (§ grant-role above): the group can ingest into any space where it
  has write authorization (membership/owner/admin) — a broad, workspace-wide power.
- **Per-space** (§ access rule above): the group can ingest into **one** named
  space only. Narrower; preferred when scoping a group to a specific workspace.

### Identity & admin actions catalog (usermanagement `/api/admin`)

Beyond the KG capabilities above, these are the management actions and who may do
them (Admin unless noted):

| Action | Endpoint / tool |
|---|---|
| Create / list custom groups (roles) | `POST/GET /api/admin/roles` · `brainkb_create_role`, `brainkb_available_roles` |
| Assign / remove a role on a user | `POST/DELETE /api/admin/users/{id}/roles` · `brainkb_assign_role` / `brainkb_remove_role` *(Admin role = **SuperAdmin-only**)* |
| Grant / revoke a capability to a **user** | `brainkb_grant_capability` / `brainkb_revoke_capability` |
| Grant / revoke a capability to a **group** | `brainkb_grant_role_capability` / `brainkb_revoke_role_capability` |
| List capability catalog / a group's caps | `brainkb_list_capabilities` · `brainkb_role_capabilities` |
| Create / list permissions (resource·action) | `POST/GET /api/admin/permissions` · `brainkb_create_permission`, `brainkb_list_permissions` |
| Per-space access rules (read/write/manage) | `brainkb_add_access_rule` / `brainkb_remove_access_rule` |
| Activate / deactivate login | `brainkb_activate_user` / `brainkb_deactivate_user` |
| Ban / unban (removal — **no delete**) | `brainkb_ban_user` / `brainkb_unban_user` *(banning an Admin = **SuperAdmin-only**)* |

Onboarding is via Globus/ORCID/GitHub sign-in (auto-creates the profile + default
role); there is **no self-registration** (`/api/register` → 405).

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

Ingestion is **submit-and-forget**: the request saves data to disk, creates a
`pending` job, and returns immediately with a `job_id`; processing runs in the
background (concurrent file uploads + batched DB writes) and the client polls job
status. A per-worker **resource-safety cap** (`MAX_CONCURRENT_INGEST_JOBS`, default
3) bounds how many jobs process at once so a burst of submissions can't exhaust
memory / the DB pool / Oxigraph and crash the process — excess jobs simply wait as
`pending` until a slot frees (backpressure, no queue rework). Search indexing is
then queued separately in the background.

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
- `POST /search/reindex` (**admin**) — queue a background backfill/rebuild of the index.
- `GET /search/index-tasks[?task_id=…]` — background indexing task status.

Hybrid design: **Postgres** holds a full-text **locator index** (`graph_search_index`:
subject + text + named graph + owning space), populated at ingest. A search runs in
Postgres (fast, filtered by space visibility/membership), then the matched subjects'
triples are fetched from **Oxigraph** (the source of truth). Anonymous → public
spaces only; authenticated → public + own/member spaces (+ legacy). Pass `space` to
scope to one workspace, omit for a full search. Private data is never returned to
non-members — the filter is enforced in the locator query.

**Indexing is asynchronous.** It never blocks ingestion: ingest enqueues an indexing
task on an in-process async queue (durable `index_tasks` table, background consumer,
atomic cross-worker claim, restart recovery) and the job completes immediately. The
`/search/reindex` backfill uses the same queue. Poll `/search/index-tasks` for status.

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
