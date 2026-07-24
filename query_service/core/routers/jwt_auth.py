import logging

from fastapi import APIRouter, HTTPException, status, Depends

from core.database import get_db_connection, insert_data, get_scopes_by_user
from core.models.user import UserIn, LoginUserIn
from core.security import get_password_hash, authenticate_user, create_access_token
from core import rbac

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", include_in_schema=False)
async def register(user: UserIn):
    """Self-registration is DISABLED — there is no separate register step.
    Users are onboarded by signing in with Globus / ORCID / GitHub
    (usermanagement `/api/auth/{provider}/login`, or `brainkb_globus_login` in the
    skill), which auto-creates and links the profile on first login."""
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
    `/api/token` is kept as a deprecated alias for backward compatibility.
    """
    async with get_db_connection() as conn:
        authenticated_user = await authenticate_user(user.email, user.password, conn)
        scopes = await get_scopes_by_user(user_id=authenticated_user["id"], conn=conn)
        # Enrich the token with profile_id + roles so its shape matches
        # usermanagement's v2 token. Signed with query_service's own secret
        # (per-service isolation preserved); roles remain informational since
        # authorization re-reads them from the DB (core.rbac).
        email = authenticated_user["email"]
        profile_id = await conn.fetchval(
            'SELECT id FROM "Web_user_profile" WHERE lower(email) = lower($1)', email
        )
        roles = sorted(await rbac.active_roles(email))
        access_token = create_access_token(
            email, scopes,
            user_id=authenticated_user["id"], profile_id=profile_id, roles=roles,
        )
        return {"access_token": access_token, "token_type": "bearer"}
