# BrainKB Authorization (RBAC)

Status: implemented on branch `improve-ingestion-query-service`.

**JWT = authentication / API access. Roles = authorization (what you may do).**
The query_service authenticates via JWT (scopes gate *API access* only) and then
authorizes actions from the user's **roles**, mapped to **capabilities**, plus
per-resource **space membership**.

## Where roles come from

Roles live in the Django-owned RBAC tables and join to a JWT user **by email**:

```
Web_jwtuser.email == Web_user_profile.email
Web_user_profile.id -> Web_user_role (is_active, not expired) -> role name
```

query_service only **reads** roles (see `core/rbac.py`). It never assigns roles —
creating/removing Admins is **role assignment**, owned by the usermanagement/Django
side. This keeps the two systems consistent and means the KG API cannot be used to
escalate privileges.

## Role hierarchy

```
SuperAdmin  >=  Admin  >  write roles  >  read roles  >  (no role)
```

- **SuperAdmin** — ultimate authority, **bootstrapped at deployment**. Can do
  everything Admin can; the SuperAdmin-vs-Admin difference (managing admins) is
  role assignment, handled outside query_service.
- **Admin** — all KG capabilities, incl. granting delegatable capabilities.
- **write roles** — Curator, Lab Member, Submitter, Annotator, Mapper,
  Knowledge Contributor: create their own private spaces + ingest.
- **read roles** — Reviewer, Validator, Moderator, etc.: read member content.
- **no role** — a JWT user not linked to a profile/role gets **public content
  only** (read), nothing else.

## Capabilities

| Capability | Granted by | Gates |
|---|---|---|
| `create_private_space` | write roles, admins | create an individual/private space |
| `create_team_space` | admins (or delegated) | create a team space |
| `manage_team_space` | admins (or delegated) | manage a team space's members/visibility/graphs |
| `ingest` | write roles, admins | ingest into a graph (also needs space owner/editor) |
| `recover` | write roles, admins | recover stuck/errored jobs |
| `read_private` | any role | read non-public content you're a member of |
| `sparql_admin` | admins only | run arbitrary SPARQL |
| `grant` | admins only | grant/revoke delegatable capabilities |

**Delegated upgrades:** Admin/SuperAdmin can grant a specific user extra
capabilities via `POST /api/admin/capabilities/grant` — e.g. let a Curator or Lab
Member create/manage **team** spaces. Only **delegatable** caps may be granted
(everything except `grant` and `sparql_admin`), so the grant endpoint can't turn a
non-admin into an admin.

## Enforcement points (layered)

For each action: **JWT scope** (API access) → **capability** (role) → **space
membership** (resource).

| Action | Capability required | + resource check |
|---|---|---|
| Create individual/private space | `create_private_space` | — |
| Create team space | `create_team_space` | — |
| Manage space (members/visibility/graphs) | owner, or `manage_team_space`/admin | space ownership |
| Ingest (`/insert/*`) | `ingest` | space owner/editor of the target graph |
| Recover jobs | `recover` | own jobs |
| Arbitrary SPARQL (`/query/sparql/`) | `sparql_admin` | — |
| Read space / data | `read_private` for private; public = anyone (anon) | membership for private |

## Space types

- **individual** — a personal/private workspace; any write-capable user can create
  one (`create_private_space`).
- **team** — a shared workspace; only Admin/SuperAdmin (or a user granted
  `create_team_space`) can create/manage it.

## Admin capability endpoints

- `GET  /api/admin/capabilities?member=<email>` — a user's roles, effective
  capabilities, and grants (admin only).
- `POST /api/admin/capabilities/grant`  `{member, capability}` — delegate a cap.
- `POST /api/admin/capabilities/revoke` `{member, capability}`.

## Notes / next

- Coarse per-space roles today are owner/editor/viewer plus the capability gates
  above. **Fine-grained in-space rules** (e.g. an action inside a space limited to
  Admins, or to specific Lab Members) are the next iteration — the primitives
  (space membership + roles + capabilities) are in place to build on.
- JWT scopes (`read`/`write`/`admin`) remain as an API-access layer for defense in
  depth; the authoritative "who can do what" is the role/capability layer above.
