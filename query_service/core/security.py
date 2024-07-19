# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : security.py
# @Software: PyCharm

import datetime
import logging
from typing import Annotated, List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from core.configuration import load_environment
from core.database import get_user

logger = logging.getLogger(__name__)

SECRET_KEY = load_environment()["JWT_SECRET_KEY"]
ALGORITHM = load_environment()["JWT_ALGORITHM"]
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"])

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def access_token_expire_minutes() -> int:
    return 30


def create_access_token(email: str, scopes: List[str]) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=access_token_expire_minutes()
    )
    jwt_data = {"sub": email, "exp": expire, "scopes": scopes}
    encoded_jwt = jwt.encode(jwt_data, key=SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


async def authenticate_user(email, password, conn):
    logger.debug("Authenticating user", extra={"email": email})
    user = await get_user(conn=conn, email=email)
    if not user:
        raise credentials_exception
    if not verify_password(password, user["password"]):
        raise credentials_exception
    return user


def decode_jwt(token: str):
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded_token
    except JWTError:
        raise HTTPException(status_code=403, detail="Could not validate credentials")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
):
    try:
        payload = decode_jwt(token)
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
    except ExpiredSignatureError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except JWTError as e:
        raise credentials_exception from e
    user = await get_user(email=email)
    if user is None:
        raise credentials_exception
    return user


def verify_scopes(required_scopes: List[str], token: str) -> bool:
    decoded_token = decode_jwt(token)
    token_scopes = decoded_token.get("scopes", [])
    return all(scope in token_scopes for scope in required_scopes)


security = HTTPBearer()


def require_scopes(required_scopes: List[str]):
    def scoped_endpoint(credentials: HTTPAuthorizationCredentials = Depends(security)):

        if not verify_scopes(required_scopes, credentials.credentials):
            raise HTTPException(status_code=403, detail="Insufficient scopes")

    return scoped_endpoint
