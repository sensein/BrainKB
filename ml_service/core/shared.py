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
logger = logging.getLogger(__name__)
import fitz
from io import BytesIO
import asyncio
from pathlib import Path
from datetime import datetime, timezone
import tempfile
import aiofiles

# for multi-agent
UPLOAD_DIR = Path("uploads").resolve()
UPLOAD_DIR.mkdir(exist_ok=True)


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
async def _get_base_from_context(jsonld_data):
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
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(context)
                response.raise_for_status()
                context = response.json()
        except httpx.RequestError as e:
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


async def convert_to_turtle(jsonld_data):
    """
    Converts JSON-LD data to Turtle format.
    Returns:
        - Serialized Turtle string on success.
        - False if an error occurs.
    """
    logger.info("Converting JSON-LD data to Turtle format")
    base = await _get_base_from_context(jsonld_data)
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




async def named_graph_exists(named_graph_iri: str) -> dict:
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
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(endpoint)
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
    except httpx.RequestError as e:
        return {
            "status": "error",
            "message": f"Error connecting to query service: {str(e)}"
        }



def is_valid_doi(doi: str) -> bool:
    doi_pattern = r"^10.\d{4,9}/[-._;()/:A-Z0-9]+$"
    return re.match(doi_pattern, doi, re.IGNORECASE) is not None


async def fetch_open_access_pdf(doi: str) -> bytes | str:
    doi = doi.strip()
    if not doi.startswith("http"):
        if not is_valid_doi(doi):
            return "Invalid DOI format."
        doi_url = f"https://doi.org/{doi}"
    else:
        doi_url = doi

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(doi_url)
            response.raise_for_status()
            final_url = str(response.url)
            response_text = response.text
    except httpx.RequestError:
        return "Failed to resolve DOI."

    try:
        soup = BeautifulSoup(response_text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" in href.lower():
                pdf_url = urljoin(final_url, href)
                async with httpx.AsyncClient(timeout=30.0) as pdf_client:
                    pdf_response = await pdf_client.get(pdf_url)
                    if pdf_response.status_code == 200:
                        return pdf_response.content
                    else:
                        return "Failed to download PDF."
        return "No PDF link found on page."
    except Exception as e:
        return f"Error occurred: {e}"
async def extract_full_text_fitz(pdf_bytes):
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
            async with aiofiles.open(temp_file_path, 'rb') as pdf_file:
                pdf_content = await pdf_file.read()
                # httpx uses a tuple format: (filename, content, content_type)
                files = {'file': ('document.pdf', pdf_content, 'application/pdf')}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        grobid_url,
                        files=files,
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
        except httpx.TimeoutException:
            logger.warning("External service request timed out. Falling back to local extraction from PDF bytes.")
        except httpx.ConnectError as e:
            logger.warning(f"Could not connect to external service: {e}. Falling back to local extraction from PDF bytes.")
        except httpx.RequestError as e:
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
    # Run blocking PDF extraction in thread pool
    try:
        logger.info("Using local PyMuPDF extraction from PDF bytes")
        def _extract_text():
            doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
            full_text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return full_text
        
        full_text = await asyncio.to_thread(_extract_text)
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

async def load_config(config: Union[str, Path, Dict], type: str) -> dict:
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
        async with aiofiles.open(config_path, "r", encoding="utf-8") as file:
            content = await file.read()
            config_file_content = yaml.safe_load(content)
            logger.info(f"file processing - {config_path}, type: {type}")
            return config_file_content

    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {config}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML file {config}: {e}")

