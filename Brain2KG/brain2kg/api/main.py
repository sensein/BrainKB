import logging

from contextlib import asynccontextmanager
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException

from brain2kg.api.configure_logging import configure_logging
from brain2kg.api.routers.eda import router as eda_router
from brain2kg.api.routers.index import router as index_router
from brain2kg.api.routers.jwt_auth import router as jwt_router

app = FastAPI()
logger = logging.getLogger(__name__)
app.add_middleware(CorrelationIdMiddleware)


app.include_router(index_router)
app.include_router(jwt_router)
app.include_router(eda_router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Starting FastAPI")


# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)