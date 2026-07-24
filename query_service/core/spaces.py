# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @File    : spaces.py

"""
Spaces: owner-controlled containers of named graphs with private/public
visibility and team membership.

A space is a sovereign, IRI-addressable container (think Solid-style pod) that a
user or team owns. Named graphs belong to a space; ingestion into a graph is
allowed only for the owning space's owner/editors, while reads are allowed to
members always and to ANYONE (even anonymous) when the space is public.

Storage is hybrid (see SPACES_MODEL.md):
  * Postgres (spaces / space_members / space_graphs) is the enforcement source of
    truth — fast per-request authorization.
  * A best-effort RDF mirror in the spaces metadata graph makes space manifests
    portable/decentralizable and queryable via SPARQL.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
from rdflib import Graph, Literal, Namespace, URIRef, RDF
from rdflib.namespace import DCTERMS

from core.database import get_db_connection
from core.shared import get_oxigraph_auth
from core.graph_database_connection_manager import _get_endpoint
from core.provenance import agent_ref, BRAINKB, PROV

logger = logging.getLogger(__name__)

SPACES_METADATA_GRAPH = "https://brainkb.org/metadata/spaces/"
SPACE_BASE = "https://brainkb.org/space/"
SCHEMA = Namespace("https://schema.org/")

ROLES = ("owner", "editor", "viewer")
READ_ROLES = ("owner", "editor", "viewer")
WRITE_ROLES = ("owner", "editor")


def space_iri(slug: str) -> str:
    return f"{SPACE_BASE}{quote(str(slug), safe='')}"


# ---------------------------------------------------------------------------
# Postgres CRUD
# ---------------------------------------------------------------------------

async def create_space(slug: str, name: str, description: Optional[str], owner: str,
                       visibility: str = "private", space_type: str = "individual") -> Dict[str, Any]:
    """Create a space and register the owner as a member with role 'owner'."""
    if visibility not in ("private", "public"):
        raise ValueError("visibility must be 'private' or 'public'")
    if space_type not in ("individual", "team"):
        raise ValueError("space_type must be 'individual' or 'team'")
    space_id = uuid.uuid4().hex
    now = time.time()
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO spaces (space_id, slug, name, description, owner, visibility, space_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                """,
                space_id, slug, name, description, owner, visibility, space_type, now,
            )
            await conn.execute(
                """
                INSERT INTO space_members (space_id, member, role, added_at)
                VALUES ($1, $2, 'owner', $3)
                """,
                space_id, owner, now,
            )
    return await get_space(slug)


async def get_space(slug: str) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM spaces WHERE slug = $1", slug)
        if not row:
            return None
        members = await conn.fetch(
            "SELECT member, role FROM space_members WHERE space_id = $1 ORDER BY role, member",
            row["space_id"],
        )
        graphs = await conn.fetch(
            "SELECT named_graph_iri FROM space_graphs WHERE space_id = $1 ORDER BY named_graph_iri",
            row["space_id"],
        )
        return {
            "space_id": row["space_id"],
            "slug": row["slug"],
            "name": row["name"],
            "description": row["description"],
            "owner": row["owner"],
            "visibility": row["visibility"],
            "space_type": row.get("space_type", "individual"),
            "iri": space_iri(row["slug"]),
            "members": [{"member": m["member"], "role": m["role"]} for m in members],
            "graphs": [g["named_graph_iri"] for g in graphs],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


async def get_space_for_graph(named_graph_iri: str) -> Optional[Dict[str, Any]]:
    """Return the space that owns a named graph, or None if the graph is unmapped."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.* FROM spaces s
            JOIN space_graphs g ON g.space_id = s.space_id
            WHERE g.named_graph_iri = $1
            """,
            named_graph_iri,
        )
        if not row:
            return None
        return {
            "space_id": row["space_id"], "slug": row["slug"], "name": row["name"],
            "owner": row["owner"], "visibility": row["visibility"],
            "space_type": row.get("space_type", "individual"),
        }


async def hidden_graphs_for(member: Optional[str]) -> set:
    """
    Return the set of named-graph IRIs the caller must NOT see in listings: graphs
    belonging to a PRIVATE space the caller is not a member of. Public-space graphs
    and legacy (unmapped) graphs are never hidden. Anonymous callers (member=None)
    have every private-space graph hidden.
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT g.named_graph_iri
            FROM space_graphs g
            JOIN spaces s ON s.space_id = g.space_id
            WHERE s.visibility = 'private'
              AND NOT EXISTS (
                  SELECT 1 FROM space_members m
                  WHERE m.space_id = s.space_id AND m.member = $1
              )
            """,
            member,
        )
        return {r["named_graph_iri"] for r in rows}


async def member_role(space_id: str, member: Optional[str]) -> Optional[str]:
    if not member:
        return None
    async with get_db_connection() as conn:
        return await conn.fetchval(
            "SELECT role FROM space_members WHERE space_id = $1 AND member = $2",
            space_id, member,
        )


async def list_visible_spaces(member: Optional[str]) -> List[Dict[str, Any]]:
    """Spaces the caller may see: all public spaces plus any they are a member of.
    Anonymous callers (member=None) see only public spaces."""
    async with get_db_connection() as conn:
        if member:
            rows = await conn.fetch(
                """
                SELECT DISTINCT s.slug, s.name, s.description, s.owner, s.visibility, s.created_at
                FROM spaces s
                LEFT JOIN space_members m ON m.space_id = s.space_id AND m.member = $1
                WHERE s.visibility = 'public' OR m.member IS NOT NULL
                ORDER BY s.created_at DESC
                """,
                member,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT s.slug, s.name, s.description, s.owner, s.visibility, s.created_at
                FROM spaces s WHERE s.visibility = 'public'
                ORDER BY s.created_at DESC
                """,
            )
        return [
            {"slug": r["slug"], "name": r["name"], "description": r["description"],
             "owner": r["owner"], "visibility": r["visibility"], "iri": space_iri(r["slug"]),
             "created_at": r["created_at"]}
            for r in rows
        ]


async def add_member(space_id: str, member: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO space_members (space_id, member, role, added_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (space_id, member) DO UPDATE SET role = EXCLUDED.role
            """,
            space_id, member, role, time.time(),
        )


async def remove_member(space_id: str, member: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            "DELETE FROM space_members WHERE space_id = $1 AND member = $2 AND role <> 'owner'",
            space_id, member,
        )


async def set_visibility(slug: str, visibility: str) -> None:
    if visibility not in ("private", "public"):
        raise ValueError("visibility must be 'private' or 'public'")
    async with get_db_connection() as conn:
        await conn.execute(
            "UPDATE spaces SET visibility = $1, updated_at = $2 WHERE slug = $3",
            visibility, time.time(), slug,
        )


async def attach_graph(space_id: str, named_graph_iri: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO space_graphs (space_id, named_graph_iri, added_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (named_graph_iri) DO NOTHING
            """,
            space_id, named_graph_iri, time.time(),
        )
        # Point any already-indexed rows for this graph at the space so search
        # access-filtering picks up the (new) workspace immediately. Done inline
        # (not via core.search) to avoid an import cycle.
        await conn.execute(
            "UPDATE graph_search_index SET space_id = $1 WHERE named_graph_iri = $2",
            space_id, named_graph_iri,
        )


# ---------------------------------------------------------------------------
# Authorization (enforcement)
# ---------------------------------------------------------------------------

ACTIONS = ("read", "write", "manage")
RULE_SUBJECTS = ("global_role", "member", "space_role")
_SPACE_ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


async def add_access_rule(space_id: str, action: str, subject_type: str,
                          subject_value: str, created_by: str) -> None:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    if subject_type not in RULE_SUBJECTS:
        raise ValueError(f"subject_type must be one of {RULE_SUBJECTS}")
    if subject_type == "space_role" and subject_value not in _SPACE_ROLE_RANK:
        raise ValueError("space_role subject_value must be viewer/editor/owner")
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO space_access_rules (space_id, action, subject_type, subject_value, created_by, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (space_id, action, subject_type, subject_value) DO NOTHING
            """,
            space_id, action, subject_type, subject_value, created_by, time.time(),
        )


async def remove_access_rule(space_id: str, rule_id: int) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            "DELETE FROM space_access_rules WHERE id = $1 AND space_id = $2", rule_id, space_id
        )


async def list_access_rules(space_id: str, action: Optional[str] = None) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        if action:
            rows = await conn.fetch(
                "SELECT id, action, subject_type, subject_value FROM space_access_rules WHERE space_id=$1 AND action=$2 ORDER BY id",
                space_id, action)
        else:
            rows = await conn.fetch(
                "SELECT id, action, subject_type, subject_value FROM space_access_rules WHERE space_id=$1 ORDER BY action, id",
                space_id)
        return [dict(r) for r in rows]


async def matches_access_rule(space_id: str, action: str, email: Optional[str]) -> bool:
    """True iff the caller matches at least one access rule for (space, action).
    Pure rule match — no owner/admin bypass, no 'no rules' default."""
    from core import rbac
    rules = await list_access_rules(space_id, action)
    if not rules:
        return False
    roles = await rbac.active_roles(email)
    srole = await member_role(space_id, email)
    srank = _SPACE_ROLE_RANK.get(srole or "", 0)
    for r in rules:
        st, sv = r["subject_type"], r["subject_value"]
        if st == "global_role" and sv in roles:
            return True
        if st == "member" and email and sv == email:
            return True
        if st == "space_role" and srank >= _SPACE_ROLE_RANK.get(sv, 99):
            return True
    return False


async def space_action_permitted(space: Dict[str, Any], action: str, email: Optional[str]) -> bool:
    """
    Fine-grained per-space check for read/write. Returns True if the caller may do
    `action` in this space under the space's access rules.

    - Owner and global Admin/SuperAdmin always pass (no lockout).
    - No rules for the action -> True (the endpoint's normal capability / membership
      / visibility gates still apply separately).
    - Rules present -> caller must match at least one.
    """
    from core import rbac
    space_id = space["space_id"]
    if email and await member_role(space_id, email) == "owner":
        return True
    if await rbac.is_admin(email):
        return True
    if not await list_access_rules(space_id, action):
        return True
    return await matches_access_rule(space_id, action, email)


async def can_write_space(space: Dict[str, Any], email: Optional[str]) -> Tuple[bool, str]:
    """Whether ``email`` may WRITE (ingest) into ``space``. Write is GRANTED by any
    of:
      * global Admin/SuperAdmin,
      * owner/editor membership of the space,
      * a matching **write** access rule — by ``global_role`` (a group/role),
        ``member`` (an email), or ``space_role``.

    This is what lets an admin hand a whole group ingest access to a team space
    without adding every user as a member: add a write rule with
    ``subject_type=global_role`` (e.g. ``Lab Member``). The caller still needs the
    ``INGEST`` capability (a write-capable role) — enforced separately at the
    endpoint — so a read-only group can't ingest even with a write rule."""
    from core import rbac
    space_id = space["space_id"]
    if await rbac.is_admin(email):
        return True, "admin"
    role = await member_role(space_id, email)
    if role in WRITE_ROLES:
        return True, f"member ({role})"
    if await matches_access_rule(space_id, "write", email):
        return True, "space write access rule (group/role/member)"
    return False, ("requires owner/editor membership, or a space write access rule "
                   "granting your group/role write (ask an admin)")


async def authorize(named_graph_iri: str, member: Optional[str], need: str) -> Tuple[bool, str]:
    """
    Decide whether ``member`` (a user email, or None if anonymous) may read/write
    the given named graph, based on the owning space's visibility and membership.

    Backward-compat: a graph not mapped to any space is treated as legacy — access
    falls through to whatever scope check the endpoint already applied (returns
    allowed=True here). Only space-mapped graphs are governed by space ACL.
    """
    space = await get_space_for_graph(named_graph_iri)
    if space is None:
        return True, "legacy (unmapped) graph — governed by endpoint scope only"

    if need == "read":
        if space["visibility"] == "public":
            return True, "public space"
        role = await member_role(space["space_id"], member)
        if role in READ_ROLES:
            return True, f"member ({role})"
        return False, "private space — membership required"

    if need == "write":
        role = await member_role(space["space_id"], member)
        if role in WRITE_ROLES:
            return True, f"member ({role})"
        return False, "write requires owner/editor membership of the space"

    return False, f"unknown access mode: {need}"


# ---------------------------------------------------------------------------
# RDF mirror (best-effort, for portability / decentralization)
# ---------------------------------------------------------------------------

def _space_manifest_graph(space: Dict[str, Any]) -> Graph:
    g = Graph()
    g.bind("brainkb", BRAINKB)
    g.bind("prov", PROV)
    g.bind("dcterms", DCTERMS)
    g.bind("schema", SCHEMA)
    s = URIRef(space_iri(space["slug"]))
    g.add((s, RDF.type, BRAINKB.Space))
    g.add((s, BRAINKB.slug, Literal(space["slug"])))
    g.add((s, SCHEMA.name, Literal(space["name"])))
    if space.get("description"):
        g.add((s, DCTERMS.description, Literal(space["description"])))
    g.add((s, BRAINKB.visibility, Literal(space["visibility"])))
    g.add((s, BRAINKB.owner, agent_ref(space["owner"])))
    for m in space.get("members", []):
        pred = {"owner": BRAINKB.owner, "editor": BRAINKB.editor, "viewer": BRAINKB.viewer}[m["role"]]
        g.add((s, pred, agent_ref(m["member"])))
    for giri in space.get("graphs", []):
        g.add((s, BRAINKB.containsGraph, URIRef(giri)))
    return g


async def mirror_space_to_rdf(space: Dict[str, Any]) -> bool:
    """Upsert a space's manifest into the spaces metadata graph via SPARQL Update.
    Best-effort — a mirror failure never fails the enforcing Postgres operation."""
    try:
        s = space_iri(space["slug"])
        triples = _space_manifest_graph(space).serialize(format="nt")
        update = (
            f"DELETE {{ GRAPH <{SPACES_METADATA_GRAPH}> {{ <{s}> ?p ?o }} }} "
            f"WHERE {{ GRAPH <{SPACES_METADATA_GRAPH}> {{ <{s}> ?p ?o }} }} ; "
            f"INSERT DATA {{ GRAPH <{SPACES_METADATA_GRAPH}> {{ {triples} }} }}"
        )
        endpoint = _get_endpoint("post")  # .../update
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            resp = await client.post(endpoint, data={"update": update}, auth=auth)
        if resp.status_code in (200, 204):
            return True
        logger.warning("[spaces] RDF mirror failed (HTTP %s): %s", resp.status_code, (resp.text or "")[:400])
        return False
    except Exception as e:
        logger.warning(f"[spaces] Error mirroring space to RDF: {e}", exc_info=True)
        return False


async def construct_space_graphs(space: Dict[str, Any]) -> str:
    """SPARQL CONSTRUCT returning all triples across the space's named graphs."""
    graphs = space.get("graphs", [])
    if not graphs:
        return "CONSTRUCT {} WHERE {}"
    unions = " UNION ".join(f"{{ GRAPH <{g}> {{ ?s ?p ?o }} }}" for g in graphs)
    return f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ {unions} }}"
