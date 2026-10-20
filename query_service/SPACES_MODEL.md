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

- `spaces(space_id, slug, name, description, owner, visibility, space_type,
  parent_space_id, …)` — `visibility ∈ {private, public}`; `parent_space_id` makes
  it a **subspace** (see below).
- `space_members(space_id, member, role)` — `role ∈ {owner, editor, viewer}`;
  `member` is the user email (= the PROV agent id).
- `space_graphs(space_id, named_graph_iri)` — a named graph belongs to exactly one
  space.

- `space_effective_members` (view) — every member's role in every space, including
  roles inherited from the spaces above it; all set-based access checks read it.
- `reserved_graphs(iri, match_type, reason, space_id, …)` — graph IRIs/prefixes only
  admins (or the space they're reserved for) may register or bind.

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
| POST | `/spaces` | write | Create a space (caller = owner); `parent_slug` creates a subspace (manage rights on the parent) |
| GET  | `/spaces` | optional | List visible spaces (public + own; anon → public only) |
| GET  | `/spaces/{slug}` | optional | Space manifest (public to anyone, private to members): graphs, direct and inherited members, visible ancestors and subspaces, your role |
| GET  | `/spaces/{slug}/tree` | optional | The space and all visible subspaces, nested, with your role in each |
| GET  | `/spaces/writable` | read | Spaces the caller can ingest into (the same checks ingestion applies), with their graphs and descriptions, plus graphs in no space; `writable` is a reserved slug |
| DELETE | `/spaces/{slug}?confirm={slug}` | SuperAdmin | Delete the space and everything in it (see below) |
| PATCH | `/spaces/{slug}` | owner | Rename the space, change its description, or give it a new `slug` (see *Renaming a space* below) |
| PATCH | `/spaces/{slug}/visibility` | owner | Flip private/public |
| POST | `/spaces/{slug}/members` | owner | Add/update a member (role) |
| DELETE | `/spaces/{slug}/members/{member}` | owner | Remove a member |
| POST | `/spaces/{slug}/graphs` | owner/editor | Register + bind a named graph to the space |
| GET  | `/spaces/{slug}/data` | optional | Read the space's RDF (JSON-LD); public = anonymous |
| GET/POST | `/spaces/{slug}/access-rules` | member / manager | List / add a read, write or manage rule (global role, member, or space role) |
| DELETE | `/spaces/{slug}/access-rules/{id}` | manager | Remove an access rule |
| GET/POST | `/admin/reserved-graphs` | Admin | List / add a reserved graph IRI or prefix |
| DELETE | `/admin/reserved-graphs/{id}` | Admin | Remove a reservation |

Ingestion (`/insert/{raw,files}/knowledge-graph-triples`) now also checks space
write-authorization for the target graph (in addition to the `write` scope and the
user-identity check).

## Subspaces

A space can sit inside another space, to any depth (`parent_space_id`, set at
creation and never changed, so the tree has no cycles).

- **Roles inherit downward.** A member of a space has the same role in every
  subspace below it; with several, the strongest wins (owner > editor > viewer).
  Roles never flow up: a subspace's owner gets nothing in the parent.
  `member_role()` computes this, so every check that uses it (read, write, manage,
  access rules) inherits; listing, hidden graphs and search use the
  `space_effective_members` view.
- **Who creates one:** anyone who can manage the parent. The subspace takes the
  parent's `space_type`; its creator is its owner; it can add its own members.
- **Visibility is per space.** A private space can hold a public subspace (e.g. a
  data release). A subspace names its parent only to callers who can see the parent.
- **Deletion order:** a space with subspaces can't be deleted (409 listing them;
  the FK is `ON DELETE RESTRICT`). Delete the subspaces first.
- A graph reserved for a space can also be bound in its subspaces.

## Deleting a space (SuperAdmin only)

`DELETE /spaces/{slug}?confirm={slug}` — irreversible. Triplestore first: drop the
space's named graphs and their ingestion delta graphs, remove the graphs' registry
entries and the space's RDF manifest (one SPARQL Update). Only then Postgres: the
space row (members, graph bindings and access rules cascade) and its search-index
rows. If the triplestore step fails (502), nothing in Postgres is touched and the
call can be retried. The deletion is recorded in the provenance graph
(`brainkb:SpaceDeletionActivity`, `prov:invalidated` the space and each graph).
Never delete a space's graph with a raw `DROP GRAPH`: that leaves the space, its
registry entry and its search index behind.

## Reserved named graphs

An Admin/SuperAdmin can reserve one graph IRI (`exact`) or every IRI under a prefix
(`prefix`), with a reason and optionally for one space. Only an admin — or, if it's
reserved for a space, that space's managers/editors (and its subspaces') — may then
register (`POST /api/register-named-graph`) or bind (`POST /spaces/{slug}/graphs`)
it; anyone else gets 403 with the reason. BrainKB's own
`https://brainkb.org/metadata/…` and `…/provenance/…` graphs are always reserved and
can't be bound by anyone, admins included. Graphs already bound when a reservation
is made stay where they are (the response lists them).

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
      brainkb:containsGraph <{named_graph_iri}> ;
      brainkb:parentSpace <https://brainkb.org/space/{parent-slug}> .   # subspaces only
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


## Renaming a space

`PATCH /spaces/{slug}` with a new `slug` renames the space and moves every graph whose IRI is
built from the old slug — `https://brainkb.org/graph/<slug>/…` and
`https://brainkb.org/synthscholar/<slug>/…` — to the same IRI with the new slug. Graphs bound to
the space under any other IRI keep it. In one step (`spaces.rename_space`):

- **Postgres** (one transaction): `spaces.slug`, `space_graphs`, `graph_search_index`,
  `reserved_graphs` reserved for the space, and SynthScholar reviews and files are updated;
  `space_aliases` and `graph_aliases` record the old slug and IRIs.
- **Triplestore** (one SPARQL Update, run before the transaction commits): each graph's triples are
  copied to the new IRI and the old graph dropped; its registry entry moves; every ingestion
  activity's `brainkb:targetGraph` gains the new IRI (the old one is kept, so history is found under
  either); `dcterms:replaces` links new → old. If this fails, the transaction rolls back and nothing
  has changed.
- **Afterwards**: the space manifest is re-mirrored and a `brainkb:SpaceRenameActivity` is written to
  the provenance graph (`prov:used` the old IRIs, `prov:generated` the new ones,
  `prov:wasRevisionOf` / `dcterms:replaces`).

**Aliases.** An old slug still resolves to the space (`GET /spaces/{old}` returns it with
`renamed_from`). An old graph IRI is governed by the renamed space — never by the unmapped/legacy
rules — and nobody can bind it, register a space with the old slug, or rename onto it. Ingesting into
an old IRI is refused (409) with `renamed_to`, so data never lands in an orphaned graph. Renaming
again chains the aliases to the newest IRI; renaming back makes the original slug and IRIs the
space's own again. Triples inside a moved graph are not rewritten: IRIs they contain that carry the
old slug (e.g. SynthScholar file IRIs) resolve through the aliases.
