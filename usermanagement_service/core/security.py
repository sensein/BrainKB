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
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Union, Any, Annotated, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from cryptography.fernet import Fernet, InvalidToken

from core.configuration import config
from core.database import jwt_user_repo
from core.models.user import LoginUserIn, UserRoleEnum

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = config.jwt_secret_key  # Uses USERMANAGEMENT_SERVICE_JWT_SECRET_KEY
ALGORITHM = config.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


async def authenticate_user(email: str, password: str, session: AsyncSession) -> Optional[Any]:
    """Authenticate a JWT user by email and password"""
    try:
        # Get JWT user by email
        jwt_user = await jwt_user_repo.get_by_email(session, email)
        if not jwt_user:
            return None
        
        # Verify password
        if not verify_password(password, jwt_user.password):
            return None
        
        return jwt_user
    except Exception as e:
        logger.error(f"Error authenticating JWT user {email}: {str(e)}")
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
    """Create a JWT access token with user ID (legacy - no profile context)."""
    to_encode = {
        "sub": email,
        "scopes": scopes,
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_access_token_v2(
    *,
    email: str,
    jwt_user_id: Optional[int],
    profile_id: Optional[int],
    roles: List[str],
    scopes: List[str],
    auth_source: str = "password",
) -> str:
    """Create a JWT carrying both JWT-level scopes and profile-level roles.
    auth_source: 'password' | 'github' | 'orcid' | 'globus'."""
    to_encode = {
        "sub": email,
        "scopes": scopes,
        "user_id": jwt_user_id,
        "profile_id": profile_id,
        "roles": roles,
        "auth_source": auth_source,
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ---- Fernet helpers for encrypting OAuth tokens at rest ----

_fernet_instance: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Lazy Fernet loader. Derives a 32-byte key from the configured secret if it
    isn't a valid Fernet key, so small configs don't fail hard. In prod, set a
    proper key via USERMANAGEMENT_OAUTH_TOKEN_ENC_KEY."""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    raw = config.oauth_token_enc_key
    if not raw:
        # Fall back to JWT secret so things boot; warn loudly.
        logger.warning("USERMANAGEMENT_OAUTH_TOKEN_ENC_KEY is not set; deriving a key from JWT secret. Set it in production.")
        raw = SECRET_KEY or "change-me-unsafe-default"

    try:
        # Try to use as-is if it's already a valid Fernet key.
        _fernet_instance = Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception:
        # Derive a 32-byte urlsafe key from the input.
        digest = hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).digest()
        _fernet_instance = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet_instance


def encrypt_token(plain: Optional[str]) -> Optional[str]:
    if plain is None:
        return None
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_token(ciphertext: Optional[str]) -> Optional[str]:
    if ciphertext is None:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt OAuth token (InvalidToken)")
        return None


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
    """Get current user from token string. Returns claims including profile_id and roles (new fields)
    alongside the legacy scopes/user_id fields."""
    payload = verify_token(token)
    if payload is None:
        return None

    email: str = payload.get("sub")
    if email is None:
        return None

    return {
        "email": email,
        "user_id": payload.get("user_id"),
        "profile_id": payload.get("profile_id"),
        "scopes": payload.get("scopes", []),
        "roles": payload.get("roles", []),
        "auth_source": payload.get("auth_source", "password"),
    }


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


# Optional credentials — won't 401 if absent. Used by endpoints that work for
# both authed and unauthed users (e.g. page access checks for public pages).
_optional_security = HTTPBearer(auto_error=False)


def get_current_user_optional(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_optional_security)],
) -> Optional[dict]:
    if credentials is None:
        return None
    return get_current_user_from_token(credentials.credentials)


def require_admin(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """Dependency: caller must have the Admin role (profile-level role).
    Checks JWT 'roles' claim for 'Admin' or the bootstrap admin emails from config.
    The bootstrap list is a fallback for the very first admin, before any role
    is assigned in the DB."""
    email = (current_user.get("email") or "").lower()
    roles = current_user.get("roles", []) or []

    if UserRoleEnum.ADMIN.value in roles:
        return current_user

    if email and email in config.bootstrap_admin_emails:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin role required",
    )
