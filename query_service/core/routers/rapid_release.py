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
# @File    : rapid_release.py
# @Software: PyCharm

from fastapi import APIRouter, Request, HTTPException, status
from core.graph_database_connection_manager import (fetch_data_gdb, concurrent_query,  convert_to_turtle, insert_data_gdb)
import json
import logging
from core.configuration import load_environment
from core.shared import read_yaml_config, yaml_config_to_query_dict

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/statistics")
async def donor_count():
    file = load_environment()["RAPID_RELEASE_FILE"]
    data = read_yaml_config(file)
    response = concurrent_query(yaml_config_to_query_dict(data, "rapid_releasestatistics", "slug", "sparql_query"))
    return response