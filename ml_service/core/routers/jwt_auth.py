import logging

from fastapi import APIRouter, HTTPException, status, Depends

from core.database import get_db_connection, get_user, insert_data, get_scopes_by_user
from core.models.user import UserIn, LoginUserIn
from core.security import get_password_hash, authenticate_user, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", status_code=201)
async def register(user: UserIn):
    """
    Register a new user. Uses proper connection management to avoid connection leaks.
    """
    async with get_db_connection() as conn:
        if await get_user(conn=conn, email=user.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with that email already exists",
            )
        hashed_password = await get_password_hash(user.password)

        return await insert_data(
            conn=conn, fullname=user.full_name, email=user.email, password=hashed_password
        )


@router.post("/token")
async def login(user: LoginUserIn):
    """
    Authenticate user and return JWT token. Uses proper connection management to avoid connection leaks.
    """
    async with get_db_connection() as conn:
        authenticated_user = await authenticate_user(user.email, user.password, conn)
        scopes = await get_scopes_by_user(user_id=authenticated_user["id"])
        access_token = create_access_token(authenticated_user["email"], scopes)
        return {"access_token": access_token, "token_type": "bearer"}
