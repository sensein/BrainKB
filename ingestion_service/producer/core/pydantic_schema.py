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
from datetime import datetime
from typing import Dict, Any
from pydantic import BaseModel, Field


class BaseSchema(BaseModel):
    user: str
    date_created: datetime = datetime.now()
    date_modified: datetime = datetime.now()


class InputJSONSchema(BaseSchema):
    json_data: Dict[Any, Any]

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class InputJSONSLdchema(BaseModel):
    user: str
    kg_data: Dict[Any, Any]


class InputTextSchema(BaseSchema):
    user: str = "testuser"
    text_data: str


class InputTurtleSchema(BaseModel):
    user: str = "testuser"
    turtle_kg_data: str = Field(..., description="RDF Turtle data as a multiline string.")

