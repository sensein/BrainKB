import logging

from fastapi import APIRouter, HTTPException, status, Depends

from core.database import get_db_connection, insert_data, get_scopes_by_user
from core.models.user import UserIn, LoginUserIn
from core.security import get_password_hash, authenticate_user, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", include_in_schema=False)
async def register(user: UserIn):
    """Self-registration is DISABLED — no separate register step. Users onboard by
    signing in with Globus / ORCID / GitHub (profile auto-created on first login)."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail=("Self-registration is disabled. Sign in with Globus / ORCID / GitHub "
                "— your account is created automatically on first login."),
    )


@router.post("/login")
@router.post("/token", include_in_schema=False)  # deprecated alias of /login
async def login(user: LoginUserIn):
    """
    Authenticate (password) and return a JWT. Primary path is `/api/login`;
    `/api/token` is a deprecated alias.
    """
    async with get_db_connection() as conn:
        authenticated_user = await authenticate_user(user.email, user.password, conn)
        scopes = await get_scopes_by_user(user_id=authenticated_user["id"], conn=conn)
        access_token = create_access_token(authenticated_user["email"], scopes)
        return {"access_token": access_token, "token_type": "bearer"}
