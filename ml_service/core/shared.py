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
import re
import httpx
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
from fastapi import WebSocket, WebSocketDisconnect
logger = logging.getLogger(__name__)
import fitz
from io import BytesIO
import requests
import asyncio
from enum import Enum
import yaml
from structsense import kickoff
from pathlib import Path
from core.shared import load_environment  # adjust this import to your setup
import json
from pymongo import MongoClient, ReturnDocument
from datetime import datetime, timezone
import tempfile

# for multi-agent
UPLOAD_DIR = Path("uploads").resolve()
UPLOAD_DIR.mkdir(exist_ok=True)

def upsert_ner_annotations(input_data):
    """
    Upserts NER annotations into a MongoDB collection with versioning and history.
    """

    env = load_environment()
    mongo_url = env.get("MONGO_DB_URL")
    db_name = env.get("NER_DATABASE")
    collection_name = env.get("NER_COLLECTION")
    client = MongoClient(mongo_url)

    try:
        db = client[db_name]
        collection = db[collection_name]

        judge_terms = input_data["judged_structured_information"]
        document_name = input_data.get("documentName")
        processed_at = input_data.get("processedAt")

        now = datetime.now(timezone.utc)

        inserted = 0
        updated = 0

        for _, annotations in judge_terms.items():
            for ann in annotations:
                ann.setdefault("doi", "")
                ann.setdefault("paper_title", "")
                ann.setdefault("paper_location", "")

                if document_name:
                    ann["documentName"] = document_name
                if processed_at:
                    ann["processedAt"] = processed_at

                filter_criteria = {
                    "doi": ann["doi"],
                    "paper_title": ann["paper_title"],
                    "paper_location": ann["paper_location"],
                    "entity": ann["entity"]
                }

                existing_doc = collection.find_one(filter_criteria)
                version = 1
                if existing_doc:
                    version = existing_doc.get("version", 1) + 1
                    updated += 1
                else:
                    inserted += 1

                update_fields = {**ann, "updated_at": now, "version": version}
                update_fields = {k: v for k, v in update_fields.items() if v is not None}

                history_entry = {
                    "timestamp": now,
                    "updated_fields": {
                        k: ann[k]
                        for k in ann
                        if k not in filter_criteria and ann[k] is not None
                    },
                }

                collection.find_one_and_update(
                    filter_criteria,
                    {
                        "$set": update_fields,
                        "$setOnInsert": {"created_at": now},
                        "$push": {"history": history_entry}
                    },
                    upsert=True,
                    return_document=ReturnDocument.AFTER
                )


        return {
            "Inserted": inserted,
            "Updated": updated
        }
    finally:
        client.close()


def upsert_structured_resources(input_data):
    """
    Upserts structured resource extraction results into a MongoDB collection with versioning and history.
    Dynamically handles any structure keys and nested objects.
    """

    env = load_environment()
    mongo_url = env.get("MONGO_DB_URL")
    db_name = env.get("NER_DATABASE")
    collection_name = "structured_resource" #env.get("STRUCTURED_RESOURCES_COLLECTION")
    client = None

    try:
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        db = client[db_name]
        collection = db[collection_name]

        # Extract the structured data from the input
        structured_data = input_data.get("data", [])
        document_name = input_data.get("documentName", "")
        processed_at = input_data.get("processedAt", "")
        source_type = input_data.get("sourceType", "")  # doi, pdf, text, file
        source_content = input_data.get("sourceContent", "")  # original input

        now = datetime.now(timezone.utc)

        inserted = 0
        updated = 0

        for idx, resource_data in enumerate(structured_data):
            print(f"Processing resource {idx}: {type(resource_data)}")

            # Ensure required fields exist and handle None values
            if not isinstance(resource_data, dict):
                print(f"Skipping non-dict resource: {resource_data}")
                continue

            #  Attach metadata as top-level fields
            resource_data["documentName"] = str(document_name or "")
            resource_data["processedAt"] = str(processed_at or "")
            resource_data["sourceType"] = str(source_type or "")
            resource_data["sourceContent"] = str(source_content or "")

            # Dynamic structure detection and cleaning
            cleaned_resource_data = clean_and_validate_structure(resource_data)

            # Dynamic filter criteria generation
            filter_criteria = generate_filter_criteria(cleaned_resource_data, document_name, idx, now)

            print(f"Filter criteria: {filter_criteria}")

            existing_doc = collection.find_one(filter_criteria)
            version = 1
            if existing_doc:
                version = existing_doc.get("version", 1) + 1
                updated += 1
            else:
                inserted += 1

            # Prepare update fields with versioning
            update_fields = {**cleaned_resource_data, "updated_at": now, "version": version}

            # Create history entry
            history_entry = {
                "timestamp": now,
                "updated_fields": {
                    k: resource_data[k]
                    for k in resource_data
                    if k not in filter_criteria and resource_data[k] is not None and resource_data[k] != "null"
                },
                "source_type": source_type,
                "source_content_preview": source_content[:200] + "..." if len(source_content) > 200 else source_content
            }

            print(f"About to upsert with filter: {filter_criteria}")
            print(f"Update fields keys: {list(update_fields.keys())}")

            collection.find_one_and_update(
                filter_criteria,
                {
                    "$set": update_fields,
                    "$setOnInsert": {"created_at": now},
                    "$push": {"history": history_entry}
                },
                upsert=True,
                return_document=ReturnDocument.AFTER
            )

        return {
            "Inserted": inserted,
            "Updated": updated,
            "Total_Processed": len(structured_data)
        }
    except Exception as e:
        print(f"Exception in upsert_structured_resources: {str(e)}")
        print(f"Exception type: {type(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        if client:
            try:
                client.close()
                print("MongoDB client closed successfully")
            except Exception as close_error:
                print(f"Error closing MongoDB client: {close_error}")


def clean_and_validate_structure(data):
    """
    Dynamically cleans and validates any nested structure.
    Handles None values, null strings, and ensures proper types.
    """
    if not isinstance(data, dict):
        return {}

    cleaned_data = {}

    for key, value in data.items():
        if value is None or value == "null" or value == "":
            continue

        if isinstance(value, str):
            cleaned_value = value.strip()
            if cleaned_value and cleaned_value != "null":
                cleaned_data[key] = cleaned_value
        elif isinstance(value, dict):
            # Recursively clean nested dictionaries
            nested_cleaned = clean_and_validate_structure(value)
            if nested_cleaned:  # Only include if not empty
                cleaned_data[key] = nested_cleaned
        elif isinstance(value, list):
            # Clean list elements
            cleaned_list = []
            for item in value:
                if item is not None and item != "null" and item != "":
                    if isinstance(item, str):
                        cleaned_item = item.strip()
                        if cleaned_item and cleaned_item != "null":
                            cleaned_list.append(cleaned_item)
                    else:
                        cleaned_list.append(str(item))
            if cleaned_list:  # Only include if not empty
                cleaned_data[key] = cleaned_list
        else:
            # Convert other types to string
            cleaned_data[key] = str(value)

    return cleaned_data


def generate_filter_criteria(data, document_name, idx, now):
    """
    Dynamically generates filter criteria based on available fields.
    Prioritizes fields that are most likely to be unique identifiers.
    """
    filter_criteria = {
        "documentName": document_name
    }

    # Priority order for unique identifiers
    priority_fields = [
        ("name", "name"),
        ("resource.name", "resource.name"),
        ("type", "type"),
        ("resource.type", "resource.type"),
        ("category", "category"),
        ("resource.category", "resource.category"),
        ("id", "id"),
        ("resource.id", "resource.id")
    ]

    # Try to find the best unique identifier
    for field_path, filter_key in priority_fields:
        value = get_nested_value(data, field_path)
        if value and value.strip():
            filter_criteria[filter_key] = value.strip()
            break

    # If no good identifier found, create a fallback
    if len(filter_criteria) == 1:  # Only has documentName
        fallback_name = f"unnamed_resource_{now.strftime('%Y%m%d_%H%M%S')}_{idx}"
        filter_criteria["name"] = fallback_name

    return filter_criteria


def get_nested_value(data, path):
    """
    Safely gets a nested value from a dictionary using dot notation.
    Example: get_nested_value(data, "resource.name")
    """
    keys = path.split('.')
    current = data

    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None

    return current


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



def is_valid_doi(doi: str) -> bool:
    doi_pattern = r"^10.\d{4,9}/[-._;()/:A-Z0-9]+$"
    return re.match(doi_pattern, doi, re.IGNORECASE) is not None


def fetch_open_access_pdf(doi: str) -> bytes | str:
    doi = doi.strip()
    if not doi.startswith("http"):
        if not is_valid_doi(doi):
            return "Invalid DOI format."
        doi_url = f"https://doi.org/{doi}"
    else:
        doi_url = doi

    try:
        response = requests.get(doi_url, allow_redirects=True, timeout=10)
        response.raise_for_status()
        final_url = response.url
    except requests.RequestException:
        return "Failed to resolve DOI."

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" in href.lower():
                pdf_url = urljoin(final_url, href)
                pdf_response = requests.get(pdf_url, stream=True)
                if pdf_response.status_code == 200:
                    return pdf_response.content
                else:
                    return "Failed to download PDF."
        return "No PDF link found on page."
    except Exception as e:
        return f"Error occurred: {e}"
def extract_full_text_fitz(pdf_bytes):
    """
    Extract full text from PDF bytes.
    First tries external GROBID service if enabled, falls back to local PyMuPDF extraction.
    
    Args:
        pdf_bytes: PDF file content as bytes
        
    Returns:
        str: Extracted text content
    """
    env = load_environment()
    grobid_url = env.get("GROBID_SERVER_URL_OR_EXTERNAL_SERVICE")
    use_external = env.get("EXTERNAL_PDF_EXTRACTION_SERVICE", "False").lower() in ("true", "1", "yes")
    
    # Step 1: Try external service first if enabled (saves PDF to temp file, sends file, then deletes)
    if use_external and grobid_url:
        temp_file_path = None
        try:
            logger.info(f"Attempting to extract text using external service: {grobid_url}")
            
            # Save PDF bytes to a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(pdf_bytes)
                temp_file_path = temp_file.name
            
            logger.info(f"Saved PDF to temporary file: {temp_file_path}")
            
            # Send PDF file to external service
            # Try field name 'file' (common for file uploads)
            with open(temp_file_path, 'rb') as pdf_file:
                files = {'file': ('document.pdf', pdf_file, 'application/pdf')}
                response = requests.post(
                    grobid_url,
                    files=files,
                    timeout=30,  # 30 second timeout
                    headers={'Accept': 'text/plain'}
                )
            
            if response.status_code == 200:
                extracted_text = response.text
                logger.info(f"Successfully extracted text from PDF using external service ({len(extracted_text)} chars)")
                return extracted_text
            else:
                logger.warning(
                    f"External service returned status {response.status_code}: {response.text[:200]}. "
                    "Falling back to local extraction from PDF bytes."
                )
        except requests.exceptions.Timeout:
            logger.warning("External service request timed out. Falling back to local extraction from PDF bytes.")
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Could not connect to external service: {e}. Falling back to local extraction from PDF bytes.")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error calling external service: {e}. Falling back to local extraction from PDF bytes.")
        except Exception as e:
            logger.warning(f"Unexpected error calling external service: {e}. Falling back to local extraction from PDF bytes.")
        finally:
            # Always clean up temp file in finally block
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    logger.debug(f"Cleaned up temporary file: {temp_file_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temporary file {temp_file_path}: {cleanup_error}")
    
    # Step 2: Fallback to local extraction from PDF bytes using PyMuPDF (if external service fails or not enabled)
    try:
        logger.info("Using local PyMuPDF extraction from PDF bytes")
        doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
        full_text = "\n".join(page.get_text() for page in doc)
        doc.close()
        logger.info(f"Successfully extracted text using PyMuPDF ({len(full_text)} chars)")
        return full_text
    except Exception as e:
        logger.error(f"Error during local PDF extraction from bytes: {e}")
        raise Exception(f"Failed to extract text from PDF: {e}")



async def call_openrouter_llm(prompt: str, model: str = "openai/gpt-4") -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "OpenRouter API key not set."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": """
            You are a research assistant working with the Brain Behavior Quantification and Synchronization (BBQS) consortium. 

            The consortium tracks resources in the following categories:
            - Models (e.g., pose estimation models, embedding models)
            - Datasets (e.g., annotated video data, behavioral recordings)
            - Papers (e.g., methods or applications related to behavioral quantification)
            - Tools (e.g., analysis software, labeling interfaces)
            - Benchmarks (e.g., standardized datasets or protocols for evaluating performance)
            - Leaderboards (e.g., systems ranking models based on performance on a task)

            Your input will be a description, webpage, or paper about a **single primary resource**. However, that resource may mention other entities like datasets, benchmarks, or tools. These should not be extracted as separate resources.

            Instead, extract the primary resource with the following fields:
            - `name`: Resource name
            - `description`: A concise summary of the resource
            - `type`: One of [Model, Dataset, Paper, Tool, Benchmark, Leaderboard]
            - `category`: Domain category (e.g., Pose Estimation, Gaze Detection, Behavioral Quantification)
            - `target`: General target (e.g., Animal, Human, Mammals)
            - `specific_target`: Free-text list of specific sub-targets (e.g., Mice, Macaque)
            - `url`: Canonical URL (GitHub, HuggingFace, arXiv, lab site, etc.)
            - `mentions` (optional): Dictionary of referenced models, datasets, benchmarks, papers, or tools used or discussed within the resource.
            - `provenance` (optional): A dictionary indicating the source section from which each field was extracted (e.g., title, abstract, methods)

            Also include a `mentions` field if applicable. This is a dictionary that may include referenced datasets, models, benchmarks, or tools used or described within the resource. 
            Be mindful that webpages may contain many extraneous references and links that are not relevant to the primary resource and should not be included in mentions.
            If a field is missing or unknown, use `null`. Only return a single JSON object under the key `resource`"""},
            {"role": "user", "content": prompt}
        ]
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"OpenRouter request failed: {response.status_code} - {response.text}"

def load_env_vars_from_ui(env_vars: dict):
    """
    Loads environment variables passed from a UI input dictionary.

    Args:
        env_vars (dict): Dictionary containing environment variable key-value pairs
                         required for the StructSense or multi-agent application.

    Notes:
        - All expected environment variables will be set.
        - Missing variables will default to 'false'.
        - Boolean values are converted to lowercase strings.
    """

    expected_keys = [
        "ENABLE_WEIGHTSANDBIAS",
        "ENABLE_MLFLOW",
        "ENABLE_KG_SOURCE",
        "ONTOLOGY_DATABASE",
        "WEAVIATE_API_KEY",
        "WEAVIATE_HTTP_HOST",
        "WEAVIATE_HTTP_PORT",
        "WEAVIATE_HTTP_SECURE",
        "WEAVIATE_GRPC_HOST",
        "WEAVIATE_GRPC_PORT",
        "WEAVIATE_GRPC_SECURE",
        "OLLAMA_API_ENDPOINT",
        "OLLAMA_MODEL",
        "GROBID_SERVER_URL_OR_EXTERNAL_SERVICE",
        "EXTERNAL_PDF_EXTRACTION_SERVICE"
    ]

    for key in expected_keys:
        value = env_vars.get(key, "false")

        # Convert booleans and None to lowercase string
        if isinstance(value, bool):
            value = str(value).lower()
        elif value is None:
            value = "false"

        os.environ[key] = str(value)

    # Log confirmation for key services
    logger.info("*" * 100)
    logger.info(f"GROBID_SERVER_URL_OR_EXTERNAL_SERVICE = {os.getenv('GROBID_SERVER_URL_OR_EXTERNAL_SERVICE')}")
    logger.info(f"EXTERNAL_PDF_EXTRACTION_SERVICE = {os.getenv('EXTERNAL_PDF_EXTRACTION_SERVICE')}")
    logger.info("*" * 100)

def load_config(config: Union[str, Path, Dict], type: str) -> dict:
    """
    Loads the configuration from a YAML file

    Args:
        config (Union[str, Path, dict]): The configuration source.
        type (str): The type of the configuration, e.g., crew or tasks

    Returns:
        dict: Parsed LLM configuration.

    Raises:
        FileNotFoundError: If the YAML file is not found.
        ValueError: If the input is not a valid YAML file or dictionary.
        yaml.YAMLError: If there is an error parsing the YAML configuration.
    """
    if isinstance(config, dict):
        return config

    # Try different path resolutions for config file
    if isinstance(config, str):
        paths_to_try = [
            Path(config),  # As provided
            Path.cwd() / config,  # Relative to current directory
            Path(config).absolute(),  # Absolute path
            Path(config).resolve(),  # Resolved path (handles .. and .)
        ]

        logger.info(f"Trying config paths: {[str(p) for p in paths_to_try]}")

        # Find first existing path with valid extension
        config_path = next(
            (
                p
                for p in paths_to_try
                if p.exists() and p.suffix.lower() in {".yml", ".yaml"}
            ),
            paths_to_try[0],  # Default to first path if none exist
        )
    else:
        config_path = Path(config)

    if not config_path.exists() or config_path.suffix.lower() not in {".yml", ".yaml"}:
        error_msg = (
            f"Invalid configuration: {config}\n"
            f"Expected a YAML file (.yml or .yaml) or a dictionary.\n"
            "Tried the following paths:\n" + "\n".join(f"- {p}" for p in paths_to_try)
        )
        raise ValueError(error_msg)

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config_file_content = yaml.safe_load(file)
            logger.info(f"file processing - {file}, type: {type}")
            return config_file_content

    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {config}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML file {config}: {e}")

def _is_safe_path(p: Path, base: Path) -> bool:
    """Return True if p is inside base."""
    try:
        return p.resolve().is_relative_to(base)
    except AttributeError:
        # Fallback for older versions
        p_res = p.resolve()
        base_res = base.resolve()
        return str(p_res).startswith(str(base_res) + str(Path.sep))

def run_kickoff_with_config(
    config_path: str,
    input_source: Union[str, dict],
    api_key: str,
    chunking: bool,
):
    # Load all sections from your config file
    all_config = load_config(config_path, "all")

    agent_config = all_config.get("agent_config", {})
    embedder_config = all_config.get("embedder_config", {})
    task_config = all_config.get("task_config", {})
    knowledge_config = all_config.get("knowledge_config", {})

    # input_source can be a file path (str) or text content (str)
    # Convert to string if needed
    input_source_str = str(input_source) if input_source else ""

    # Call your new kickoff
    try:
        result = kickoff(
            agentconfig=agent_config,
            taskconfig=task_config,
            embedderconfig=embedder_config,
            knowledgeconfig=knowledge_config,
            input_source=input_source_str,
            enable_human_feedback=False,
            api_key=api_key,
            enable_chunking=chunking,
        )
        return True, result
    except Exception as e:
        return False, str(e)

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

def _json_sendable(obj):
    """Best-effort JSON serialization for arbitrary results."""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except TypeError:
        return json.dumps(obj, default=str, ensure_ascii=False)

def _to_bool(v, default):
    """Convert various types to boolean."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(v, (int, float)):
        return bool(v)
    return default

def _setup_environment():
    """Set up environment variables for downstream libraries."""
    env = load_environment()
    os.environ["ENABLE_KG_SOURCE"] = env.get("ENABLE_KG_SOURCE")
    os.environ["ONTOLOGY_DATABASE"] = env.get("ONTOLOGY_DATABASE")
    os.environ["WEAVIATE_GRPC_HOST"] = env.get("WEAVIATE_GRPC_HOST")
    os.environ["WEAVIATE_HTTP_HOST"] = env.get("WEAVIATE_HTTP_HOST")
    os.environ["WEAVIATE_API_KEY"] = env.get("WEAVIATE_API_KEY")
    os.environ["EXTERNAL_PDF_EXTRACTION_SERVICE"] = env.get("EXTERNAL_PDF_EXTRACTION_SERVICE")
    os.environ["GROBID_SERVER_URL_OR_EXTERNAL_SERVICE"] = env.get("GROBID_SERVER_URL_OR_EXTERNAL_SERVICE")
    os.environ["OLLAMA_API_ENDPOINT"] =  env.get("OLLAMA_API_ENDPOINT")
    os.environ["OLLAMA_MODEL"] = env.get("OLLAMA_MODEL")



    logger.info("*" * 100)
    logger.info("GROBID: %s", os.getenv("GROBID_SERVER_URL_OR_EXTERNAL_SERVICE"))
    logger.info("EXTERNAL_PDF_EXTRACTION_SERVICE: %s", os.getenv("EXTERNAL_PDF_EXTRACTION_SERVICE"))
    logger.info("*" * 100)

async def _cleanup_files(write_file, target_path: Optional[Path]):
    """Clean up file handles and temporary files."""
    try:
        if write_file is not None:
            await asyncio.to_thread(write_file.close)
        if target_path and target_path.exists():
            target_path.unlink(missing_ok=True)
        if target_path:
            target_path.with_suffix(target_path.suffix + ".json").unlink(missing_ok=True)
    except Exception:
        pass

_job_storage: Dict[str, Dict] = {}

def _create_job(task_id: str, client_id: str, filename: str) -> Dict:
    """Create a new job entry."""
    job = {
        "task_id": task_id,
        "client_id": client_id,
        "filename": filename,
        "status": JobStatus.PENDING,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "result": None,
        "error": None,
    }
    _job_storage[task_id] = job
    return job

def _update_job_status(task_id: str, status: JobStatus, result=None, error=None):
    """Update job status and result."""
    if task_id in _job_storage:
        _job_storage[task_id]["status"] = status
        _job_storage[task_id]["updated_at"] = datetime.now().isoformat()
        if result is not None:
            _job_storage[task_id]["result"] = result
        if error is not None:
            _job_storage[task_id]["error"] = error

def _get_job(task_id: str) -> Optional[Dict]:
    """Get job by task_id."""
    return _job_storage.get(task_id)

async def _process_job_background(
        task_id: str,
        config_path: str,
        input_source: Union[str, Path],
        api_key: str,
        chunking: bool,
        target_path: Optional[Path] = None
):
    """Process job in background - continues even if client disconnects."""
    _update_job_status(task_id, JobStatus.RUNNING)

    try:
        _setup_environment()
        if api_key is None:
            env = load_environment()
            api_key = env.get("OPENROUTER_API_KEY")

        def _run():
            return run_kickoff_with_config(
                config_path=config_path,
                input_source=input_source,
                api_key=api_key,
                chunking=chunking,
            )

        status, result = await asyncio.to_thread(_run)

        if status:
            _update_job_status(task_id, JobStatus.COMPLETED, result=result)
        else:
            _update_job_status(task_id, JobStatus.FAILED, error=str(result))

    except Exception as e:
        logger.exception(f"Background job {task_id} error")
        _update_job_status(task_id, JobStatus.FAILED, error=str(e))
    finally:
        # Clean up files after processing
        if target_path and target_path.exists():
            try:
                sidecar = target_path.with_suffix(target_path.suffix + ".json")
                await asyncio.to_thread(target_path.unlink, True)
                await asyncio.to_thread(sidecar.unlink, True)
            except Exception:
                pass

async def _handle_websocket_connection(websocket: WebSocket, client_id: str, default_config: str, api_key: str):
    """Shared WebSocket connection handler for PDF processing."""
    # Note: websocket.accept() should already be called in the router endpoint before this function
    # Do NOT call accept() here to avoid double-accept errors

    write_file = None
    target_path: Optional[Path] = None
    expected_bytes: Optional[int] = None
    received_bytes = 0
    last_message_text: Optional[str] = None
    client_connected = True  # Track if client is still connected

    # per-connection kickoff params (set during "start")
    cfg_path = default_config
    env_file = None
    api_key = api_key
    chunking = False

    async def _send_update(task_id: str):
        """Send status update to connected client."""
        nonlocal client_connected
        if not client_connected:
            return

        job = _get_job(task_id)
        if job:
            try:
                update = {
                    "type": "job_update",
                    "task_id": task_id,
                    "status": job["status"],
                    "updated_at": job["updated_at"],
                }

                if job["status"] == JobStatus.COMPLETED:
                    update["result"] = job["result"]
                    await websocket.send_text(_json_sendable(update))
                elif job["status"] == JobStatus.FAILED:
                    update["error"] = job["error"]
                    await websocket.send_text(_json_sendable(update))
                elif job["status"] == JobStatus.RUNNING:
                    await websocket.send_text(_json_sendable(update))
            except Exception:
                client_connected = False

    try:
        while True:
            message = await websocket.receive()

            # ---- TEXT FRAMES (JSON control) ----
            if message.get("text") is not None:
                try:
                    meta = json.loads(message["text"])
                except json.JSONDecodeError:
                    await websocket.send_text(_json_sendable({"type": "error", "message": "Invalid JSON control frame"}))
                    continue

                mtype = meta.get("type")

                if mtype == "status":
                    # Check job status for reconnection
                    task_id = meta.get("task_id")
                    if not task_id:
                        await websocket.send_text(_json_sendable({"type": "error", "message": "task_id required"}))
                        continue

                    job = _get_job(task_id)
                    if not job:
                        await websocket.send_text(_json_sendable({"type": "error", "message": f"Job {task_id} not found"}))
                        continue

                    response = {
                        "type": "job_status",
                        "task_id": task_id,
                        "status": job["status"],
                        "created_at": job["created_at"],
                        "updated_at": job["updated_at"],
                    }

                    if job["status"] == JobStatus.COMPLETED:
                        response["result"] = job["result"]
                    elif job["status"] == JobStatus.FAILED:
                        response["error"] = job["error"]

                    await websocket.send_text(_json_sendable(response))

                elif mtype == "message":
                    last_message_text = (meta.get("text") or "").strip()
                    if not last_message_text:
                        await websocket.send_text(_json_sendable({"type": "error", "message": "Empty message"}))
                        continue
                    await websocket.send_text(_json_sendable({"type": "ok", "message": "message stored"}))

                elif mtype == "start":
                    if write_file is not None:
                        await websocket.send_text(_json_sendable({"type": "error", "message": "Transfer already in progress"}))
                        continue

                    # pull kickoff overrides (optional) from the client
                    cfg_path = meta.get("config") or cfg_path
                    env_file = meta.get("env_file") or env_file
                    api_key = meta.get("api_key") or api_key
                    chunking = _to_bool(meta.get("chunking"), chunking)
                    
                    # Get input type and handle accordingly
                    input_type = meta.get("input_type", "pdf")  # default to "pdf" for backward compatibility
                    doi = meta.get("doi")
                    text_content = meta.get("text_content")
                    input_source = None
                    filename = None
                    target_path = None

                    if input_type == "doi" and doi:
                        # Handle DOI input
                        try:
                            await websocket.send_text(_json_sendable({"type": "status", "message": "Fetching PDF from DOI..."}))
                            pdf_bytes = await asyncio.to_thread(fetch_open_access_pdf, doi)
                            
                            if isinstance(pdf_bytes, str):
                                # Error occurred
                                await websocket.send_text(_json_sendable({"type": "error", "message": pdf_bytes}))
                                continue
                            
                            # First try GROBID service (if enabled) - sends PDF bytes directly
                            await websocket.send_text(_json_sendable({"type": "status", "message": "Attempting text extraction via GROBID service..."}))
                            input_source = await asyncio.to_thread(extract_full_text_fitz, pdf_bytes)
                            filename = f"doi_{doi.replace('/', '_')}.txt"
                        except Exception as e:
                            await websocket.send_text(_json_sendable({"type": "error", "message": f"Error processing DOI: {str(e)}"}))
                            continue
                    
                    elif input_type == "pdf" and meta.get("name"):
                        # Handle PDF file upload (existing behavior)
                        name = meta.get("name").split("/")[-1]
                        if not name.lower().endswith(".pdf"):
                            await websocket.send_text(_json_sendable({"type": "error", "message": "Only .pdf files allowed"}))
                            continue

                        # expected size (optional)
                        expected_bytes = meta.get("size")
                        try:
                            expected_bytes = int(expected_bytes) if expected_bytes is not None else None
                        except Exception:
                            expected_bytes = None

                        # safe path
                        target_path = (UPLOAD_DIR / name).resolve()
                        if not _is_safe_path(target_path, UPLOAD_DIR):
                            await websocket.send_text(_json_sendable({"type": "error", "message": "Bad path"}))
                            target_path = None
                            continue

                        # open file writer off the loop
                        write_file = await asyncio.to_thread(open, target_path, "wb")
                        received_bytes = 0
                        filename = name

                        # sidecar metadata (optional)
                        if last_message_text:
                            meta_path = target_path.with_suffix(target_path.suffix + ".json")
                            await asyncio.to_thread(
                                meta_path.write_text,
                                json.dumps({"client_id": client_id, "message": last_message_text}, ensure_ascii=False, indent=2)
                            )

                        await websocket.send_text(_json_sendable({"type": "ack", "message": "ready"}))
                        continue  # Wait for file upload via binary frames
                    
                    elif input_type == "text" and text_content:
                        # Handle text input
                        input_source = str(text_content)
                        filename = "text_input.txt"
                    
                    else:
                        await websocket.send_text(_json_sendable({
                            "type": "error", 
                            "message": f"Invalid input_type '{input_type}' or missing required data. For 'pdf', provide 'name'. For 'doi', provide 'doi'. For 'text', provide 'text_content'."
                        }))
                        continue

                    # For non-file inputs (doi, text), start processing immediately
                    if input_source is not None:
                        # Generate task_id and create job
                        import uuid
                        task_id = str(uuid.uuid4())
                        job = _create_job(task_id, client_id, filename or "input")

                        # Send task_id to client immediately
                        await websocket.send_text(_json_sendable({
                            "type": "task_created",
                            "task_id": task_id,
                            "filename": filename,
                            "message": "Processing started. You can disconnect and reconnect later with this task_id."
                        }))

                        # Start background processing task
                        asyncio.create_task(_process_job_background(
                            task_id=task_id,
                            config_path=cfg_path,
                            input_source=input_source,
                            api_key=api_key,
                            chunking=chunking,
                            target_path=None  # No file to clean up for DOI/text
                        ))

                        # Monitor job and send updates if client is still connected
                        async def _monitor_job():
                            """Monitor job and send updates to connected client."""
                            nonlocal client_connected
                            while client_connected:
                                job = _get_job(task_id)
                                if not job:
                                    break

                                if job["status"] in [JobStatus.COMPLETED, JobStatus.FAILED]:
                                    await _send_update(task_id)
                                    break
                                elif job["status"] == JobStatus.RUNNING:
                                    await _send_update(task_id)

                                await asyncio.sleep(2)  # Check every 2 seconds

                        asyncio.create_task(_monitor_job())
                        
                        # reset state for next request
                        last_message_text = None

                elif mtype == "end":
                    if write_file is None:
                        await websocket.send_text(_json_sendable({"type": "error", "message": "No transfer in progress"}))
                        continue

                    # finalize file
                    try:
                        await asyncio.to_thread(write_file.flush)
                    finally:
                        await asyncio.to_thread(write_file.close)
                        write_file = None

                    ok = (expected_bytes is None) or (received_bytes == expected_bytes)
                    filename = target_path.name if target_path else None

                    if not target_path or not target_path.exists():
                        await websocket.send_text(_json_sendable({"type": "error", "message": "File not found"}))
                        continue

                    # Generate task_id and create job
                    import uuid
                    task_id = str(uuid.uuid4())
                    job = _create_job(task_id, client_id, filename)

                    # Store file path in job for background processing
                    job["file_path"] = str(target_path)

                    # Send task_id to client immediately
                    await websocket.send_text(_json_sendable({
                        "type": "task_created",
                        "task_id": task_id,
                        "filename": filename,
                        "message": "Processing started. You can disconnect and reconnect later with this task_id."
                    }))

                    # Start background processing task (continues even if client disconnects)
                    asyncio.create_task(_process_job_background(
                        task_id=task_id,
                        config_path=cfg_path,
                        input_source=target_path,
                        api_key=api_key,
                        chunking=chunking,
                        target_path=target_path
                    ))

                    # Monitor job and send updates if client is still connected
                    async def _monitor_job():
                        """Monitor job and send updates to connected client."""
                        nonlocal client_connected
                        while client_connected:
                            job = _get_job(task_id)
                            if not job:
                                break

                            if job["status"] in [JobStatus.COMPLETED, JobStatus.FAILED]:
                                await _send_update(task_id)
                                break
                            elif job["status"] == JobStatus.RUNNING:
                                await _send_update(task_id)

                            await asyncio.sleep(2)  # Check every 2 seconds

                    asyncio.create_task(_monitor_job())

                    # reset state for next upload
                    target_path = None
                    expected_bytes = None
                    received_bytes = 0
                    last_message_text = None

                else:
                    await websocket.send_text(_json_sendable({"type": "error", "message": f"Unknown control type: {mtype}"}))

            # ---- BINARY FRAMES (PDF CHUNKS) ----
            elif message.get("bytes") is not None:
                if write_file is None:
                    await websocket.send_text(_json_sendable({"type": "error", "message": "Binary chunk before start"}))
                    continue

                chunk = message["bytes"]
                received_bytes += len(chunk)
                await asyncio.to_thread(write_file.write, chunk)

                # progress every ~1MB
                if received_bytes % (1 << 20) < len(chunk):
                    await websocket.send_text(_json_sendable({"type": "progress", "bytes": received_bytes}))

    except WebSocketDisconnect:
        client_connected = False
        # Don't cleanup files here - job may still be processing in background
        # Only cleanup if file upload was incomplete
        if write_file is not None:
            await _cleanup_files(write_file, target_path)

    except Exception as e:
        client_connected = False
        try:
            await websocket.send_text(_json_sendable({"type": "error", "message": str(e)}))
        except Exception:
            pass
        # Don't cleanup files here - job may still be processing in background
        if write_file is not None:
            await _cleanup_files(write_file, target_path)