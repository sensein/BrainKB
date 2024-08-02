from typing import Annotated

from fastapi import APIRouter, Depends

from brain2kg.api.models.user import LoginUserIn
from brain2kg.api.security import get_current_user, require_scopes

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Welcome to Brain2KG!"}


@router.get("/token-check", dependencies=[Depends(require_scopes(["read"]))])
async def token_check(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    return {"message": "token check passed success"}