import logging
from contextlib import asynccontextmanager
from datetime import datetime

# logging
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from core.configure_logging import configure_logging
from core.routers.index import router as index_router
from core.routers.jwt_auth import router as jwt_router
from core.routers.user_management import router as user_management_router
from core.database import user_db_manager, user_activity_repo
from core.models.user import ActivityType
from core.security import verify_token
from fastapi.middleware.cors import CORSMiddleware


class ActivityLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically log user activities"""
    
    async def dispatch(self, request: Request, call_next):
        # Get response
        response = await call_next(request)
        
        # Only log activities for profile-related endpoints (not JWT auth endpoints)
        if request.url.path.startswith("/api/users") and request.method != "GET" and not request.url.path.startswith("/api/token"):
            try:
                # Extract token from Authorization header
                auth_header = request.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header.split(" ")[1]
                    payload = verify_token(token)
                    user_id = payload.get("user_id")
                    
                    if user_id:
                        # Determine activity type based on endpoint and method
                        activity_type = self._determine_activity_type(request)
                        description = self._generate_description(request)
                        
                        # Log activity asynchronously (don't wait for it)
                        try:
                            async with user_db_manager.get_async_session() as session:
                                await user_activity_repo.log_activity(
                                    session=session,
                                    user_id=user_id,
                                    activity_type=activity_type,
                                    description=description,
                                    ip_address=request.client.host,
                                    user_agent=request.headers.get("user-agent")
                                )
                        except Exception as e:
                            logger.error(f"Failed to log activity: {str(e)}")
                            
            except Exception as e:
                logger.error(f"Error in activity logging middleware: {str(e)}")
        
        return response
    
    def _determine_activity_type(self, request: Request) -> ActivityType:
        """Determine activity type based on request"""
        path = request.url.path
        method = request.method
        
        if "/profile" in path:
            return ActivityType.PROFILE_UPDATE
        elif "/contributions" in path:
            if method == "POST":
                return ActivityType.CONTENT_SUBMISSION
            elif method == "PUT":
                return ActivityType.CONTENT_REVIEW
        elif "/roles" in path:
            return ActivityType.CONTENT_CURATION
        elif "/activities/log" in path:
            return ActivityType.LOGIN  # This will be overridden by the actual activity
        
        return ActivityType.LOGIN  # Default
    
    def _generate_description(self, request: Request) -> str:
        """Generate description for the activity"""
        path = request.url.path
        method = request.method
        
        if "/profile" in path:
            return f"{method} profile"
        elif "/contributions" in path:
            return f"{method} contribution"
        elif "/roles" in path:
            return f"{method} role assignment"
        
        return f"{method} {path}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging()
    logger.info("Starting FastAPI")
    
    # Initialize user database with ORM
    try:
        user_db_manager.init_sync_engine()
        user_db_manager.create_user_tables()
        logger.info("User database tables created/verified successfully")
    except Exception as e:
        logger.error(f"User database initialization failed: {str(e)}")
        raise
    
    yield
    # Shutdown
    logger.info("Shutting down FastAPI")


app = FastAPI(lifespan=lifespan)
logger = logging.getLogger(__name__)

origins = [
    "https://beta.brainkb.org",
    "https://sandbox.brainkb.org",
    "localhost:3000",
    "http://localhost:3000",
    "http://127.0.0.1:300",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(ActivityLoggingMiddleware)


app.include_router(index_router)
app.include_router(jwt_router, prefix="/api", tags=["Security Endpoints"])
app.include_router(user_management_router, prefix="/api", tags=["User Management"])


# log all HTTP exception when raised
@app.exception_handler(HTTPException)
async def http_exception_handler_logging(request, exc):
    logger.error(f"HTTP Exception raised: {exc.status_code} {exc.detail}")
    return await http_exception_handler(request, exc)
