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


def yaml_config_to_query_dict(yaml_data: Dict[str, Any], yaml_list_key: str, dict_key_item: str,
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


def contains_ip(string):
    # Regex pattern for matching IPv4
    ipv4_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'

    # Regex pattern for matching IPv6
    ipv6_pattern = r'\b(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}\b'

    # Check if the string is an exact match or contains an IP
    if re.search(ipv4_pattern, string) or re.search(ipv6_pattern, string):
        return True
    return False