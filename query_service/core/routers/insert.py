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
# @File    : insert.py
# @Software: PyCharm


from fastapi import APIRouter, Request, HTTPException, status
from core.graph_database_connection_manager import insert_data_gdb
import json
import logging
from core.pydantic_schema import InputKGTripleSchema, NamedGraphSchema
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from fastapi import Depends
from core.shared import convert_ttl_to_named_graph, named_graph_metadata
from core.graph_database_connection_manager import  fetch_data_gdb
import datetime
router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/insert/knowledge-graph-triples/",
             include_in_schema=True
             )
async def insert_knowledge_graph_triples(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
        request: InputKGTripleSchema
):
    try:
        data = json.loads(request.json())
        logger.info(f"Received data: {data}")
        if data["type"] == "ttl":
            named_graph_ttl = convert_ttl_to_named_graph(ttl_str=data["kg_data"],
                                                         named_graph_uri=data["named_graph_iri"])
            response = insert_data_gdb(named_graph_ttl)
            return response

    except json.JSONDecodeError as e:
        logger.error("JSON decoding failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON format"
        )
    except Exception as e:
        logger.error("An error occurred", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred processing the request",
        )
@router.post("/register-named-graph/")
async def create_named_graph(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        request: NamedGraphSchema
):
    try:
        data = json.loads(request.json())

        # Ensure named_graph_url ends with '/'
        named_graph_url = data['named_graph_url']
        description = data['description']
        if not named_graph_url.endswith('/'):
            named_graph_url += '/'

        query = f"""
        ASK WHERE {{
          GRAPH <https://brainkb.org/metadata/named-graph> {{
            ?s ?p ?o.
            FILTER(?s = <{named_graph_url}>)
          }}
        }}
        """
        named_graph_exists = fetch_data_gdb(query)
        if not named_graph_exists["message"]["boolean"]:

            response = insert_data_gdb(named_graph_metadata(
                named_graph_url=named_graph_url,
                description=description,
                )
            )
            return response
        else:
            return "Graph is already registered."
    except json.JSONDecodeError as e:
        logger.error("JSON decoding failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON format {e}"
        )
    except Exception as e:
        logger.error("An error occurred", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred processing the request {e}",
        )

