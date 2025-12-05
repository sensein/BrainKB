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


from fastapi import APIRouter, Request, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Query, Body
from fastapi.responses import JSONResponse
from core.graph_database_connection_manager import insert_data_gdb, insert_data_gdb_async
import logging
from core.pydantic_schema import InputKGTripleSchema, NamedGraphSchema
from typing import Annotated, List, Dict, Any, Optional
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from fastapi import Depends
from core.shared import (
    convert_ttl_to_named_graph, named_graph_metadata, convert_json_to_ttl, 
    convert_to_turtle, chunk_ttl_to_named_graphs,
    human_size, human_rate, get_ext, get_content_type_for_ext,
    convert_jsonld_to_ntriples_flat, detect_raw_format,
    compute_summary, contains_ip, attach_provenance,
    get_oxigraph_endpoint, get_oxigraph_auth
)
from core.graph_database_connection_manager import fetch_data_gdb_async, check_named_graph_exists
from core.database import (
    create_job,
    update_job_status,
    get_job_details,
    insert_job_result,
    update_job_progress,
    get_job_results,
    get_job_by_id_and_user,
    list_user_jobs,
    batch_update_job_completion,
    batch_insert_job_results,
)
from core.configuration import load_environment
import datetime
import uuid
import asyncio
import tempfile
import os
import time
import httpx
from pathlib import Path
from rdflib import Graph
router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration constants
MAX_FILE_SIZE_BYTES = int(1.5 * 1024 * 1024 * 1024)  # 1.5 GB
MAX_RAW_SIZE_BYTES = MAX_FILE_SIZE_BYTES
JOB_BASE_DIR = "/tmp/oxigraph_jobs"  # Default directory for temporary job files

# Get default graph from configuration
# load_environment() is now robust and handles Docker environments gracefully
DEFAULT_GRAPH = load_environment().get("DEFAULT_NAMED_GRAPH", "named_graph")

# Supported file extensions
SUPPORTED_EXTS = {"ttl", "turtle", "nt", "nq", "trig", "rdf", "owl", "jsonld", "json"}

# Ensure job directory exists
os.makedirs(JOB_BASE_DIR, exist_ok=True)



async def upload_single_file_path(
    client: httpx.AsyncClient,
    filepath: str,
    original_size: int,
    graph: str,
) -> Dict[str, Any]:
    """
    Upload a single local file to Oxigraph via Graph Store HTTP.
    Uses graph provided by caller.
    Files with provenance are saved as Turtle format, so we read them as text.
    """
    filename = os.path.basename(filepath)
    ext = get_ext(filename)
    
    # Get Oxigraph endpoint and auth from configuration
    endpoint = get_oxigraph_endpoint()
    url = f"{endpoint}?graph={graph}"
    auth = get_oxigraph_auth()
    
    # Files with provenance are saved as Turtle format (text)
    # All text-based RDF formats (ttl, nt, jsonld, rdf/xml, owl) get provenance attached
    if ext in ["ttl", "turtle", "nt", "nq", "jsonld", "json", "rdf", "owl"]:
        # Read as text (files with provenance are saved as Turtle text)
        # All text-based files with provenance are in Turtle format, regardless of original extension
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                file_data = f.read()
            # Send as Turtle (all text files with provenance are saved as Turtle)
            payload = file_data.encode("utf-8")
            content_type = "text/turtle"
        except Exception as e:
            return {
                "file": filename,
                "ext": ext,
                "size_bytes": original_size,
                "elapsed_s": 0.0,
                "http_status": 0,
                "success": False,
                "bps": 0.0,
                "response_body": f"Error reading text file: {e}",
            }
    else:
        # Other formats (trig, etc.) - read as binary
        content_type = get_content_type_for_ext(ext)
        with open(filepath, "rb") as f:
            payload = f.read()
    
    start = time.time()
    resp = await client.post(
        url,
        content=payload,
        headers={"Content-Type": content_type},
        auth=auth,
    )
    end = time.time()
    elapsed = max(end - start, 1e-6)
    success = resp.status_code in (200, 201, 204)
    bps = original_size / elapsed
    
    try:
        resp_text = resp.text
    except Exception:
        resp_text = ""
    
    max_len = 2000
    if resp_text and len(resp_text) > max_len:
        resp_text = resp_text[:max_len] + "... [truncated]"
    
    return {
        "file": filename,
        "ext": ext,
        "size_bytes": original_size,
        "elapsed_s": elapsed,
        "http_status": resp.status_code,
        "success": success,
        "bps": bps,
        "response_body": resp_text,
    }


async def run_ingest_job(
    job_id: str,
    max_concurrency: int,
):
    """Background job runner for file ingestion."""
    try:
        # Mark job as running and get job_dir + graph
        await update_job_status(job_id, "running", start_time=time.time())
        job_details = await get_job_details(job_id)
        if not job_details:
            return
        job_dir = job_details["job_dir"]
        graph = job_details["graph"]
        
        # Collect files in job_dir
        file_infos: List[Dict[str, Any]] = []
        for name in os.listdir(job_dir):
            path = os.path.join(job_dir, name)
            if not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
            file_infos.append({"path": path, "size_bytes": size})
        
        async with httpx.AsyncClient(
            timeout=None,
            limits=httpx.Limits(
                max_connections=max_concurrency * 2,
                max_keepalive_connections=max_concurrency * 2,
            ),
        ) as client:
            sem = asyncio.Semaphore(max_concurrency)
            
            async def worker(fi: Dict[str, Any]):
                filepath = fi["path"]
                size = fi["size_bytes"]
                async with sem:
                    res = await upload_single_file_path(
                        client,
                        filepath,
                        size,
                        graph,
                    )
                    # Insert job result and update progress
                    await insert_job_result(
                        job_id=job_id,
                        file_name=res["file"],
                        ext=res["ext"],
                        size_bytes=res["size_bytes"],
                        elapsed_s=res["elapsed_s"],
                        http_status=res["http_status"],
                        success=bool(res["success"]),
                        bps=res["bps"],
                        response_body=res["response_body"],
                    )
                    await update_job_progress(
                        job_id=job_id,
                        success_increment=1 if res["success"] else 0,
                        fail_increment=0 if res["success"] else 1,
                    )
                return res
            
            tasks = [worker(fi) for fi in file_infos]
            if tasks:
                await asyncio.gather(*tasks)

        await update_job_status(job_id, "done", end_time=time.time())
    except Exception as e:
        # Mark job as errored
        await update_job_status(job_id, "error", end_time=time.time())
        logger.error(f"[run_ingest_job] Job {job_id} failed: {e}", exc_info=True)


@router.post("/insert/raw/knowledge-graph-triples",
             include_in_schema=True,
dependencies=[Depends(require_scopes(["write"]))],
             )
async def insert_knowledge_graph_triples(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier (who is sending the raw data)")],
    data: Annotated[str, Body(..., media_type="text/plain")],
    named_graph_iri: Annotated[str, Query(description="Named graph IRI to ingest into")] = DEFAULT_GRAPH,
):
    """
    Ingest raw KG data (triples) directly in the request body.
    - `user_id` identifies who sent it (for tracking/logging).
    - `named_graph_iri` is the graph to ingest into (defaults to 'named_graph').
    - `data` is plain text (text/plain).
      - starts with '{' or '[' -> JSON-LD
      - contains '@prefix' or '@base' -> Turtle
      - otherwise -> N-Triples (raw triples)
    - Creates a job record + job_results
    - Validates that the named graph is registered before ingestion.
    - Attaches provenance information to the ingested data.
    """
    # First, check if the named graph is registered
    if not await check_named_graph_exists(named_graph_iri):
        return JSONResponse(
            {
                "error": f"Named graph '{named_graph_iri}' is not registered. Please register it first using /api/register-named-graph",
                "named_graph_iri": named_graph_iri,
            },
            status_code=400,
        )
    
    job_id = uuid.uuid4().hex
    
    # Get Oxigraph endpoint from configuration
    endpoint = get_oxigraph_endpoint()
    
    raw_bytes = data.encode("utf-8")
    if len(raw_bytes) > MAX_RAW_SIZE_BYTES:
        return JSONResponse(
            {
                "error": f"Raw payload exceeds max allowed size of {human_size(MAX_RAW_SIZE_BYTES)}",
                "max_bytes": MAX_RAW_SIZE_BYTES,
            },
            status_code=413,
        )
    
    detected = detect_raw_format(data)
    
    # Attach provenance to the data before ingestion
    # Convert to Turtle format if needed (provenance attachment requires Turtle)
    # Run RDF parsing in thread pool to avoid blocking event loop
    try:
        def parse_and_attach_provenance():
            """Synchronous function to parse RDF and attach provenance."""
            if detected == "jsonld":
                # Convert JSON-LD to Turtle first
                temp_graph = Graph()
                temp_graph.parse(data=data, format="json-ld")
                ttl_data = temp_graph.serialize(format="turtle")
            elif detected == "nt":
                # Convert N-Triples to Turtle for provenance
                temp_graph = Graph()
                temp_graph.parse(data=data, format="nt")
                ttl_data = temp_graph.serialize(format="turtle")
            else:  # "ttl" - already in Turtle format
                ttl_data = data
            
            # Attach provenance (who ingested the data)
            return attach_provenance(user_id, ttl_data)
        
        # Run CPU-intensive RDF parsing in thread pool
        loop = asyncio.get_event_loop()
        data_with_provenance = await loop.run_in_executor(None, parse_and_attach_provenance)
        # Use Turtle format with provenance (Oxigraph accepts Turtle)
        data = data_with_provenance
        detected = "ttl"  # Update format after provenance attachment
    except Exception as e:
        logger.warning(f"Failed to attach provenance: {e}. Continuing without provenance.", exc_info=True)
        # Continue with original data if provenance attachment fails
    
    # Create job in "running" state
    start_wall = time.time()
    await create_job(
        job_id=job_id,
        user_id=user_id,
        status="running",
        total_files=1,
        processed_files=0,
        success_count=0,
        fail_count=0,
        endpoint=endpoint,
        graph=named_graph_iri,
        job_dir=f"RAW:{user_id}",
        start_time=start_wall,
        end_time=None,
    )

    # Prepare payload with provenance (data is now in Turtle format)
    try:
        # After provenance attachment, data is always in Turtle format
        payload = data.encode("utf-8")
        content_type = "text/turtle"
    except Exception as e:
        result = {
            "file": "raw_payload",
            "ext": detected,
            "size_bytes": 0,
            "elapsed_s": 0.0,
            "http_status": 0,
            "success": False,
            "bps": 0.0,
            "response_body": f"Failed to prepare payload (detected={detected}): {e}",
        }
        summary = compute_summary([result])
        await insert_job_result(
            job_id=job_id,
            file_name=result["file"],
            ext=result["ext"],
            size_bytes=result["size_bytes"],
            elapsed_s=result["elapsed_s"],
            http_status=result["http_status"],
            success=bool(result["success"]),
            bps=result["bps"],
            response_body=result["response_body"],
        )
        await update_job_status(job_id, "error", end_time=time.time())
        await update_job_progress(job_id, success_increment=0, fail_increment=1)
        return JSONResponse(
            {
                "job_id": job_id,
                "user_id": user_id,
                "named_graph_iri": named_graph_iri,
                "status": "error",
                "summary": summary,
            },
            status_code=400,
        )
    
    url = f"{endpoint}?graph={named_graph_iri}"
    
    # Get auth from configuration
    auth = get_oxigraph_auth()
    
    async with httpx.AsyncClient(timeout=None) as client:
        start_time = time.time()
        resp = await client.post(
            url,
            content=payload,
            headers={"Content-Type": content_type},
            auth=auth,
        )
        end_time = time.time()
    
    elapsed = max(end_time - start_time, 1e-6)
    size_bytes = len(payload)
    bps = size_bytes / elapsed
    rate_human = human_rate(bps)
    size_human = human_size(size_bytes)
    
    try:
        resp_text = resp.text
    except Exception:
        resp_text = ""
    
    max_len = 2000
    if resp_text and len(resp_text) > max_len:
        resp_text = resp_text[:max_len] + "... [truncated]"
    
    success = resp.status_code in (200, 201, 204)
    result = {
        "file": "raw_payload",
        "ext": detected,
        "size_bytes": size_bytes,
        "elapsed_s": elapsed,
        "http_status": resp.status_code,
        "success": success,
        "bps": bps,
        "response_body": resp_text,
    }
    
    summary = compute_summary([result])
    
    # Batch all database operations into a single transaction (much faster!)
    await batch_update_job_completion(
        job_id=job_id,
        file_name=result["file"],
        ext=result["ext"],
        size_bytes=result["size_bytes"],
        elapsed_s=result["elapsed_s"],
        http_status=result["http_status"],
        success=bool(result["success"]),
        bps=result["bps"],
        response_body=result["response_body"],
        status="done" if success else "error",
        end_time=end_time,
    )
    
    return {
        "job_id": job_id,
        "user_id": user_id,
        "status": "done" if success else "error",
        "endpoint": endpoint,
        "named_graph_iri": named_graph_iri,
        "detected_format": detected,
        "size_bytes": size_bytes,
        "size_human": size_human,
        "elapsed_s": round(elapsed, 6),
        "bps": bps,
        "rate_human": rate_human,
        "http_status": resp.status_code,
        "success": success,
        "response_body": resp_text,
        "summary": summary,
    }

@router.post("/insert/files/knowledge-graph-triples",
             include_in_schema=True,
dependencies=[Depends(require_scopes(["write"]))],
             )
async def insert_file_knowledge_graph_triples(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier for job isolation")],
    files: Annotated[list[UploadFile], File(...)],
    background_tasks: BackgroundTasks,
    named_graph_iri: Annotated[str, Query(description="Named graph IRI to ingest into")] = DEFAULT_GRAPH,
    max_concurrency: Annotated[int, Query(ge=1, le=64, description="Maximum concurrent uploads")] = 4,
):
    """
    Upload RDF files (ttl, nt, jsonld, etc.), create a user-scoped job, and start background ingestion.
    Graph defaults to 'named_graph' but can be overridden via named_graph_iri.
    Oxigraph endpoint and auth always come from environment variables.
    Validates that the named graph is registered before ingestion.
    Attaches provenance information to ingested files.
    """
    # First, check if the named graph is registered
    if not await check_named_graph_exists(named_graph_iri):
        return JSONResponse(
            {
                "error": f"Named graph '{named_graph_iri}' is not registered. Please register it first using /api/register-named-graph",
                "named_graph_iri": named_graph_iri,
            },
            status_code=400,
        )
    
    job_id = uuid.uuid4().hex  # generate for job tracking
    
    # Get Oxigraph endpoint from configuration
    endpoint = get_oxigraph_endpoint()
    
    job_dir = os.path.join(JOB_BASE_DIR, user_id, f"job_{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    
    pre_results: List[Dict[str, Any]] = []
    total_files = 0
    
    # Save uploads to disk with chunked writing + size limit
    for uf in files:
        filename = uf.filename or "unnamed"
        ext = get_ext(filename)
        total_files += 1
        
        if ext not in SUPPORTED_EXTS:
            pre_results.append(
                {
                    "file": filename,
                    "ext": ext,
                    "size_bytes": 0,
                    "elapsed_s": 0.0,
                    "http_status": 415,
                    "success": False,
                    "bps": 0.0,
                    "response_body": f"Unsupported extension: .{ext}",
                }
            )
            continue
        
        path = os.path.join(job_dir, filename)
        size = 0
        too_large = False
        
        # For text-based formats, read into memory and attach provenance before saving
        # For binary formats, save directly to disk
        if ext in ["ttl", "turtle", "nt", "nq", "jsonld", "json", "rdf", "owl"]:
            # Read uploaded file into memory (text-based)
            file_data_chunks = []
            try:
                while True:
                    chunk = await uf.read(2 * 1024 * 1024)  # 2 MB
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_SIZE_BYTES:
                        too_large = True
                        break
                    file_data_chunks.append(chunk)
                
                if too_large:
                    pre_results.append(
                        {
                            "file": filename,
                            "ext": ext,
                            "size_bytes": size,
                            "elapsed_s": 0.0,
                            "http_status": 413,
                            "success": False,
                            "bps": 0.0,
                            "response_body": (
                                f"File exceeds max allowed size {MAX_FILE_SIZE_BYTES} bytes (~1.5 GB)"
                            ),
                        }
                    )
                    continue
                
                # Decode chunks to text
                try:
                    file_data = b"".join(file_data_chunks).decode("utf-8")
                except UnicodeDecodeError:
                    # Try with errors='ignore' if UTF-8 fails
                    file_data = b"".join(file_data_chunks).decode("utf-8", errors="ignore")
                
                # Determine format
                if ext in ["ttl", "turtle"]:
                    format_type = "ttl"
                elif ext in ["nt", "nq"]:
                    format_type = "nt"
                elif ext in ["jsonld", "json"]:
                    format_type = "jsonld"
                elif ext == "rdf":
                    format_type = "rdf"
                elif ext == "owl":
                    format_type = "owl"
                else:
                    format_type = "ttl"  # Default to turtle
                
                # Process RDF and attach provenance in thread pool to avoid blocking
                def process_file_with_provenance():
                    """Synchronous function to parse RDF and attach provenance."""
                    # Convert to Turtle if needed for provenance
                    if format_type == "jsonld":
                        temp_graph = Graph()
                        temp_graph.parse(data=file_data, format="json-ld")
                        ttl_data = temp_graph.serialize(format="turtle")
                    elif format_type == "nt":
                        temp_graph = Graph()
                        temp_graph.parse(data=file_data, format="nt")
                        ttl_data = temp_graph.serialize(format="turtle")
                    elif format_type == "rdf":
                        # RDF/XML format
                        temp_graph = Graph()
                        temp_graph.parse(data=file_data, format="xml")
                        ttl_data = temp_graph.serialize(format="turtle")
                    elif format_type == "owl":
                        # OWL format (also XML-based)
                        temp_graph = Graph()
                        temp_graph.parse(data=file_data, format="xml")
                        ttl_data = temp_graph.serialize(format="turtle")
                    else:  # "ttl"
                        ttl_data = file_data
                    
                    # Attach provenance (returns Turtle format)
                    return attach_provenance(user_id, ttl_data)
                
                # Run CPU-intensive RDF parsing in thread pool
                loop = asyncio.get_event_loop()
                ttl_data_with_provenance = await loop.run_in_executor(None, process_file_with_provenance)
                
                # Save once with provenance (Turtle format)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(ttl_data_with_provenance)
                
            except Exception as e:
                logger.warning(f"Failed to attach provenance to {filename}: {e}. Saving without provenance.", exc_info=True)
                # If provenance fails, save original data
                with open(path, "wb") as out:
                    for chunk in file_data_chunks:
                        out.write(chunk)
        else:
            # Binary formats - save directly to disk (no provenance)
            with open(path, "wb") as out:
                while True:
                    chunk = await uf.read(2 * 1024 * 1024)  # 2 MB
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_SIZE_BYTES:
                        too_large = True
                        break
                    out.write(chunk)
            
            if too_large:
                try:
                    os.remove(path)
                except OSError:
                    pass
                pre_results.append(
                    {
                        "file": filename,
                        "ext": ext,
                        "size_bytes": size,
                        "elapsed_s": 0.0,
                        "http_status": 413,
                        "success": False,
                        "bps": 0.0,
                        "response_body": (
                            f"File exceeds max allowed size {MAX_FILE_SIZE_BYTES} bytes (~1.5 GB)"
                        ),
                    }
                )
                continue
        
        # Files that pass all checks will be ingested later by run_ingest_job
    
    if total_files == 0:
        return JSONResponse(
            {"error": "No files were uploaded."},
            status_code=400,
        )
    
    # Insert job row + pre-results into DB
    processed_files = len(pre_results)
    success_count = sum(1 for r in pre_results if r["success"])
    fail_count = len(pre_results) - success_count
    
    await create_job(
        job_id=job_id,
        user_id=user_id,
        status="pending",
        total_files=total_files,
        processed_files=processed_files,
        success_count=success_count,
        fail_count=fail_count,
        endpoint=endpoint,
        graph=named_graph_iri,
        job_dir=job_dir,
        start_time=None,
        end_time=None,
    )
    
    # Batch insert pre-results (much faster than individual inserts)
    if pre_results:
        await batch_insert_job_results(job_id, pre_results)
    
    # Start background ingest job
    background_tasks.add_task(
        run_ingest_job,
        job_id,
        max_concurrency,
    )
    
    return {
        "job_id": job_id,
        "user_id": user_id,
        "named_graph_iri": named_graph_iri,
        "total_files": total_files,
        "pre_failed_files": len(pre_results),
        "status_url": f"/api/insert/jobs?job_id={job_id}&user_id={user_id}",
        "message": "Job created and ingestion started in background.",
    }

@router.get("/insert/jobs",
            include_in_schema=True
            )
async def get_job_status(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier")],
    job_id: Annotated[Optional[str], Query(description="If provided, return a single job; otherwise list all jobs for this user")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Page size when listing jobs")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination when listing jobs")] = 0,
    started_after: Annotated[Optional[float], Query(description="(list mode) jobs with start_time >= this UNIX epoch seconds")] = None,
    started_before: Annotated[Optional[float], Query(description="(list mode) jobs with start_time <= this UNIX epoch seconds")] = None,
):
    """
    GET /insert/jobs
    Two modes:
    1) Single job mode (job_id provided):
       - Returns that job for this user, including summary (when done/error)
    2) List mode (job_id omitted):
       - Returns a paginated list of jobs for this user
       - Supports optional started_after / started_before filters
    """
    
    if job_id:
        job = await get_job_by_id_and_user(job_id, user_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        
        total = job["total_files"]
        processed = job["processed_files"]
        progress = (100.0 * processed / total) if total else 0.0
        
        resp: Dict[str, Any] = {
            "job_id": job_id,
            "user_id": user_id,
            "status": job["status"],
            "total_files": total,
            "processed_files": processed,
            "progress_percent": round(progress, 2),
            "success_count": job["success_count"],
            "fail_count": job["fail_count"],
            "endpoint": job["endpoint"],
            "named_graph_iri": job["graph"],
        }
        
        # Only pull full summary when job is finished/errored
        if job["status"] in ("done", "error"):
            results = await get_job_results(job_id)
            resp["summary"] = compute_summary(results)
        
        return resp
    
    # Mode 2: List all jobs for user
    return await list_user_jobs(
        user_id=user_id,
        limit=limit,
        offset=offset,
        started_after=started_after,
        started_before=started_before,
    )


@router.get("/insert/user/jobs",
            include_in_schema=True
            )
async def list_user_jobs_endpoint(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier")],
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum number of jobs to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of jobs to skip")] = 0,
    started_after: Annotated[Optional[float], Query(description="Filter: jobs with start_time >= this UNIX epoch seconds")] = None,
    started_before: Annotated[Optional[float], Query(description="Filter: jobs with start_time <= this UNIX epoch seconds")] = None,

):
    """
    List all jobs for a user, with pagination and optional time range filters.
    Returns saved statistics for all jobs.
    """
    return await list_user_jobs(
        user_id=user_id,
        limit=limit,
        offset=offset,
        started_after=started_after,
        started_before=started_before,
    )


@router.post("/register-named-graph")
async def create_named_graph(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        request: NamedGraphSchema
):
    try:
        # Access Pydantic model fields directly (request is a NamedGraphSchema, not a Request object)
        # Convert HttpUrl to string
        named_graph_url = str(request.named_graph_url)
        description = request.description

        # Ensure named_graph_url ends with '/'
        if not named_graph_url.endswith('/'):
            named_graph_url += '/'

        metadata_graph_uri = "https://brainkb.org/metadata/named-graph"
        
        # Note: Metadata graph is initialized on service startup, so it should exist
        # Check if the specific named graph is already registered
        query = f"""
        ASK WHERE {{
          GRAPH <{metadata_graph_uri}> {{
            ?s ?p ?o.
            FILTER(?s = <{named_graph_url}>)
          }}
        }}
        """
        named_graph_exists = await fetch_data_gdb_async(query)
        if not named_graph_exists.get("message", {}).get("boolean", False):
            # Register the new named graph
            response = await insert_data_gdb_async(named_graph_metadata(
                named_graph_url=named_graph_url,
                description=description,
                )
            )
            return response
        else:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "status": "fail",
                    "message": "Graph is already registered."
                }
            )
    except Exception as e:
        logger.error("An error occurred", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred processing the request {e}",
        )

