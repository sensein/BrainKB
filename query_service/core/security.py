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
import asyncio
from typing import Annotated, List, Optional, Dict

from fastapi import Depends, HTTPException, status, WebSocket
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


async def get_password_hash(password: str) -> str:
    """Hash password asynchronously to avoid blocking the event loop."""
    return await asyncio.to_thread(pwd_context.hash, password)


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password asynchronously to avoid blocking the event loop."""
    return await asyncio.to_thread(pwd_context.verify, plain_password, hashed_password)


async def authenticate_user(email, password, conn):
    logger.debug("Authenticating user", extra={"email": email})
    user = await get_user(conn=conn, email=email)
    if not user:
        raise credentials_exception
    if not await verify_password(password, user["password"]):
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


async def authenticate_websocket(websocket: WebSocket, required_scopes: Optional[List[str]] = None) -> Optional[Dict]:
    """
    Authenticate WebSocket connection using JWT token from Authorization header.
    Matches the exact implementation of HTTP authentication (get_current_user + require_scopes).
    
    Args:
        websocket: WebSocket connection object
        required_scopes: List of required scopes (e.g., ["write"]). If None, scope check is skipped.
    
    Returns:
        User dict if authenticated and authorized, None otherwise.
    """
    try:
        # Extract token from Authorization header (same as HTTP - OAuth2PasswordBearer/HTTPBearer)
        # Priority: Authorization header (matching HTTP implementation)
        auth_header = websocket.headers.get("authorization", "")
        token = None
        
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif auth_header.startswith("bearer "):
            token = auth_header[7:]
        
        # Fallback to query parameter if not in header (WebSocket-specific convenience)
        if not token:
            token = websocket.query_params.get("token")
        
        if not token:
            logger.warning("No JWT token provided in WebSocket connection")
            return None
        
        # Decode and validate JWT token (same logic as get_current_user)
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except ExpiredSignatureError:
            logger.warning("JWT token has expired")
            return None
        except JWTError as e:
            logger.warning(f"JWT token validation failed: {str(e)}")
            return None
        
        # Verify email (sub claim) - same as get_current_user
        email = payload.get("sub")
        if email is None:
            logger.warning("JWT token missing 'sub' claim")
            return None
        
        # Verify scopes if required (same logic as require_scopes)
        if required_scopes:
            token_scopes = payload.get("scopes", [])
            if not all(scope in token_scopes for scope in required_scopes):
                logger.warning(f"Insufficient scopes. Required: {required_scopes}, Token has: {token_scopes}")
                return None
        
        # Get user from database (same as get_current_user)
        user = await get_user(email=email)
        if user is None:
            logger.warning(f"User not found for email: {email}")
            return None
        
        return user
        
    except Exception as e:
        logger.error(f"WebSocket authentication error: {str(e)}", exc_info=True)
        return None
