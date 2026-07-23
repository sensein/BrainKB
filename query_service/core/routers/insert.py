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
from fastapi.responses import JSONResponse, Response
from core.graph_database_connection_manager import insert_data_gdb, insert_data_gdb_async
import logging
from core.pydantic_schema import InputKGTripleSchema, NamedGraphSchema
from typing import Annotated, List, Dict, Any, Optional, Tuple
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes, verify_user_access
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
from core.spaces import authorize as authorize_space_access
from core import spaces as _spaces
from core import rbac
from core.provenance import (
    build_ingestion_provenance,
    build_recovery_provenance,
    agent_ref,
    write_provenance,
    query_provenance_jsonld,
    construct_for_job,
    construct_for_named_graph,
    delta_graph_for,
    merge_delta_into_target,
    count_graph_triples,
    construct_delta_content,
    delta_history_for_graph,
    compare_deltas,
)
import datetime
import uuid
import asyncio
import tempfile
import os
import shutil
import time
import httpx
from pathlib import Path
from rdflib import Graph
router = APIRouter()
logger = logging.getLogger(__name__)


def _agent_email(user):
    """Caller's identity string (email), used for space membership checks."""
    try:
        return user["email"]
    except (KeyError, TypeError, IndexError):
        return None

# Global dictionary to track running background tasks
# Maps job_id -> asyncio.Task for checking if job is actually running
_running_job_tasks: Dict[str, asyncio.Task] = {}

# Configuration constants
MAX_FILE_SIZE_BYTES = int(1.5 * 1024 * 1024 * 1024)  # 1.5 GB
MAX_RAW_SIZE_BYTES = MAX_FILE_SIZE_BYTES
JOB_BASE_DIR = "/tmp/oxigraph_jobs"  # Default directory for temporary job files

# Get default graph from configuration
# load_environment() is now robust and handles Docker environments gracefully
DEFAULT_GRAPH = load_environment().get("DEFAULT_NAMED_GRAPH", "named_graph")

# Supported file extensions
SUPPORTED_EXTS = {"ttl", "turtle", "nt", "nq", "trig", "rdf", "owl", "jsonld", "json"}

# Triple-level change tracking. When enabled, each job stages its triples in a
# per-job delta graph (an exact, queryable record of what the job added) which is
# then merged into the target graph. Costs extra storage (delta graphs persist);
# set TRACK_TRIPLE_DELTAS=false to upload directly to the target instead.
TRACK_TRIPLE_DELTAS = os.getenv("TRACK_TRIPLE_DELTAS", "true").strip().lower() in ("1", "true", "yes", "on")

# Resource-safety cap: maximum ingest jobs PROCESSING concurrently per worker
# process. Ingestion stays fire-and-forget (submit and forget) — this just bounds
# how many jobs run at once so a burst of submissions can't exhaust memory, the DB
# pool, or Oxigraph. Excess jobs return immediately and wait as 'pending' until a
# slot frees (backpressure without a queue). Effective global cap ≈ this × workers.
MAX_CONCURRENT_INGEST_JOBS = int(os.getenv("MAX_CONCURRENT_INGEST_JOBS", "3"))
_ingest_semaphore: Optional[asyncio.Semaphore] = None


def _get_ingest_semaphore() -> asyncio.Semaphore:
    """Lazily create the per-worker ingest concurrency limiter (binds to the loop)."""
    global _ingest_semaphore
    if _ingest_semaphore is None:
        _ingest_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INGEST_JOBS)
    return _ingest_semaphore

# Ensure job directory exists
os.makedirs(JOB_BASE_DIR, exist_ok=True)



async def process_file_with_provenance(
    filepath: str,
    user_id: str,
    ext: str,
    skip_provenance: bool = False,
) -> Tuple[str, bool]:
    """
    Process a file by attaching provenance if it's a text-based RDF format.
    Returns (processed_filepath, success).
    For text-based formats, creates a new file with provenance attached.
    For binary formats, returns original filepath unchanged.
    
    Always uses full provenance attachment (complete graph parsing and entity linking)
    unless skip_provenance=True is explicitly set.
    """
    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)
    
    # Only process text-based RDF formats
    if ext not in ["ttl", "turtle", "nt", "nq", "jsonld", "json", "rdf", "owl"]:
        # Binary formats - no provenance, use original file
        return filepath, True
    
    # Skip provenance if requested (for faster ingestion)
    if skip_provenance:
        return filepath, True
    
    # Always use full provenance attachment unless explicitly skipped
    # Full provenance includes complete graph parsing and entity linking
    try:
        # Read file in chunks to handle large files
        file_data_chunks = []
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(10 * 1024 * 1024)  # 10 MB chunks
                if not chunk:
                    break
                file_data_chunks.append(chunk)
        
        # Decode to text
        try:
            file_data = b"".join(file_data_chunks).decode("utf-8")
        except UnicodeDecodeError:
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
            format_type = "ttl"
        
        # Process in thread pool to avoid blocking
        def parse_and_attach_provenance_sync():
            """Synchronous function to parse RDF and attach provenance."""
            temp_graph = Graph()
            if format_type == "jsonld":
                temp_graph.parse(data=file_data, format="json-ld")
            elif format_type == "nt":
                temp_graph.parse(data=file_data, format="nt")
            elif format_type in ["rdf", "owl"]:
                temp_graph.parse(data=file_data, format="xml")
            else:  # "ttl"
                temp_graph.parse(data=file_data, format="turtle")
            
            ttl_data = temp_graph.serialize(format="turtle")
            return attach_provenance(user_id, ttl_data)
        
        loop = asyncio.get_event_loop()
        ttl_data_with_provenance = await loop.run_in_executor(None, parse_and_attach_provenance_sync)
        
        # Save processed file (with provenance) to a new file
        processed_filepath = filepath + ".processed.ttl"
        with open(processed_filepath, "w", encoding="utf-8") as f:
            f.write(ttl_data_with_provenance)
        
        return processed_filepath, True
        
    except Exception as e:
        logger.warning(f"Failed to attach provenance to {filename}: {e}. Using original file.", exc_info=True)
        # Return original filepath if processing fails
        return filepath, False


async def _process_large_file_with_lightweight_provenance(
    filepath: str,
    user_id: str,
    ext: str,
) -> Tuple[str, bool]:
    """
    OPTIMIZATION: For large files, append lightweight provenance without full graph parsing.
    This avoids loading entire 40MB+ files into memory for parsing.
    """
    from rdflib import Graph, URIRef, Literal, RDF, XSD, DCTERMS, PROV
    from rdflib import Namespace
    import datetime
    import uuid
    
    filename = os.path.basename(filepath)
    processed_filepath = filepath + ".processed.ttl"
    
    try:
        # Generate lightweight provenance (minimal RDF, no full graph parsing)
        start_time = datetime.datetime.utcnow().isoformat() + "Z"
        provenance_uuid = str(uuid.uuid4())
        BASE = Namespace("https://identifiers.org/brain-bican/vocab/")
        
        prov_entity = URIRef(BASE[f"provenance/{provenance_uuid}"])
        ingestion_activity = URIRef(BASE[f"ingestionActivity/{provenance_uuid}"])
        user_uri = URIRef(BASE[f"agent/{user_id}"])
        
        # Create minimal provenance graph
        prov_graph = Graph()
        prov_graph.add((prov_entity, RDF.type, PROV.Entity))
        prov_graph.add((prov_entity, PROV.generatedAtTime, Literal(start_time, datatype=XSD.dateTime)))
        prov_graph.add((prov_entity, PROV.wasAttributedTo, user_uri))
        prov_graph.add((prov_entity, PROV.wasGeneratedBy, ingestion_activity))
        prov_graph.add((ingestion_activity, RDF.type, PROV.Activity))
        prov_graph.add((ingestion_activity, RDF.type, BASE["IngestionActivity"]))
        prov_graph.add((ingestion_activity, PROV.generatedAtTime, Literal(start_time, datatype=XSD.dateTime)))
        prov_graph.add((ingestion_activity, PROV.wasAssociatedWith, user_uri))
        prov_graph.add((prov_entity, DCTERMS.provenance, Literal(f"Data ingested by {user_id} on {start_time}")))
        
        # Serialize provenance to Turtle
        provenance_ttl = prov_graph.serialize(format="turtle")
        
        # Stream original file and append provenance (memory efficient)
        with open(processed_filepath, "w", encoding="utf-8") as out:
            # Copy original file content
            with open(filepath, "r", encoding="utf-8", errors="ignore") as inf:
                # For very large files, copy in chunks
                while True:
                    chunk = inf.read(10 * 1024 * 1024)  # 10 MB chunks
                    if not chunk:
                        break
                    out.write(chunk)
            
            # Append provenance at the end
            out.write("\n\n# Provenance metadata\n")
            out.write(provenance_ttl)
        
        return processed_filepath, True
        
    except Exception as e:
        logger.warning(f"Failed lightweight provenance for {filename}: {e}. Using original file.", exc_info=True)
        return filepath, False


async def upload_single_file_path(
    client: httpx.AsyncClient,
    filepath: str,
    original_size: int,
    graph: str,
    user_id: str,
    skip_provenance: bool = False,
    job_id: Optional[str] = None,
    file_index: Optional[int] = None,
    total_files: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Upload a single local file to Oxigraph via Graph Store HTTP.
    Processes file (attaches provenance) before uploading if needed.
    Uses graph provided by caller.
    
    OPTIMIZATION: Uses streaming upload for large files to avoid loading entire file into memory.
    """
    filename = os.path.basename(filepath)
    ext = get_ext(filename)
    
    # Update processing state: Starting file processing
    if job_id:
        from core.database import update_job_processing_state, insert_processing_log
        file_info = f"({file_index + 1}/{total_files})" if file_index is not None and total_files else ""
        status_msg = f"Processing file {file_info}: {filename}"
        await update_job_processing_state(
            job_id=job_id,
            current_file=filename,
            current_stage="processing",
            status_message=status_msg
        )
        # Log to history
        await insert_processing_log(
            job_id=job_id,
            file_name=filename,
            stage="processing",
            status_message=status_msg,
            file_index=file_index,
            total_files=total_files,
        )
    
    # Provenance is tracked natively as PROV-O in Oxigraph's dedicated provenance
    # graph (see core/provenance.py and PROVENANCE_MODEL.md), NOT embedded into the
    # domain data. The uploaded file is therefore sent to Oxigraph unmodified.
    # `skip_provenance` is retained on the API for backward compatibility but no
    # longer controls domain-data embedding (which has been removed).
    processed_filepath = filepath

    # Update processing state: Uploading file
    if job_id:
        from core.database import insert_processing_log
        status_msg = f"Uploading {filename} to Oxigraph"
        await update_job_processing_state(
            job_id=job_id,
            current_stage="uploading",
            status_message=status_msg
        )
        # Log to history
        await insert_processing_log(
            job_id=job_id,
            file_name=filename,
            stage="uploading",
            status_message=status_msg,
            file_index=file_index,
            total_files=total_files,
        )
    
    # Get Oxigraph endpoint and auth from configuration
    endpoint = get_oxigraph_endpoint()
    url = f"{endpoint}?graph={graph}"
    auth = get_oxigraph_auth()
    
    # OPTIMIZATION: For large files, use chunked reading to avoid memory spikes
    LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50 MB - only for memory optimization during upload
    processed_size = os.path.getsize(processed_filepath) if os.path.exists(processed_filepath) else original_size
    
    start = time.time()
    
    if processed_size > LARGE_FILE_THRESHOLD and ext in ["ttl", "turtle", "nt", "nq", "jsonld", "json", "rdf", "owl"]:
        # For large files, read in chunks to avoid memory spikes
        # Note: We still need to load into memory for httpx, but we do it in chunks
        try:
            content_type = "text/turtle" if processed_filepath.endswith(".ttl") else get_content_type_for_ext(ext)
            
            # Read file in chunks and combine (more memory efficient than reading all at once)
            chunks = []
            with open(processed_filepath, "rb") as f:
                while True:
                    chunk = f.read(16 * 1024 * 1024)  # 16 MB chunks
                    if not chunk:
                        break
                    chunks.append(chunk)
            payload = b"".join(chunks)
            
            resp = await client.post(
                url,
                content=payload,
                headers={"Content-Type": content_type},
                auth=auth,
            )
        except Exception as e:
            return {
                "file": filename,
                "ext": ext,
                "size_bytes": original_size,
                "elapsed_s": 0.0,
                "http_status": 0,
                "success": False,
                "bps": 0.0,
                "response_body": f"Error reading large file: {e}",
            }
    else:
        # For smaller files, read into memory (faster for small files)
        if ext in ["ttl", "turtle", "nt", "nq", "jsonld", "json", "rdf", "owl"]:
            # Text-based formats - read as text (processed files are in Turtle format)
            try:
                with open(processed_filepath, "r", encoding="utf-8") as f:
                    file_data = f.read()
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
                    "response_body": f"Error reading processed file: {e}",
                }
        else:
            # Binary formats - read as binary
            content_type = get_content_type_for_ext(ext)
            with open(processed_filepath, "rb") as f:
                payload = f.read()
        
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
    
    # Update processing state: File completed
    if job_id:
        from core.database import update_job_processing_state, insert_processing_log
        status_msg = f"Completed {filename} ({'success' if success else 'failed'})"
        if file_index is not None and total_files:
            status_msg = f"File {file_index + 1}/{total_files}: {status_msg}"
        await update_job_processing_state(
            job_id=job_id,
            current_stage="processing" if success else "error",
            status_message=status_msg
        )
        # Log completion to history
        await insert_processing_log(
            job_id=job_id,
            file_name=filename,
            stage="completed" if success else "failed",
            status_message=status_msg,
            file_index=file_index,
            total_files=total_files,
        )
    
    # Clean up processed file if it's different from original
    if processed_filepath != filepath and os.path.exists(processed_filepath):
        try:
            os.remove(processed_filepath)
        except Exception:
            pass
    
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
    user_id: str,
    skip_provenance: bool = False,
):
    """Background ingest runner, gated by a per-worker concurrency limiter so a
    burst of concurrent submissions cannot exhaust resources and crash the process.

    While waiting for a slot the job stays 'pending' (accurate — it is queued). The
    actual work runs in _run_ingest_job_body once a slot is acquired."""
    sem = _get_ingest_semaphore()
    if sem.locked():
        logger.info(
            f"[run_ingest_job] Job {job_id} is waiting for an ingest slot "
            f"(max {MAX_CONCURRENT_INGEST_JOBS} concurrent/worker)"
        )
    async with sem:
        await _run_ingest_job_body(job_id, max_concurrency, user_id, skip_provenance)


async def _run_ingest_job_body(
    job_id: str,
    max_concurrency: int,
    user_id: str,
    skip_provenance: bool = False,
):
    """Background job runner for file ingestion.
    Processes files (attaches provenance) and uploads them to Oxigraph.
    
    OPTIMIZATION: Batches database operations to reduce connection overhead.
    
    RECOVERY: Uses try-finally to ensure job status is always updated, even on crashes.
    """
    # Maximum job timeout: 2 hours (7200 seconds) for very large jobs
    # This prevents jobs from running indefinitely
    MAX_JOB_TIMEOUT = 2 * 60 * 60  # 2 hours
    job_start_time = time.time()

    delta_graph = delta_graph_for(job_id)

    async def _write_ingestion_prov(status_label: str, results):
        """Best-effort finalizer: merge the per-job delta graph into the target,
        then record this job as a PROV-O IngestionActivity (+ IngestionDelta) in
        Oxigraph. Never raises — a provenance failure must not fail the job."""
        try:
            details = await get_job_details(job_id)
            named_graph = details.get("graph") if details else None
            if not named_graph:
                return
            results = results or []
            succ = sum(1 for r in results if r.get("success"))
            fail = len(results) - succ

            added_count = None
            effective_delta_graph = None
            if TRACK_TRIPLE_DELTAS:
                # Count what the job staged, then merge the delta into the target graph.
                added_count = await count_graph_triples(delta_graph)
                if added_count and added_count > 0:
                    await merge_delta_into_target(delta_graph, named_graph)
                    effective_delta_graph = delta_graph

            prov_graph = build_ingestion_provenance(
                job_id=job_id,
                agent_id=user_id,
                named_graph_iri=named_graph,
                started_at=datetime.datetime.fromtimestamp(job_start_time, datetime.timezone.utc).isoformat(),
                ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                status=status_label,
                total_files=len(results),
                success_count=succ,
                fail_count=fail,
                results=results,
                agent_type="user",
                delta_graph=effective_delta_graph,
                added_triple_count=added_count,
            )
            await write_provenance(prov_graph)

            # Queue search indexing to run in the BACKGROUND (do not block the job
            # on it — indexing a large graph can be slow). Best-effort enqueue.
            try:
                from core.indexing import enqueue_ingest
                await enqueue_ingest(named_graph, effective_delta_graph)
            except Exception as _se:
                logger.warning(f"[run_ingest_job] Failed to queue search indexing for {job_id}: {_se}")
        except Exception as _pe:
            logger.warning(f"[run_ingest_job] Provenance write failed for {job_id}: {_pe}")

    try:
        # Mark job as running (start_time was already set when job was created)
        from core.database import update_job_processing_state, insert_processing_log
        await update_job_status(job_id, "running")
        status_msg = "Initializing job and preparing files"
        await update_job_processing_state(
            job_id=job_id,
            current_stage="initializing",
            status_message=status_msg
        )
        # Log initialization
        await insert_processing_log(
            job_id=job_id,
            stage="initializing",
            status_message=status_msg,
        )
        job_details = await get_job_details(job_id)
        if not job_details:
            logger.warning(f"[run_ingest_job] Job {job_id} details not found, marking as error")
            await update_job_status(job_id, "error", end_time=time.time())
            return
        
        job_dir = job_details["job_dir"]
        graph = job_details["graph"]
        # When delta tracking is on, stage uploads in the per-job delta graph;
        # _write_ingestion_prov merges it into the target graph at the end.
        upload_graph = delta_graph if TRACK_TRIPLE_DELTAS else graph

        # Collect files in job_dir (exclude .processed files)
        file_infos: List[Dict[str, Any]] = []
        for name in os.listdir(job_dir):
            if name.endswith(".processed.ttl"):
                continue  # Skip processed files
            path = os.path.join(job_dir, name)
            if not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
            file_infos.append({"path": path, "size_bytes": size})
        
        if not file_infos:
            logger.warning(f"[run_ingest_job] Job {job_id} has no files to process, marking as done")
            await update_job_status(job_id, "done", end_time=time.time())
            return
        
        # Set timeout for the entire job execution
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(MAX_JOB_TIMEOUT, connect=30.0, read=300.0, write=300.0),
            limits=httpx.Limits(
                max_connections=max_concurrency * 2,
                max_keepalive_connections=max_concurrency * 2,
            ),
        ) as client:
            sem = asyncio.Semaphore(max_concurrency)
            
            async def worker(fi: Dict[str, Any], index: int):
                filepath = fi["path"]
                size = fi["size_bytes"]
                async with sem:
                    # Check timeout before processing each file
                    elapsed = time.time() - job_start_time
                    if elapsed > MAX_JOB_TIMEOUT:
                        raise TimeoutError(f"Job {job_id} exceeded maximum timeout of {MAX_JOB_TIMEOUT}s")
                    
                    res = await upload_single_file_path(
                        client,
                        filepath,
                        size,
                        upload_graph,
                        user_id,
                        skip_provenance=skip_provenance,
                        job_id=job_id,
                        file_index=index,
                        total_files=len(file_infos),
                    )
                    return res
            
            tasks = [worker(fi, idx) for idx, fi in enumerate(file_infos)]
            all_results = []
            if tasks:
                # Use asyncio.wait_for to enforce overall timeout
                try:
                    all_results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=MAX_JOB_TIMEOUT
                    )
                    # Handle exceptions in results
                    processed_results = []
                    for i, result in enumerate(all_results):
                        if isinstance(result, Exception):
                            logger.error(f"[run_ingest_job] File {file_infos[i]['path']} failed: {result}")
                            processed_results.append({
                                "file": os.path.basename(file_infos[i]["path"]),
                                "ext": get_ext(os.path.basename(file_infos[i]["path"])),
                                "size_bytes": file_infos[i]["size_bytes"],
                                "elapsed_s": 0.0,
                                "http_status": 0,
                                "success": False,
                                "bps": 0.0,
                                "response_body": f"Error: {str(result)}",
                            })
                        else:
                            processed_results.append(result)
                    all_results = processed_results
                except asyncio.TimeoutError:
                    logger.error(f"[run_ingest_job] Job {job_id} timed out after {MAX_JOB_TIMEOUT}s")
                    raise TimeoutError(f"Job {job_id} exceeded maximum timeout of {MAX_JOB_TIMEOUT}s")
            
            # OPTIMIZATION: Batch database operations instead of individual calls
            BATCH_SIZE = 10  # Batch every 10 files
            for i in range(0, len(all_results), BATCH_SIZE):
                batch = all_results[i:i + BATCH_SIZE]
                await _batch_update_job_results(job_id, batch)

        # Clear processing state and mark as done
        from core.database import update_job_processing_state, insert_processing_log
        status_msg = "All files processed successfully"
        await update_job_processing_state(
            job_id=job_id,
            current_file=None,
            current_stage="completed",
            status_message=status_msg
        )
        # Log completion
        await insert_processing_log(
            job_id=job_id,
            stage="completed",
            status_message=status_msg,
        )
        await update_job_status(job_id, "done", end_time=time.time())
        # Record PROV-O ingestion provenance in Oxigraph (source of truth)
        _succ = sum(1 for r in all_results if r.get("success"))
        _fail = len(all_results) - _succ
        _status_label = "done" if _fail == 0 else ("failed" if _succ == 0 else "partial")
        await _write_ingestion_prov(_status_label, all_results)
        logger.info(f"[run_ingest_job] Job {job_id} completed successfully")

    except asyncio.TimeoutError as e:
        # Mark job as errored due to timeout
        from core.database import update_job_processing_state, insert_processing_log
        status_msg = f"Job timed out after {MAX_JOB_TIMEOUT}s"
        await update_job_processing_state(
            job_id=job_id,
            current_stage="error",
            status_message=status_msg
        )
        await insert_processing_log(
            job_id=job_id,
            stage="error",
            status_message=status_msg,
        )
        await update_job_status(job_id, "error", end_time=time.time())
        await _write_ingestion_prov("error", [])
        logger.error(f"[run_ingest_job] Job {job_id} timed out: {e}", exc_info=True)
    except Exception as e:
        # Mark job as errored
        from core.database import update_job_processing_state, insert_processing_log
        status_msg = f"Job failed: {str(e)[:200]}"  # Truncate long error messages
        await update_job_processing_state(
            job_id=job_id,
            current_stage="error",
            status_message=status_msg
        )
        await insert_processing_log(
            job_id=job_id,
            stage="error",
            status_message=status_msg,
        )
        await update_job_status(job_id, "error", end_time=time.time())
        await _write_ingestion_prov("error", [])
        logger.error(f"[run_ingest_job] Job {job_id} failed: {e}", exc_info=True)
    finally:
        # Ensure job status is always updated, even if something goes wrong
        # Double-check that status was updated
        try:
            from core.database import get_db_connection
            async with get_db_connection() as conn:
                current_status = await conn.fetchval(
                    "SELECT status FROM jobs WHERE job_id = $1",
                    job_id
                )
                # If still running, mark as error (shouldn't happen, but safety net)
                if current_status == "running":
                    logger.warning(f"[run_ingest_job] Job {job_id} was still in 'running' status in finally block, marking as error")
                    await update_job_status(job_id, "error", end_time=time.time())
        except Exception as e:
            logger.error(f"[run_ingest_job] Failed to verify job {job_id} status in finally block: {e}", exc_info=True)

        # Clean up temporary job files. Uploads can be up to 1.5 GB each and were
        # previously never removed, so /tmp/oxigraph_jobs grew unbounded. The recovery
        # path only marks jobs as 'error' (it does not reprocess these files), so it is
        # safe to remove them once the job has reached a terminal state.
        try:
            details = await get_job_details(job_id)
            job_dir = details.get("job_dir") if details else None
            if job_dir and os.path.isdir(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)
                logger.info(f"[run_ingest_job] Cleaned up temporary job directory for {job_id}: {job_dir}")
        except Exception as e:
            logger.warning(f"[run_ingest_job] Failed to clean up job directory for {job_id}: {e}")


async def check_job_recoverable(
    job_id: str,
    user_id: str,
    max_age_hours: float = 2.0,
    min_age_minutes: float = 5.0,
) -> Dict[str, Any]:
    """
    Check if a job is recoverable without actually recovering it.
    This is a lightweight check that can be called before attempting recovery.
    
    Returns:
        Dict with 'recoverable' boolean and reason if not recoverable
    """
    from core.database import get_db_connection
    
    try:
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        min_age_seconds = min_age_minutes * 60
        
        async with get_db_connection() as conn:
            # Get job details including unrecoverable flag
            job = await conn.fetchrow(
                """
                SELECT job_id, user_id, status, start_time, processed_files, total_files,
                       unrecoverable, unrecoverable_reason
                FROM jobs
                WHERE job_id = $1 AND user_id = $2
                """,
                job_id,
                user_id,
            )
            
            if not job:
                return {
                    "recoverable": False,
                    "reason": "Job not found or does not belong to user",
                    "job_id": job_id,
                }

            # Liveness check: if the background task is still alive in THIS process,
            # the job is genuinely running (regardless of age) and must not be recovered.
            # Recovering an active job would mark it 'error' mid-flight and can cause
            # duplicate/partial ingests. Note: this only sees tasks in the current worker
            # process; cross-worker liveness is not visible here (see _running_job_tasks).
            task = _running_job_tasks.get(job_id)
            if task is not None and not task.done():
                return {
                    "recoverable": False,
                    "process_running": True,
                    "reason": "Job is still actively running in this server process; an active job cannot be recovered.",
                    "job_id": job_id,
                    "status": job["status"],
                }

            # Check if job is already marked as unrecoverable
            if job.get("unrecoverable"):
                return {
                    "recoverable": False,
                    "reason": job.get("unrecoverable_reason") or "Job has been marked as unrecoverable",
                    "job_id": job_id,
                    "status": job["status"],
                    "unrecoverable": True,
                }
            
            # Check if job is in a recoverable state
            # "done", "partial", and "failed" are all completed states (not recoverable)
            if job["status"] == "done":
                # Check if it's actually partial or failed based on counts
                fail_count = job.get("fail_count", 0)
                success_count = job.get("success_count", 0)
                if fail_count == 0:
                    return {
                        "recoverable": False,
                        "reason": "Job is already completed successfully",
                        "job_id": job_id,
                        "status": job["status"],
                    }
                elif success_count == 0 and fail_count > 0:
                    return {
                        "recoverable": False,
                        "reason": "Job completed but all files failed",
                        "job_id": job_id,
                        "status": job["status"],
                    }
                else:
                    return {
                        "recoverable": False,
                        "reason": "Job completed with partial success (some files succeeded, some failed)",
                        "job_id": job_id,
                        "status": job["status"],
                    }
            
            if job["status"] == "pending":
                return {
                    "recoverable": False,
                    "reason": "Job is still pending and has not started yet",
                    "job_id": job_id,
                    "status": job["status"],
                }
            
            # For error status, always recoverable
            if job["status"] == "error":
                return {
                    "recoverable": True,
                    "reason": "Job is in error state and can be recovered",
                    "job_id": job_id,
                    "status": job["status"],
                }
            
            # For running status, check age
            if job["status"] == "running":
                if not job["start_time"]:
                    return {
                        "recoverable": False,
                        "reason": "Job has no start time",
                        "job_id": job_id,
                        "status": job["status"],
                    }
                
                age_seconds = current_time - job["start_time"]
                age_minutes = age_seconds / 60
                age_hours = age_seconds / 3600
                
                if age_seconds < min_age_seconds:
                    return {
                        "recoverable": False,
                        "reason": f"Job is too recent ({age_minutes:.1f} minutes old). Minimum age is {min_age_minutes} minutes",
                        "job_id": job_id,
                        "status": job["status"],
                        "age_minutes": round(age_minutes, 2),
                    }
                
                if age_seconds <= max_age_seconds:
                    return {
                        "recoverable": False,
                        "reason": f"Job is still within normal processing time ({age_hours:.1f} hours). Maximum age for recovery is {max_age_hours} hours",
                        "job_id": job_id,
                        "status": job["status"],
                        "age_hours": round(age_hours, 2),
                    }
                
                # Job is old enough to be considered stuck
                return {
                    "recoverable": True,
                    "reason": f"Job has been running for {age_hours:.1f} hours and appears to be stuck",
                    "job_id": job_id,
                    "status": job["status"],
                    "age_hours": round(age_hours, 2),
                }
            
            # Unknown status
            return {
                "recoverable": False,
                "reason": f"Unknown job status: {job['status']}",
                "job_id": job_id,
                "status": job["status"],
            }
            
    except Exception as e:
        logger.error(f"[check_job_recoverable] Error checking job {job_id}: {e}", exc_info=True)
        return {
            "recoverable": False,
            "reason": f"Error checking job recoverability: {str(e)}",
            "job_id": job_id,
        }


async def recover_stuck_jobs(
    max_age_hours: float = 2.0,
    min_age_minutes: float = 5.0,
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
    force_recovery: bool = False,  # Deprecated - kept for backward compatibility but not used
):
    """
    Recovery mechanism to detect and fix stuck jobs.
    
    Finds jobs that have been in 'running' status for too long and marks them as 'error'.
    This handles cases where:
    - Server crashed or was restarted while jobs were running
    - Background tasks crashed unexpectedly
    - Jobs exceeded timeout but status wasn't updated
    - Process was killed (OOM, system shutdown, etc.)
    
    Args:
        max_age_hours: Maximum age in hours for a running job before it's considered stuck
        min_age_minutes: Minimum age in minutes before considering a job stuck (prevents false positives)
        user_id: Optional user ID to filter jobs (if None, recovers all users' jobs - use with caution)
        job_id: Optional specific job ID to recover (if provided, only recovers this job)
        force_recovery: If True, allows recovery even if job doesn't meet normal criteria (manual override)
    
    Returns:
        Number of jobs recovered
    """
    from core.database import get_db_connection
    
    try:
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        min_age_seconds = min_age_minutes * 60
        
        async with get_db_connection() as conn:
            # Build query with optional filters (normal recovery)
            # Exclude jobs marked as unrecoverable
            where_clauses = [
                "status = 'running'",
                "start_time IS NOT NULL",
                "unrecoverable IS NOT TRUE",  # Exclude unrecoverable jobs
                f"($1 - start_time) >= ${2}",
                f"($1 - start_time) > ${3}",
            ]
            params = [current_time, min_age_seconds, max_age_seconds]
            param_index = 4
            
            # Add user_id filter if provided
            if user_id:
                where_clauses.append(f"user_id = ${param_index}")
                params.append(user_id)
                param_index += 1
            
            # Add job_id filter if provided
            if job_id:
                where_clauses.append(f"job_id = ${param_index}")
                params.append(job_id)
                param_index += 1
            
            where_sql = " AND ".join(where_clauses)
            
            # Find jobs that have been running for too long
            # Jobs are considered stuck if they're older than max_age_hours
            # But we require minimum age to avoid false positives (jobs that just started)
            # Exclude jobs already marked as unrecoverable
            stuck_jobs = await conn.fetch(
                f"""
                SELECT job_id, user_id, start_time, total_files, processed_files,
                       current_file, current_stage, status_message
                FROM jobs
                WHERE {where_sql}
                ORDER BY start_time ASC
                """,
                *params
            )
            
            if stuck_jobs:
                logger.warning(f"[recover_stuck_jobs] Found {len(stuck_jobs)} stuck job(s) (likely from server crash/restart)")
                
                for job in stuck_jobs:
                    job_id = job["job_id"]
                    user_id = job["user_id"]
                    start_time = job["start_time"]
                    age_hours = (current_time - start_time) / 3600
                    processed = job["processed_files"]
                    total = job["total_files"]
                    current_file = job.get("current_file")
                    
                    # Determine likely cause based on age and progress
                    if age_hours > 24:
                        cause = "Server was down for extended period (likely crash or maintenance)"
                    elif processed == 0:
                        cause = "Job never started processing (likely server crash during startup)"
                    elif current_file:
                        cause = f"Job was interrupted while processing {current_file} (likely server crash)"
                    else:
                        cause = "Job was interrupted (likely server restart or crash)"
                    
                    logger.warning(
                        f"[recover_stuck_jobs] Recovering stuck job {job_id} "
                        f"(user: {user_id}, age: {age_hours:.2f} hours, "
                        f"progress: {processed}/{total} files, cause: {cause})"
                    )
                    
                    # Update processing state to indicate recovery
                    await update_job_processing_state(
                        job_id=job_id,
                        current_stage="error",
                        status_message=f"Job recovered after server crash/restart. Was processing for {age_hours:.2f} hours."
                    )
                    
                    # Mark as error with current time as end_time
                    await update_job_status(job_id, "error", end_time=current_time)
                    
                    # Insert a job result indicating recovery from crash
                    await insert_job_result(
                        job_id=job_id,
                        file_name="[SYSTEM]",
                        ext="recovery",
                        size_bytes=0,
                        elapsed_s=current_time - start_time,
                        http_status=0,
                        success=False,
                        bps=0.0,
                        response_body=(
                            f"Job was automatically recovered after being stuck in 'running' status for {age_hours:.2f} hours. "
                            f"Cause: {cause}. "
                            f"Progress: {processed}/{total} files processed. "
                            f"This typically indicates a server crash, restart, or process termination during job execution. "
                            f"The job was marked as 'error' to prevent it from running indefinitely."
                        ),
                    )

                    # Record the automated recovery as a PROV-O RecoveryActivity (system agent)
                    try:
                        await write_provenance(
                            build_recovery_provenance(job_id=job_id, cause=cause)
                        )
                    except Exception as _pe:
                        logger.warning(f"[recover_stuck_jobs] Provenance write failed for {job_id}: {_pe}")

                logger.info(f"[recover_stuck_jobs] Recovered {len(stuck_jobs)} stuck job(s) from server crash/restart")
                return len(stuck_jobs)
            else:
                logger.debug("[recover_stuck_jobs] No stuck jobs found")
                return 0
                
    except Exception as e:
        logger.error(f"[recover_stuck_jobs] Error recovering stuck jobs: {e}", exc_info=True)
        return 0


async def _batch_update_job_results(job_id: str, results: List[Dict[str, Any]]):
    """
    OPTIMIZATION: Batch insert job results and update progress in a single transaction.
    This reduces database connection overhead significantly.
    """
    if not results:
        return
    
    # Prepare batch data
    batch_results = [
        {
            "file": r["file"],
            "ext": r["ext"],
            "size_bytes": r["size_bytes"],
            "elapsed_s": r["elapsed_s"],
            "http_status": r["http_status"],
            "success": bool(r["success"]),
            "bps": r["bps"],
            "response_body": r["response_body"],
        }
        for r in results
    ]
    
    # Batch insert results
    await batch_insert_job_results(job_id, batch_results)
    
    # Update progress counters
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    
    # Use a single update query for all progress
    from core.database import get_db_connection
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE jobs
                SET processed_files = processed_files + $1,
                    success_count = success_count + $2,
                    fail_count = fail_count + $3
                WHERE job_id = $4
                """,
                len(results),
                success_count,
                fail_count,
                job_id,
            )


@router.post("/insert/raw/knowledge-graph-triples",
             include_in_schema=True,
dependencies=[Depends(require_scopes(["write"]))],
             )
async def insert_knowledge_graph_triples(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier (who is sending the raw data)")],
    data: Annotated[str, Body(..., media_type="text/plain")],
    background_tasks: BackgroundTasks,
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
    - Saves data to disk immediately and processes in background.
    - Creates a job record for tracking progress.
    - Validates that the named graph is registered before ingestion.
    - Attaches provenance information to the ingested data in background.
    """
    # Ensure the caller can only create jobs under their own identity
    verify_user_access(user_id, user)

    # First, check if the named graph is registered
    if not await check_named_graph_exists(named_graph_iri):
        return JSONResponse(
            {
                "error": f"Named graph '{named_graph_iri}' is not registered. Please register it first using /api/register-named-graph",
                "named_graph_iri": named_graph_iri,
            },
            status_code=400,
        )

    # Role-based authorization: ingesting requires a write-capable role. JWT
    # scope is only API access — it does not by itself grant permission to ingest.
    if not await rbac.has_capability(_agent_email(user), rbac.INGEST):
        return JSONResponse(
            {"error": "Not authorized to ingest: a write-capable role is required."},
            status_code=403,
        )
    # If the graph belongs to a space, enforce space write-authorization
    # (owner/editor). Unmapped legacy graphs fall through (scope check applies).
    _graph_key = named_graph_iri if named_graph_iri.endswith("/") else named_graph_iri + "/"
    _allowed, _reason = await authorize_space_access(_graph_key, _agent_email(user), "write")
    if not _allowed:
        return JSONResponse(
            {"error": f"Not authorized to ingest into this graph: {_reason}", "named_graph_iri": named_graph_iri},
            status_code=403,
        )
    # Fine-grained per-space write rules (if any) further restrict who can ingest.
    _space_for_graph = await _spaces.get_space_for_graph(_graph_key)
    if _space_for_graph and not await _spaces.space_action_permitted(_space_for_graph, "write", _agent_email(user)):
        return JSONResponse(
            {"error": "Not authorized to ingest into this graph: restricted by a space access rule.",
             "named_graph_iri": named_graph_iri},
            status_code=403,
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
    
    # Create job directory and save raw data to disk immediately (no processing)
    job_dir = os.path.join(JOB_BASE_DIR, user_id, f"job_{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    
    # Save raw data to disk immediately (fast, no processing)
    raw_filepath = os.path.join(job_dir, f"raw_payload.{detected}")
    try:
        with open(raw_filepath, "w", encoding="utf-8") as f:
            f.write(data)
    except Exception as e:
        return JSONResponse(
            {
                "error": f"Failed to save raw data to disk: {e}",
            },
            status_code=500,
        )
    
    # Create job in "pending" state (will be processed in background)
    # Set start_time immediately when job is created (when user submits request)
    job_start_time = time.time()
    logger.info(f"[insert_knowledge_graph_triples] Creating job {job_id} with start_time={job_start_time} (Unix epoch seconds)")
    await create_job(
        job_id=job_id,
        user_id=user_id,
        status="pending",
        total_files=1,
        processed_files=0,
        success_count=0,
        fail_count=0,
        endpoint=endpoint,
        graph=named_graph_iri,
        job_dir=job_dir,
        start_time=job_start_time,
        end_time=None,
    )
    
    # Start background processing job and track it
    async def run_and_track_job():
        try:
            await run_ingest_job(job_id, 1, user_id, False)
        finally:
            # Remove from tracking when done (success or error)
            _running_job_tasks.pop(job_id, None)
    
    # Create and track the task (we're in an async context, so create_task works)
    task = asyncio.create_task(run_and_track_job())
    _running_job_tasks[job_id] = task
    # Also add to background_tasks for FastAPI lifecycle management
    background_tasks.add_task(lambda: None)  # Dummy task to keep FastAPI happy
    
    return {
        "job_id": job_id,
        "user_id": user_id,
        "named_graph_iri": named_graph_iri,
        "status": "pending",
        "detected_format": detected,
        "size_bytes": len(raw_bytes),
        "size_human": human_size(len(raw_bytes)),
        "message": "Data saved to disk. Processing (provenance + ingestion) started in background.",
        "status_url": f"/api/query/jobs?job_id={job_id}&user_id={user_id}",
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
    max_concurrency: Annotated[int, Query(ge=1, le=64, description="Maximum concurrent uploads")] = 8,
    skip_provenance: Annotated[bool, Query(description="Skip provenance attachment for faster ingestion (recommended for large files)")] = False,
):
    """
    Upload RDF files (ttl, nt, jsonld, etc.), create a user-scoped job, and start background ingestion.
    Graph defaults to 'named_graph' but can be overridden via named_graph_iri.
    Oxigraph endpoint and auth always come from environment variables.
    Validates that the named graph is registered before ingestion.
    Attaches provenance information to ingested files.
    """
    # Ensure the caller can only create jobs under their own identity
    verify_user_access(user_id, user)

    # First, check if the named graph is registered
    if not await check_named_graph_exists(named_graph_iri):
        return JSONResponse(
            {
                "error": f"Named graph '{named_graph_iri}' is not registered. Please register it first using /api/register-named-graph",
                "named_graph_iri": named_graph_iri,
            },
            status_code=400,
        )

    # Role-based authorization: ingesting requires a write-capable role. JWT
    # scope is only API access — it does not by itself grant permission to ingest.
    if not await rbac.has_capability(_agent_email(user), rbac.INGEST):
        return JSONResponse(
            {"error": "Not authorized to ingest: a write-capable role is required."},
            status_code=403,
        )
    # If the graph belongs to a space, enforce space write-authorization
    # (owner/editor). Unmapped legacy graphs fall through (scope check applies).
    _graph_key = named_graph_iri if named_graph_iri.endswith("/") else named_graph_iri + "/"
    _allowed, _reason = await authorize_space_access(_graph_key, _agent_email(user), "write")
    if not _allowed:
        return JSONResponse(
            {"error": f"Not authorized to ingest into this graph: {_reason}", "named_graph_iri": named_graph_iri},
            status_code=403,
        )
    # Fine-grained per-space write rules (if any) further restrict who can ingest.
    _space_for_graph = await _spaces.get_space_for_graph(_graph_key)
    if _space_for_graph and not await _spaces.space_action_permitted(_space_for_graph, "write", _agent_email(user)):
        return JSONResponse(
            {"error": "Not authorized to ingest into this graph: restricted by a space access rule.",
             "named_graph_iri": named_graph_iri},
            status_code=403,
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
        
        # Save file to disk immediately (chunked write, no processing)
        # Processing (provenance + ingestion) will happen in background
        try:
            with open(path, "wb") as out:
                while True:
                    chunk = await uf.read(2 * 1024 * 1024)  # 2 MB chunks
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
        except Exception as e:
            logger.error(f"Failed to save file {filename} to disk: {e}", exc_info=True)
            pre_results.append(
                {
                    "file": filename,
                    "ext": ext,
                    "size_bytes": 0,
                    "elapsed_s": 0.0,
                    "http_status": 500,
                    "success": False,
                    "bps": 0.0,
                    "response_body": f"Failed to save file to disk: {e}",
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
    
    # Set start_time immediately when job is created (when user submits request)
    job_start_time = time.time()
    logger.info(f"[insert_file_knowledge_graph_triples] Creating job {job_id} with start_time={job_start_time} (Unix epoch seconds)")
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
        start_time=job_start_time,
        end_time=None,
    )
    
    # Batch insert pre-results (much faster than individual inserts)
    if pre_results:
        await batch_insert_job_results(job_id, pre_results)
    
    # Start background ingest job and track it
    async def run_and_track_job():
        try:
            await run_ingest_job(job_id, max_concurrency, user_id, skip_provenance)
        finally:
            # Remove from tracking when done (success or error)
            _running_job_tasks.pop(job_id, None)
    
    # Create and track the task (we're in an async context, so create_task works)
    task = asyncio.create_task(run_and_track_job())
    _running_job_tasks[job_id] = task
    # Also add to background_tasks for FastAPI lifecycle management
    background_tasks.add_task(lambda: None)  # Dummy task to keep FastAPI happy
    
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
            include_in_schema=True,
            dependencies=[Depends(require_scopes(["read"]))],
            )
async def list_jobs(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier")],
    limit: Annotated[int, Query(ge=1, le=500, description="Page size when listing jobs")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination when listing jobs")] = 0,
    started_after: Annotated[Optional[float], Query(description="Filter: jobs with start_time >= this UNIX epoch seconds")] = None,
    started_before: Annotated[Optional[float], Query(description="Filter: jobs with start_time <= this UNIX epoch seconds")] = None,
):
    """
    GET /insert/jobs
    List all jobs for a user with pagination and optional time range filters.
    Returns paginated list of jobs with their basic information.
    """
    verify_user_access(user_id, user)
    return await list_user_jobs(
        user_id=user_id,
        limit=limit,
        offset=offset,
        started_after=started_after,
        started_before=started_before,
    )


@router.get("/insert/user/jobs/detail",
            include_in_schema=True,
            dependencies=[Depends(require_scopes(["read"]))],
            )
async def get_job_detail(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier")],
    job_id: Annotated[str, Query(..., description="Job identifier to fetch details for")],
):
    """
    GET /insert/user/jobs/detail
    Get detailed information for a single job by job_id and user_id.
    Returns full job details including summary (when job is done/error).
    """
    verify_user_access(user_id, user)
    job = await get_job_by_id_and_user(job_id, user_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    total = job["total_files"]
    processed = job["processed_files"]
    progress = (100.0 * processed / total) if total else 0.0
    
    # Calculate elapsed time
    start_time = job.get("start_time")
    end_time = job.get("end_time")
    current_time = time.time()
    elapsed_seconds = None
    if start_time:
        if end_time:
            elapsed_seconds = end_time - start_time
        else:
            elapsed_seconds = current_time - start_time
    
    # Determine effective status based on completion and failure counts
    effective_status = job["status"]
    fail_count = job["fail_count"]
    success_count = job["success_count"]
    
    # Refine status for completed jobs:
    # - "done" = all files succeeded (fail_count = 0)
    # - "partial" = some succeeded, some failed (both > 0)
    # - "failed" = all files failed (success_count = 0 and fail_count > 0)
    if job["status"] == "done":
        if fail_count == 0:
            effective_status = "done"  # All succeeded
        elif success_count == 0 and fail_count > 0:
            effective_status = "failed"  # All failed
        else:
            effective_status = "partial"  # Some succeeded, some failed
    
    resp: Dict[str, Any] = {
        "job_id": job_id,
        "user_id": user_id,
        "status": effective_status,  # Use effective status (shows "failed" if done with failures)
        "original_status": job["status"],  # Keep original status for reference
        "total_files": total,
        "processed_files": processed,
        "progress_percent": round(progress, 2),
        "success_count": success_count,
        "fail_count": fail_count,
        "endpoint": job["endpoint"],
        "named_graph_iri": job["graph"],
        "start_time": start_time,
        "end_time": end_time,
        "elapsed_seconds": round(elapsed_seconds, 2) if elapsed_seconds else None,
        # Detailed processing information for UI
        "current_file": job.get("current_file"),
        "current_stage": job.get("current_stage"),
        "status_message": job.get("status_message"),
        # Recovery status
        "unrecoverable": bool(job.get("unrecoverable")),
        "unrecoverable_reason": job.get("unrecoverable_reason"),
        # Failure indication
        "has_failures": fail_count > 0,
        "all_succeeded": fail_count == 0 and processed > 0,
    }
    
    # Add warning if job is running but no files processed yet (might be stuck in initialization)
    if job["status"] == "running" and processed == 0 and total > 0 and elapsed_seconds:
        # If job has been running for more than 2 minutes with 0 processed files, it might be stuck
        if elapsed_seconds > 120:  # 2 minutes
            resp["warning"] = f"Job has been running for {round(elapsed_seconds/60, 1)} minutes but no files have been processed yet. Job may be stuck in initialization."
            resp["stuck_in_initialization"] = True
        else:
            resp["initializing"] = True
            resp["initialization_message"] = "Job is initializing and preparing files..."
    
    # Add human-readable stage descriptions
    stage_descriptions = {
        "pending": "Job is queued and waiting to start",
        "initializing": "Preparing files and initializing job",
        "processing": "Processing file",
        "attaching_provenance": "Attaching provenance metadata to file",
        "uploading": "Uploading file to Oxigraph",
        "completed": "All files processed successfully",
        "error": "An error occurred during processing",
        "done": "All files processed successfully",
        "partial": f"Job completed: {success_count} succeeded, {fail_count} failed",
        "failed": "All files failed",
    }
    
    # Update stage description based on effective status
    if effective_status == "partial":
        resp["stage_description"] = f"Job completed with partial success: {success_count} file(s) succeeded, {fail_count} file(s) failed out of {total} total"
    elif effective_status == "failed":
        resp["stage_description"] = f"Job completed but all {fail_count} file(s) failed"
    elif effective_status == "done":
        resp["stage_description"] = f"All {total} file(s) processed successfully"
    elif job.get("current_stage"):
        resp["stage_description"] = stage_descriptions.get(
            job["current_stage"],
            f"Current stage: {job['current_stage']}"
        )
    
    if job.get("current_stage"):
        resp["stage_description"] = stage_descriptions.get(
            job["current_stage"],
            f"Current stage: {job['current_stage']}"
        )
    
    # Add estimated time remaining (if job is running and we have progress)
    if job["status"] == "running" and processed > 0 and total > 0 and elapsed_seconds:
        avg_time_per_file = elapsed_seconds / processed
        remaining_files = total - processed
        estimated_remaining = avg_time_per_file * remaining_files
        resp["estimated_remaining_seconds"] = round(estimated_remaining, 2)
    
    # Get processing history/log for UI
    from core.database import get_processing_log
    processing_log = await get_processing_log(job_id, limit=200)  # Get last 200 log entries
    resp["processing_history"] = processing_log
    
    # Always pull results and summary (even for running jobs) to show failures in real-time
    results = await get_job_results(job_id)
    resp["summary"] = compute_summary(results)
    
    # Also include a simplified failures list for easier access
    if results:
        resp["failed_files"] = [
            {
                "file": r.get("file", ""),
                "http_status": r.get("http_status", 0),
                "response_body": r.get("response_body", ""),
                "ext": r.get("ext", ""),
            }
            for r in results if not r.get("success", False)
        ]
    else:
        resp["failed_files"] = []
    
    return resp


@router.get("/insert/jobs/check-recoverable",
            include_in_schema=True,
            dependencies=[Depends(require_scopes(["read"]))],
            )
async def check_job_recoverable_endpoint(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier")],
    job_id: Annotated[str, Query(..., description="Job ID to check")],
    max_age_hours: Annotated[float, Query(ge=0.1, le=24.0, description="Maximum age in hours for a running job before it's considered stuck")] = 2.0,
    min_age_minutes: Annotated[float, Query(ge=1.0, le=60.0, description="Minimum age in minutes before considering a job stuck")] = 5.0,
):
    """
    GET /insert/jobs/check-recoverable
    Check if a job is recoverable without actually recovering it.
    
    This is a lightweight, non-blocking check that can be called before attempting recovery.
    Returns whether the job can be recovered and the reason.
    
    Use this endpoint before calling the recover endpoint to avoid unnecessary processing.
    """
    verify_user_access(user_id, user)
    try:
        result = await check_job_recoverable(
            job_id=job_id,
            user_id=user_id,
            max_age_hours=max_age_hours,
            min_age_minutes=min_age_minutes,
        )
        return {
            "status": "success",
            **result,
        }
    except Exception as e:
        logger.error(f"Error in check_job_recoverable_endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check job recoverability: {str(e)}"
        )


@router.post("/insert/jobs/recover",
            include_in_schema=True,
            dependencies=[Depends(require_scopes(["write"]))],
            )
async def recover_stuck_jobs_endpoint(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier - required for security")],
    job_id: Annotated[Optional[str], Query(description="Optional specific job ID to recover. If not provided, recovers all stuck jobs for the user")] = None,
    max_age_hours: Annotated[float, Query(ge=0.1, le=24.0, description="Maximum age in hours for a running job before it's considered stuck")] = 2.0,
    min_age_minutes: Annotated[float, Query(ge=1.0, le=60.0, description="Minimum age in minutes before considering a job stuck (prevents false positives)")] = 5.0,
):
    """
    POST /insert/jobs/recover
    Manually trigger recovery of stuck jobs.
    
    IMPORTANT: Recovery only proceeds if the job is recoverable (checked first).
    If a job is not recoverable, it will be marked as unrecoverable to prevent future attempts.
    
    Finds jobs that have been in 'running' status for longer than max_age_hours
    and marks them as 'error'. This is useful for:
    - Recovering jobs after server crashes or restarts
    - Fixing jobs that got stuck due to process termination
    - Manual cleanup of orphaned jobs
    - Recovering from OOM kills or system shutdowns
    
    Security:
    - Requires user_id parameter (users can only recover their own jobs)
    - If job_id is provided, checks recoverability first before attempting recovery
    - If job_id is not provided, recovers all stuck jobs for the user
    
    Workflow:
    1. Check if job is recoverable (lightweight check)
    2. If recoverable: proceed with recovery
    3. If not recoverable: mark as unrecoverable and return error (no recovery attempted)
    
    Returns the number of jobs recovered and details about recovered jobs.
    """
    verify_user_access(user_id, user)
    if not await rbac.has_capability(_agent_email(user), rbac.RECOVER):
        return JSONResponse(
            {"error": "Not authorized to recover jobs: a write-capable role is required."},
            status_code=403,
        )
    try:
        # For single job recovery, MUST check recoverability first (includes process check)
        if job_id:
            # Verify job belongs to user (security check)
            from core.database import get_job_by_id_and_user
            job = await get_job_by_id_and_user(job_id, user_id)
            if not job:
                return JSONResponse(
                    {
                        "status": "error",
                        "message": f"Job {job_id} not found or does not belong to user {user_id}",
                    },
                    status_code=404,
                )
            
            # Check if job is already marked as unrecoverable
            from core.database import get_db_connection
            async with get_db_connection() as conn:
                unrecoverable_check = await conn.fetchval(
                    "SELECT unrecoverable FROM jobs WHERE job_id = $1",
                    job_id
                )
                if unrecoverable_check:
                    unrecoverable_reason = await conn.fetchval(
                        "SELECT unrecoverable_reason FROM jobs WHERE job_id = $1",
                        job_id
                    )
                    return JSONResponse(
                        {
                            "status": "error",
                            "recoverable": False,
                            "reason": unrecoverable_reason or "Job has been marked as unrecoverable",
                            "job_id": job_id,
                            "message": f"Job is marked as unrecoverable: {unrecoverable_reason or 'Previously marked as unrecoverable'}",
                            "unrecoverable": True,
                        },
                        status_code=400,
                    )
            
            # Check recoverability before attempting recovery (checks both DB and process)
            check_result = await check_job_recoverable(
                job_id=job_id,
                user_id=user_id,
                max_age_hours=max_age_hours,
                min_age_minutes=min_age_minutes,
            )
            
            # If process is still running, inform user and do NOT recover
            if check_result.get("process_running"):
                return JSONResponse(
                    {
                        "status": "error",
                        "recoverable": False,
                        "reason": check_result["reason"],
                        "job_id": job_id,
                        "message": check_result["reason"],
                        "process_running": True,
                    },
                    status_code=400,
                )
            
            # If not recoverable (for other reasons), mark as unrecoverable and return error
            if not check_result["recoverable"]:
                # Mark job as unrecoverable to prevent future attempts
                async with get_db_connection() as conn:
                    await conn.execute(
                        """
                        UPDATE jobs
                        SET unrecoverable = TRUE,
                            unrecoverable_reason = $1
                        WHERE job_id = $2
                        """,
                        check_result["reason"],
                        job_id,
                    )
                
                logger.info(f"[recover_stuck_jobs_endpoint] Job {job_id} marked as unrecoverable: {check_result['reason']}")
                
                return JSONResponse(
                    {
                        "status": "error",
                        "recoverable": False,
                        "reason": check_result["reason"],
                        "job_id": job_id,
                        "message": f"Job is not recoverable: {check_result['reason']}. Job has been marked as unrecoverable.",
                        "unrecoverable": True,
                    },
                    status_code=400,
                )
        
        # Proceed with recovery (only if check passed or bulk recovery)
        recovered_count = await recover_stuck_jobs(
            max_age_hours=max_age_hours,
            min_age_minutes=min_age_minutes,
            user_id=user_id,
            job_id=job_id,
            force_recovery=False,  # No force mode - always respect check
        )
        
        message = (
            f"Recovered {recovered_count} stuck job(s)" if recovered_count > 0
            else "No stuck jobs found matching criteria"
        )
        
        if job_id:
            message += f" (job_id: {job_id})"
        
        return {
            "status": "success",
            "recovered_count": recovered_count,
            "user_id": user_id,
            "job_id": job_id,
            "max_age_hours": max_age_hours,
            "min_age_minutes": min_age_minutes,
            "message": message,
        }
    except Exception as e:
        logger.error(f"Error in recover_stuck_jobs_endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to recover stuck jobs: {str(e)}"
        )


@router.post("/register-named-graph",
             dependencies=[Depends(require_scopes(["write"]))],
             )
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
            # Attribute the registration to the authenticated user (PROV-O). This is
            # recorded on the registry entry itself (see named_graph_metadata) rather
            # than duplicated as a separate activity in the provenance graph.
            try:
                agent_id = user["email"] or user["id"]
            except (KeyError, TypeError, IndexError):
                agent_id = "unknown"
            agent_uri = str(agent_ref(str(agent_id)))

            # Register the new named graph
            response = await insert_data_gdb_async(named_graph_metadata(
                named_graph_url=named_graph_url,
                description=description,
                agent_uri=agent_uri,
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


@router.get(
    "/provenance/job",
    include_in_schema=True,
    dependencies=[Depends(require_scopes(["read"]))],
    summary="PROV-O provenance bundle for one ingestion job",
    description=(
        "Returns the **W3C PROV-O bundle** (JSON-LD) for a single ingestion job: "
        "the `IngestionActivity` (with agent, start/end time, status, file counts), "
        "the generated bundle entity, each per-file entity (upload status, HTTP "
        "status, size), the `IngestionDelta` entity, and any recovery activity that "
        "acted on the job. Access-controlled — the `user_id` must match the "
        "authenticated caller."
    ),
)
async def get_job_provenance(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier (must match the authenticated user)")],
    job_id: Annotated[str, Query(..., description="Job identifier to fetch provenance for")],
):
    """
    Return the full PROV-O provenance bundle (JSON-LD) for a single ingestion job,
    reconstructed from the dedicated provenance graph in Oxigraph.

    Scope: everything about ONE job (activity + bundle + files + delta + recovery).
    For a whole graph's history use /provenance/named-graph.
    """
    verify_user_access(user_id, user)
    jsonld = await query_provenance_jsonld(construct_for_job(job_id))
    if jsonld is None:
        return JSONResponse(
            {"error": "Failed to retrieve provenance from the graph database"},
            status_code=502,
        )
    return Response(content=jsonld, media_type="application/ld+json")


@router.get(
    "/provenance/named-graph",
    include_in_schema=True,
    dependencies=[Depends(require_scopes(["read"]))],
    summary="PROV-O activity history for a named graph",
    description=(
        "Returns the **W3C PROV-O provenance** (JSON-LD) describing how a named "
        "graph's data came to be: every ingestion activity that targeted it, with "
        "the agent, start/end times, per-file entities, and job status.\n\n"
        "Difference from `GET /api/query/registered-named-graphs`:\n"
        "- **registered-named-graphs** = the *registry/catalog* — which graphs "
        "exist and their registration metadata (one row per graph).\n"
        "- **provenance/named-graph** = the *activity history* — what was ingested "
        "into a given graph, when, and by whom (a PROV-O bundle, potentially many "
        "activities). Reads the provenance graph `https://brainkb.org/provenance/`."
    ),
)
async def get_named_graph_provenance(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    iri: Annotated[str, Query(..., description="Named graph IRI to fetch the ingestion/activity provenance for")],
):
    """
    Return the PROV-O provenance (JSON-LD) for every ingestion activity that
    targeted the given named graph.

    This is the *history of data mutations* on the graph, distinct from the
    registry catalog returned by /api/query/registered-named-graphs. Registration
    attribution lives on the registry entry (see that endpoint's `registered_by`).
    """
    jsonld = await query_provenance_jsonld(construct_for_named_graph(iri))
    if jsonld is None:
        return JSONResponse(
            {"error": "Failed to retrieve provenance from the graph database"},
            status_code=502,
        )
    return Response(content=jsonld, media_type="application/ld+json")


@router.get("/provenance/delta", include_in_schema=True,
            dependencies=[Depends(require_scopes(["read"]))])
async def get_job_delta(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier (must match the authenticated user)")],
    job_id: Annotated[str, Query(..., description="Job identifier whose added triples to return")],
):
    """
    GET /provenance/delta
    Return the exact set of triples a job added (its delta graph) as JSON-LD.
    This is the incremental change that job contributed to the target graph.
    """
    verify_user_access(user_id, user)
    jsonld = await query_provenance_jsonld(construct_delta_content(job_id))
    if jsonld is None:
        return JSONResponse(
            {"error": "Failed to retrieve delta from the graph database"},
            status_code=502,
        )
    return Response(content=jsonld, media_type="application/ld+json")


@router.get("/provenance/delta/history", include_in_schema=True,
            dependencies=[Depends(require_scopes(["read"]))])
async def get_delta_history(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    iri: Annotated[str, Query(..., description="Named graph IRI to list the change history for")],
):
    """
    GET /provenance/delta/history
    Return the ordered change history of a named graph: one entry per ingestion
    delta (job, added triple count, timestamp, status), newest first.
    """
    history = await delta_history_for_graph(iri)
    if history is None:
        return JSONResponse(
            {"error": "Failed to retrieve delta history from the graph database"},
            status_code=502,
        )
    return {"named_graph_iri": iri, "changes": history, "total": len(history)}


@router.get("/provenance/delta/compare", include_in_schema=True,
            dependencies=[Depends(require_scopes(["read"]))])
async def compare_job_deltas(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    user_id: Annotated[str, Query(..., description="User identifier (must match the authenticated user)")],
    job_id_a: Annotated[str, Query(..., description="First job identifier")],
    job_id_b: Annotated[str, Query(..., description="Second job identifier")],
):
    """
    GET /provenance/delta/compare
    Compare the triples added by two jobs. Returns counts (A-only, B-only,
    shared) and the differing triples as JSON-LD, so users can see exactly how
    two ingestion changes differ.
    """
    verify_user_access(user_id, user)
    result = await compare_deltas(job_id_a, job_id_b)
    if result is None:
        return JSONResponse(
            {"error": "Failed to compare deltas (one or both delta graphs unavailable)"},
            status_code=502,
        )
    return result

