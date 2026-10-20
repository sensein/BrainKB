# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @File    : spaces.py (router)

"""REST endpoints for spaces — private/public containers of named graphs."""

import logging
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, HttpUrl

from core.models.user import LoginUserIn
from core.security import get_current_user, get_current_user_optional, require_scopes
from core.shared import named_graph_metadata
from core.provenance import agent_ref, query_provenance_jsonld
from core.graph_database_connection_manager import insert_data_gdb_async, check_named_graph_exists
from core import spaces as sp
from core import rbac
from core import reserved_graphs as reserved

router = APIRouter()
logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
# path segments under /spaces/ that are routes, not spaces
_RESERVED_SLUGS = {"writable"}


def _agent(user) -> str:
    """Caller's identity string (email preferred), matching the PROV agent id."""
    try:
        return str(user["email"] or user["id"])
    except (KeyError, TypeError, IndexError):
        return "unknown"


async def _can_manage(space: dict, email: str) -> bool:
    """Who may manage a space (members/visibility/graphs/access-rules):

      * **Admin/SuperAdmin** — every space (platform-wide).
      * **Owner** (the creator) — their own space.
      * A non-admin with **manage_team_space** — ONLY team spaces they are
        **assigned to** (a member of), not every team space.
      * Anyone matched by a per-space **'manage'** access rule (explicit assignment).

    i.e. unless you're an Admin, you can manage only the team spaces you created or
    were assigned to — never all of them."""
    if await rbac.is_admin(email):
        return True
    srole = await sp.member_role(space["space_id"], email)
    if srole == "owner":
        return True
    if await sp.matches_access_rule(space["space_id"], "manage", email):
        return True
    if (space.get("space_type") == "team" and srole is not None
            and await rbac.has_capability(email, rbac.MANAGE_TEAM_SPACE)):
        return True
    return False


class SpaceCreate(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    visibility: str = "private"
    space_type: str = "individual"   # 'individual' | 'team'; a subspace takes its parent's
    parent_slug: Optional[str] = None  # create as a subspace of this space


class MemberIn(BaseModel):
    member: str
    role: str = "viewer"


class VisibilityIn(BaseModel):
    visibility: str


class SpaceGraphIn(BaseModel):
    named_graph_url: HttpUrl
    description: str = ""


@router.post("/spaces", status_code=201,
             dependencies=[Depends(require_scopes(["write"]))],
             summary="Create a space",
             description="Create an owner-controlled space (private by default). The "
                         "caller becomes its owner. Members can later be added and the "
                         "space flipped public for anonymous read access.")
async def create_space(body: SpaceCreate, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not _SLUG_RE.match(body.slug):
        raise HTTPException(400, "slug must be lowercase alphanumeric/hyphen, 3-64 chars")
    if body.slug in _RESERVED_SLUGS:
        raise HTTPException(400, f"'{body.slug}' is reserved; choose another slug")
    if body.visibility not in ("private", "public"):
        raise HTTPException(400, "visibility must be 'private' or 'public'")
    if body.space_type not in ("individual", "team"):
        raise HTTPException(400, "space_type must be 'individual' or 'team'")

    # Role-based authorization: team spaces require create_team_space (Admin/
    # SuperAdmin, or a user an admin has granted it); individual/private spaces
    # require create_private_space (any write-capable role).
    email = _agent(user)
    parent = None
    if body.parent_slug:
        # A subspace: whoever can manage the parent may create one (the parent's
        # members get the same roles in it). It takes the parent's space type, so
        # no separate team-space capability is needed.
        parent = await sp.get_space(body.parent_slug)
        if not parent:
            raise HTTPException(404, f"parent space '{body.parent_slug}' not found")
        if not await _can_manage(parent, email):
            raise HTTPException(403, f"only someone who can manage '{body.parent_slug}' can create a subspace in it")
        if not await rbac.has_capability(email, rbac.CREATE_PRIVATE_SPACE):
            raise HTTPException(403, "not authorized to create a space (needs a write-capable role)")
    elif body.space_type == "team":
        if not await rbac.has_capability(email, rbac.CREATE_TEAM_SPACE):
            raise HTTPException(403, "not authorized to create a team space (needs Admin/SuperAdmin "
                                     "or a granted create_team_space capability)")
    else:
        if not await rbac.has_capability(email, rbac.CREATE_PRIVATE_SPACE):
            raise HTTPException(403, "not authorized to create a space (needs a write-capable role)")

    if await sp.get_space(body.slug):
        raise HTTPException(409, f"space '{body.slug}' already exists")
    # Under a public space everything is public: a subspace there is created public.
    visibility = body.visibility
    if parent and (parent["visibility"] == "public" or sp.public_ancestor(parent)):
        visibility = "public"
    space = await sp.create_space(body.slug, body.name, body.description, email,
                                  visibility, parent["space_type"] if parent else body.space_type,
                                  parent["space_id"] if parent else None)
    await sp.mirror_space_to_rdf(space)
    return space


@router.get("/spaces",
            summary="List visible spaces",
            description="Lists spaces the caller may see: all public spaces plus any "
                        "the caller is a member of. Anonymous callers see only public "
                        "spaces (no token required).")
async def list_spaces(user: Annotated[Optional[object], Depends(get_current_user_optional)]):
    member = _agent(user) if user else None
    return {"spaces": await sp.list_visible_spaces(member)}


@router.get("/spaces/writable",
            summary="Spaces (and graphs) the caller may ingest into",
            description="Every space the caller may write to — owner/editor membership, a "
                        "role inherited from a parent space, a space write access rule, or "
                        "Admin/SuperAdmin — with its graphs and their descriptions, plus "
                        "parent_slug to show subspaces as a tree. `can_ingest` is false "
                        "without a write-capable role (then nothing can be ingested anywhere). "
                        "`unmapped_graphs` are registered graphs in no space, which any caller "
                        "with `can_ingest` may still write to. Uses the same checks as ingestion.")
async def writable_spaces(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    email = _agent(user)
    can_ingest = await rbac.has_capability(email, rbac.INGEST)
    if not can_ingest:
        return {"can_ingest": False, "spaces": [], "unmapped_graphs": [],
                "reason": "ingesting needs a write-capable role; ask an admin"}
    slugs = (await sp.all_space_slugs() if await rbac.is_admin(email)
             else [x["slug"] for x in await sp.list_visible_spaces(email)])
    descriptions = await sp.graph_descriptions() or {}
    spaces = []
    for slug in slugs:
        space = await sp.get_space(slug)
        if not space:
            continue
        allowed, how = await sp.can_write_space(space, email)
        if not allowed:
            continue
        spaces.append({
            "slug": space["slug"], "name": space["name"], "visibility": space["visibility"],
            "parent_slug": space["ancestors"][-1]["slug"] if space.get("ancestors") else None,
            "access": how,
            "graphs": [{"iri": g, "description": descriptions.get(g, "")} for g in space["graphs"]],
        })
    writable = {s["slug"] for s in spaces}
    for s in spaces:   # a parent the caller can't write to is not shown; the subspace becomes a root
        if s["parent_slug"] not in writable:
            s["parent_slug"] = None
    bound = await sp.bound_graphs()
    unmapped = [{"iri": g, "description": d} for g, d in sorted(descriptions.items()) if g not in bound]
    return {"can_ingest": True, "spaces": spaces, "unmapped_graphs": unmapped}


@router.get("/spaces/{slug}",
            summary="Get a space",
            description="Returns a space's manifest (members, graphs, visibility) if the "
                        "caller may see it — public to anyone, private to members only.")
async def get_space(slug: str, user: Annotated[Optional[object], Depends(get_current_user_optional)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    member = _agent(user) if user else None
    role = await sp.member_role(space["space_id"], member)
    if space["visibility"] != "public":
        # Private: needs membership AND a role that grants read_private
        # (a JWT user with no role gets public content only).
        if role is None or not await rbac.has_capability(member, rbac.READ_PRIVATE):
            raise HTTPException(403, "private space — membership and a role are required")
    # Fine-grained per-space read rules (if any) further restrict who can read.
    if not await sp.space_action_permitted(space, "read", member):
        raise HTTPException(403, "restricted by a space access rule (read)")
    space = await _with_visible_hierarchy(space, member)
    detail = await sp.member_role_detail(space["space_id"], member)
    space["your_role"], space["role_inherited"] = (detail if detail else (None, False))
    # Owner/member emails are for members and admins only, not public readers.
    if role is None and not await rbac.is_admin(member):
        return sp.redact_people(space)
    return space


async def _visible_slugs(member: Optional[str]) -> Optional[set]:
    """Slugs the caller may see; None means every space (Admin/SuperAdmin)."""
    if member and await rbac.is_admin(member):
        return None
    return {x["slug"] for x in await sp.list_visible_spaces(member)}


async def _with_visible_hierarchy(space: dict, member: Optional[str]) -> dict:
    """Keep only the ancestors and subspaces the caller may see: a private parent's
    name is not shown to someone who can only see its public subspace."""
    visible = await _visible_slugs(member)
    keep = (lambda x: True) if visible is None else (lambda x: x["slug"] in visible)
    out = dict(space)
    out["ancestors"] = [a for a in space.get("ancestors", []) if keep(a)]
    out["subspaces"] = [c for c in space.get("subspaces", []) if keep(c)]
    out["parent_slug"] = (space["ancestors"][-1]["slug"]
                          if space.get("ancestors") and keep(space["ancestors"][-1]) else None)
    out.pop("parent_space_id", None)
    return out


@router.get("/spaces/{slug}/tree",
            summary="A space and all its subspaces, nested",
            description="The space and every subspace below it (any depth) that the caller "
                        "may see, each with visibility, the caller's role (and whether it is "
                        "inherited from a parent) and its graph count.")
async def space_tree(slug: str, user: Annotated[Optional[object], Depends(get_current_user_optional)]):
    member = _agent(user) if user else None
    root = await sp.get_space(slug)
    if not root:
        return JSONResponse({"error": "space not found"}, status_code=404)
    visible = await _visible_slugs(member)
    if visible is not None and slug not in visible:
        raise HTTPException(403, "private space — membership and a role are required")

    async def node(sp_: dict, depth: int) -> dict:
        detail = await sp.member_role_detail(sp_["space_id"], member)
        children = []
        if depth < 64:
            for c in sp_.get("subspaces", []):
                if visible is None or c["slug"] in visible:
                    full = await sp.get_space(c["slug"])
                    if full:
                        children.append(await node(full, depth + 1))
        return {"slug": sp_["slug"], "name": sp_["name"], "visibility": sp_["visibility"],
                "your_role": detail[0] if detail else None,
                "role_inherited": detail[1] if detail else False,
                "graphs": len(sp_.get("graphs") or []), "subspaces": children}
    return await node(root, 0)


@router.patch("/spaces/{slug}/visibility",
              dependencies=[Depends(require_scopes(["write"]))],
              summary="Set space visibility (owner only)",
              description="Flip a space between 'private' and 'public'. Public spaces are "
                          "readable by anyone, including unauthenticated clients. Making a space "
                          "public makes all its subspaces public; a subspace of a public space "
                          "cannot be made private (409). Under a private space each subspace "
                          "can be public or private on its own.")
async def set_visibility(slug: str, body: VisibilityIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    if not await _can_manage(space, _agent(user)):
        raise HTTPException(403, "not authorized to change this space's visibility")
    if body.visibility not in ("private", "public"):
        raise HTTPException(400, "visibility must be 'private' or 'public'")
    # A public space makes all its subspaces public, so a subspace of a public space
    # cannot be private on its own; under a private space each subspace chooses.
    above = sp.public_ancestor(space)
    if body.visibility == "private" and above:
        raise HTTPException(409, f"'{slug}' is inside the public space '{above}', and everything in a public "
                                 f"space is public — make '{above}' private first")
    changed = await sp.set_visibility(slug, body.visibility)
    for s_ in changed:          # this space and, when made public, its subspaces
        changed_space = await sp.get_space(s_)
        if changed_space:
            await sp.mirror_space_to_rdf(changed_space)
    space = await sp.get_space(slug)
    space["visibility_changed"] = changed
    return space


@router.delete("/spaces/{slug}",
               dependencies=[Depends(require_scopes(["admin"]))],
               summary="Delete a space and everything in it (SuperAdmin only)",
               description="Irreversible. Drops the space's named graphs and their ingestion "
                           "delta graphs, removes the graphs' registry entries and the space's "
                           "RDF manifest, then deletes the space with its members, graph "
                           "bindings, access rules and search-index entries. The deletion is "
                           "recorded in the provenance graph (prov:invalidated). Requires the "
                           "SuperAdmin role and `confirm` equal to the slug.")
async def delete_space(
    slug: str,
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    confirm: Annotated[str, Query(..., description="Must equal the space's slug")],
):
    if not await rbac.is_superadmin(_agent(user)):
        raise HTTPException(403, "only a SuperAdmin can delete a space")
    if confirm != slug:
        raise HTTPException(400, "confirm must equal the space's slug")
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    try:
        result = await sp.delete_space(space, _agent(user))
    except sp.SpaceHasSubspaces as e:
        raise HTTPException(409, f"'{slug}' still has subspaces ({', '.join(e.slugs)}); delete them first")
    except sp.SpaceDeletionError as e:
        logger.error("[spaces] deleting %s failed: %s", slug, e)
        raise HTTPException(502, f"space not deleted: {e}. Nothing was removed from the space "
                                 "registry; it is safe to retry.")
    # The space's SynthScholar reviews (their kept files) go with it; their graphs
    # were among the dropped ones.
    from core import synthscholar as _ss
    try:
        result["synthscholar_reviews_removed"] = await _ss.delete_space_reviews(slug)
    except Exception as e:      # the space is gone either way; a leftover row is skipped on re-ingest
        logger.error("[spaces] removing %s's SynthScholar reviews failed: %s", slug, e)
    logger.info("[spaces] %s deleted space %s (%d graphs, %d delta graphs)", _agent(user), slug,
                len(result["dropped_graphs"]), len(result["dropped_delta_graphs"]))
    return result


@router.post("/spaces/{slug}/members",
             dependencies=[Depends(require_scopes(["write"]))],
             summary="Add or update a member (owner only)")
async def add_member(slug: str, body: MemberIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    if not await _can_manage(space, _agent(user)):
        raise HTTPException(403, "not authorized to manage members of this space")
    if body.role not in sp.ROLES:
        raise HTTPException(400, f"role must be one of {sp.ROLES}")
    await sp.add_member(space["space_id"], body.member, body.role)
    space = await sp.get_space(slug)
    await sp.mirror_space_to_rdf(space)
    return space


@router.delete("/spaces/{slug}/members/{member}",
               dependencies=[Depends(require_scopes(["write"]))],
               summary="Remove a member (owner only)")
async def remove_member(slug: str, member: str, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    if not await _can_manage(space, _agent(user)):
        raise HTTPException(403, "not authorized to manage members of this space")
    await sp.remove_member(space["space_id"], member)
    space = await sp.get_space(slug)
    await sp.mirror_space_to_rdf(space)
    return space


@router.post("/spaces/{slug}/graphs",
             dependencies=[Depends(require_scopes(["write"]))],
             summary="Register a named graph into a space (owner/editor)",
             description="Registers a named graph and binds it to this space so that "
                         "ingestion and reads on that graph are governed by the space's "
                         "membership and visibility.")
async def add_graph(slug: str, body: SpaceGraphIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    _role = await sp.member_role(space["space_id"], _agent(user))
    if not (await _can_manage(space, _agent(user)) or _role in sp.WRITE_ROLES):
        raise HTTPException(403, "only the space owner/editors (or a space manager) can add graphs")

    named_graph_url = str(body.named_graph_url)
    if not named_graph_url.endswith("/"):
        named_graph_url += "/"

    allowed, why = await reserved.check_allowed(named_graph_url, _agent(user), space["space_id"])
    if not allowed:
        raise HTTPException(403, why)

    # Bind first: a graph is globally unique to one space, so if another space
    # already holds it this must fail with a conflict rather than register registry
    # metadata for a graph we cannot attach.
    try:
        await sp.attach_graph(space["space_id"], named_graph_url)
    except sp.GraphAlreadyBound as e:
        raise HTTPException(409, str(e))

    # Register in the graph registry if not already there (idempotent-ish).
    if not await check_named_graph_exists(named_graph_url):
        await insert_data_gdb_async(named_graph_metadata(
            named_graph_url=named_graph_url,
            description=body.description,
            agent_uri=str(agent_ref(_agent(user))),
        ))
    space = await sp.get_space(slug)
    await sp.mirror_space_to_rdf(space)
    return space


@router.get("/spaces/{slug}/data",
            summary="Read a space's data (public = anonymous)",
            description="Returns the RDF (JSON-LD) across all named graphs in the space. "
                        "Public spaces are readable by anyone (no token); private spaces "
                        "require membership.")
async def read_space_data(slug: str, user: Annotated[Optional[object], Depends(get_current_user_optional)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    member = _agent(user) if user else None
    if space["visibility"] != "public":
        # Private: membership AND a role that grants read_private.
        if await sp.member_role(space["space_id"], member) is None \
                or not await rbac.has_capability(member, rbac.READ_PRIVATE):
            raise HTTPException(403, "private space — membership and a role are required")
    # Fine-grained per-space read rules (if any) further restrict who can read.
    if not await sp.space_action_permitted(space, "read", member):
        raise HTTPException(403, "restricted by a space access rule (read)")
    if not space["graphs"]:
        return Response(content='{"@graph": []}', media_type="application/ld+json")
    jsonld = await query_provenance_jsonld(await sp.construct_space_graphs(space))
    if jsonld is None:
        return JSONResponse({"error": "failed to read space data"}, status_code=502)
    return Response(content=jsonld, media_type="application/ld+json")


# --------------------------------------------------------------------------- #
# Admin: delegated capability grants (Admin/SuperAdmin only)
# --------------------------------------------------------------------------- #

class GrantIn(BaseModel):
    member: str
    capability: str


class RoleGrantIn(BaseModel):
    role: str
    capability: str


class AccessRuleIn(BaseModel):
    action: str          # read | write | manage
    subject_type: str    # global_role | member | space_role
    subject_value: str   # role name / email / viewer|editor|owner


@router.get("/spaces/{slug}/access-rules",
            summary="List a space's fine-grained access rules")
async def list_access_rules(slug: str, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    email = _agent(user)
    # visible to managers or members of the space
    if not await _can_manage(space, email) and await sp.member_role(space["space_id"], email) is None:
        raise HTTPException(403, "must be a member or manager of the space")
    return {"slug": slug, "rules": await sp.list_access_rules(space["space_id"])}


@router.post("/spaces/{slug}/access-rules",
             dependencies=[Depends(require_scopes(["write"]))],
             summary="Add a fine-grained access rule (space manager only)",
             description="Restrict a space action to a subject. action: read|write|manage. "
                         "subject_type: global_role (e.g. 'Admin','Lab Member') | member "
                         "(an email) | space_role (viewer|editor|owner). When rules exist "
                         "for an action, only matching callers may perform it (owner and "
                         "Admin/SuperAdmin always bypass).")
async def add_access_rule(slug: str, body: AccessRuleIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    if not await _can_manage(space, _agent(user)):
        raise HTTPException(403, "not authorized to manage this space's access rules")
    try:
        await sp.add_access_rule(space["space_id"], body.action, body.subject_type,
                                 body.subject_value, _agent(user))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"slug": slug, "rules": await sp.list_access_rules(space["space_id"])}


@router.delete("/spaces/{slug}/access-rules/{rule_id}",
               dependencies=[Depends(require_scopes(["write"]))],
               summary="Delete a fine-grained access rule (space manager only)")
async def delete_access_rule(slug: str, rule_id: int, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    if not await _can_manage(space, _agent(user)):
        raise HTTPException(403, "not authorized to manage this space's access rules")
    await sp.remove_access_rule(space["space_id"], rule_id)
    return {"slug": slug, "rules": await sp.list_access_rules(space["space_id"])}


class ReservedGraphIn(BaseModel):
    iri: HttpUrl
    match_type: str = "exact"
    reason: Optional[str] = None
    space_slug: Optional[str] = None


@router.get("/admin/reserved-graphs",
            dependencies=[Depends(require_scopes(["admin"]))],
            summary="List reserved named graphs (Admin/SuperAdmin)",
            description="System reservations (BrainKB's own metadata/provenance graphs, "
                        "always reserved) and admin-managed ones: an exact IRI or every IRI "
                        "under a prefix that only an Admin/SuperAdmin — or, when reserved "
                        "for a space, that space's managers — may register or bind.")
async def list_reserved_graphs(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required")
    return {"reserved": await reserved.list_all()}


@router.post("/admin/reserved-graphs", status_code=201,
             dependencies=[Depends(require_scopes(["admin"]))],
             summary="Reserve a named graph IRI or prefix (Admin/SuperAdmin)",
             description="match_type 'exact' reserves one graph IRI; 'prefix' reserves every "
                         "IRI that starts with it. Optional space_slug reserves it for that "
                         "space. Graphs already bound stay bound; the response lists them.")
async def add_reserved_graph(body: ReservedGraphIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required")
    space_id = None
    if body.space_slug:
        space = await sp.get_space(body.space_slug)
        if not space:
            raise HTTPException(404, f"space '{body.space_slug}' not found")
        space_id = space["space_id"]
    try:
        return await reserved.add(str(body.iri), body.match_type, body.reason, _agent(user), space_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except reserved.ReservationConflict as e:
        raise HTTPException(409, str(e))


@router.delete("/admin/reserved-graphs/{reservation_id}",
               dependencies=[Depends(require_scopes(["admin"]))],
               summary="Remove a graph reservation (Admin/SuperAdmin)")
async def remove_reserved_graph(reservation_id: int, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required")
    if not await reserved.remove(reservation_id):
        raise HTTPException(404, "reservation not found (system reservations cannot be removed)")
    return {"removed": reservation_id}


@router.get("/admin/capabilities",
            dependencies=[Depends(require_scopes(["admin"]))],
            summary="List a user's effective capabilities (admin only)")
async def get_capabilities(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    member: Annotated[str, Query(..., description="User email to inspect")],
):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required")
    return {
        "member": member,
        "roles": sorted(await rbac.active_roles(member)),
        "capabilities": sorted(await rbac.capabilities(member)),
        "grants": await rbac.list_grants(member),
    }


@router.post("/admin/capabilities/grant",
             dependencies=[Depends(require_scopes(["admin"]))],
             summary="Grant a capability to a user (admin only)",
             description="Delegated upgrade: e.g. grant 'create_team_space' or "
                         "'manage_team_space' to a Curator/Lab Member so they can create "
                         "and manage team spaces. Requires the caller to hold an "
                         "Admin/SuperAdmin role.")
async def grant_capability(body: GrantIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required to grant capabilities")
    if body.capability not in rbac.GRANTABLE_CAPS:
        raise HTTPException(400, f"capability is not delegatable; valid: {sorted(rbac.GRANTABLE_CAPS)}")
    await rbac.grant_capability(body.member, body.capability, _agent(user))
    return {"status": "granted", "member": body.member, "capability": body.capability}


@router.post("/admin/capabilities/revoke",
             dependencies=[Depends(require_scopes(["admin"]))],
             summary="Revoke a granted capability (admin only)")
async def revoke_capability(body: GrantIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required to revoke capabilities")
    await rbac.revoke_capability(body.member, body.capability)
    return {"status": "revoked", "member": body.member, "capability": body.capability}


@router.get("/admin/capabilities/available",
            dependencies=[Depends(require_scopes(["admin"]))],
            summary="List all KG capabilities and which are delegatable (admin only)",
            description="Catalog of query_service capabilities. 'grantable' are the ones "
                        "an admin may delegate to a user or role/group; 'grant' and "
                        "'sparql_admin' are admin-intrinsic (not delegatable).")
async def available_capabilities(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required")
    return {
        "all": sorted(rbac.ALL_CAPS),
        "grantable": sorted(rbac.GRANTABLE_CAPS),
        "admin_only": sorted(rbac.ALL_CAPS - rbac.GRANTABLE_CAPS),
        "descriptions": {
            rbac.CREATE_PRIVATE_SPACE: "Create your own individual/private space",
            rbac.CREATE_TEAM_SPACE: "Create a team (shared) space",
            rbac.MANAGE_TEAM_SPACE: "Manage a team space's members, visibility, graphs, access rules",
            rbac.INGEST: "Ingest data (also needs per-space write: membership or a space write access rule)",
            rbac.RECOVER: "Recover stuck/errored ingest jobs",
            rbac.READ_PRIVATE: "Read non-public content you're a member of",
            rbac.SPARQL_ADMIN: "Run arbitrary SPARQL (admin-only, not delegatable)",
            rbac.GRANT: "Grant/revoke capabilities to others (admin-only, not delegatable)",
        },
    }


@router.get("/admin/capabilities/role",
            dependencies=[Depends(require_scopes(["admin"]))],
            summary="List capabilities granted to a role/group (admin only)")
async def role_capabilities(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    role: Annotated[str, Query(..., description="Role/group name, e.g. 'uk_collaborator'")],
):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required")
    return {"role": role, "grants": await rbac.list_role_grants(role)}


@router.post("/admin/capabilities/grant-role",
             dependencies=[Depends(require_scopes(["admin"]))],
             summary="Grant a capability to a whole role/group (admin only)",
             description="Give every member of a role/group a delegatable capability — "
                         "e.g. grant 'ingest' or 'create_private_space' to a custom group "
                         "like 'uk_collaborator'. 'grant'/'sparql_admin' are not delegatable.")
async def grant_role_capability(body: RoleGrantIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required to grant capabilities")
    if body.capability not in rbac.GRANTABLE_CAPS:
        raise HTTPException(400, f"capability is not delegatable; valid: {sorted(rbac.GRANTABLE_CAPS)}")
    await rbac.grant_role_capability(body.role, body.capability, _agent(user))
    return {"status": "granted", "role": body.role, "capability": body.capability}


@router.post("/admin/capabilities/revoke-role",
             dependencies=[Depends(require_scopes(["admin"]))],
             summary="Revoke a capability from a role/group (admin only)")
async def revoke_role_capability(body: RoleGrantIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    if not await rbac.is_admin(_agent(user)):
        raise HTTPException(403, "Admin/SuperAdmin role required to revoke capabilities")
    await rbac.revoke_role_capability(body.role, body.capability)
    return {"status": "revoked", "role": body.role, "capability": body.capability}
