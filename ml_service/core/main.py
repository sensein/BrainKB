import logging

# logging
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException

from core.configure_logging import configure_logging
from core.routers.index import router as index_router
from core.routers.jwt_auth import router as jwt_router
from core.routers.structsense import router as structsense_router

app = FastAPI()
logger = logging.getLogger(__name__)
app.add_middleware(CorrelationIdMiddleware)


app.include_router(index_router, prefix="/api")
app.include_router(jwt_router, prefix="/api", tags=["Security"])
app.include_router(structsense_router, prefix="/api", tags=["Multi-agent Systems"])

@app.on_event("startup")
async def startup_event():
    configure_logging()
    logger.info("Starting FastAPI")
    # Initialize database connection pool
    from core.database import init_db_pool
    await init_db_pool()
    logger.info("Database connection pool initialized")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down FastAPI")
    # Close database connection pool
    from core.database import get_db_pool
    pool = await get_db_pool()
    if pool:
        await pool.close()
        logger.info("Database connection pool closed")


# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)
