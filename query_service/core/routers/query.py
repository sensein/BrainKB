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
# @File    : query.py
# @Software: PyCharm

from fastapi import APIRouter, HTTPException
from core.graph_database_connection_manager import fetch_data_gdb_async, check_named_graph_exists
import logging
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import taxonomy_postprocessing
from core import rbac
from fastapi import Depends
from pydantic import BaseModel, root_validator
from typing import List
router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/query/registered-named-graphs",
    dependencies=[Depends(require_scopes(["read"]))],
    summary="List registered named graphs (the registry/catalog)",
    description=(
        "Returns the **catalog of named graphs** that have been registered in "
        "BrainKB — i.e. *which* graphs exist and may be ingested into. Each entry "
        "carries its `description`, `registered_at` timestamp, and `registered_by` "
        "(the user who registered it). Data is read from the registry graph "
        "`https://brainkb.org/metadata/named-graph`.\n\n"
        "Visibility-filtered: graphs that belong to a **private space** the caller "
        "is not a member of are omitted (so private graph existence is not leaked). "
        "Public-space graphs and legacy (unmapped) graphs are always listed.\n\n"
        "This answers *\"what graphs are available?\"*. It is NOT a history of what "
        "was ingested — for the ingestion/activity history of a specific graph, use "
        "`GET /api/provenance/named-graph?iri=…`."
    ),
)
async def get_named_graphs(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    """List every registered named graph with its registration metadata,
    filtered so private-space graphs the caller can't access are hidden.

    Registry (catalog) view: one row per graph with description, when it was
    registered, and by whom. Contrast with /api/provenance/named-graph, which
    returns the PROV-O activity history (ingestions) that targeted a graph.
    """
    query_named_graph = """
          PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX dcterms: <http://purl.org/dc/terms/>
        Select distinct ?graph ?description ?registered_at ?registered_by
        WHERE  {
          GRAPH <https://brainkb.org/metadata/named-graph> {
            ?graph dcterms:description ?description;
               prov:generatedAtTime ?registered_at.
            OPTIONAL { ?graph prov:wasAttributedTo ?registered_by. }
          }
        }
    """
    response = await fetch_data_gdb_async(query_named_graph)

    if response.get("status") != "success":
        logger.error(f"Failed to fetch named graphs: {response.get('message')}")
        return {"error": "Failed to fetch named graphs", "details": response.get("message")}

    response_graph = {}
    for graphs_info in response["message"]["results"]["bindings"]:
        response_graph[graphs_info["graph"]["value"]] = {
            "graph": graphs_info["graph"]["value"],
            "description": graphs_info["description"]["value"],
            "registered_at": graphs_info["registered_at"]["value"],
            "registered_by": graphs_info.get("registered_by", {}).get("value"),
        }

    # Hide graphs belonging to private spaces the caller is not a member of, so
    # private graph existence is not leaked via the registry listing.
    from core.spaces import hidden_graphs_for
    try:
        member = user["email"]
    except (KeyError, TypeError, IndexError):
        member = None
    hidden = await hidden_graphs_for(member)
    if hidden:
        response_graph = {k: v for k, v in response_graph.items() if k not in hidden}
    return response_graph


@router.get("/query/sparql/",
            dependencies=[Depends(require_scopes(["admin"]))],
            summary="Run an arbitrary SPARQL query (admin only)",
            description=(
                "Executes a caller-supplied SPARQL query against the graph database. "
                "This is a powerful, unrestricted capability, so it is gated to the "
                "**admin** scope only — deliberately NOT the default 'read' scope that "
                "the fixed-shape read endpoints (e.g. /query/taxonomy, /query/"
                "registered-named-graphs) use."
            ),
            )
async def sparql_query(
    user: Annotated[LoginUserIn, Depends(get_current_user)], sparql_query: str
):
    # Authorization is role-based: arbitrary SPARQL requires the sparql_admin
    # capability (Admin/SuperAdmin). The JWT scope only gates API access.
    try:
        email = user["email"]
    except (KeyError, TypeError, IndexError):
        email = None
    if not await rbac.has_capability(email, rbac.SPARQL_ADMIN):
        raise HTTPException(status_code=403, detail="Arbitrary SPARQL requires an Admin/SuperAdmin role.")
    response = await fetch_data_gdb_async(sparql_query)
    return response

@router.get("/query/taxonomy",
            dependencies=[Depends(require_scopes(["read"]))],)
async def get_taxonomy(
        user: Annotated[LoginUserIn, Depends(get_current_user)]
):
    query_taxonomy = """
        PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
        PREFIX DHBA: <https://purl.brain-bican.org/ontology/dmbao/DMBA_>

        SELECT ?id ?name ?accession_id ?parentNode ?abbrNode ?abbrMeaning ?abbrTerm ?parcellationTerm ?geneAnnotation ?cellType ?hex ?setAccessionId
        WHERE {
            # 1. Find all CellTypeTaxon nodes
            ?id a bican:CellTypeTaxon .

            # 2. Get CellTypeTaxon name
            OPTIONAL { ?id rdfs:label ?name . }

            # 3. Get CellTypeTaxon accession_id
            OPTIONAL { ?id bican:accession_id ?accession_id . }

            # 4. Get CellTypeTaxon Parent Node
            OPTIONAL { 
                ?id bican:has_parent ?parentNode . 
            }

            # 5. Get CellTypeTaxon Abbreviation Nodes
            OPTIONAL {
                ?id bican:has_abbreviation ?abbrNode .
                ?abbrNode a bican:Abbreviation ;
                    bican:meaning ?abbrMeaning ;
                    bican:term ?abbrTerm .
                OPTIONAL { ?abbrNode bican:denotes_parcellation_term ?parcellationTerm . }
                OPTIONAL { ?abbrNode bican:denotes_gene_annotation    ?geneAnnotation . }
                OPTIONAL { ?abbrNode bican:denotes_cell_type          ?cellType . }            
            }

            # 6. Get CellTypeTaxon Color Hex Triplet
            OPTIONAL {
                ?colorNode a bican:DisplayColor ;
                        bican:is_color_for_taxon ?cid ;
                        bican:color_hex_triplet ?hex .
                FILTER(STR(?id) = STR(?cid))
            }

            # 7. Get CellTypeSet Node
            OPTIONAL {
                ?cellTypeSetNode a bican:CellTypeSet ;
                        bican:contains_taxon ?id ;
                        bican:accession_id ?setAccessionId .
            }


        }
    """
    response = await fetch_data_gdb_async(query_taxonomy)
    
    if response.get("status") != "success":
        logger.error(f"Failed to fetch taxonomy: {response.get('message')}")
        return {"error": "Failed to fetch taxonomy", "details": response.get("message")}
    
    response_taxonomy = {}
    for taxon_info in response["message"]["results"]["bindings"]:
        response_taxonomy[taxon_info["id"]["value"]] = {
            "id": taxon_info["id"]["value"],
            "parent": taxon_info.get("parent", {}).get("value"),
            "name": taxon_info.get("name", {}).get("value"),
            "hex": taxon_info.get("hex", {}).get("value"),
        }
    processed_taxonomy = taxonomy_postprocessing(response_taxonomy)
    return processed_taxonomy

#! TODO: Update lines 119-126 with this:
# data = {}
# for row in response:
#     id_, name, accession_id, parentNode, abbrNode, abbrMeaning, abbrTerm, parcellationTerm, geneAnnotation, cellType, hex_, setAccessionId = row
#     id_ = str(id_)
#     name = str(name) if name else None
#     accession_id = str(accession_id) if accession_id else None
#     parentNode = str(parentNode) if parentNode else None
#     abbrNode = str(abbrNode) if abbrNode else None
#     abbrMeaning = str(abbrMeaning) if abbrMeaning else None
#     abbrTerm = str(abbrTerm) if abbrTerm else None
#     denotes = str(parcellationTerm) if parcellationTerm else None
#     denotes = str(geneAnnotation) if geneAnnotation else denotes
#     denotes = str(cellType) if cellType else denotes
#     hex_ = str(hex_) if hex_ else None

#     if str(id_) in data:
#         if abbrNode in data[id_]["abbreviations"]:
#             if denotes:
#                 data[id_]["abbreviations"][abbrNode]["denotes"].append(denotes)
#         else:
#             data[id_]["abbreviations"][abbrNode] = {"term": abbrTerm, "meaning": abbrMeaning, "denotes": [denotes]}
#     else:
#         data[id_] = {
#             "name": name,
#             "accession_id": accession_id,
#             "parent": parentNode,
#             "abbreviations": dict({abbrNode: {"term": abbrTerm,  "meaning": abbrMeaning, "denotes": [denotes]}}) if abbrNode else {},
#             "hex": hex_,
#             "belongs_to_set": setAccessionId
#         }


