# -*- coding: utf-8 -*-
"""Personal Access Tokens (PATs) — browser-free auth for the CLI / MCP skills.

A PAT is an opaque, long-lived, revocable credential. The user mints one **once**
(needing a normal login only at that moment), pastes it into their MCP/skill
config (``BRAINKB_TOKEN``), and from then on every call authenticates with the
PAT — no browser, no password, no paste-code.

  POST   /api/auth/tokens          (authenticated)  mint a PAT — plaintext shown ONCE
  GET    /api/auth/tokens          (authenticated)  list the caller's PATs (metadata only)
  DELETE /api/auth/tokens/{id}     (authenticated)  revoke one of the caller's PATs
  POST   /api/auth/pat/exchange    (PAT in body)    PAT -> short-lived per-service access token

Design notes
------------
* The token is opaque (``brainkb_pat_<random>``) — NOT a JWT and NOT RSA-signed —
  so nothing key-related is exposed to the user. Only its SHA-256 hash is stored.
* Validation is a DB lookup (hash match, not revoked, not expired, user not
  banned). That makes a PAT **instantly revocable**, unlike a signed token that
  lives until it expires.
* On exchange we re-read the user's roles from the DB and derive scopes, then
  mint the same RS256 per-service access token the refresh-token flow issues —
  so downstream services need **no changes** and containment (per-``aud`` tokens)
  is preserved.
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core import tokens_rs256
from core.configuration import config
from core.database import (
    user_db_manager, personal_access_token_repo, user_profile_repo,
    user_role_repo, jwt_user_repo,
)
from core.routers.sso import _scopes_for_roles
from core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

_PAT_PREFIX = "brainkb_pat_"
# Default lifetime and hard cap for a PAT, in days (configurable via env).
_PAT_DEFAULT_DAYS = max(1, int(os.getenv("USERMANAGEMENT_PAT_DEFAULT_DAYS", "3")))
_PAT_MAX_DAYS = max(1, int(os.getenv("USERMANAGEMENT_PAT_MAX_DAYS", "365")))
# Sliding expiry: when true (default), each successful use pushes the PAT's expiry
# forward by _PAT_DEFAULT_DAYS (the idle window) — so an actively-used token keeps
# working and never re-prompts, while an unused one expires after that many idle
# days. The extension is capped at created_at + _PAT_MAX_DAYS (an absolute ceiling,
# so a token can't roll forever). Set false for fixed-lifetime tokens.
_PAT_SLIDING = os.getenv("USERMANAGEMENT_PAT_SLIDING", "true").strip().lower() not in ("0", "false", "no")
# Upper bound on how many active (unrevoked, unexpired) tokens a user may hold —
# a light guard against unbounded token sprawl.
_PAT_MAX_PER_USER = max(1, int(os.getenv("USERMANAGEMENT_PAT_MAX_PER_USER", "20")))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _gen_token() -> str:
    """Mint a fresh opaque PAT: ``brainkb_pat_`` + 43 urlsafe chars (~256 bits)."""
    return _PAT_PREFIX + secrets.token_urlsafe(32)


class CreateTokenIn(BaseModel):
    name: str = Field("", max_length=120,
                      description="Human label so you can tell tokens apart, e.g. 'laptop'.")
    days: int = Field(_PAT_DEFAULT_DAYS, ge=1, le=_PAT_MAX_DAYS,
                      description=f"Lifetime in days (1..{_PAT_MAX_DAYS}).")


class PatExchangeIn(BaseModel):
    token: str
    audience: str


@router.post("/auth/tokens", tags=["PAT"])
async def create_token(body: CreateTokenIn, current_user: dict = Depends(get_current_user)):
    """Mint a Personal Access Token for the logged-in user. The plaintext token is
    returned **once** — it is never stored (only a hash) and cannot be retrieved
    again. Paste it into your MCP/skill config as ``BRAINKB_TOKEN``."""
    email = current_user.get("email") or current_user.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no identity in token")

    days = min(max(1, int(body.days or _PAT_DEFAULT_DAYS)), _PAT_MAX_DAYS)
    token = _gen_token()
    token_hash = _hash(token)
    # Non-secret display fragment: prefix + first 4 chars of the random part.
    display_prefix = token[: len(_PAT_PREFIX) + 4]
    expires_at = datetime.utcnow() + timedelta(days=days)

    async with user_db_manager.get_async_session() as session:
        profile = await user_profile_repo.get_by_email(session, email)
        profile_id = profile.id if profile else current_user.get("profile_id")
        if profile and getattr(profile, "is_banned", False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_suspended")
        jwt_user = await jwt_user_repo.get_by_email_any_status(session, email)
        jwt_user_id = jwt_user.id if jwt_user else current_user.get("user_id")

        if profile_id is not None:
            existing = await personal_access_token_repo.list_for_profile(session, profile_id)
            active = [t for t in existing if not t.revoked and t.expires_at >= datetime.utcnow()]
            if len(active) >= _PAT_MAX_PER_USER:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(f"You already have {len(active)} active tokens "
                            f"(max {_PAT_MAX_PER_USER}). Revoke one first."),
                )

        row = await personal_access_token_repo.create(
            session, token_hash=token_hash, prefix=display_prefix, name=body.name,
            profile_id=profile_id, jwt_user_id=jwt_user_id, email=email, expires_at=expires_at,
        )
        # Capture values before commit (attributes expire afterward → MissingGreenlet).
        pat_id = row.id
        created_prefix = row.prefix
        await session.commit()

    return {
        "id": pat_id,
        "token": token,               # shown ONCE — never returned again
        "prefix": created_prefix,
        "name": body.name,
        "expires_at": expires_at.isoformat() + "Z",
        "expires_in_days": days,
        "note": ("Copy this token now — it will not be shown again. Set it as "
                 "BRAINKB_TOKEN in your MCP/skill config."),
    }


@router.get("/auth/tokens", tags=["PAT"])
async def list_tokens(current_user: dict = Depends(get_current_user)):
    """List the caller's PATs (metadata only — the secret is never returned)."""
    email = current_user.get("email") or current_user.get("sub")
    async with user_db_manager.get_async_session() as session:
        profile = await user_profile_repo.get_by_email(session, email)
        profile_id = profile.id if profile else current_user.get("profile_id")
        if profile_id is None:
            return {"tokens": []}
        rows = await personal_access_token_repo.list_for_profile(session, profile_id)
        now = datetime.utcnow()
        tokens = [
            {
                "id": r.id,
                "name": r.name,
                "prefix": r.prefix,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                "last_used_at": r.last_used_at.isoformat() + "Z" if r.last_used_at else None,
                "expires_at": r.expires_at.isoformat() + "Z" if r.expires_at else None,
                "revoked": r.revoked,
                "expired": bool(r.expires_at and r.expires_at < now),
                "active": (not r.revoked) and bool(r.expires_at and r.expires_at >= now),
            }
            for r in rows
        ]
    return {"tokens": tokens}


@router.delete("/auth/tokens/{pat_id}", tags=["PAT"])
async def revoke_token(pat_id: int, current_user: dict = Depends(get_current_user)):
    """Revoke one of the caller's PATs. Takes effect immediately — the next
    exchange with that token fails."""
    email = current_user.get("email") or current_user.get("sub")
    async with user_db_manager.get_async_session() as session:
        profile = await user_profile_repo.get_by_email(session, email)
        profile_id = profile.id if profile else current_user.get("profile_id")
        if profile_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
        ok = await personal_access_token_repo.revoke(session, pat_id, profile_id)
        await session.commit()
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Token not found or already revoked")
    return {"revoked": True, "id": pat_id}


@router.post("/auth/pat/exchange", tags=["PAT"])
async def pat_exchange(body: PatExchangeIn):
    """Exchange a Personal Access Token for a short-lived per-service access token
    (``aud=<service>``). The PAT itself is the credential — no other auth needed.

    Roles are re-read fresh from the DB and scopes derived from them, so a
    demoted/banned user (or a revoked token) cannot mint a privileged token."""
    token = (body.token or "").strip()
    if not token.startswith(_PAT_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not a BrainKB access token")
    if body.audience not in config.token_audiences:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown audience '{body.audience}'. Allowed: {config.token_audiences}",
        )

    token_hash = _hash(token)
    async with user_db_manager.get_async_session() as session:
        row = await personal_access_token_repo.get_valid_by_hash(session, token_hash)
        if row is None:
            await session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Token invalid, expired, or revoked")
        # Capture PAT-linked identity before touching related rows / committing.
        email = row.email
        profile_id = row.profile_id
        jwt_user_id = row.jwt_user_id

        # Sliding expiry: recent use extends the window so an actively-used token
        # never re-prompts; an idle one still expires after _PAT_DEFAULT_DAYS. Cap
        # the roll at created_at + _PAT_MAX_DAYS so it can't live forever. Only ever
        # push expiry forward, never shorten it.
        if _PAT_SLIDING:
            now = datetime.utcnow()
            sliding = now + timedelta(days=_PAT_DEFAULT_DAYS)
            cap = (row.created_at or now) + timedelta(days=_PAT_MAX_DAYS)
            new_exp = min(sliding, cap)
            if new_exp > row.expires_at:
                row.expires_at = new_exp

        profile = await user_profile_repo.get_by_email(session, email)
        if profile is not None:
            profile_id = profile.id
            if getattr(profile, "is_banned", False):
                await session.commit()
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_suspended")
        roles = await user_role_repo.get_user_role_names(session, profile_id) if profile_id else []
        await session.commit()

    access = tokens_rs256.create_access_token(
        audience=body.audience,
        email=email,
        profile_id=profile_id,
        roles=roles,
        scopes=_scopes_for_roles(roles),
        auth_source="pat",
        jwt_user_id=jwt_user_id,
    )
    return {
        "access_token": access,
        "token_type": "bearer",
        "aud": body.audience,
        "expires_in": tokens_rs256.access_token_ttl_seconds(),
    }
