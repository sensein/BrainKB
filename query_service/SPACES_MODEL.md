# BrainKB Spaces (private/public, team-owned)

Status: implemented on branch `improve-ingestion-query-service`.

Spaces let a user or team create their own **owner-controlled container** of named
graphs, keep it **private**, or publish it **publicly** for anyone — including
unauthenticated clients — to read. This supports a decentralized model where each
space is a sovereign, IRI-addressable pod (`https://brainkb.org/space/{slug}`).

## Storage split (confirmed architecture)

- **Postgres** — identity/teams/enforcement only: JWT users, and the space tables
  (`spaces`, `space_members`, `space_graphs`). This is the source of truth for
  authorization and is what every request checks (fast, joinable with the JWT user).
- **Oxigraph (graph DB)** — all knowledge-graph data AND provenance AND a
  best-effort **RDF mirror** of each space manifest (in the spaces metadata graph
  `https://brainkb.org/metadata/spaces/`), so spaces are portable/queryable via SPARQL.

The RDF mirror is best-effort: a mirror failure never fails the enforcing Postgres
write.

## Model

- `spaces(space_id, slug, name, description, owner, visibility, …)` —
  `visibility ∈ {private, public}`.
- `space_members(space_id, member, role)` — `role ∈ {owner, editor, viewer}`;
  `member` is the user email (= the PROV agent id).
- `space_graphs(space_id, named_graph_iri)` — a named graph belongs to exactly one
  space.

Roles: **owner** manages members/visibility/graphs; **editor** may ingest;
**viewer** may read a private space; **public** grants read to everyone.

## Authorization (enforced on every request)

`spaces.authorize(named_graph_iri, member, need)`:

| Space state | read | write (ingest) |
|-------------|------|----------------|
| public      | **anyone (even anonymous)** | owner/editor only |
| private     | owner/editor/viewer | owner/editor |
| *unmapped (legacy graph)* | falls through to endpoint scope | falls through to endpoint scope |

Backward-compat: graphs never attached to a space (e.g. pre-existing graphs) are
"unmapped" and keep their previous scope-only behavior; only space-mapped graphs
are governed by space ACL.

**Public = anonymous**: public reads require no token. Read endpoints that serve
space data use an optional-auth dependency (`get_current_user_optional`) — a token
is used if present, but its absence is not an error for public spaces.

## Endpoints (`/api`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/spaces` | write | Create a space (caller = owner) |
| GET  | `/spaces` | optional | List visible spaces (public + own; anon → public only) |
| GET  | `/spaces/{slug}` | optional | Space manifest (public to anyone, private to members) |
| PATCH | `/spaces/{slug}/visibility` | owner | Flip private/public |
| POST | `/spaces/{slug}/members` | owner | Add/update a member (role) |
| DELETE | `/spaces/{slug}/members/{member}` | owner | Remove a member |
| POST | `/spaces/{slug}/graphs` | owner/editor | Register + bind a named graph to the space |
| GET  | `/spaces/{slug}/data` | optional | Read the space's RDF (JSON-LD); public = anonymous |

Ingestion (`/insert/{raw,files}/knowledge-graph-triples`) now also checks space
write-authorization for the target graph (in addition to the `write` scope and the
user-identity check).

## RDF manifest (mirror)

```turtle
GRAPH <https://brainkb.org/metadata/spaces/> {
  <https://brainkb.org/space/{slug}>
      a brainkb:Space ;
      brainkb:slug "{slug}" ; schema:name "…" ; dcterms:description "…" ;
      brainkb:visibility "public" ;
      brainkb:owner  <https://brainkb.org/prov/agent/{owner}> ;
      brainkb:editor <…/agent/{editor}> ;
      brainkb:viewer <…/agent/{viewer}> ;
      brainkb:containsGraph <{named_graph_iri}> .
}
```

## Notes

- `registered-named-graphs` is **visibility-filtered**: graphs in a private space
  the caller isn't a member of are omitted, so private graph existence is not
  leaked. Public-space and legacy (unmapped) graphs remain listed. The endpoint
  requires authentication (read scope); anonymous discovery of public spaces is via
  `GET /api/spaces`.
- Job-scoped provenance endpoints are **intentionally owner-restricted** (by
  `user_id` = authenticated identity) and stay that way — job provenance is not made
  public even for public spaces. Ingestion is likewise restricted to activated JWT
  users with valid credentials (and space owner/editor membership); it is never
  anonymous. Only *reads* of public spaces are anonymous.
