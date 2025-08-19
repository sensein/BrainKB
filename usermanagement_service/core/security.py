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

import logging
from datetime import datetime, timedelta
from typing import Optional, Union, Any, Annotated
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.configuration import config
from core.database import user_repo
from core.models.user import LoginUserIn

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = config.jwt_secret_key
ALGORITHM = config.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


async def authenticate_user(email: str, password: str, session: AsyncSession) -> Optional[Any]:
    """Authenticate a user by email and password"""
    try:
        # Get user by email
        user = await user_repo.get_by_email(session, email)
        if not user:
            return None
        
        # Verify password
        if not verify_password(password, user.password):
            return None
        
        return user
    except Exception as e:
        logger.error(f"Error authenticating user {email}: {str(e)}")
        return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_access_token_with_user_id(email: str, scopes: list, user_id: int) -> str:
    """Create a JWT access token with user ID"""
    to_encode = {
        "sub": email,
        "scopes": scopes,
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Union[dict, None]:
    """Verify and decode a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.error(f"JWT token verification failed: {str(e)}")
        return None


def get_current_user(token: str) -> Optional[dict]:
    """Get current user from token"""
    payload = verify_token(token)
    if payload is None:
        return None
    
    email: str = payload.get("sub")
    if email is None:
        return None
    
    return {"email": email, "user_id": payload.get("user_id")}


def get_user_scopes(token: str) -> list:
    """Get user scopes from token"""
    payload = verify_token(token)
    if payload is None:
        return []
    
    return payload.get("scopes", [])


def has_scope(token: str, required_scope: str) -> bool:
    """Check if user has required scope"""
    scopes = get_user_scopes(token)
    return required_scope in scopes


def has_any_scope(token: str, required_scopes: list) -> bool:
    """Check if user has any of the required scopes"""
    user_scopes = get_user_scopes(token)
    return any(scope in user_scopes for scope in required_scopes)


def has_all_scopes(token: str, required_scopes: list) -> bool:
    """Check if user has all required scopes"""
    user_scopes = get_user_scopes(token)
    return all(scope in user_scopes for scope in required_scopes)


# FastAPI Security and Dependencies
security = HTTPBearer()


def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]) -> dict:
    """Get current user from JWT token - FastAPI dependency"""
    token = credentials.credentials
    user_data = get_current_user_from_token(token)
    
    if user_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user_data


def get_current_user_from_token(token: str) -> Optional[dict]:
    """Get current user from token string"""
    payload = verify_token(token)
    if payload is None:
        return None
    
    email: str = payload.get("sub")
    if email is None:
        return None
    
    return {"email": email, "user_id": payload.get("user_id"), "scopes": payload.get("scopes", [])}


def require_scopes(required_scopes: list):
    """Dependency to require specific scopes"""
    def scope_checker(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
        user_scopes = current_user.get("scopes", [])
        
        # Check if user has any of the required scopes
        if not any(scope in user_scopes for scope in required_scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        
        return current_user
    
    return scope_checker


def require_all_scopes(required_scopes: list):
    """Dependency to require all specific scopes"""
    def scope_checker(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
        user_scopes = current_user.get("scopes", [])
        
        # Check if user has all required scopes
        if not all(scope in user_scopes for scope in required_scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        
        return current_user
    
    return scope_checker
