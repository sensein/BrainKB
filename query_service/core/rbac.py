# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @File    : rbac.py

"""
Role-based access control for BrainKB.

Separation of concerns:
  * JWT  -> authentication + API access (who you are; can you call the API).
  * Roles -> authorization (what you may DO): create spaces, ingest, admin, etc.

Roles live in the Django-owned RBAC tables and are joined to a JWT user by email:
    Web_jwtuser.email == Web_user_profile.email
    Web_user_profile.id -> Web_user_role (active, non-expired) -> role name

Roles map to capabilities via the policy below. Admins/SuperAdmins can also grant
extra capabilities to individual users (delegated upgrades) via
`user_capability_grants` — e.g. letting a Curator create/manage team spaces.

A JWT user with NO active role is treated as having NO capabilities: read-only
access to PUBLIC content, nothing else.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Set

from core.database import get_db_connection

logger = logging.getLogger(__name__)

# ---- capabilities ----------------------------------------------------------
CREATE_PRIVATE_SPACE = "create_private_space"   # make your own individual/private space
CREATE_TEAM_SPACE = "create_team_space"         # create a team space (Admin/SuperAdmin or granted)
MANAGE_TEAM_SPACE = "manage_team_space"         # manage members/visibility/graphs of team spaces
INGEST = "ingest"                               # ingest data (still needs per-space write membership)
RECOVER = "recover"                             # recover stuck/errored jobs
SPARQL_ADMIN = "sparql_admin"                   # run arbitrary SPARQL
GRANT = "grant"                                 # grant/revoke capabilities to other users
READ_PRIVATE = "read_private"                   # read non-public content you're a member of

ALL_CAPS = {
    CREATE_PRIVATE_SPACE, CREATE_TEAM_SPACE, MANAGE_TEAM_SPACE, INGEST,
    RECOVER, SPARQL_ADMIN, GRANT, READ_PRIVATE,
}

# Capabilities an admin may DELEGATE to another user via the grant endpoint.
# Admin-intrinsic caps (grant, sparql_admin) are intentionally NOT delegatable:
# they come only from an Admin/SuperAdmin role, so the grant endpoint cannot be
# used to escalate a non-admin into an admin.
GRANTABLE_CAPS = {
    CREATE_PRIVATE_SPACE, CREATE_TEAM_SPACE, MANAGE_TEAM_SPACE, INGEST,
    RECOVER, READ_PRIVATE,
}

# ---- role hierarchy / policy ----------------------------------------------
# Hierarchy (highest first): SuperAdmin >= Admin > write roles > read roles > none.
# SuperAdmin is the ultimate authority and is bootstrapped at deployment. Both
# SuperAdmin and Admin get every KG capability here; the *difference* between them
# (e.g. SuperAdmin creating/removing Admins) is ROLE ASSIGNMENT, which is owned by
# the usermanagement/Django side — query_service never assigns roles, it only
# reads them and grants delegatable KG capabilities. This keeps the two systems
# consistent and prevents privilege escalation through the KG API.
SUPERADMIN_ROLE = "SuperAdmin"
ADMIN_ROLES = {"Admin", "SuperAdmin"}
# Roles that confer "write" (may create their own private space + ingest).
WRITE_ROLES = {
    "Admin", "SuperAdmin", "Curator", "Lab Member", "Submitter",
    "Annotator", "Mapper", "Knowledge Contributor",
}


def _caps_for_role(role: str) -> Set[str]:
    if role in ADMIN_ROLES:
        return set(ALL_CAPS)                       # admins can do everything
    if role in WRITE_ROLES:
        return {CREATE_PRIVATE_SPACE, INGEST, RECOVER, READ_PRIVATE}
    # any other active role (Reviewer, Validator, Moderator, ...) = read member content
    return {READ_PRIVATE}


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

async def active_roles(email: Optional[str]) -> Set[str]:
    """Active, non-expired role names for the JWT user's email (via profile)."""
    if not email:
        return set()
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT r.role
            FROM "Web_user_role" r
            JOIN "Web_user_profile" p ON p.id = r.profile_id
            WHERE p.email = $1
              AND r.is_active IS TRUE
              AND (r.expires_at IS NULL OR r.expires_at > now())
            """,
            email,
        )
        return {row["role"] for row in rows}


async def granted_capabilities(email: Optional[str]) -> Set[str]:
    """Extra capabilities granted directly to this user (delegated upgrades)."""
    if not email:
        return set()
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            "SELECT capability FROM user_capability_grants WHERE member = $1",
            email,
        )
        return {row["capability"] for row in rows if row["capability"] in ALL_CAPS}


async def role_granted_capabilities(roles: Set[str]) -> Set[str]:
    """Capabilities attached to any of ``roles`` via role/group-level grants
    (role_capability_grants). Lets an admin grant a whole custom group/role a
    capability (e.g. give 'uk_collaborator' the ingest capability)."""
    if not roles:
        return set()
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            "SELECT capability FROM role_capability_grants WHERE role = ANY($1::text[])",
            list(roles),
        )
        return {row["capability"] for row in rows if row["capability"] in ALL_CAPS}


async def capabilities(email: Optional[str]) -> Set[str]:
    """Effective capabilities = role-derived caps ∪ role/group grants ∪ per-user grants."""
    caps: Set[str] = set()
    roles = await active_roles(email)
    for r in roles:
        caps |= _caps_for_role(r)
    if roles:  # only users with at least one role can be granted extras
        caps |= await role_granted_capabilities(roles)
        caps |= await granted_capabilities(email)
    return caps


async def has_capability(email: Optional[str], cap: str) -> bool:
    return cap in await capabilities(email)


async def is_admin(email: Optional[str]) -> bool:
    return bool(await active_roles(email) & ADMIN_ROLES)


# ---------------------------------------------------------------------------
# delegated grants (admin only — enforced at the endpoint)
# ---------------------------------------------------------------------------

async def grant_capability(member: str, capability: str, granted_by: str) -> None:
    if capability not in GRANTABLE_CAPS:
        raise ValueError(f"capability is not delegatable: {capability}")
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO user_capability_grants (member, capability, granted_by, created_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (member, capability) DO NOTHING
            """,
            member, capability, granted_by, time.time(),
        )


async def revoke_capability(member: str, capability: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            "DELETE FROM user_capability_grants WHERE member = $1 AND capability = $2",
            member, capability,
        )


async def list_grants(member: str) -> list:
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            "SELECT capability, granted_by, created_at FROM user_capability_grants WHERE member = $1",
            member,
        )
        return [dict(r) for r in rows]


# ---- role/group-level grants (admin only — enforced at the endpoint) --------

async def grant_role_capability(role: str, capability: str, granted_by: str) -> None:
    if capability not in GRANTABLE_CAPS:
        raise ValueError(f"capability is not delegatable: {capability}")
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO role_capability_grants (role, capability, granted_by, created_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (role, capability) DO NOTHING
            """,
            role, capability, granted_by, time.time(),
        )


async def revoke_role_capability(role: str, capability: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            "DELETE FROM role_capability_grants WHERE role = $1 AND capability = $2",
            role, capability,
        )


async def list_role_grants(role: Optional[str] = None) -> list:
    async with get_db_connection() as conn:
        if role:
            rows = await conn.fetch(
                "SELECT role, capability, granted_by, created_at FROM role_capability_grants WHERE role = $1 ORDER BY capability",
                role,
            )
        else:
            rows = await conn.fetch(
                "SELECT role, capability, granted_by, created_at FROM role_capability_grants ORDER BY role, capability"
            )
        return [dict(r) for r in rows]
