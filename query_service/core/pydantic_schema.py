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
from typing import Dict, Any, List


class InputKGTripleSchema(BaseModel):
    type: str
    named_graph_iri: str
    kg_data: str


class NamedGraphSchema(BaseModel):
    named_graph_url: HttpUrl
    description: str


# Model for handling basic SPARQL query response
class HeadModel(BaseModel):
    """Represents the header of a SPARQL query result."""

    vars: List[str]


class BindingCategoryModel(BaseModel):
    """Represents the category for a binding in a SPARQL query result."""

    value: str


class BindingModel(BaseModel):
    """Represents the binding in a SPARQL query result."""

    categories: BindingCategoryModel


class ResultsModel(BaseModel):
    """Represents the list of bindings in a SPARQL query result."""

    bindings: List[BindingModel]


class MessageModel(BaseModel):
    """Encapsulates the header and results for a SPARQL query response."""

    head: HeadModel
    results: ResultsModel


class DataModel(BaseModel):
    """Represents the top-level SPARQL query response."""

    status: str
    message: MessageModel


# Model for handling concatenated predicate-object responses
class BindingPredicateObjectModel(BaseModel):
    """Represents subject, predicates, and objects binding."""

    subject: Dict[str, Any]
    predicates: Dict[str, Any]
    objects: Dict[str, Any]


class ResultsPredicateObjectModel(BaseModel):
    """Represents the list of predicate-object bindings."""

    bindings: List[BindingPredicateObjectModel]


class MessagePredicateObjectModel(BaseModel):
    """Encapsulates results for concatenated predicate-object responses."""

    results: ResultsPredicateObjectModel


class ResponsePredicateObjectModel(BaseModel):
    """Represents the top-level response for predicate-object data."""

    status: str
    message: MessagePredicateObjectModel


# Model for handling statistics (count) responses
class CountBindingModel(BaseModel):
    """Represents the count binding in a SPARQL statistics query."""

    count: Dict[str, Any]


class ResultsCountModel(BaseModel):
    """Represents the list of count bindings."""

    bindings: List[CountBindingModel]


class MessageCountModel(BaseModel):
    """Encapsulates results for count-based responses."""

    results: ResultsCountModel


class DataModelCount(BaseModel):
    """Represents the top-level response for count data."""

    status: str
    message: MessageCountModel
