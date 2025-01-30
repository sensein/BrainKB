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
# @File    : shared.py
# @Software: PyCharm

from rdflib import Graph
import yaml
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Any
import re
import os

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader


class ValueNotSetException(Exception):
    def __init__(self):
        Exception.__init__(self)
        self.message = "Required value is not set"

    def __str__(self):
        return self.message


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


def convert_to_turtle(jsonlddata):
    return Graph().parse(data=jsonlddata, format="json-ld").serialize(format="turtle")


def read_yaml_config(source_path: str) -> Dict[str, Any]:
    """Reads a YAML file and returns the parsed data as a dictionary."""
    try:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        config_file = os.path.join(root_dir, f"{source_path}")

        with open(config_file, "r") as file:
            return yaml.load(file, Loader=Loader)

    except FileNotFoundError:
        print(f"Error: The file {source_path} was not found.")
        return {}
    except yaml.YAMLError as e:
        print(f"Error: Failed to parse YAML file. {e}")
        return {}


def yaml_config_list_to_query_dict(
    yaml_data: Dict[str, Any],
    yaml_list_key: str,
    dict_key_item: str,
    dict_value_item: str,
) -> List[Dict[str, Any]]:
    """Converts a YAML list into a list of dictionaries for key-value pairs."""
    if yaml_list_key not in yaml_data:
        print(f"Error: Key '{yaml_list_key}' not found in YAML data.")
        return []

    try:
        return [
            {item[dict_key_item]: item[dict_value_item]}
            for item in yaml_data[yaml_list_key]
            if dict_key_item in item and dict_value_item in item
        ]
    except KeyError as e:
        print(f"Error: Missing key {e} in one of the items.")
        return []


def yaml_config_single_dict_to_query(
    yaml_data, superkey, sparql_query_key="sparql_query"
):
    """
    Extracts the SPARQL query from a YAML structure given a superkey and sparql_query_key.

    Args:
        yaml_data (dict): The loaded YAML data as a dictionary.
        superkey (str): The top-level key under which to look for the SPARQL query.
        sparql_query_key (str): The key containing the SPARQL query inside the superkey's dictionary. Defaults to 'sparql_query'.

    Returns:
        str: The SPARQL query string if found, or None if the key is not found.

    Example: for the following content in yaml file,  superkey is 'all_donor' and  sparql_query_key is 'sparql_query'
        all_donor:
          name: "Donor"
          slug: "alldonordata"
          short_description: ""
          sparql_query: |-
             PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
              PREFIX biolink: <https://w3id.org/biolink/vocab/>

              SELECT ?s (GROUP_CONCAT(DISTINCT STR(?p); SEPARATOR=", ") AS ?predicates)
                          (GROUP_CONCAT(DISTINCT STR(?o); SEPARATOR=", ") AS ?objects)
              WHERE {
                GRAPH <https://www.portal.brain-bican.org/grapidrelease> {
                  ?s ?p ?o .
                  ?s biolink:category bican:Donor .
                }
              }
              GROUP BY ?s
    """
    if superkey not in yaml_data:
        print(f"Error: '{superkey}' not found in YAML data.")
        return None

    # Extract the SPARQL query using the provided key
    sparql_query = yaml_data.get(superkey, {}).get(sparql_query_key)

    if sparql_query is None:
        print(f"Error: '{sparql_query_key}' not found under '{superkey}'.")

    return sparql_query


def contains_ip(string):
    # Regex pattern for matching IPv4
    ipv4_pattern = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"

    # Regex pattern for matching IPv6
    ipv6_pattern = r"\b(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}\b"

    # Check if the string is an exact match or contains an IP
    return re.search(ipv4_pattern, string) or re.search(ipv6_pattern, string)


def transform_data_categories(data: Dict[str, Any]):
    try:
        # Validate input data using the DataModel schema
        validated_data = DataModel(**data)

        # Extract the header (first item in 'vars')
        header = validated_data.message.head.vars[0]

        # Extract the values from 'bindings'
        results = [
            item.categories.value for item in validated_data.message.results.bindings
        ]

        # Return the transformed data
        return {"header": header, "results": results}

    except ValidationError as e:
        return {"error": f"Validation error: {e}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}


# Define the clean_response_concatenated_predicate_object function using Pydantic
def clean_response_concatenated_predicate_object(response: Dict[str, Any]):
    try:
        # Validate input response
        validated_response = ResponsePredicateObjectModel(**response)

        cleaned_data = []

        # Process the 'bindings' section
        for binding in validated_response.message.results.bindings:
            subject = binding.subject["value"]
            predicates = binding.predicates["value"].split(", ")
            objects = binding.objects["value"].split(", ")

            cleaned_data.append(
                {"subject": subject, "predicates": predicates, "objects": objects}
            )

        return cleaned_data

    except ValidationError as e:
        return {"error": f"Validation error: {e}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}


def clean_response_statistics(response: List[Dict[str, Any]]):
    cleaned_data = {}

    try:
        for item in response:
            for key, value in item.items():
                validated_data = DataModelCount(**value)
                count = validated_data.message.results.bindings[0].count["value"]
                cleaned_data[key] = int(count)

        return cleaned_data

    except ValidationError as e:
        return {"error": f"Validation error: {e}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}

def convert_ttl_to_named_graph(ttl_str: str, named_graph_uri: str = "https://brainkb.org/test") -> str:
    """
    Converts a Turtle (TTL) file to a Named Graph format and returns it as a string.

    :param ttl_str: A string containing Turtle (TTL) formatted RDF data.
    :param named_graph_uri: URI of the named graph.
    :return: A string containing the N-Quads formatted data.

    Example:
        Input ttl:
            @prefix ex: <http://example.org/> .
            ex:Alice ex:knows ex:Bob .
        Output:
            Graph <http://example.org/myGraph> {
             <http://example.org/Alice> <http://example.org/knows> <http://example.org/Bob> .
           }


    """
    g = Graph()
    g.parse(data=ttl_str, format="turtle")
    # format output to include `Graph <> {}` syntax
    n3_named_graph_data = f"Graph <{named_graph_uri}> {{\n"
    n3_named_graph_data += g.serialize(format="nt")  # Serialize as N-Triples (s p o .) for structured output
    n3_named_graph_data += "}\n"

    return n3_named_graph_data
