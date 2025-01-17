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


import json
from rdflib import Graph
import requests
import logging

logger = logging.getLogger(__name__)

# Helper function to resolve issues during the conversion from JSON-LD to Turtle representation.
#
# Problem:
# The generated Turtle representation includes local file paths
# (e.g., <file:///Users/tekrajchhetri/Documents/convert_to_ttl/...>)
# instead of the correct base IRI.
#
# Expected Output:
# The Turtle representation should look like this:
# bican:ID123 a bican:GeneAnnotation ;
#     rdfs:label "LOC106504536" ;
#     schema1:identifier "106504536" ;
#     biolink:in_taxon_label "Sus scrofa" .
#
# Issue:
# Currently, the output includes local file paths, for example:
# <file:///Users/tekrajchhetri/Documents/convert_to_ttl/000015fd3d6a449b47e75651210a6cc74fca918255232c8af9e46d077034c84d>
# a bican:GeneAnnotation ;
#     rdfs:label "LOC106504536" ;
#     schema1:identifier "106504536" ;
#     biolink:in_taxon_label "Sus scrofa" .
#
# This function ensures that the base IRI is used, correcting the issue.
def _get_base_from_context(jsonld_data):
    """
    Extracts the @base value from the @context.
    Handles both inline contexts (dictionaries) and external contexts (strings).
    Raises an error if neither @base nor @vocab is available.
    """
    context = jsonld_data.get('@context', {})
    logger.info(f"Extracting context {context}")

    # If @context is a string, fetch the external context
    if isinstance(context, str):
        try:
            response = requests.get(context)
            response.raise_for_status()
            context = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch the external context from {context}: {e}")
            raise ValueError(f"Failed to fetch the external context from {context}: {e}")

    # Ensure context is now a dictionary
    if not isinstance(context, dict):
        logger.error(f"The @context must resolve to a dictionary. Found: {type(context)}")
        raise ValueError(f"The @context must resolve to a dictionary. Found: {type(context)}")

    to_fetch_context = context.get("@context")
    if to_fetch_context is None:
        return None

    base = to_fetch_context.get('@base') or to_fetch_context.get('@vocab') or None

    if not base or base is None:
        # Raise an error if neither @base nor @vocab is found
        logger.info(
            "The JSON-LD context does not contain '@base' or '@vocab'. Please define a base URI in the context.")
        return None
    return base


def convert_to_turtle(jsonld_data):
    """
    Converts JSON-LD data to Turtle format.
    Returns:
        - Serialized Turtle string on success.
        - False if an error occurs.
    """
    logger.info("Converting JSON-LD data to Turtle format")
    base = _get_base_from_context(jsonld_data)
    try:
        graph = Graph()
        if base is not None:
            graph.parse(data=json.dumps(jsonld_data), format='json-ld', base=base)
        else:
            graph.parse(data=json.dumps(jsonld_data), format='json-ld')
        serialized_graph = graph.serialize(format='turtle')
        return serialized_graph
    except Exception as e:
        logger.error(f"Error converting JSON-LD to Turtle: {e}")
        return False




def has_context(json_obj):
    """Simple JSON-LD check for presence of the context"""
    return '@context' in json_obj


def is_valid_jsonld(jsonld_str):
    try:
        jsonld_obj = json.loads(jsonld_str)
        return has_context(jsonld_obj["kg_data"])
    except ValueError:
        return False

