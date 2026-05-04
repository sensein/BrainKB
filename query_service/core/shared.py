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
from __future__ import annotations
import yaml
from core.configuration import load_environment
from pydantic import ValidationError
import time
import sys
import re
import os
from rdflib import Graph, URIRef, Literal, RDF, XSD , DCTERMS, PROV
import datetime
import uuid
from rdflib import Namespace
import requests
from rdflib import ConjunctiveGraph
from typing import Dict, Any, List, Optional

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
        sys.stdout.write(f"Error: The file {source_path} was not found.\n")
        return {}
    except yaml.YAMLError as e:
        sys.stdout.write(f"Error: Failed to parse YAML file. {e}\n")
        return {}


def yaml_config_list_to_query_dict(
    yaml_data: Dict[str, Any],
    yaml_list_key: str,
    dict_key_item: str,
    dict_value_item: str,
) -> List[Dict[str, Any]]:
    """Converts a YAML list into a list of dictionaries for key-value pairs."""
    if yaml_list_key not in yaml_data:
        sys.stdout.write(f"Error: Key '{yaml_list_key}' not found in YAML data.\n")
        return []

    try:
        return [
            {item[dict_key_item]: item[dict_value_item]}
            for item in yaml_data[yaml_list_key]
            if dict_key_item in item and dict_value_item in item
        ]
    except KeyError as e:
        sys.stdout.write(f"Error: Missing key {e} in one of the items.\n")
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
        sys.stdout.write(f"Error: '{superkey}' not found in YAML data.\n")
        return None

    # Extract the SPARQL query using the provided key
    sparql_query = yaml_data.get(superkey, {}).get(sparql_query_key)

    if sparql_query is None:
        sys.stdout.write(f"Error: '{sparql_query_key}' not found under '{superkey}'.\n")

    return sparql_query


def contains_ip(string):
    # Regex pattern for matching IPv4
    ipv4_pattern = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"

    # Regex pattern for matching IPv6
    ipv6_pattern = r"\b(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}\b"

    # Check if the string is an exact match or contains an IP
    return re.search(ipv4_pattern, string) or re.search(ipv6_pattern, string)


def transform_data_categories(data: Dict[str, Any]):
    from core.pydantic_schema import DataModel
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
    from core.pydantic_schema import ResponsePredicateObjectModel
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
    from core.pydantic_schema import DataModelCount
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


def chunk_ttl_to_named_graphs(ttl_str: str, named_graph_uri: str = "https://brainkb.org/test", chunk_size: int = 1000) -> list[str]:
    """
    Converts a large Turtle (TTL) file to multiple Named Graph chunks for batch insertion.
    This is useful for large files that might timeout during insertion.

    :param ttl_str: A string containing Turtle (TTL) formatted RDF data.
    :param named_graph_uri: URI of the named graph.
    :param chunk_size: Number of triples per chunk. 
                       Default: 1000 for medium files, use 500 for very large files (50-60MB).
    :return: A list of strings, each containing a chunk in Named Graph format.
    """
    g = Graph()
    g.parse(data=ttl_str, format="turtle")
    
    # Get all triples
    triples = list(g)
    
    if len(triples) <= chunk_size:
        # If file is small enough, return as single chunk
        return [convert_ttl_to_named_graph(ttl_str, named_graph_uri)]
    
    # Split into chunks
    chunks = []
    for i in range(0, len(triples), chunk_size):
        chunk_triples = triples[i:i + chunk_size]
        # Create a temporary graph with this chunk
        chunk_graph = Graph()
        chunk_graph += chunk_triples
        
        # Convert to named graph format
        n3_named_graph_data = f"Graph <{named_graph_uri}> {{\n"
        n3_named_graph_data += chunk_graph.serialize(format="nt")
        n3_named_graph_data += "}\n"
        
        chunks.append(n3_named_graph_data)
    
    return chunks


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

# def taxonomy_postprocessing(items):
#     # going through the query output and create dictionary with parents_id and lists of childs ids
#     taxon_dict = {}
#     for tax_id, el in items.items():
#         if el['parent'] is None:
#             par_id = "root"
#             par_nm = "root"
#         else:
#             par_id = el['parent']
#             par_nm = items[par_id]["name"]
    
#         if par_id not in taxon_dict:
#             taxon_dict[par_id] = {"meta": {"name": par_nm}, "childrens_id": [tax_id]}
#         else:
#             taxon_dict[par_id]["childrens_id"].append(tax_id)


#     # creating a simple function for one level of children for testing the figure:
#     fig_dict = {"name": "root",  "nodeColor": "#ffffff",  "children": []}
#     for child_id in taxon_dict["root"]['childrens_id']:
#         fig_dict["children"].append({"name": taxon_dict[child_id]["meta"]["name"], "nodeColor": "#ebb3a7", "children": []})
    
#     return fig_dict
def getting_childrens(items):
    # going through the query output and create dictionary with parents_id and lists of childs ids
    taxon_dict = {}
    for tax_id, el in items.items():
        if el['parent'] is None:
            par_id = "root"
            par_nm, par_col = "root", '#ffffff'
        else:
            par_id = el['parent']
            par_nm, par_col = items[par_id]["name"], items[par_id]["hex"]
    
        if par_id not in taxon_dict:
            taxon_dict[par_id] = {"meta": {"name": par_nm, "color": par_col}, "childrens_id": [tax_id]}
        else:
            taxon_dict[par_id]["childrens_id"].append(tax_id)

    # adding elements without children
    for tax_id, el in items.items():
        if tax_id not in taxon_dict:
            taxon_dict[tax_id] = {"meta": {"name": items[tax_id]["name"],  "color": items[tax_id]["hex"]}, "childrens_id": []}

    return taxon_dict

def create_tree(taxon_children):
    children_list_root = []
    update_childrens(children_list_root, "root", taxon_children)
    fig_dict = {"name": "root",  "nodeColor": "#ffffff",  "children": children_list_root}

    return fig_dict


def update_childrens(children_list, parent_id, taxon_children_dict):
    """ modyfies children_list"""
    if parent_id in taxon_children_dict:
        for child_id in taxon_children_dict[parent_id]["childrens_id"]:
            #print("child id", child_id)
            children_list_current = []
            update_childrens(children_list_current, child_id, taxon_children_dict)
            children_list.append({"name": taxon_children_dict[child_id]["meta"]["name"], "nodeColor": taxon_children_dict[child_id]["meta"]["color"], "children": children_list_current})
        return
    else:
        return


def taxonomy_postprocessing(items):
    taxon_children = getting_childrens(items)

    # creating a simple function for one level of children for testing the figure:
    fig_dict = create_tree(taxon_children)
    return fig_dict



def human_size(num_bytes: float) -> str:
    """Return human readable size: KB, MB, GB, ..."""
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if num_bytes < 1024 or unit == units[-1]:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


def human_rate(bytes_per_sec: float) -> str:
    """Return human readable throughput per second."""
    units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
    for unit in units:
        if bytes_per_sec < 1024 or unit == units[-1]:
            return f"{bytes_per_sec:.2f} {unit}"
        bytes_per_sec /= 1024
    return f"{bytes_per_sec:.2f} PB/s"


def get_ext(filename: str) -> str:
    """Extract file extension from filename."""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def get_content_type_for_ext(ext: str) -> str:
    """
    Content types for payload we actually send to Oxigraph.
    For jsonld we convert to N-Triples, so we use application/n-triples.
    """
    ext = ext.lower()
    if ext == "jsonld":
        return "application/n-triples"
    
    CONTENT_TYPES = {
        "ttl": "text/turtle",
        "nt": "application/n-triples",
        "nq": "application/n-quads",
        "trig": "application/trig",
        "rdf": "application/rdf+xml",
        "owl": "application/rdf+xml",
    }
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def convert_jsonld_to_ntriples_flat(data: bytes) -> bytes:
    """
    Convert JSON-LD bytes -> N-Triples bytes using rdflib, flattening named graphs.
    """

    cg = ConjunctiveGraph()
    cg.parse(data=data, format="json-ld")
    g = Graph()
    for s, p, o, _ctx in cg.quads((None, None, None, None)):
        g.add((s, p, o))
    return g.serialize(format="nt").encode('utf-8')


def detect_raw_format(text: str) -> str:
    """
    Very simple heuristic to decide how to treat raw input:
    - Starts with '{' or '[' -> JSON-LD
    - Contains '@prefix' or '@base' -> Turtle
    - Otherwise -> N-Triples (raw KG triples)
    """
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "jsonld"
    if "@prefix" in text or "@base" in text:
        return "ttl"
    # fallback: raw triples in N-Triples-like syntax
    return "nt"


def compute_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute summary statistics from job results."""
    total_files = len(results)
    success_results = [r for r in results if r.get("success")]
    fail_results = [r for r in results if not r.get("success")]
    total_bytes = sum(r.get("size_bytes", 0) for r in results)
    total_success_bytes = sum(r.get("size_bytes", 0) for r in success_results)
    
    if results:
        overall_elapsed = max(r.get("elapsed_s", 0.0) for r in results)
    else:
        overall_elapsed = 0.0
    overall_elapsed = max(overall_elapsed, 1e-6)
    
    avg_file_size = total_bytes / total_files if total_files else 0.0
    avg_success_file_size = (
        total_success_bytes / len(success_results) if success_results else 0.0
    )
    overall_bps = total_bytes / overall_elapsed if overall_elapsed else 0.0
    success_bps = total_success_bytes / overall_elapsed if overall_elapsed else 0.0
    
    if results:
        max_result = max(results, key=lambda r: r.get("size_bytes", 0))
        min_result = min(results, key=lambda r: r.get("size_bytes", 0))
        max_file_size = max_result.get("size_bytes", 0)
        max_file_name = max_result.get("file", "")
        min_file_size = min_result.get("size_bytes", 0)
        min_file_name = min_result.get("file", "")
    else:
        max_file_size = min_file_size = 0
        max_file_name = min_file_name = ""
    
    per_ext: Dict[str, Dict[str, float]] = {}
    for r in results:
        ext = r.get("ext", "")
        d = per_ext.setdefault(ext, {"count": 0, "bytes": 0})
        d["count"] += 1
        d["bytes"] += r.get("size_bytes", 0)
    
    for ext, d in per_ext.items():
        d["avg_size"] = d["bytes"] / d["count"] if d["count"] else 0.0
    
    success_count = len(success_results)
    fail_count = len(fail_results)
    success_rate = (100.0 * success_count / total_files) if total_files else 0.0
    
    failures = [
        {
            "file": r.get("file", ""),
            "http_status": r.get("http_status", 0),
            "response_body": r.get("response_body", ""),
        }
        for r in fail_results
    ]
    
    summary = {
        "total_files": total_files,
        "success_count": success_count,
        "fail_count": fail_count,
        "success_rate_percent": round(success_rate, 2),
        "total_bytes": total_bytes,
        "total_success_bytes": total_success_bytes,
        "total_bytes_human": human_size(total_bytes),
        "total_success_bytes_human": human_size(total_success_bytes),
        "avg_file_size_bytes": avg_file_size,
        "avg_file_size_human": human_size(avg_file_size),
        "avg_success_file_size_bytes": avg_success_file_size,
        "avg_success_file_size_human": human_size(avg_success_file_size),
        "max_file_name": max_file_name,
        "max_file_size_bytes": max_file_size,
        "max_file_size_human": human_size(max_file_size),
        "min_file_name": min_file_name,
        "min_file_size_bytes": min_file_size,
        "min_file_size_human": human_size(min_file_size),
        "overall_elapsed_s": round(overall_elapsed, 3),
        "overall_bps": overall_bps,
        "overall_rate_human": human_rate(overall_bps),
        "success_bps": success_bps,
        "success_rate_human": human_rate(success_bps),
        "per_extension": {
            ext: {
                "count": d["count"],
                "total_bytes": d["bytes"],
                "total_bytes_human": human_size(d["bytes"]),
                "avg_size_bytes": d["avg_size"],
                "avg_size_human": human_size(d["avg_size"]),
            }
            for ext, d in per_ext.items()
        },
        "failures": failures,
    }
    return summary


def extract_base_namespace(graph: Graph) -> Namespace:
    """
    Extract the base namespace from an RDF graph.
    Looks for common namespace patterns or uses a default.
    
    Args:
        graph: RDFlib Graph object
        
    Returns:
        Namespace: The base namespace for the graph
    """
    # Try to find a common namespace pattern
    # Look for namespaces that might indicate the base
    for prefix, namespace in graph.namespaces():
        if prefix == "" or prefix.lower() in ["", "base", "default"]:
            return Namespace(str(namespace))
        # Check for common base patterns
        if "brain-bican" in str(namespace).lower() or "identifiers.org" in str(namespace):
            return Namespace(str(namespace))
    
    # Default to brain-bican namespace if nothing found
    return Namespace("https://identifiers.org/brain-bican/vocab/")



def attach_provenance(user: str, ttl_data: str) -> str:
    """
    Attach provenance about the ingestion activity at graph-level:
    "We received this data from user X on date T."

    Returns TTL with the original data unchanged + extra provenance triples.
    """
    # Define PROV namespace via rdflib
    PROV = Namespace("http://www.w3.org/ns/prov#")
    # Validate input parameters
    if not isinstance(user, str) or not user.strip():
        raise ValueError("User must be a non-empty string.")
    if not isinstance(ttl_data, str) or not ttl_data.strip():
        raise ValueError("TTL data must be a non-empty string.")

    try:
        g = Graph()
        g.parse(data=ttl_data, format="turtle")
    except Exception as e:
        raise RuntimeError(f"Error parsing TTL data: {e}")

    # Bind prefixes so serialization is readable
    g.bind("prov", PROV)
    g.bind("dct", DCTERMS)

    try:
        BASE = extract_base_namespace(g)  # your helper that returns a Namespace
    except Exception as e:
        raise RuntimeError(f"Failed to extract base namespace: {e}")

    # Generate timestamps (UTC, ISO 8601)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Generate a unique UUID for this ingestion
    provenance_uuid = str(uuid.uuid4())

    # URIs for ingestion entity, activity, and user agent
    ingestion_entity = URIRef(BASE[f"provenance/{provenance_uuid}"])
    ingestion_activity = URIRef(BASE[f"ingestionActivity/{provenance_uuid}"])
    user_uri = URIRef(BASE[f"agent/{user}"])

    # Agent (user)
    g.add((user_uri, RDF.type, PROV.Agent))

    # Ingestion activity
    g.add((ingestion_activity, RDF.type, PROV.Activity))
    g.add((ingestion_activity, RDF.type, BASE["IngestionActivity"]))
    g.add((ingestion_activity, PROV.startedAtTime,
           Literal(now, datatype=XSD.dateTime)))
    g.add((ingestion_activity, PROV.wasAssociatedWith, user_uri))

    # Ingestion entity describing this ingestion event / bundle
    g.add((ingestion_entity, RDF.type, PROV.Entity))
    g.add((ingestion_entity, PROV.generatedAtTime,
           Literal(now, datatype=XSD.dateTime)))
    g.add((ingestion_entity, PROV.wasAttributedTo, user_uri))
    g.add((ingestion_entity, PROV.wasGeneratedBy, ingestion_activity))

    # Human-readable provenance note
    g.add((
        ingestion_entity,
        DCTERMS.provenance,
        Literal(f"Data ingested by {user} on {now}")
    ))

    # Serialize the same graph (original triples + extra provenance)
    return g.serialize(format="turtle")

# def attach_provenance(user: str, ttl_data: str) -> str:
#     """
#     Attach the provenance information about the ingestion activity. Saying, we received this triple by X user on XXXX date.
#     It appends provenance triples externally while keeping the original triples intact.
#
#     Parameters:
#     - user (str): The username of the person posting the data.
#     - ttl_data (str): The existing Turtle (TTL) RDF data.
#
#     Returns:
#     - str: Combined RDF (Turtle format) containing original data and provenance metadata.
#     """
#     # Validate input parameters
#     if not isinstance(user, str) or not user.strip():
#         raise ValueError("User must be a non-empty string.")
#     if not isinstance(ttl_data, str) or not ttl_data.strip():
#         raise ValueError("TTL data must be a non-empty string.")
#
#     try:
#         original_graph = Graph()
#         original_graph.parse(data=ttl_data, format="turtle")
#     except Exception as e:
#         raise RuntimeError(f"Error parsing TTL data: {e}")
#
#     try:
#         BASE = extract_base_namespace(original_graph)
#     except Exception as e:
#         raise RuntimeError(f"Failed to extract base namespace: {e}")
#
#     try:
#         # Create provenance graph
#         prov_graph = Graph()
#
#         # Generate timestamps (ISO 8601 format, UTC)
#         start_time = datetime.datetime.utcnow().isoformat() + "Z"
#
#         # Generate a unique UUID for provenance entity
#         provenance_uuid = str(uuid.uuid4())
#         prov_entity = URIRef(BASE[f"provenance/{provenance_uuid}"])
#         ingestion_activity = URIRef(BASE[f"ingestionActivity/{provenance_uuid}"])
#         user_uri = URIRef(BASE[f"agent/{user}"])
#
#         # Define provenance entity
#         prov_graph.add((prov_entity, RDF.type, PROV.Entity))
#         prov_graph.add((prov_entity, PROV.generatedAtTime, Literal(start_time, datatype=XSD.dateTime)))
#         prov_graph.add((prov_entity, PROV.wasAttributedTo, user_uri))
#         prov_graph.add((prov_entity, PROV.wasGeneratedBy, ingestion_activity))
#
#         # Define ingestion activity
#         # here we say IngestionActivity is an activity of type prov:Activity
#         prov_graph.add((ingestion_activity, RDF.type, PROV.Activity))
#         prov_graph.add((ingestion_activity, RDF.type, BASE["IngestionActivity"]))
#         prov_graph.add((ingestion_activity, PROV.generatedAtTime, Literal(start_time, datatype=XSD.dateTime)))
#         prov_graph.add((ingestion_activity, PROV.wasAssociatedWith, user_uri))
#
#         # Attach provenance to original triples
#         # OPTIMIZATION: Use set to avoid duplicate checks and limit entities for performance
#         # Adaptive limit based on graph size to balance performance vs completeness
#         graph_size = len(original_graph)
#         if graph_size > 100000:  # Very large graphs (>100k triples)
#             max_entities = 500  # Limit more aggressively
#         elif graph_size > 50000:  # Large graphs (50k-100k triples)
#             max_entities = 750
#         else:  # Medium/small graphs (<50k triples)
#             max_entities = 1000  # Can process more entities
#
#         entity_count = 0
#         seen_entities = set()
#
#         for entity in original_graph.subjects():
#             if entity_count >= max_entities:
#                 break
#             if isinstance(entity, URIRef) and entity not in seen_entities:
#                 seen_entities.add(entity)
#                 prov_graph.add((ingestion_activity, PROV.wasAssociatedWith, entity))
#                 entity_count += 1
#
#         # add a Dublin Core provenance statement -- this is the new addition to say it's ingested by user
#         prov_graph.add((prov_entity, DCTERMS.provenance, Literal(f"Data ingested by {user} on {start_time}")))
#
#         # Combine both graphs (original + provenance) so that we have new provenance information attached.
#         final_graph = original_graph + prov_graph
#
#         return final_graph.serialize(format="turtle")
#     except Exception as e:
#         raise RuntimeError(f"Error generating provenance RDF: {e}")


def get_oxigraph_endpoint() -> str:
    """
    Get the Oxigraph Graph Store HTTP endpoint URL from configuration.
    Constructs the full endpoint URL based on hostname and port.

    Returns:
        str: The full endpoint URL (e.g., "http://oxigraph:7878/store")
    """

    env = load_environment()
    hostname = env.get("GRAPHDATABASE_HOSTNAME", "http://localhost")
    port = env.get("GRAPHDATABASE_PORT", 7878)


    if hostname.startswith("http://") or hostname.startswith("https://"):
        base_url = hostname
    elif contains_ip(hostname):
        base_url = f"http://{hostname}:{port}"
    else:
        # Docker service name or hostname - construct full URL
        base_url = f"http://{hostname}:{port}"

    # Use Graph Store HTTP endpoint. This is specific for oxigraph
    endpoint = f"{base_url}/store"
    return endpoint


def get_oxigraph_auth() -> Optional[tuple]:
    """
    Get Oxigraph authentication credentials from configuration.
    
    Returns:
        tuple: (username, password) if credentials are set, None otherwise
    """
    env = load_environment()
    username = env.get("GRAPHDATABASE_USERNAME")
    password = env.get("GRAPHDATABASE_PASSWORD")
    return (username, password) if username and password else None

