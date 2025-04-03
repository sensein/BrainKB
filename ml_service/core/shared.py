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
from core.configuration import load_environment
import yaml
from fastapi import HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from typing import List, Optional, Dict, Union

logger = logging.getLogger(__name__)


def parse_yaml_or_json(input_str: Optional[Union[str, dict]], file_or_model_type: Optional[Union[UploadFile, BaseModel]] = None, model_type: Optional[BaseModel] = None) -> BaseModel:
    logger.debug(f"parse_yaml_or_json called with: input_str={type(input_str)}, file_or_model_type={type(file_or_model_type)}, model_type={model_type}")
    
    # Handle the case where model_type is passed as the second parameter
    if isinstance(file_or_model_type, type) and issubclass(file_or_model_type, BaseModel):
        logger.debug("Detected model_type as second parameter")
        model_type = file_or_model_type
        file = None
    else:
        file = file_or_model_type
    
    raw = None
    # If input_str is already a dict, use it directly
    if isinstance(input_str, dict):
        logger.debug("Input is already a dictionary")
        raw = input_str
    # Otherwise, try to parse it from a file or string
    elif file and hasattr(file, 'file'):
        logger.debug(f"Parsing from file: {file.filename}")
        try:
            raw_bytes = file.file.read()
            raw = yaml.safe_load(raw_bytes)
            logger.debug(f"Successfully parsed YAML from file: {type(raw)}")
        except Exception as e:
            logger.error(f"Error parsing YAML file: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid YAML file: {str(e)}")
    elif input_str:
        logger.debug("Parsing from string")
        try:
            raw = json.loads(input_str)
            logger.debug("Successfully parsed as JSON")
        except (json.JSONDecodeError, TypeError):
            try:
                raw = yaml.safe_load(input_str)
                logger.debug("Successfully parsed as YAML")
            except Exception as e:
                logger.error(f"Error parsing string as YAML/JSON: {str(e)}")
                raise HTTPException(status_code=400, detail=f"Invalid YAML/JSON string: {str(e)}")

    if raw is None:
        logger.error("Missing or invalid config input")
        raise HTTPException(status_code=400, detail="Missing or invalid config input.")

    if model_type is None:
        logger.error("Model type is required")
        raise HTTPException(status_code=400, detail="Model type is required.")

    try:
        logger.debug(f"Validating against model: {model_type.__name__}")
        result = model_type(**raw)
        logger.debug("Validation successful")
        return result
    except ValidationError as e:
        logger.error(f"Validation error: {e.errors()}")
        raise HTTPException(status_code=422, detail=e.errors())


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

def check_url_for_slash(url:str):
    if not url.endswith("/"):
        return url + "/"
    return url

def check_if_url_wellformed(url:str):
    "We want to ensure that the name graph IRI is wellformed, i.e., starts with http or https, not www"
    if url is None:
        return False
    else:
        return True if url.startswith("http://") or  url.startswith("https://") else False


import requests


def named_graph_exists(named_graph_iri: str) -> dict:
    """
    Checks whether a named graph exists in the registered named graphs list.

    Args:
        named_graph_iri (str): The IRI of the named graph to check.

    Returns:
        dict: A dictionary indicating success or failure with a relevant message.
    """

    query_service_url = load_environment().get("QUERY_SERVICE_BASE_URL", "")
    endpoint = f"{check_url_for_slash(query_service_url)}query/registered-named-graphs"

    # Validate the named graph IRI
    print(check_if_url_wellformed(named_graph_iri))
    if not check_if_url_wellformed(named_graph_iri):
        return {
            "status": "error",
            "message": "The graph IRI is not well-formed. It should start with 'http' or 'https'."
        }

    try:
        response = requests.get(endpoint)
        response.raise_for_status()  # Raise an error for bad responses (4xx, 5xx)

        registered_graphs = response.json()
        formatted_iri= check_url_for_slash(named_graph_iri)
        if formatted_iri in registered_graphs:
            return {
                "status": True,
                "formatted_iri": formatted_iri
            }
        return {
                "status": False,
                "message": f"The graph is not registered. Available graphs: {list(registered_graphs.keys())}"
            }
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Error connecting to query service: {str(e)}"
        }
