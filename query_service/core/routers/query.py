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

from fastapi import APIRouter, Request, HTTPException, status
from core.graph_database_connection_manager import (
    fetch_data_gdb,
    convert_to_turtle,
    insert_data_gdb,
)
import json
import logging
from core.pydantic_schema import InputJSONSLdchema
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from fastapi import Depends

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/query/insert-jsonld", include_in_schema=False)
async def insert_jsonld(
    user: Annotated[LoginUserIn, Depends(get_current_user)], request: InputJSONSLdchema
):
    try:
        data = json.loads(request.json())
        logger.info(f"Received data: {data}")

        turtle_data = convert_to_turtle(data["kg_data"])
        logger.info(f"Converted Turtle data: {turtle_data}")

        response = insert_data_gdb(turtle_data)
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


@router.get("/query/sparql/", include_in_schema=False)
async def sparql_query(
    user: Annotated[LoginUserIn, Depends(get_current_user)], sparql_query: str
):
    response = fetch_data_gdb(sparql_query)
    return response
