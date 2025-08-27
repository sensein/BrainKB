import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends, Request

from core.database import user_db_manager, jwt_user_repo
from core.models.user import UserIn, LoginUserIn, ActivityType
from core.security import get_password_hash, authenticate_user, create_access_token_with_user_id, verify_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", status_code=201)
async def register(user: UserIn):
    async with user_db_manager.get_async_session() as session:
        # Check if JWT user already exists
        existing_jwt_user = await jwt_user_repo.get_by_email(session, user.email)
        if existing_jwt_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with that email already exists",
            )

        hashed_password = get_password_hash(user.password)
        
        # Create JWT user
        try:
            new_jwt_user = await jwt_user_repo.create_user(
                session=session,
                full_name=user.full_name,
                email=user.email,
                password=hashed_password
            )
            
            return {
                "detail": "Registration completed successfully! Admin will activate your account after verification."
            }
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            # Check if it's a duplicate email error
            if "duplicate key value violates unique constraint" in str(e) and "email" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A user with that email already exists",
                )
            else:
                raise HTTPException(status_code=400, detail="Registration failed. Please try again.")


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

        access_token = create_access_token_with_user_id(user_record.email, scopes, user_record.id)

        
        return {"access_token": access_token, "token_type": "bearer"}


