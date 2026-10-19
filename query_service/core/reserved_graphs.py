"""Reserved named graphs: IRIs (exact, or every IRI under a prefix) that only an
Admin/SuperAdmin may register or bind to a space, optionally reserved for one space
whose managers/editors may then bind it too.

Two kinds:

* **System** (built in, cannot be removed): BrainKB's own metadata and provenance
  graphs. Nobody — admins included — may register them or bind them to a space,
  since that would put the graph registry or the provenance record under a space's
  access rules.
* **Admin-managed** (the ``reserved_graphs`` table): created and removed by an
  Admin/SuperAdmin. A reservation governs *future* registration and binding; a
  graph already bound when it is reserved stays where it is.

Enforced where graphs come into existence: ``POST /spaces/{slug}/graphs`` and
``POST /api/register-named-graph``.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from core.database import get_db_connection
from core import rbac

SYSTEM_RESERVED_PREFIXES: Tuple[str, ...] = (
    "https://brainkb.org/metadata/",
    "https://brainkb.org/provenance/",
)
MATCH_TYPES = ("exact", "prefix")


def normalize(iri: str) -> str:
    """The same normalisation graph registration applies (a trailing slash)."""
    iri = str(iri or "").strip()
    return iri if iri.endswith("/") else iri + "/"


def _system_entry(prefix: str) -> Dict[str, Any]:
    return {"id": None, "iri": prefix, "match_type": "prefix", "system": True,
            "reason": "BrainKB system graph (registry / provenance)", "space_slug": None}


def _system_hit(iri: str) -> Optional[Dict[str, Any]]:
    for prefix in SYSTEM_RESERVED_PREFIXES:
        if iri.startswith(prefix):
            return _system_entry(prefix)
    return None


def _row(r) -> Dict[str, Any]:
    return {"id": r["id"], "iri": r["iri"], "match_type": r["match_type"], "system": False,
            "reason": r["reason"], "space_id": r["space_id"], "space_slug": r["space_slug"],
            "created_by": r["created_by"], "created_at": r["created_at"]}


_SELECT = ("SELECT r.id, r.iri, r.match_type, r.reason, r.space_id, s.slug AS space_slug, "
           "r.created_by, r.created_at FROM reserved_graphs r LEFT JOIN spaces s USING (space_id)")


async def find(iri: str) -> Optional[Dict[str, Any]]:
    """The reservation covering this graph IRI, if any: system first, then an exact
    reservation, then the longest matching prefix."""
    iri = normalize(iri)
    hit = _system_hit(iri)
    if hit:
        return hit
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            _SELECT + " WHERE (r.match_type = 'exact' AND r.iri = $1) "
                      "OR (r.match_type = 'prefix' AND starts_with($1, r.iri)) "
                      "ORDER BY (r.match_type = 'exact') DESC, length(r.iri) DESC LIMIT 1",
            iri,
        )
    return _row(rows[0]) if rows else None


async def check_allowed(iri: str, email: Optional[str], space_id: Optional[str] = None) -> Tuple[bool, str]:
    """May this caller register / bind this graph (into ``space_id``, if binding)?

    The caller has already passed the endpoint's own checks (may manage or write the
    space). System graphs: nobody. Admin-managed: Admin/SuperAdmin always; anyone the
    endpoint allowed on the space it is reserved for; nobody else."""
    res = await find(iri)
    if res is None:
        return True, ""
    if res["system"]:
        return False, f"'{normalize(iri)}' is a reserved BrainKB system graph and cannot be registered or bound"
    if await rbac.is_admin(email):
        return True, ""
    if res.get("space_id") and space_id and res["space_id"] == space_id:
        return True, ""
    scope = f" for space '{res['space_slug']}'" if res.get("space_slug") else ""
    why = f" ({res['reason']})" if res.get("reason") else ""
    return False, (f"'{normalize(iri)}' is reserved{scope}{why}; only an Admin/SuperAdmin"
                   + (" or that space's managers" if scope else "") + " may register or bind it")


async def list_all() -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        rows = await conn.fetch(_SELECT + " ORDER BY r.iri")
    system = [_system_entry(p) for p in SYSTEM_RESERVED_PREFIXES]
    return system + [_row(r) for r in rows]


class ReservationConflict(Exception):
    pass


async def add(iri: str, match_type: str, reason: Optional[str], created_by: str,
              space_id: Optional[str] = None) -> Dict[str, Any]:
    """Reserve an IRI or prefix. Returns the reservation plus the graphs it already
    covers (left where they are). Raises ReservationConflict when it duplicates an
    existing reservation, overlaps a system graph, or is reserved for a space while
    the exact graph is already bound to a different space."""
    if match_type not in MATCH_TYPES:
        raise ValueError(f"match_type must be one of {MATCH_TYPES}")
    iri = normalize(iri)
    if not iri.startswith(("http://", "https://")) or any(c in iri for c in '<>"{}|\\^` '):
        raise ValueError("iri must be an absolute http(s) IRI")
    if _system_hit(iri) or any(p.startswith(iri) for p in SYSTEM_RESERVED_PREFIXES):
        raise ReservationConflict("overlaps a BrainKB system graph, which is always reserved")
    async with get_db_connection() as conn:
        if match_type == "exact":
            covered = await conn.fetch(
                "SELECT g.named_graph_iri, s.slug, g.space_id FROM space_graphs g "
                "JOIN spaces s USING (space_id) WHERE g.named_graph_iri = $1", iri)
        else:
            covered = await conn.fetch(
                "SELECT g.named_graph_iri, s.slug, g.space_id FROM space_graphs g "
                "JOIN spaces s USING (space_id) WHERE starts_with(g.named_graph_iri, $1) "
                "ORDER BY g.named_graph_iri", iri)
        if space_id and match_type == "exact" and covered and covered[0]["space_id"] != space_id:
            raise ReservationConflict(
                f"'{iri}' is already bound to space '{covered[0]['slug']}'; it cannot be reserved for another space")
        row = await conn.fetchrow(
            "INSERT INTO reserved_graphs (iri, match_type, reason, space_id, created_by, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (iri, match_type) DO NOTHING RETURNING id",
            iri, match_type, reason, space_id, created_by, time.time())
        if row is None:
            raise ReservationConflict(f"'{iri}' ({match_type}) is already reserved")
        full = await conn.fetchrow(_SELECT + " WHERE r.id = $1", row["id"])
    out = _row(full)
    out["already_bound"] = [{"graph": c["named_graph_iri"], "space": c["slug"]} for c in covered]
    return out


async def remove(reservation_id: int) -> bool:
    async with get_db_connection() as conn:
        status = await conn.execute("DELETE FROM reserved_graphs WHERE id = $1", reservation_id)
    return status.endswith(" 1")
