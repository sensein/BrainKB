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
logger = logging.getLogger(__name__)
import fitz
from io import BytesIO
import requests
from core.shared import load_environment  # adjust this import to your setup
import json
from pymongo import MongoClient, ReturnDocument
from datetime import datetime, timezone
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

                # ✅ Attach as top-level fields with exact names
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


def download_open_access_pdf(doi: str, filename: str = "paper.pdf"):
    doi = doi.strip()
    if not doi.startswith("http"):
        if not is_valid_doi(doi):
            return "Invalid DOI format."
        doi_url = f"https://doi.org/{doi}"
    else:
        doi_url = doi

    try:
        # Step 1: Resolve DOI
        response = requests.get(doi_url, allow_redirects=True, timeout=10)
        response.raise_for_status()
        final_url = response.url
    except requests.RequestException as e:

        return "Failed to resolve DOI"

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" in href.lower():
                pdf_url = urljoin(final_url, href)

                # Step 3: Download PDF
                pdf_response = requests.get(pdf_url, stream=True)
                if pdf_response.status_code == 200:
                    save_path = os.path.join(os.getcwd(), filename)
                    with open(save_path, "wb") as f:
                        for chunk in pdf_response.iter_content(chunk_size=8192):
                            f.write(chunk)
                else:
                    return "Unable to download PDF"

        return "Unable to download PDF"
    except Exception as e:
        return f"Error {e} occured, unable to download PDF"

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
    doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)
    return full_text



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