# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : provenance.py
# @Software: PyCharm

"""
Native PROV-O provenance tracking in Oxigraph.

BrainKB stores knowledge in a triplestore, so provenance is tracked as W3C
PROV-O triples written to a dedicated provenance named graph and queried with
SPARQL. See PROVENANCE_MODEL.md for the full design.

This module is intentionally self-contained and best-effort: helpers here build
and persist provenance, but callers must ensure a provenance failure never fails
the underlying operation (wrap calls in try/except).
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from rdflib import Graph, Literal, Namespace, URIRef, RDF, XSD, DCTERMS

from core.shared import get_oxigraph_endpoint, get_oxigraph_auth
from core.graph_database_connection_manager import _get_endpoint

logger = logging.getLogger(__name__)

# Dedicated named graph holding all provenance.
PROVENANCE_GRAPH = "https://brainkb.org/provenance/"

# Per-job delta graphs live under this base. Each ingestion job stages its
# triples in its own delta graph, giving an exact, queryable record of what that
# job added (triple-level change tracking) before/after merging into the target.
PROVENANCE_DELTA_BASE = "https://brainkb.org/provenance/delta/"

# Namespaces
PROV = Namespace("http://www.w3.org/ns/prov#")
BRAINKB = Namespace("https://brainkb.org/vocab/")          # custom vocabulary
PROV_BASE = Namespace("https://brainkb.org/prov/")          # instance IRIs


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _new_graph() -> Graph:
    g = Graph()
    g.bind("prov", PROV)
    g.bind("brainkb", BRAINKB)
    g.bind("dcterms", DCTERMS)
    return g


def agent_ref(agent_id: str) -> URIRef:
    """Mint the agent IRI for a user/system identifier."""
    return URIRef(PROV_BASE[f"agent/{quote(str(agent_id), safe='')}"])


def activity_ref(job_id: str) -> URIRef:
    return URIRef(PROV_BASE[f"activity/{quote(str(job_id), safe='')}"])


def delta_graph_for(job_id: str) -> str:
    """The per-job delta graph IRI (holds exactly the triples this job added)."""
    return f"{PROVENANCE_DELTA_BASE}{quote(str(job_id), safe='')}"


# ---------------------------------------------------------------------------
# Builders — each returns an rdflib Graph of PROV-O triples
# ---------------------------------------------------------------------------

def build_ingestion_provenance(
    *,
    job_id: str,
    agent_id: str,
    named_graph_iri: str,
    started_at: str,
    ended_at: str,
    status: str,
    total_files: int,
    success_count: int,
    fail_count: int,
    results: Optional[List[Dict[str, Any]]] = None,
    agent_type: str = "user",
    delta_graph: Optional[str] = None,
    added_triple_count: Optional[int] = None,
) -> Graph:
    """Build the PROV-O bundle for a completed (terminal) ingestion job.

    When ``delta_graph`` is given, a ``brainkb:IngestionDelta`` entity is added
    describing the incremental change: which named graph it derives from, the
    delta graph holding the exact added triples, and (optionally) the count.
    """
    g = _new_graph()

    activity = activity_ref(job_id)
    bundle = URIRef(PROV_BASE[f"bundle/{quote(str(job_id), safe='')}"])
    agent = agent_ref(agent_id)

    # Agent
    g.add((agent, RDF.type, PROV.Agent))
    g.add((agent, RDF.type, PROV.SoftwareAgent if agent_type == "system" else PROV.Person))

    # Activity
    g.add((activity, RDF.type, PROV.Activity))
    g.add((activity, RDF.type, BRAINKB.IngestionActivity))
    g.add((activity, PROV.startedAtTime, Literal(started_at, datatype=XSD.dateTime)))
    g.add((activity, PROV.endedAtTime, Literal(ended_at, datatype=XSD.dateTime)))
    g.add((activity, PROV.wasAssociatedWith, agent))
    g.add((activity, BRAINKB.targetGraph, URIRef(named_graph_iri)))
    g.add((activity, BRAINKB.jobStatus, Literal(status)))
    g.add((activity, BRAINKB.totalFiles, Literal(int(total_files), datatype=XSD.integer)))
    g.add((activity, BRAINKB.successCount, Literal(int(success_count), datatype=XSD.integer)))
    g.add((activity, BRAINKB.failCount, Literal(int(fail_count), datatype=XSD.integer)))

    # Ingested bundle entity
    g.add((bundle, RDF.type, PROV.Entity))
    g.add((bundle, PROV.wasGeneratedBy, activity))
    g.add((bundle, PROV.wasAttributedTo, agent))
    g.add((bundle, PROV.generatedAtTime, Literal(ended_at, datatype=XSD.dateTime)))
    g.add((bundle, DCTERMS.isPartOf, URIRef(named_graph_iri)))

    # Per-file entities
    for r in results or []:
        fname = str(r.get("file", "unknown"))
        file_entity = URIRef(PROV_BASE[f"file/{quote(str(job_id), safe='')}/{quote(fname, safe='')}"])
        g.add((file_entity, RDF.type, PROV.Entity))
        g.add((file_entity, PROV.wasGeneratedBy, activity))
        g.add((file_entity, DCTERMS.isPartOf, bundle))
        g.add((file_entity, BRAINKB.fileName, Literal(fname)))
        g.add((file_entity, BRAINKB.uploadStatus, Literal("success" if r.get("success") else "failed")))
        if r.get("http_status") is not None:
            g.add((file_entity, BRAINKB.httpStatus, Literal(int(r["http_status"]), datatype=XSD.integer)))
        if r.get("size_bytes") is not None:
            g.add((file_entity, BRAINKB.sizeBytes, Literal(int(r["size_bytes"]), datatype=XSD.integer)))

    # Incremental-change (delta) entity: an isolated, queryable record of exactly
    # the triples this job contributed to the target graph.
    if delta_graph:
        delta = URIRef(PROV_BASE[f"delta/{quote(str(job_id), safe='')}"])
        g.add((delta, RDF.type, PROV.Entity))
        g.add((delta, RDF.type, BRAINKB.IngestionDelta))
        g.add((delta, PROV.wasGeneratedBy, activity))
        # The change derives from (is applied to) the target named graph
        g.add((delta, PROV.wasDerivedFrom, URIRef(named_graph_iri)))
        g.add((delta, BRAINKB.changeType, Literal("addition")))
        g.add((delta, BRAINKB.targetGraph, URIRef(named_graph_iri)))
        g.add((delta, BRAINKB.deltaGraph, URIRef(delta_graph)))
        g.add((delta, DCTERMS.isPartOf, bundle))
        g.add((delta, PROV.generatedAtTime, Literal(ended_at, datatype=XSD.dateTime)))
        if added_triple_count is not None:
            g.add((delta, BRAINKB.addedTripleCount, Literal(int(added_triple_count), datatype=XSD.integer)))

    return g


def build_registration_provenance(
    *,
    named_graph_url: str,
    agent_id: str,
    at: Optional[str] = None,
) -> Graph:
    """Build PROV-O for a named-graph registration (agent: user)."""
    g = _new_graph()
    at = at or _now_iso()
    activity = URIRef(PROV_BASE[f"activity/reg-{uuid.uuid4().hex}"])
    agent = agent_ref(agent_id)

    g.add((agent, RDF.type, PROV.Agent))
    g.add((agent, RDF.type, PROV.Person))
    g.add((activity, RDF.type, PROV.Activity))
    g.add((activity, RDF.type, BRAINKB.RegistrationActivity))
    g.add((activity, PROV.startedAtTime, Literal(at, datatype=XSD.dateTime)))
    g.add((activity, PROV.wasAssociatedWith, agent))
    g.add((activity, BRAINKB.targetGraph, URIRef(named_graph_url)))
    g.add((URIRef(named_graph_url), PROV.wasGeneratedBy, activity))
    return g


def build_recovery_provenance(
    *,
    job_id: str,
    at: Optional[str] = None,
    cause: str = "",
) -> Graph:
    """Build PROV-O for an automated crash-recovery action (agent: system)."""
    g = _new_graph()
    at = at or _now_iso()
    ts = at.replace(":", "").replace("-", "").replace(".", "")
    activity = URIRef(PROV_BASE[f"activity/rec-{quote(str(job_id), safe='')}-{quote(ts, safe='')}"])
    system_agent = agent_ref("system")

    g.add((system_agent, RDF.type, PROV.Agent))
    g.add((system_agent, RDF.type, PROV.SoftwareAgent))
    g.add((activity, RDF.type, PROV.Activity))
    g.add((activity, RDF.type, BRAINKB.RecoveryActivity))
    g.add((activity, PROV.startedAtTime, Literal(at, datatype=XSD.dateTime)))
    g.add((activity, PROV.wasAssociatedWith, system_agent))
    # Link the recovery activity to the ingestion activity it acted upon
    g.add((activity, PROV.used, activity_ref(job_id)))
    if cause:
        g.add((activity, DCTERMS.description, Literal(cause)))
    return g


# ---------------------------------------------------------------------------
# Persistence + retrieval
# ---------------------------------------------------------------------------

async def write_provenance(graph: Graph) -> bool:
    """
    Append PROV-O triples to the provenance named graph via Oxigraph's Graph
    Store HTTP protocol (POST merges into the graph). Best-effort: returns True
    on success, False on failure (never raises).
    """
    if graph is None or len(graph) == 0:
        return True
    try:
        payload = graph.serialize(format="turtle")
        endpoint = get_oxigraph_endpoint()  # .../store
        url = f"{endpoint}?graph={quote(PROVENANCE_GRAPH, safe='')}"
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            resp = await client.post(
                url,
                content=payload.encode("utf-8"),
                headers={"Content-Type": "text/turtle"},
                auth=auth,
            )
        if resp.status_code in (200, 201, 204):
            return True
        logger.warning(
            "[provenance] Failed to write provenance (HTTP %s): %s",
            resp.status_code, (resp.text or "")[:500],
        )
        return False
    except Exception as e:
        logger.warning(f"[provenance] Error writing provenance: {e}", exc_info=True)
        return False


async def merge_delta_into_target(delta_graph: str, target_graph: str) -> bool:
    """
    Copy all triples from a per-job delta graph into the target named graph via
    SPARQL Update ADD (server-side; the delta graph is preserved as the change
    record). Best-effort: returns True on success, False otherwise.
    """
    try:
        update = f"ADD SILENT <{delta_graph}> TO <{target_graph}>"
        endpoint = _get_endpoint("post")  # .../update for OXIGRAPH
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
            resp = await client.post(endpoint, data={"update": update}, auth=auth)
        if resp.status_code in (200, 204):
            return True
        logger.warning(
            "[provenance] Delta merge failed (HTTP %s): %s",
            resp.status_code, (resp.text or "")[:500],
        )
        return False
    except Exception as e:
        logger.warning(f"[provenance] Error merging delta graph: {e}", exc_info=True)
        return False


async def count_graph_triples(graph_iri: str) -> Optional[int]:
    """Count triples in a named graph. Returns None on error."""
    try:
        query = f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{graph_iri}> {{ ?s ?p ?o }} }}"
        endpoint = _get_endpoint("get")  # .../query for OXIGRAPH
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(
                endpoint,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
                auth=auth,
            )
        if resp.status_code != 200:
            return None
        bindings = resp.json().get("results", {}).get("bindings", [])
        return int(bindings[0]["n"]["value"]) if bindings else 0
    except Exception as e:
        logger.warning(f"[provenance] Error counting triples in {graph_iri}: {e}", exc_info=True)
        return None


async def query_provenance_jsonld(construct_query: str) -> Optional[str]:
    """
    Execute a SPARQL CONSTRUCT against Oxigraph and return JSON-LD text.
    Returns None on error.

    Oxigraph does not serialize CONSTRUCT results as JSON-LD (it offers
    Turtle / N-Triples / N-Quads / RDF-XML), so we request Turtle and convert to
    JSON-LD locally with rdflib. This keeps the JSON-LD API contract independent
    of the triplestore's supported output formats.
    """
    try:
        endpoint = _get_endpoint("get")  # .../query for OXIGRAPH
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(
                endpoint,
                data={"query": construct_query},
                headers={"Accept": "text/turtle"},
                auth=auth,
            )
        if resp.status_code != 200:
            logger.warning(
                "[provenance] CONSTRUCT query failed (HTTP %s): %s",
                resp.status_code, (resp.text or "")[:500],
            )
            return None
        g = Graph()
        g.parse(data=resp.text, format="turtle")
        g.bind("prov", PROV)
        g.bind("brainkb", BRAINKB)
        g.bind("dcterms", DCTERMS)
        return g.serialize(format="json-ld", auto_compact=True)
    except Exception as e:
        logger.warning(f"[provenance] Error querying provenance: {e}", exc_info=True)
        return None


def construct_for_job(job_id: str) -> str:
    """SPARQL CONSTRUCT for all provenance about a single job (activity, bundle,
    per-file entities, and the connected agent)."""
    activity = str(activity_ref(job_id))
    bundle = str(URIRef(PROV_BASE[f"bundle/{quote(str(job_id), safe='')}"]))
    delta = str(URIRef(PROV_BASE[f"delta/{quote(str(job_id), safe='')}"]))
    file_prefix = f"{str(PROV_BASE)}file/{quote(str(job_id), safe='')}/"
    return f"""
    CONSTRUCT {{ ?s ?p ?o }}
    WHERE {{
      GRAPH <{PROVENANCE_GRAPH}> {{
        {{ <{activity}> ?p ?o . BIND(<{activity}> AS ?s) }}
        UNION
        {{ <{bundle}> ?p ?o . BIND(<{bundle}> AS ?s) }}
        UNION
        {{ <{delta}> ?p ?o . BIND(<{delta}> AS ?s) }}
        UNION
        {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s), "{file_prefix}")) }}
        UNION
        {{ <{activity}> (<{PROV.wasAssociatedWith}>|<{PROV.used}>) ?s . ?s ?p ?o }}
        UNION
        {{ <{bundle}> <{PROV.wasAttributedTo}> ?s . ?s ?p ?o }}
        UNION
        {{ ?s <{PROV.used}> <{activity}> . ?s ?p ?o }}
        UNION
        {{ ?rec <{PROV.used}> <{activity}> ; <{PROV.wasAssociatedWith}> ?s . ?s ?p ?o }}
      }}
    }}
    """


def construct_delta_content(job_id: str) -> str:
    """SPARQL CONSTRUCT returning the exact triples a job added (its delta graph)."""
    dg = delta_graph_for(job_id)
    return f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{dg}> {{ ?s ?p ?o }} }}"


async def _fetch_construct_graph(construct_query: str) -> Optional[Graph]:
    """Run a CONSTRUCT and return the result parsed into an rdflib Graph."""
    try:
        endpoint = _get_endpoint("get")
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            resp = await client.post(
                endpoint,
                data={"query": construct_query},
                headers={"Accept": "text/turtle"},
                auth=auth,
            )
        if resp.status_code != 200:
            logger.warning(
                "[provenance] CONSTRUCT fetch failed (HTTP %s): %s",
                resp.status_code, (resp.text or "")[:500],
            )
            return None
        g = Graph()
        g.parse(data=resp.text, format="turtle")
        return g
    except Exception as e:
        logger.warning(f"[provenance] Error fetching graph: {e}", exc_info=True)
        return None


async def delta_history_for_graph(named_graph_iri: str) -> Optional[List[Dict[str, Any]]]:
    """
    Return the change history for a named graph: one entry per ingestion delta
    (job, added triple count, timestamp, status), newest first.
    """
    query = f"""
    PREFIX prov: <{str(PROV)}>
    PREFIX brainkb: <{str(BRAINKB)}>
    SELECT ?delta ?activity ?count ?time ?status ?deltaGraph
    WHERE {{
      GRAPH <{PROVENANCE_GRAPH}> {{
        ?delta a brainkb:IngestionDelta ;
               brainkb:targetGraph <{named_graph_iri}> ;
               prov:wasGeneratedBy ?activity .
        OPTIONAL {{ ?delta brainkb:addedTripleCount ?count }}
        OPTIONAL {{ ?delta prov:generatedAtTime ?time }}
        OPTIONAL {{ ?delta brainkb:deltaGraph ?deltaGraph }}
        OPTIONAL {{ ?activity brainkb:jobStatus ?status }}
      }}
    }}
    ORDER BY DESC(?time)
    """
    try:
        endpoint = _get_endpoint("get")
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(
                endpoint,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
                auth=auth,
            )
        if resp.status_code != 200:
            return None
        out = []
        for b in resp.json().get("results", {}).get("bindings", []):
            out.append({
                "delta": b.get("delta", {}).get("value"),
                "activity": b.get("activity", {}).get("value"),
                "added_triple_count": int(b["count"]["value"]) if "count" in b else None,
                "generated_at": b.get("time", {}).get("value"),
                "status": b.get("status", {}).get("value"),
                "delta_graph": b.get("deltaGraph", {}).get("value"),
            })
        return out
    except Exception as e:
        logger.warning(f"[provenance] Error fetching delta history: {e}", exc_info=True)
        return None


async def compare_deltas(job_id_a: str, job_id_b: str) -> Optional[Dict[str, Any]]:
    """
    Compare the triples added by two jobs. Returns counts and the differing
    triples (A-only / B-only) as JSON-LD, plus the shared-triple count.
    """
    ga = await _fetch_construct_graph(construct_delta_content(job_id_a))
    gb = await _fetch_construct_graph(construct_delta_content(job_id_b))
    if ga is None or gb is None:
        return None

    only_a = ga - gb          # in A, not in B
    only_b = gb - ga          # in B, not in A
    common = ga & gb          # in both

    def _jsonld(graph: Graph):
        graph.bind("prov", PROV)
        graph.bind("brainkb", BRAINKB)
        graph.bind("dcterms", DCTERMS)
        return json.loads(graph.serialize(format="json-ld", auto_compact=True))

    return {
        "job_a": job_id_a,
        "job_b": job_id_b,
        "a_total": len(ga),
        "b_total": len(gb),
        "only_in_a_count": len(only_a),
        "only_in_b_count": len(only_b),
        "common_count": len(common),
        "only_in_a": _jsonld(only_a),
        "only_in_b": _jsonld(only_b),
    }


def construct_for_named_graph(named_graph_iri: str) -> str:
    """SPARQL CONSTRUCT for all activity that targeted a given named graph."""
    return f"""
    CONSTRUCT {{ ?activity ?p ?o . ?ent ?ep ?eo }}
    WHERE {{
      GRAPH <{PROVENANCE_GRAPH}> {{
        ?activity <{BRAINKB.targetGraph}> <{named_graph_iri}> ;
                  ?p ?o .
        OPTIONAL {{ ?ent <{PROV.wasGeneratedBy}> ?activity ; ?ep ?eo . }}
      }}
    }}
    """
