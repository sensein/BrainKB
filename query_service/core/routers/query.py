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

from fastapi import APIRouter
from core.graph_database_connection_manager import fetch_data_gdb, check_named_graph_exists
import logging
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import taxonomy_postprocessing
from fastapi import Depends
from pydantic import BaseModel, root_validator
from typing import List
router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/query/registered-named-graphs")
async def get_named_graphs():
    query_named_graph = """
          PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX dcterms: <http://purl.org/dc/terms/>
        Select distinct ?graph ?description ?registered_at
        WHERE  {
          GRAPH <https://brainkb.org/metadata/named-graph> {
            ?graph dcterms:description ?description;
               prov:generatedAtTime ?registered_at.
          } 
        }
    """
    response =  fetch_data_gdb(query_named_graph)

    response_graph = {}
    for graphs_info in response["message"]["results"]["bindings"]:
        response_graph[graphs_info["graph"]["value"]] = {
            "graph": graphs_info["graph"]["value"],
            "description": graphs_info["description"]["value"],
            "registered_at": graphs_info["registered_at"]["value"]
        }
    return response_graph


@router.get("/query/sparql/",
            dependencies=[Depends(require_scopes(["write","admin"]))],
            )
async def sparql_query(
    user: Annotated[LoginUserIn, Depends(get_current_user)], sparql_query: str
):
    response = fetch_data_gdb(sparql_query)
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

        SELECT ?id ?parent ?name ?hex
        WHERE {
            GRAPH <http://hmbataxonomy20250927.com/> {
                ?id a bican:CellTypeTaxon .
                OPTIONAL { ?id bican:has_parent ?parent . }
                OPTIONAL { ?id rdfs:label ?name . }

                # Find a DisplayColor node linked to this taxon
                OPTIONAL {
                    ?colorNode a bican:DisplayColor ;
                            bican:is_color_for_taxon ?cid ;
                            bican:color_hex_triplet ?hex .
                        FILTER(STR(?id) = STR(?cid))
                }
            }   
        }
    """
    response = fetch_data_gdb(query_taxonomy)
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


