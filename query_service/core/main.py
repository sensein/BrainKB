import logging

# logging
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException

from core.configure_logging import configure_logging
from core.routers.index import router as index_router
from core.routers.jwt_auth import router as jwt_router
from core.routers.query import router as query_router
from core.routers.rapid_release import router as rapid_release
from core.routers.insert import router as insert_router
from core.configuration import load_environment
from core.database import init_db_pool
from core.graph_database_connection_manager import initialize_metadata_graph

from fastapi.middleware.cors import CORSMiddleware

environment = load_environment()["ENV_STATE"]


origins = [  
    "https://beta.brainkb.org",
"https://sandbox.brainkb.org",
    "http://localhost:3000/",
    "http://localhost:3000",
    "http://127.0.0.1:3000:"
]

if environment == "prods":
    app = FastAPI(docs_url=None, redoc_url=None)
else:
    app = FastAPI()
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)


app.include_router(index_router, prefix="/api")
app.include_router(jwt_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(insert_router,prefix="/api")

# rapid-release
app.include_router(rapid_release, prefix="/api/rapid-release", tags=["Rapid release"])


@app.on_event("startup")
async def startup_event():
    configure_logging()
    logger.info("Starting FastAPI")
    
    # Wait for database to be ready with retries
    from core.database import get_db_pool
    import asyncio
    import asyncpg
    
    max_retries = 30
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to connect to database (attempt {attempt + 1}/{max_retries})...")
            # Initialize database connection pool
            await init_db_pool()
            logger.info("Database connection pool initialized")
            
            # Test connection by creating tables
            pool = await get_db_pool()
            try:
                conn = await asyncio.wait_for(pool.acquire(), timeout=5.0)
                try:
                    # Test connection with a simple query
                    await conn.fetchval("SELECT 1")
                    logger.info("Database connection test successful")
                    
                    # Create job tracking tables if they don't exist
                    await conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jobs (
                            job_id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            total_files INTEGER NOT NULL,
                            processed_files INTEGER NOT NULL,
                            success_count INTEGER NOT NULL,
                            fail_count INTEGER NOT NULL,
                            start_time DOUBLE PRECISION,
                            end_time DOUBLE PRECISION,
                            endpoint TEXT NOT NULL,
                            graph TEXT NOT NULL,
                            job_dir TEXT NOT NULL,
                            current_file TEXT,
                            current_stage TEXT,
                            status_message TEXT
                        )
                        """
                    )
                    # Add new columns if they don't exist (for existing databases)
                    # These columns are used for live status update and to track the job status for recovery purpose.
                    try:
                        await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS current_file TEXT")
                        await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS current_stage TEXT")
                        await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS status_message TEXT")
                        await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS unrecoverable BOOLEAN DEFAULT FALSE")
                        await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS unrecoverable_reason TEXT")
                    except Exception:
                        pass  # Columns may already exist
                    await conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS job_results (
                            id SERIAL PRIMARY KEY,
                            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                            file_name TEXT NOT NULL,
                            ext TEXT NOT NULL,
                            size_bytes BIGINT NOT NULL,
                            elapsed_s DOUBLE PRECISION NOT NULL,
                            http_status INTEGER NOT NULL,
                            success BOOLEAN NOT NULL,
                            bps DOUBLE PRECISION NOT NULL,
                            response_body TEXT
                        )
                        """
                    )
                    await conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS job_processing_log (
                            id SERIAL PRIMARY KEY,
                            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                            file_name TEXT,
                            stage TEXT NOT NULL,
                            status_message TEXT,
                            timestamp DOUBLE PRECISION NOT NULL,
                            file_index INTEGER,
                            total_files INTEGER
                        )
                        """
                    )
                    # Create index for faster queries
                    try:
                        await conn.execute("CREATE INDEX IF NOT EXISTS idx_job_processing_log_job_id ON job_processing_log(job_id)")
                        await conn.execute("CREATE INDEX IF NOT EXISTS idx_job_processing_log_timestamp ON job_processing_log(timestamp)")
                    except Exception:
                        pass  # Indexes may already exist
                    logger.info("Job tracking tables initialized")
                    break  # Success, exit retry loop
                finally:
                    await pool.release(conn)
            except asyncio.TimeoutError:
                logger.warning(f"Database connection timeout (attempt {attempt + 1}/{max_retries}). Retrying in {retry_delay}s...")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error("Database connection timeout after all retries")
                    raise
            except asyncpg.exceptions.PostgresError as e:
                logger.warning(f"Database error (attempt {attempt + 1}/{max_retries}): {str(e)}. Retrying in {retry_delay}s...")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Database error after all retries: {str(e)}")
                    raise
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Startup error (attempt {attempt + 1}/{max_retries}): {str(e)}. Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.error(f"Failed to initialize during startup after all retries: {str(e)}", exc_info=True)
                raise
    
    # Initialize metadata graph if it doesn't exist (non-blocking)
    logger.info("Initializing metadata graph...")
    try:
        metadata_init_success = initialize_metadata_graph()
        if metadata_init_success:
            logger.info("Metadata graph initialized successfully")
        else:
            logger.warning("Metadata graph initialization failed, but continuing...")
    except Exception as e:
        logger.warning(f"Failed to initialize metadata graph: {str(e)}. Continuing anyway...")
    
    # Recover stuck jobs (jobs that were running when server restarted or crashed)
    # Use shorter threshold on startup to catch jobs from recent crashes
    logger.info("Recovering stuck jobs from previous server session...")
    try:
        from core.routers.insert import recover_stuck_jobs
        # On startup, recover jobs that are older than 5 minutes (likely from crash)
        # This catches jobs that were running when server crashed/restarted
        recovered_count = await recover_stuck_jobs(max_age_hours=24.0, min_age_minutes=5.0)
        if recovered_count > 0:
            logger.warning(f"Recovered {recovered_count} stuck job(s) from previous server session (likely from crash/restart)")
        else:
            logger.debug("No stuck jobs found from previous server session")
    except Exception as e:
        logger.warning(f"Failed to recover stuck jobs: {str(e)}. Continuing anyway...")
    
    logger.info("FastAPI startup completed successfully")


# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)
