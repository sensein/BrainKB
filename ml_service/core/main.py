import logging

# logging
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException

from core.configure_logging import configure_logging
from core.routers.index import router as index_router
from core.routers.jwt_auth import router as jwt_router


app = FastAPI()
logger = logging.getLogger(__name__)
app.add_middleware(CorrelationIdMiddleware)


app.include_router(index_router, prefix="/api")
app.include_router(jwt_router, prefix="/api", tags=["Security"])

@app.on_event("startup")
async def startup_event():
    configure_logging()
    logger.info("Starting FastAPI")


# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)
