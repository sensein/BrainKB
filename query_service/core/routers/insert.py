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
# @File    : insert.py
# @Software: PyCharm


from fastapi import APIRouter, Request, HTTPException, status, UploadFile, File, Form
from core.graph_database_connection_manager import insert_data_gdb
import json
import logging
from core.pydantic_schema import InputKGTripleSchema, NamedGraphSchema
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from fastapi import Depends
from core.shared import convert_ttl_to_named_graph, named_graph_metadata, convert_json_to_ttl, convert_to_turtle
from core.graph_database_connection_manager import  fetch_data_gdb
import datetime
router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/insert/knowledge-graph-triples",
             include_in_schema=True
             )
async def insert_knowledge_graph_triples(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
        request: InputKGTripleSchema
):
    try:
        data = json.loads(request.json())
        logger.info(f"Received data: {data}")
        if data["type"] == "ttl":
            named_graph_ttl = convert_ttl_to_named_graph(ttl_str=data["kg_data"],
                                                         named_graph_uri=data["named_graph_iri"])
            response = insert_data_gdb(named_graph_ttl)
            return response

    except json.JSONDecodeError as e:
        logger.error("JSON decoding failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON format"
        )
    except Exception as e:
        logger.error("An error occurred", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred processing the request",
        )
        
@router.post("/insert/files/structured-resource-json-to-kg",
             include_in_schema=True
             )
async def insert_json_to_knowledge_graph(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    files: Annotated[list[UploadFile], File(...)],
    named_graph_iri: Annotated[str, Form(...)],
    base_uri: Annotated[str, Form(...)] = "http://example.org/resource/"
):
    """
    Upload and insert multiple JSON files as knowledge graph triples
    
    Args:
        files: List of uploaded JSON files
        named_graph_iri: The URI for the named graph
        base_uri: Base URI for generating resource URIs
    """
    try:
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one JSON file must be uploaded"
            )
        
        # Process each file
        results = []
        total_size = 0
        successful_files = 0
        failed_files = 0
        
        for file in files:
            try:
                # Validate file extension
                file_extension = file.filename.split('.')[-1].lower()
                if file_extension not in ["json"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File {file.filename} extension must be .json for JSON files"
                    )
                
                # Read file content
                file_content = await file.read()
                file_content_str = file_content.decode('utf-8')
                total_size += len(file_content)
                
                logger.info(f"Processing JSON file: {file.filename}, size: {len(file_content)} bytes")
                
                # Parse JSON content
                try:
                    json_data = json.loads(file_content_str)
                    logger.info(f"Successfully parsed JSON for {file.filename}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON for {file.filename}: {str(e)}")
                    results.append({
                        "filename": file.filename,
                        "status": "failed",
                        "error": f"Invalid JSON format: {str(e)}"
                    })
                    failed_files += 1
                    continue
                
                # Convert JSON to TTL format
                try:
                    ttl_data = convert_json_to_ttl(
                        json_data=json_data,
                        base_uri=base_uri
                    )
                    logger.info(f"Successfully converted JSON to TTL for {file.filename}")
                except Exception as e:
                    logger.error(f"Failed to convert JSON to TTL for {file.filename}: {str(e)}")
                    results.append({
                        "filename": file.filename,
                        "status": "failed",
                        "error": f"JSON to TTL conversion failed: {str(e)}"
                    })
                    failed_files += 1
                    continue
                
                # Convert TTL to named graph format
                named_graph_ttl = convert_ttl_to_named_graph(
                    ttl_str=ttl_data,
                    named_graph_uri=named_graph_iri
                )
                
                # Insert into graph database
                response = insert_data_gdb(named_graph_ttl)
                
                logger.info(f"Successfully inserted JSON file {file.filename} into knowledge graph")
                results.append({
                    "filename": file.filename,
                    "status": "success",
                    "file_size": len(file_content),
                    "response": response
                })
                successful_files += 1
                
            except HTTPException:
                # Re-raise HTTP exceptions as-is
                raise
            except Exception as e:
                logger.error(f"An error occurred processing JSON file {file.filename}", exc_info=True)
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(e)
                })
                failed_files += 1
        
        # Return summary response
        return {
            "message": f"Processed {len(files)} JSON files. {successful_files} successful, {failed_files} failed.",
            "named_graph_iri": named_graph_iri,
            "base_uri": base_uri,
            "total_files": len(files),
            "successful_files": successful_files,
            "failed_files": failed_files,
            "total_size": total_size,
            "results": results
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error("An error occurred during JSON file processing", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred processing the JSON files: {str(e)}",
        )

@router.post("/insert/files/knowledge-graph-triples",
             include_in_schema=True
             )
async def insert_file_knowledge_graph_triples(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    files: Annotated[list[UploadFile], File(...)],
    named_graph_iri: Annotated[str, Form(...)],
    file_type: Annotated[str, Form(...)] = "ttl"  # "ttl" or "jsonld"
):
    """
    Upload and insert knowledge graph triples from multiple files (TTL or JSON-LD format)
    
    Args:
        files: List of uploaded files (TTL or JSON-LD format)
        named_graph_iri: The URI for the named graph
        file_type: Type of files ("ttl" or "jsonld")
    """
    try:
        # Validate file type
        if file_type not in ["ttl", "jsonld"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="file_type must be either 'ttl' or 'jsonld'"
            )
        
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one file must be uploaded"
            )
        
        # Process each file
        results = []
        total_size = 0
        successful_files = 0
        failed_files = 0
        
        for file in files:
            try:
                # Validate file extension
                file_extension = file.filename.split('.')[-1].lower()
                if file_type == "ttl" and file_extension not in ["ttl", "turtle"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File {file.filename} extension must be .ttl or .turtle for TTL files"
                    )
                elif file_type == "jsonld" and file_extension not in ["json", "jsonld"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File {file.filename} extension must be .json or .jsonld for JSON-LD files"
                    )
                
                # Read file content
                file_content = await file.read()
                file_content_str = file_content.decode('utf-8')
                total_size += len(file_content)
                
                logger.info(f"Processing file: {file.filename}, type: {file_type}, size: {len(file_content)} bytes")
                
                # Convert file content to TTL if it's JSON-LD
                if file_type == "jsonld":
                    try:
                        ttl_content = convert_to_turtle(file_content_str)
                        logger.info(f"Successfully converted JSON-LD to TTL for {file.filename}")
                    except Exception as e:
                        logger.error(f"Failed to convert JSON-LD to TTL for {file.filename}: {str(e)}")
                        results.append({
                            "filename": file.filename,
                            "status": "failed",
                            "error": f"Invalid JSON-LD format: {str(e)}"
                        })
                        failed_files += 1
                        continue
                else:
                    # For TTL files, use content as-is
                    ttl_content = file_content_str
                
                # Convert TTL to named graph format
                named_graph_ttl = convert_ttl_to_named_graph(
                    ttl_str=ttl_content,
                    named_graph_uri=named_graph_iri
                )
                
                # Insert into graph database
                response = insert_data_gdb(named_graph_ttl)
                
                logger.info(f"Successfully inserted file {file.filename} into knowledge graph")
                results.append({
                    "filename": file.filename,
                    "status": "success",
                    "file_size": len(file_content),
                    "response": response
                })
                successful_files += 1
                
            except HTTPException:
                # Re-raise HTTP exceptions as-is
                raise
            except Exception as e:
                logger.error(f"An error occurred processing file {file.filename}", exc_info=True)
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(e)
                })
                failed_files += 1
        
        # Return summary response
        return {
            "message": f"Processed {len(files)} files. {successful_files} successful, {failed_files} failed.",
            "file_type": file_type,
            "named_graph_iri": named_graph_iri,
            "total_files": len(files),
            "successful_files": successful_files,
            "failed_files": failed_files,
            "total_size": total_size,
            "results": results
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error("An error occurred during file processing", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred processing the files: {str(e)}",
        )

@router.post("/register-named-graph")
async def create_named_graph(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        request: NamedGraphSchema
):
    try:
        data = json.loads(request.json())

        # Ensure named_graph_url ends with '/'
        named_graph_url = data['named_graph_url']
        description = data['description']
        if not named_graph_url.endswith('/'):
            named_graph_url += '/'

        query = f"""
        ASK WHERE {{
          GRAPH <https://brainkb.org/metadata/named-graph> {{
            ?s ?p ?o.
            FILTER(?s = <{named_graph_url}>)
          }}
        }}
        """
        named_graph_exists = fetch_data_gdb(query)
        if not named_graph_exists["message"]["boolean"]:

            response = insert_data_gdb(named_graph_metadata(
                named_graph_url=named_graph_url,
                description=description,
                )
            )
            return response
        else:
            return "Graph is already registered."
    except json.JSONDecodeError as e:
        logger.error("JSON decoding failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON format {e}"
        )
    except Exception as e:
        logger.error("An error occurred", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred processing the request {e}",
        )

