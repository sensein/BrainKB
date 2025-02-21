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
# @File    : pydantic_schema.py
# @Software: PyCharm
from pydantic import BaseModel, HttpUrl
from typing import Dict, Any


class InputKGTripleSchema(BaseModel):
    type: str
    named_graph_iri: str
    kg_data: str

class NamedGraphSchema(BaseModel):
    named_graph_url: HttpUrl
    description: str