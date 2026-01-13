import logging

from fastapi import APIRouter, HTTPException, status, Depends

from core.database import get_db_connection, insert_data, get_scopes_by_user
from core.models.user import UserIn, LoginUserIn
from core.security import get_password_hash, authenticate_user, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", status_code=201)
async def register(user: UserIn):
    """
    Register a new user. Uses proper connection management to avoid connection leaks.
    
    Note: The unique constraint check is handled atomically by the database.
    This prevents race conditions where two concurrent requests could both pass
    a pre-check and then both attempt to insert the same email.
    """
    async with get_db_connection() as conn:
        hashed_password = await get_password_hash(user.password)
        
        # Let the database enforce uniqueness atomically - no pre-check needed
        # insert_data will catch UniqueViolationError and return a user-friendly message
        return await insert_data(
            conn=conn, fullname=user.full_name, email=user.email, password=hashed_password
        )


@router.post("/token")
async def login(user: LoginUserIn):
    """
    Authenticate user and return JWT token. Uses proper connection management to avoid connection leaks.
    Reuses the same database connection for both authentication and scope retrieval to minimize connection pool usage.
    """
    async with get_db_connection() as conn:
        authenticated_user = await authenticate_user(user.email, user.password, conn)
        scopes = await get_scopes_by_user(user_id=authenticated_user["id"], conn=conn)
        access_token = create_access_token(authenticated_user["email"], scopes)
        return {"access_token": access_token, "token_type": "bearer"}
