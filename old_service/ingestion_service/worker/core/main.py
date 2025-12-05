import logging

# logging
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
import asyncio
from core.rabbit_mq_listener import start_consuming
from core.configure_logging import configure_logging
from core.routers.worker import router as index_router
import logging

logger = logging.getLogger(__name__)

async def background_task():
    logger.info("#### waiting for messages... ####")
    loop = asyncio.get_event_loop()
    # This will run start_consuming in a separate thread
    await loop.run_in_executor(None, start_consuming)

app = FastAPI()
app.add_middleware(CorrelationIdMiddleware)


app.include_router(index_router)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_task())
    configure_logging()
    logger.info("#### Starting FastAPI... ####")


# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)
