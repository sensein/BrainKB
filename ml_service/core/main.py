import logging
import asyncio
from contextlib import asynccontextmanager

# logging
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.websockets import WebSocket as StarletteWebSocket

from core.configure_logging import configure_logging
from core.routers.index import router as index_router
from core.routers.jwt_auth import router as jwt_router
from core.routers.resource_extraction_ingest import router as resource_router
from core.routers.structsense import router as structsense_router
from core.database import init_db_pool, get_db_pool, debug_pool_status
from core.configuration import load_environment

from fastapi.middleware.cors import CORSMiddleware

# Initialize logger - will be configured in lifespan
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging()
    logger.info("Starting FastAPI application")

    try:
        # Initialize database connection pool
        await init_db_pool()
        logger.info("Database connection pool initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        raise

    yield

    # Shutdown
    logger.info("Initiating FastAPI shutdown sequence")

    try:
        # Debug: Check pool status before closing
        await debug_pool_status()

        pool = await get_db_pool()
        if pool:
            logger.info("Closing database connection pool...")
            try:
                # Try graceful close with timeout
                await asyncio.wait_for(pool.close(), timeout=10.0)
                logger.info("Database connection pool closed gracefully")
            except asyncio.TimeoutError:
                logger.warning("Database pool closure timed out after 10 seconds")
                logger.warning("Forcing termination of remaining connections...")
                await pool.terminate()
                logger.info("Database connection pool terminated")
            except Exception as e:
                logger.error(f"Error during pool closure: {e}")
                logger.info("Attempting forced termination...")
                await pool.terminate()
                logger.info("Database connection pool terminated")
        else:
            logger.warning("No database pool found during shutdown")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

    logger.info("FastAPI shutdown complete")

app = FastAPI(
    lifespan=lifespan,
    title="BrainKB API",
    description="Multi-agent system and resource extraction API",
    version="1.0.0"
)

# Load environment to check if we're in development
env = load_environment()
env_state = env.get("ENV_STATE", "production").lower()

# CORS Configuration
origins = [
    "https://beta.brainkb.org",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)

# Include routers
app.include_router(index_router, prefix="/api")
app.include_router(jwt_router, prefix="/api", tags=["Security"])
app.include_router(structsense_router, prefix="/api", tags=["Multi-agent Systems"])
app.include_router(resource_router, prefix="/api", tags=["Resource Extraction"])

# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    """Log all HTTP exceptions before handling them."""
    logger.error(
        f"HTTP Exception: {exc.status_code} - {exc.detail} "
        f"[Path: {request.url.path}, Method: {request.method}]"
    )
    return await http_exception_handler(request, exc)

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Catch-all handler for unexpected exceptions."""
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)} "
        f"[Path: {request.url.path}, Method: {request.method}]",
        exc_info=True
    )
    return await http_exception_handler(
        request,
        HTTPException(status_code=500, detail="Internal server error")
    )

# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Simple health check endpoint."""
    try:
        pool = await get_db_pool()
        db_status = "healthy" if pool and pool.get_size() > 0 else "unhealthy"
    except Exception:
        db_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "environment": env_state
    }
