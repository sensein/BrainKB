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

router = APIRouter()
logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


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
    space_type: str = "individual"   # 'individual' | 'team'


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
    if body.visibility not in ("private", "public"):
        raise HTTPException(400, "visibility must be 'private' or 'public'")
    if body.space_type not in ("individual", "team"):
        raise HTTPException(400, "space_type must be 'individual' or 'team'")

    # Role-based authorization: team spaces require create_team_space (Admin/
    # SuperAdmin, or a user an admin has granted it); individual/private spaces
    # require create_private_space (any write-capable role).
    email = _agent(user)
    if body.space_type == "team":
        if not await rbac.has_capability(email, rbac.CREATE_TEAM_SPACE):
            raise HTTPException(403, "not authorized to create a team space (needs Admin/SuperAdmin "
                                     "or a granted create_team_space capability)")
    else:
        if not await rbac.has_capability(email, rbac.CREATE_PRIVATE_SPACE):
            raise HTTPException(403, "not authorized to create a space (needs a write-capable role)")

    if await sp.get_space(body.slug):
        raise HTTPException(409, f"space '{body.slug}' already exists")
    space = await sp.create_space(body.slug, body.name, body.description, email,
                                  body.visibility, body.space_type)
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


@router.get("/spaces/{slug}",
            summary="Get a space",
            description="Returns a space's manifest (members, graphs, visibility) if the "
                        "caller may see it — public to anyone, private to members only.")
async def get_space(slug: str, user: Annotated[Optional[object], Depends(get_current_user_optional)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    member = _agent(user) if user else None
    if space["visibility"] != "public":
        # Private: needs membership AND a role that grants read_private
        # (a JWT user with no role gets public content only).
        role = await sp.member_role(space["space_id"], member)
        if role is None or not await rbac.has_capability(member, rbac.READ_PRIVATE):
            raise HTTPException(403, "private space — membership and a role are required")
    # Fine-grained per-space read rules (if any) further restrict who can read.
    if not await sp.space_action_permitted(space, "read", member):
        raise HTTPException(403, "restricted by a space access rule (read)")
    return space


@router.patch("/spaces/{slug}/visibility",
              dependencies=[Depends(require_scopes(["write"]))],
              summary="Set space visibility (owner only)",
              description="Flip a space between 'private' and 'public'. Public spaces are "
                          "readable by anyone, including unauthenticated clients.")
async def set_visibility(slug: str, body: VisibilityIn, user: Annotated[LoginUserIn, Depends(get_current_user)]):
    space = await sp.get_space(slug)
    if not space:
        return JSONResponse({"error": "space not found"}, status_code=404)
    if not await _can_manage(space, _agent(user)):
        raise HTTPException(403, "not authorized to change this space's visibility")
    if body.visibility not in ("private", "public"):
        raise HTTPException(400, "visibility must be 'private' or 'public'")
    await sp.set_visibility(slug, body.visibility)
    space = await sp.get_space(slug)
    await sp.mirror_space_to_rdf(space)
    return space


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
