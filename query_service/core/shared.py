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
from typing import List, Dict, Any
import re
import os

class ValueNotSetException(Exception):
    def __init__(self):
        Exception.__init__(self)
        self.message = "Required value is not set"

    def __str__(self):
        return self.message

def convert_to_turtle(jsonlddata):
        return Graph().parse(data=jsonlddata, format='json-ld').serialize(format="turtle")


def read_yaml_config(source_path: str) -> Dict[str, Any]:
    """Reads a YAML file and returns the parsed data as a dictionary."""
    try:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        config_file = os.path.join(root_dir, f"{source_path}")
        with open(config_file, 'r') as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        print(f"Error: The file {source_path} was not found.")
        return {}
    except yaml.YAMLError as e:
        print(f"Error: Failed to parse YAML file. {e}")
        return {}


def yaml_config_list_to_query_dict(yaml_data: Dict[str, Any], yaml_list_key: str, dict_key_item: str,
                              dict_value_item: str) -> List[Dict[str, Any]]:
    """Converts a YAML list into a list of dictionaries for key-value pairs."""
    if yaml_list_key not in yaml_data:
        print(f"Error: Key '{yaml_list_key}' not found in YAML data.")
        return []

    try:
        return [{item[dict_key_item]: item[dict_value_item]} for item in yaml_data[yaml_list_key] if
                dict_key_item in item and dict_value_item in item]
    except KeyError as e:
        print(f"Error: Missing key {e} in one of the items.")
        return []


def yaml_config_single_dict_to_query(yaml_data, superkey, sparql_query_key='sparql_query'):
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
    ipv4_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'

    # Regex pattern for matching IPv6
    ipv6_pattern = r'\b(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}\b'

    # Check if the string is an exact match or contains an IP
    if re.search(ipv4_pattern, string) or re.search(ipv6_pattern, string):
        return True
    return False