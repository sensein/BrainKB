import logging

from fastapi import APIRouter, HTTPException, status, Request

from core.database import user_db_manager, jwt_user_repo, user_profile_repo, user_role_repo
from core.models.user import LoginUserIn
from core.security import authenticate_user, create_access_token_v2

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/token")
async def login(user: LoginUserIn, request: Request):
    async with user_db_manager.get_async_session() as session:
        # Authenticate user
        user_record = await authenticate_user(user.email, user.password, session)
        if not user_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get JWT user scopes from database
        scopes = await jwt_user_repo.get_user_scopes(session, user_record.id)
        if not scopes:
            scopes = ["read"]  # Default scope if no scopes found

        # Attach profile-level roles if a profile exists for this email.
        profile = await user_profile_repo.get_by_email(session, user_record.email)
        profile_id = profile.id if profile else None
        role_names = await user_role_repo.get_user_role_names(session, profile.id) if profile else []

        access_token = create_access_token_v2(
            email=user_record.email,
            jwt_user_id=user_record.id,
            profile_id=profile_id,
            roles=role_names,
            scopes=scopes,
            auth_source="password",
        )

        return {"access_token": access_token, "token_type": "bearer"}


