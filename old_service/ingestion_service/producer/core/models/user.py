from typing import Optional

from pydantic import BaseModel


class JWTUser(BaseModel):

    id: Optional[int] = None
    full_name: str
    email: str


class UserIn(JWTUser):
    password: str


class LoginUserIn(BaseModel):
    email: str
    password: str
