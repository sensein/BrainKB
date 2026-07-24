# -*- coding: utf-8 -*-
"""Phase 2 SSO endpoints (RS256 single-issuer + JWKS).

  GET  /.well-known/jwks.json   public keys for token verification
  POST /api/auth/login          {email,password} -> refresh token (aud=brainkb-auth)
  POST /api/auth/exchange       Bearer <refresh>, {audience} -> per-service access token

usermanagement is the sole issuer. Clients log in once (refresh token), then
exchange for narrow, short-lived access tokens scoped to a single service via
the `aud` claim. Roles/scopes are re-read fresh from the DB at exchange time, so
a stale refresh token cannot carry stale authorization into a service.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from core import tokens_rs256
from core.configuration import config
from core.database import (
    user_db_manager, jwt_user_repo, user_profile_repo, user_role_repo,
)
from core.models.user import LoginUserIn
from core.security import authenticate_user

logger = logging.getLogger(__name__)

# Auth endpoints (mounted at /api). JWKS is mounted separately at the root.
router = APIRouter()
wellknown_router = APIRouter()

_bearer = HTTPBearer(auto_error=True)


class ExchangeIn(BaseModel):
    audience: str


@wellknown_router.get("/.well-known/jwks.json", tags=["SSO"])
async def jwks():
    """Public JWK Set. Services fetch and cache this to verify RS256 tokens."""
    return tokens_rs256.jwks()


@router.post("/auth/login", tags=["SSO"])
async def sso_login(body: LoginUserIn):
    """Authenticate with email/password and receive a refresh token. The refresh
    token is not accepted by any service — exchange it at /api/auth/exchange."""
    async with user_db_manager.get_async_session() as session:
        user_record = await authenticate_user(body.email, body.password, session)
        if not user_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scopes = await jwt_user_repo.get_user_scopes(session, user_record.id) or ["read"]
        profile = await user_profile_repo.get_by_email(session, user_record.email)
        profile_id = profile.id if profile else None
        roles = await user_role_repo.get_user_role_names(session, profile.id) if profile else []

    refresh = tokens_rs256.create_refresh_token(
        email=user_record.email,
        profile_id=profile_id,
        roles=roles,
        scopes=scopes,
        auth_source="password",
    )
    return {
        "refresh_token": refresh,
        "token_type": "refresh",
        "expires_in": tokens_rs256.refresh_token_ttl_seconds(),
        "audiences": config.token_audiences,
    }


@router.post("/auth/exchange", tags=["SSO"])
async def sso_exchange(
    body: ExchangeIn,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
):
    """Exchange a refresh token for a short-lived access token scoped to one
    service (`audience`). Roles/scopes are re-read fresh from the DB here."""
    try:
        payload = tokens_rs256.verify_refresh_token(creds.credentials)
    except Exception as e:
        logger.info(f"Refresh token rejected: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if body.audience not in config.token_audiences:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown audience '{body.audience}'. Allowed: {config.token_audiences}",
        )

    email = payload.get("sub")
    async with user_db_manager.get_async_session() as session:
        # active-only lookup: a deactivated credential can no longer exchange.
        jwt_user = await jwt_user_repo.get_by_email(session, email)
        if not jwt_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account inactive")
        scopes = await jwt_user_repo.get_user_scopes(session, jwt_user.id) or ["read"]
        profile = await user_profile_repo.get_by_email(session, email)
        if profile and getattr(profile, "is_banned", False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_suspended")
        profile_id = profile.id if profile else None
        roles = await user_role_repo.get_user_role_names(session, profile.id) if profile else []

    access = tokens_rs256.create_access_token(
        audience=body.audience,
        email=email,
        profile_id=profile_id,
        roles=roles,
        scopes=scopes,
        auth_source=payload.get("auth_source", "password"),
    )
    return {
        "access_token": access,
        "token_type": "bearer",
        "aud": body.audience,
        "expires_in": tokens_rs256.access_token_ttl_seconds(),
    }
