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

from fastapi import Depends, HTTPException, status, WebSocket, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from core.configuration import load_environment
from core.database import get_user
from core import jwks

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


def create_access_token(
    email: str,
    scopes: List[str],
    *,
    user_id: Optional[int] = None,
    profile_id: Optional[int] = None,
    roles: Optional[List[str]] = None,
) -> str:
    """Mint a query_service access token.

    Claims are standardized to match usermanagement's v2 token shape
    (``sub``/``scopes``/``profile_id``/``roles``/``auth_source``) so the token
    is uniform across services. It is still signed with query_service's OWN
    secret — per-service token isolation is preserved; a token minted here is
    not accepted elsewhere. ``roles``/``profile_id`` are informational: query
    authorization re-reads roles from the DB (see core.rbac), so a stale claim
    cannot grant access.
    """
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=access_token_expire_minutes()
    )
    jwt_data = {"sub": email, "exp": expire, "scopes": scopes, "auth_source": "password"}
    if user_id is not None:
        jwt_data["user_id"] = user_id
    if profile_id is not None:
        jwt_data["profile_id"] = profile_id
    if roles is not None:
        jwt_data["roles"] = roles
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


def decode_token_any(token: str) -> dict:
    """Decode a bearer token from either scheme, newest first:

      1. Phase 2 SSO RS256 access token — verified against the issuer's JWKS
         and required to carry ``aud == this service`` (see core.jwks).
      2. Legacy HS256 query_service token — verified with this service's own
         secret (per-service isolation preserved).

    Returns the validated claims. Raises jose ``JWTError`` /
    ``ExpiredSignatureError`` if neither scheme validates, so existing callers'
    exception handling (401/403) keeps working unchanged.
    """
    payload = jwks.verify_access_token(token)
    if payload is not None:
        return payload
    # Fall back to the legacy HS256 token signed with our own secret.
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
):
    try:
        payload = decode_token_any(token)
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
    # An OAuth caller's credential row is a SHELL with is_active=False (they have
    # no usable password), so an active-only lookup 401s every Globus/ORCID/GitHub
    # user despite a perfectly valid token. The token records how it was issued, so
    # relax the filter only for those — on the password path is_active IS the
    # deactivation switch and must keep being enforced.
    user = await get_user(email=email,
                          include_inactive=payload.get("auth_source", "password") != "password")
    # get_user returns False (not None) when there is no active user row, so check
    # falsiness — otherwise `False` slips through as the "user" and downstream code
    # (_agent, role lookup) breaks, yielding a misleading 403 instead of a 401.
    if not user:
        raise credentials_exception
    return user


async def get_current_user_optional(request: Request):
    """
    Return the authenticated user if a valid Bearer token is present, else None.

    Unlike get_current_user this NEVER raises on a missing/invalid token — it is
    for endpoints that serve public resources anonymously but still want to know
    the caller's identity when a token is supplied (e.g. public-space reads).
    """
    auth = request.headers.get("authorization", "")
    if not auth[:7].lower() == "bearer ":
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        payload = decode_token_any(token)
        email = payload.get("sub")
        if not email:
            return None
        # get_user returns False when no active user row; normalize to None so
        # callers' truthiness/None checks behave (anonymous, not a bogus `False`).
        # include_inactive for OAuth callers, as in get_current_user — otherwise a
        # signed-in Globus user silently reads these endpoints as ANONYMOUS (e.g.
        # list_spaces returning an empty list instead of their own spaces), which
        # looks like "you have no data" rather than an auth failure.
        return (await get_user(
            email=email,
            include_inactive=payload.get("auth_source", "password") != "password",
        )) or None
    except (ExpiredSignatureError, JWTError, Exception):
        return None


def verify_scopes(required_scopes: List[str], token: str) -> bool:
    try:
        decoded_token = decode_token_any(token)
    except (ExpiredSignatureError, JWTError):
        raise HTTPException(status_code=403, detail="Could not validate credentials")
    token_scopes = decoded_token.get("scopes", [])
    return all(scope in token_scopes for scope in required_scopes)


security = HTTPBearer()


def require_scopes(required_scopes: List[str]):
    def scoped_endpoint(credentials: HTTPAuthorizationCredentials = Depends(security)):

        if not verify_scopes(required_scopes, credentials.credentials):
            raise HTTPException(status_code=403, detail="Insufficient scopes")

    return scoped_endpoint


def verify_user_access(user_id: str, current_user) -> None:
    """
    Ensure the ``user_id`` supplied in a request belongs to the authenticated user.

    Prevents Insecure Direct Object Reference (IDOR): endpoints take ``user_id`` as a
    free-form parameter, so without this check any authenticated user could read or
    recover another user's jobs simply by passing a different ``user_id``.

    Clients may identify a user by either the numeric id or the email, so a match on
    either is accepted. ``current_user`` is the record returned by ``get_current_user``.
    """
    identity = set()
    try:
        if current_user["id"] is not None:
            identity.add(str(current_user["id"]))
    except (KeyError, TypeError, IndexError):
        pass
    try:
        if current_user["email"] is not None:
            identity.add(str(current_user["email"]))
    except (KeyError, TypeError, IndexError):
        pass

    if str(user_id) not in identity:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access another user's resources.",
        )


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
        
        # Decode and validate JWT token (same logic as get_current_user):
        # RS256 SSO access token (aud-checked) first, then legacy HS256.
        try:
            payload = decode_token_any(token)
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
        
        # Get user from database (same as get_current_user, including the OAuth
        # shell allowance — a websocket caller is the same identity as an HTTP one).
        user = await get_user(email=email,
                              include_inactive=payload.get("auth_source", "password") != "password")
        # get_user returns False (not None) when no active user row — check falsiness.
        if not user:
            logger.warning(f"User not found for email: {email}")
            return None

        return user
        
    except Exception as e:
        logger.error(f"WebSocket authentication error: {str(e)}", exc_info=True)
        return None
