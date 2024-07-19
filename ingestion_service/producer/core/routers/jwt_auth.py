import logging

from fastapi import APIRouter, HTTPException, status, Depends

from core.database import connect_postgres, get_user, insert_data, get_scopes_by_user
from core.models.user import UserIn, LoginUserIn
from core.security import get_password_hash, authenticate_user, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", status_code=201)
async def register(user: UserIn, conn=Depends(connect_postgres)):

    if await get_user(conn=conn, email=user.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with that email already exists",
        )
    hashed_password = get_password_hash(user.password)

    return await insert_data(
        conn=conn, fullname=user.full_name, email=user.email, password=hashed_password
    )


@router.post("/token")
async def login(user: LoginUserIn, conn=Depends(connect_postgres)):
    user = await authenticate_user(user.email, user.password, conn)
    scopes = await get_scopes_by_user(user_id=user["id"])
    access_token = create_access_token(user["email"], scopes)
    return {"access_token": access_token, "token_type": "bearer"}
