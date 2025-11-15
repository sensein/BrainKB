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
# @File    : structsense.py
# @Software: PyCharm
from fastapi import Request
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Depends, WebSocket
from fastapi.responses import JSONResponse
import logging
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes, authenticate_websocket
from core.shared import parse_yaml_or_json, upsert_structured_resources
from core.pydantic_models import AgentConfig, TaskConfig, EmbedderConfig, SearchKeyConfig
from structsense import kickoff
import os
from datetime import datetime, timezone
from core.shared import upsert_ner_annotations
from core.shared import (_is_safe_path, run_kickoff_with_config, JobStatus, _job_storage,
                         _handle_websocket_connection, _get_job)
from core.configuration import load_environment
from pymongo import MongoClient
from typing import Optional
from bson import ObjectId


logger = logging.getLogger(__name__)


def get_mongo_client(request: Request) -> MongoClient:
    """
    Dependency to get MongoDB client from app state.
    The client is initialized once during app startup and reused for all requests.
    """
    client = request.app.state.mongo_client
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="MongoDB client not initialized. Please check server configuration."
        )
    return client


def serialize_mongo_document(doc):
    """
    Recursively convert MongoDB document to JSON-serializable format.
    Converts ObjectId to string and datetime to ISO format string.
    """
    if isinstance(doc, dict):
        return {key: serialize_mongo_document(value) for key, value in doc.items()}
    elif isinstance(doc, list):
        return [serialize_mongo_document(item) for item in doc]
    elif isinstance(doc, ObjectId):
        return str(doc)
    elif isinstance(doc, datetime):
        return doc.isoformat()
    else:
        return doc

router = APIRouter(tags=["Multi-agent Systems"])



@router.get("/ws-info")
async def ws_info():
    return JSONResponse({
        "connect_to": "/ws/{client_id}/ner or /ws/{client_id}/resource",
        "protocol": [
            {"type": "message", "text": "string (required, non-empty)"},
            {
                "type": "start",
                "input_type": "pdf|doi|text (required)",
                "name": "file.pdf (required if input_type='pdf')",
                "doi": "string (required if input_type='doi')",
                "text_content": "string (required if input_type='text')",
                "size": "int (optional, only for input_type='pdf')",
                "config": "string (optional, config file path)",
                "api_key": "string (optional)",
                "chunking": "bool (optional)"
            },
            {"type": "end", "description": "Only required for input_type='pdf' file uploads"},
            {"type": "status", "task_id": "string (for reconnection)"}
        ],
        "input_types": {
            "pdf": "Upload PDF file via binary frames between start/end messages",
            "doi": "Provide DOI string in start message, PDF will be fetched and processed automatically",
            "text": "Provide text_content in start message, will be processed immediately"
        },
        "binary": "send PDF bytes between start/end (only for input_type='pdf')",
        "responses": [
            {"type": "ack", "description": "Ready for file upload (only for input_type='pdf')"},
            {"type": "status", "message": "string", "description": "Status updates during processing"},
            {"type": "task_created", "task_id": "...", "filename": "...", "message": "..."},
            {"type": "job_status"},
            {"type": "job_update"},
            {"type": "progress", "description": "Only for input_type='pdf' file uploads"},
            {"type": "error"}
        ],
        "note": "Save task_id from 'task_created' message. Use 'status' message with task_id to check job progress after reconnection."
    })


@router.websocket("/ws/ner/{client_id}")
async def websocket_endpoint_ner(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for NER processing with JWT authentication."""
    try:
        # CRITICAL: Accept WebSocket connection FIRST before any other operations
        # FastAPI/Starlette checks origin before calling this endpoint
        # added because i was getting 403 despite cors update
        origin = websocket.headers.get("origin")
        logger.info(f"WebSocket connection attempt from origin: {origin}, client_id: {client_id}")

        await websocket.accept()

        user = await authenticate_websocket(websocket, required_scopes=["write"])
        if not user:
            logger.warning(f"Authentication failed for client_id: {client_id}")
            await websocket.close(code=1008, reason="Authentication failed")
            return

        logger.info(f"WebSocket authenticated for user: {user.get('email')}, client_id: {client_id}")

        # Extract api_key from query parameters ?api_key=XXXXX if provided
        api_key = websocket.query_params.get("api_key") or None
        logger.info(f"WebSocket connection established for client_id: {client_id}, api_key provided: {api_key is not None}")

        # Use the correct path to the config file
        config_path = os.path.join(os.path.dirname(__file__), "ner_config_gpt.yaml")
        await _handle_websocket_connection(websocket, client_id, config_path, api_key)

    except Exception as e:
        logger.error(f"WebSocket connection error for client_id {client_id}: {str(e)}", exc_info=True)
        # Attempt to close gracefully if connection is still valid
        try:
            # Only try to close if not already disconnected
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass

@router.websocket("/ws/extract-resources/{client_id}")
async def websocket_endpoint_ner(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for NER processing with JWT authentication."""
    try:
        # CRITICAL: Accept WebSocket connection FIRST before any other operations
        # FastAPI/Starlette checks origin before calling this endpoint
        # added because i was getting 403 despite cors update
        origin = websocket.headers.get("origin")
        logger.info(f"WebSocket connection attempt from origin: {origin}, client_id: {client_id}")

        await websocket.accept()

        user = await authenticate_websocket(websocket, required_scopes=["write"])
        if not user:
            logger.warning(f"Authentication failed for client_id: {client_id}")
            await websocket.close(code=1008, reason="Authentication failed")
            return

        logger.info(f"WebSocket authenticated for user: {user.get('email')}, client_id: {client_id}")

        # Extract api_key from query parameters ?api_key=XXXXX if provided
        api_key = websocket.query_params.get("api_key") or None
        logger.info(f"WebSocket connection established for client_id: {client_id}, api_key provided: {api_key is not None}")

        # Use the correct path to the config file
        config_path = os.path.join(os.path.dirname(__file__), "resource_config_gpt.yaml")
        await _handle_websocket_connection(websocket, client_id, config_path, api_key)

    except Exception as e:
        logger.error(f"WebSocket connection error for client_id {client_id}: {str(e)}", exc_info=True)
        # Attempt to close gracefully if connection is still valid
        try:
            # Only try to close if not already disconnected
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass

@router.websocket("/ws/pdf2reproschema/{client_id}")
async def websocket_endpoint_ner(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for NER processing with JWT authentication."""
    try:
        # CRITICAL: Accept WebSocket connection FIRST before any other operations
        # FastAPI/Starlette checks origin before calling this endpoint
        # added because i was getting 403 despite cors update
        origin = websocket.headers.get("origin")
        logger.info(f"WebSocket connection attempt from origin: {origin}, client_id: {client_id}")

        await websocket.accept()

        user = await authenticate_websocket(websocket, required_scopes=["write"])
        if not user:
            logger.warning(f"Authentication failed for client_id: {client_id}")
            await websocket.close(code=1008, reason="Authentication failed")
            return

        logger.info(f"WebSocket authenticated for user: {user.get('email')}, client_id: {client_id}")

        # Extract api_key from query parameters ?api_key=XXXXX if provided
        api_key = websocket.query_params.get("api_key") or None
        logger.info(f"WebSocket connection established for client_id: {client_id}, api_key provided: {api_key is not None}")

        # Use the correct path to the config file
        config_path = os.path.join(os.path.dirname(__file__), "reproschema_config_gpt.yaml")
        await _handle_websocket_connection(websocket, client_id, config_path, api_key)

    except Exception as e:
        logger.error(f"WebSocket connection error for client_id {client_id}: {str(e)}", exc_info=True)
        # Attempt to close gracefully if connection is still valid
        try:
            # Only try to close if not already disconnected
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass

@router.get("/job/{task_id}", include_in_schema=True)
async def get_job_status(task_id: str):
    """REST endpoint to check job status by task_id."""
    job = _get_job(task_id)
    if not job:
        return JSONResponse({"error": f"Job {task_id} not found"}, status_code=404)

    response = {
        "task_id": job["task_id"],
        "client_id": job["client_id"],
        "filename": job["filename"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }

    if job["status"] == JobStatus.COMPLETED:
        response["result"] = job["result"]
    elif job["status"] == JobStatus.FAILED:
        response["error"] = job["error"]

    return JSONResponse(response)





@router.post("/save/ner",
             dependencies=[Depends(require_scopes(["write"]))],
             summary="Save the results of the multi-agent model",
             description="""
             Saves the JSON data.
             Response

             Returns the result of the StructSense pipeline processing.
             """,
             responses={
                 200: {
                     "description": "Successful response",
                     "content": {
                         "application/json": {
                             "example": {"result": "Data saved successfully"}
                         }
                     }
                 },
                 400: {
                     "description": "Bad Request",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Required configuration file is missing"}
                         }
                     }
                 },
                 422: {
                     "description": "Validation Error",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Error parsing configuration files: Invalid YAML format"}
                         }
                     }
                 },
                 500: {
                     "description": "Server Error",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Kickoff error: An unexpected error occurred"}
                         }
                     }
                 }
             })

async def save_ner_result(
    request: Request,
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    client: MongoClient = Depends(get_mongo_client)
):
    try:
        data = await request.json()
        env = load_environment()
        db_name = env.get("NER_DATABASE")
        collection_name = env.get("NER_COLLECTION")
        result = upsert_ner_annotations(
            input_data=data,
            client=client,
            db_name=db_name,
            collection_name=collection_name
        )
        return JSONResponse(content=result, status_code=200)

    except Exception as e:
        logger.error(f"Error in save_ner_result: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Error: {str(e)}")


@router.post("/save/structured-resource")
async def save_structured_resource(
        request: Request,
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        client: MongoClient = Depends(get_mongo_client)
):
    try:
        data = await request.json()

        print("*"*100)
        print(data)
        print("*"*100)

        # Extract data from frontend
        structured_data = data.get("data", [])
        endpoint = data.get("endpoint", "")

        # Get metadata from request or set defaults
        document_name = data.get("documentName", f"structured_resource_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        processed_at = data.get("processedAt", datetime.now(timezone.utc).isoformat())
        source_type = data.get("sourceType", "unknown")
        source_content = data.get("sourceContent", "")

        input_data = {
            "data": structured_data,
            "documentName": document_name,
            "processedAt": processed_at,
            "sourceType": source_type,
            "sourceContent": source_content,
            "endpoint": endpoint,
            "user_id": user.id if hasattr(user, 'id') else None,
            "user_email": user.email if hasattr(user, 'email') else None
        }
        print("*"*100)
        print(type(input_data))
        print("*"*100)
        
        env = load_environment()
        db_name = env.get("NER_DATABASE")
        result = upsert_structured_resources(
            input_data=input_data,
            client=client,
            db_name=db_name,
            collection_name="structured_resource"
        )
        return JSONResponse(content=result, status_code=200)

    except Exception as e:
        logger.error(f"Error saving structured resource: {str(e)}")
        return JSONResponse(
            content={"error": f"Failed to save structured resource: {str(e)}"},
            status_code=500
        )


async def _get_documents_from_collection(
    client: MongoClient,
    db_name: str,
    collection_name: str,
    document_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
) -> JSONResponse:
    """
    Shared helper function to retrieve documents from a MongoDB collection.
    
    Args:
        client: MongoDB client (reused from app state)
        db_name: Database name
        collection_name: Collection name
        document_name: Optional filter by document name
        start_date: Optional filter by processedAt start date (ISO format)
        end_date: Optional filter by processedAt end date (ISO format)
        limit: Maximum number of results (default: 100, max: 1000)
        skip: Number of results to skip for pagination (default: 0)
    
    Returns:
        JSONResponse with documents and pagination metadata
    """
    try:
        db = client[db_name]
        collection = db[collection_name]
        
        # Build query filter
        query_filter = {}
        
        if document_name:
            query_filter["documentName"] = document_name
        
        if start_date or end_date:
            query_filter["processedAt"] = {}
            if start_date:
                query_filter["processedAt"]["$gte"] = start_date
            if end_date:
                query_filter["processedAt"]["$lte"] = end_date
        
        # Limit max results
        limit = min(limit, 1000)
        
        # Query database
        cursor = collection.find(query_filter).sort("updated_at", -1).skip(skip).limit(limit)
        results = list(cursor)
        
        # Get total count for pagination
        total_count = collection.count_documents(query_filter)
        
        # Serialize all documents (convert ObjectId and datetime to JSON-serializable format)
        serialized_results = [serialize_mongo_document(result) for result in results]
        
        return JSONResponse(content={
            "data": serialized_results,
            "total": total_count,
            "limit": limit,
            "skip": skip,
            "has_more": (skip + limit) < total_count
        }, status_code=200)
        
    except Exception as e:
        logger.error(f"Error retrieving documents from {collection_name}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve documents from {collection_name}: {str(e)}"
        )


@router.get("/ner",
            # dependencies=[Depends(require_scopes(["read"]))],
            summary="Get saved NER annotations",
            description="""
            Retrieves saved NER annotations from MongoDB.
            Supports filtering by documentName, date range, and pagination.
            """)
async def get_ner_annotations(
    request: Request,
    # user: Annotated[LoginUserIn, Depends(get_current_user)],
    client: MongoClient = Depends(get_mongo_client),
    document_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
):
    """
    Get saved NER annotations with optional filtering and pagination.
    
    Query Parameters:
    - document_name: Filter by document name
    - start_date: Filter by processedAt start date (ISO format)
    - end_date: Filter by processedAt end date (ISO format)
    - limit: Maximum number of results (default: 100, max: 1000)
    - skip: Number of results to skip for pagination (default: 0)
    """
    try:
        env = load_environment()
        db_name = env.get("NER_DATABASE")
        collection_name = env.get("NER_COLLECTION")
        
        if not db_name or not collection_name:
            raise HTTPException(
                status_code=500,
                detail="MongoDB configuration not found"
            )
        
        return await _get_documents_from_collection(
            client=client,
            db_name=db_name,
            collection_name=collection_name,
            document_name=document_name,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving NER annotations: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve NER annotations: {str(e)}")


@router.get("/structured-resource",
            # dependencies=[Depends(require_scopes(["read"]))],
            summary="Get saved structured resources",
            description="""
            Retrieves saved structured resources from MongoDB.
            Supports filtering by documentName, date range, and pagination.
            """)
async def get_structured_resources(
    request: Request,
    # user: Annotated[LoginUserIn, Depends(get_current_user)], 
    client: MongoClient = Depends(get_mongo_client),
    document_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
):
    """
    Get saved structured resources with optional filtering and pagination.
    
    Query Parameters:
    - document_name: Filter by document name
    - start_date: Filter by processedAt start date (ISO format)
    - end_date: Filter by processedAt end date (ISO format)
    - limit: Maximum number of results (default: 100, max: 1000)
    - skip: Number of results to skip for pagination (default: 0)
    """
    try:
        env = load_environment()
        db_name = env.get("NER_DATABASE")
        collection_name = "structured_resource"
        
        if not db_name:
            raise HTTPException(
                status_code=500,
                detail="MongoDB configuration not found"
            )
        
        return await _get_documents_from_collection(
            client=client,
            db_name=db_name,
            collection_name=collection_name,
            document_name=document_name,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving structured resources: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve structured resources: {str(e)}")
