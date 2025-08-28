import logging
from contextlib import asynccontextmanager

# logging
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException

from core.configure_logging import configure_logging
from core.routers.index import router as index_router
from core.routers.jwt_auth import router as jwt_router
from core.routers.resource_extraction_ingest import router as resource_router
from core.routers.structsense import router as structsense_router
from core.database import init_db_pool, get_db_pool

from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging()
    logger.info("Starting FastAPI")
    # Initialize database connection pool
    await init_db_pool()
    logger.info("Database connection pool initialized")
    yield
    # Shutdown
    logger.info("Shutting down FastAPI")
    pool = await get_db_pool()
    if pool:
        await pool.close()
        logger.info("Database connection pool closed")

app = FastAPI(lifespan=lifespan)
logger = logging.getLogger(__name__)

origins = [
    "https://beta.brainkb.org",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)


app.include_router(index_router, prefix="/api")
app.include_router(jwt_router, prefix="/api", tags=["Security"])
# app.include_router(structsense_router, prefix="/api", tags=["Multi-agent Systems"])
app.include_router(resource_router, prefix="/api", tags=["Resource Extraction"])



# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)
