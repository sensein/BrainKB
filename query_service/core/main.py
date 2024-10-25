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
from core.configuration import load_environment

from fastapi.middleware.cors import CORSMiddleware

environment = load_environment()["ENV_STATE"]
origins = [
    "https://beta.brainkb.org",
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


app.include_router(index_router)
app.include_router(jwt_router)
app.include_router(query_router)

# rapid-release
app.include_router(rapid_release, prefix="/api/rapid-release", tags=["Rapid release"])


@app.on_event("startup")
async def startup_event():
    configure_logging()
    logger.info("Starting FastAPI")


# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)
