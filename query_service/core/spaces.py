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
                       visibility: str = "private") -> Dict[str, Any]:
    """Create a space and register the owner as a member with role 'owner'."""
    if visibility not in ("private", "public"):
        raise ValueError("visibility must be 'private' or 'public'")
    space_id = uuid.uuid4().hex
    now = time.time()
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO spaces (space_id, slug, name, description, owner, visibility, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                """,
                space_id, slug, name, description, owner, visibility, now,
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
