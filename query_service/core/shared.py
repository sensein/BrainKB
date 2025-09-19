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

import yaml
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Any
import re
import os
from core.shared import load_environment
from rdflib import Graph, URIRef, Literal, RDF, XSD , DCTERMS , PROV
import datetime
import uuid
from rdflib import Namespace
import requests


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


def is_uri(value):
    """Check if a value is a URI"""
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def typed_literal(value):
    """Return rdflib Literal with appropriate datatype"""
    if isinstance(value, int):
        return Literal(value, datatype=XSD.integer)
    elif isinstance(value, float):
        return Literal(value, datatype=XSD.float)
    elif isinstance(value, bool):
        return Literal(value, datatype=XSD.boolean)
    return Literal(value)


def generate_uri(base_uri, value=None):
    """Generate a URI using a given ID value or a UUID"""
    if value and is_uri(value):
        return URIRef(value)
    if value:
        return URIRef(f"{base_uri}{value}")
    return URIRef(f"{base_uri}{uuid.uuid4()}")


def json_to_kg(json_data, base_uri="http://example.org/resource/"):
    """Convert JSON data to RDF graph"""
    graph = Graph()
    KG = Namespace(base_uri)
    graph.bind("kg", KG)

    def process_node(node, subject):
        if isinstance(node, dict):
            for key, value in node.items():
                predicate = KG[key]
                if isinstance(value, (str, int, float, bool)):
                    obj = URIRef(value) if is_uri(value) else typed_literal(value)
                    graph.add((subject, predicate, obj))

                elif isinstance(value, dict):
                    # Use URI if 'id' key exists, otherwise generate one
                    obj_uri = generate_uri(base_uri, value.get("id"))
                    graph.add((subject, predicate, obj_uri))
                    process_node(value, obj_uri)

                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, (str, int, float, bool)):
                            obj = URIRef(item) if is_uri(item) else typed_literal(item)
                            graph.add((subject, predicate, obj))

                        elif isinstance(item, dict):
                            # Use URI if 'id' exists, else generate one based on content or UUID
                            obj_uri = generate_uri(base_uri, item.get("id") or item.get("specific_target"))
                            graph.add((subject, predicate, obj_uri))
                            process_node(item, obj_uri)
        else:
            graph.add((subject, KG.value, typed_literal(str(node))))

    subject_uri = generate_uri(base_uri)
    process_node(json_data, subject_uri)
    return graph


def convert_json_to_ttl(json_data, base_uri="http://brainkb.org/"):
    """Convert JSON data to TTL format string"""
    graph = json_to_kg(json_data, base_uri)
    return graph.serialize(format="turtle")


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


def named_graph_metadata(named_graph_url, description):
    """
        Generates metadata for a named graph using the PROV and DCTERMS ontologies.

        This function creates an RDF graph containing metadata for a given named graph.
        It includes:
        - The named graph as a PROV entity.
        - A timestamp indicating when the metadata was generated.
        - A description of the named graph.

        The generated RDF graph is then converted into a named graph format.

        Args:
            named_graph_url (str): The URL of the named graph for which metadata is created.
            description (str): A textual description of the named graph.

        Returns:
            str: The serialized named graph metadata in Turtle format.

        Dependencies:
            - rdflib (for RDF graph manipulation)
            - datetime (for timestamp generation)
            - convert_ttl_to_named_graph (a function to convert RDF Turtle data into a named graph)

        Example:
            >>> metadata = named_graph_metadata("https://example.org/mygraph", "This is a sample named graph.")
            >>> print(metadata)  # Outputs the RDF metadata as a named graph in ntriple format
    """
    g = Graph()
    prov_entity = URIRef(named_graph_url)
    created_At = datetime.datetime.utcnow().isoformat() + "Z"
    g.add((prov_entity, RDF.type, PROV.Entity))
    g.add((prov_entity,PROV.generatedAtTime, Literal(created_At, datatype=XSD.dateTime)))
    g.add((prov_entity,DCTERMS.description, Literal(description, datatype=XSD.string)))
    named_graph_metadata = convert_ttl_to_named_graph(
        ttl_str=g.serialize(format='turtle'),
        named_graph_uri="https://brainkb.org/metadata/named-graph"
    )
    return named_graph_metadata

def taxonomy_postprocessing(items):
    # going through the query output and create dictionary with parents_id and lists of childs ids
    taxon_dict = {}
    for tax_id, el in items.items():
        if el['parent'] is None:
            par_id = "root"
            par_nm = "root"
        else:
            par_id = el['parent']
            par_nm = items[par_id]["name"]
    
        if par_id not in taxon_dict:
            taxon_dict[par_id] = {"meta": {"name": par_nm}, "childrens_id": [tax_id]}
        else:
            taxon_dict[par_id]["childrens_id"].append(tax_id)


    # creating a simple function for one level of children for testing the figure:
    fig_dict = {"name": "root",  "nodeColor": "#ffffff",  "children": []}
    for child_id in taxon_dict["root"]['childrens_id']:
        fig_dict["children"].append({"name": taxon_dict[child_id]["meta"]["name"], "nodeColor": "#ebb3a7", "children": []})
    
    return fig_dict