"""Unified OAuth routes: /api/auth/{provider}/login and /api/auth/{provider}/callback.

Flow:
  1. UI hits GET /api/auth/{provider}/login?redirect_after_login=/dashboard
     → we mint a state+PKCE pair, store it in Web_oauth_state, return { authorize_url }.
     UI redirects the browser to authorize_url.
  2. Provider redirects back to GET /api/auth/{provider}/callback?code=...&state=...
     → we validate state, exchange the code, fetch userinfo, upsert
       UserProfile + Web_oauth_identity + JWTUser shell, assign default role,
       issue a BrainKB JWT, then redirect to USERMANAGEMENT_FRONTEND_CALLBACK_URL
       with ?token=... in the query string.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from core.configuration import config
from core.database import (
    user_db_manager, user_profile_repo, user_role_repo, jwt_user_repo,
    oauth_identity_repo, oauth_state_repo, user_activity_repo,
)
from core.models.user import ActivityType, OAuthLoginStart, UserRoleEnum
from core.models.database_models import UserProfile as UserProfileModel, JWTUser as JWTUserModel
from core.oauth import get_provider
from core.security import (
    create_access_token_v2, encrypt_token, get_password_hash,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---- helpers ------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def _redirect_uri_for(provider_name: str) -> str:
    return f"{config.public_base_url.rstrip('/')}/api/auth/{provider_name}/callback"


async def _upsert_profile_for_oauth(session, userinfo) -> UserProfileModel:
    """Find or create a UserProfile for an OAuth identity.
    Matching order: (1) existing OAuth identity → its linked profile,
    (2) UserProfile.email, (3) UserProfile.orcid_id (for ORCID logins),
    (4) create a new profile."""
    existing_identity = await oauth_identity_repo.get_by_provider_user(
        session, userinfo.provider, userinfo.provider_user_id
    )
    if existing_identity:
        return await session.get(UserProfileModel, existing_identity.profile_id)

    if userinfo.email:
        by_email = await user_profile_repo.get_by_email(session, userinfo.email)
        if by_email:
            return by_email

    if userinfo.orcid_id:
        by_orcid = await user_profile_repo.get_by_orcid_id(session, userinfo.orcid_id)
        if by_orcid:
            return by_orcid

    if not userinfo.email:
        # Some GitHub accounts hide email and have no verified one. We can't
        # create a profile without an email — surface a clear error.
        raise HTTPException(
            status_code=400,
            detail=f"{userinfo.provider} did not return an email and no existing profile could be matched. Please make your email public on {userinfo.provider} or log in with ORCID/Globus first.",
        )

    new_profile = UserProfileModel(
        name=userinfo.name or userinfo.email.split("@")[0],
        email=userinfo.email,
        orcid_id=userinfo.orcid_id,
        github=userinfo.github_username,
    )
    session.add(new_profile)
    await session.flush()
    await session.refresh(new_profile)
    return new_profile


async def _ensure_jwt_user_shell(session, email: str, full_name: str) -> JWTUserModel:
    """Make sure a Web_jwtuser row exists for this email. OAuth users don't have
    a usable password — we store a random high-entropy hash (can't be logged in
    with, just exists so the JWT user_id claim is stable). The shell is created
    with `is_active=False`, so the lookup must not filter by activation; using
    `get_by_email` (active-only) here would re-INSERT on every sign-in and
    collide with the unique-email constraint."""
    existing = await jwt_user_repo.get_by_email_any_status(session, email)
    if existing:
        return existing
    random_password = secrets.token_urlsafe(48)
    return await jwt_user_repo.create_user(
        session=session,
        full_name=full_name,
        email=email,
        password=get_password_hash(random_password),
    )


# ---- routes -------------------------------------------------------------

@router.get("/auth/providers")
async def list_providers():
    """List OAuth providers and whether each is currently configured.
    UI can use this to show/hide login buttons."""
    from core.oauth import REGISTRY
    return {
        "providers": [
            {"name": p.name, "configured": p.is_configured(), "supports_pkce": p.supports_pkce}
            for p in REGISTRY.values()
        ]
    }


@router.get("/auth/{provider_name}/login", response_model=OAuthLoginStart)
async def oauth_login(
    provider_name: str,
    redirect_after_login: Optional[str] = Query(None, description="Relative path to send the user to after login completes"),
):
    """Start an OAuth flow. Returns the authorize URL; the UI redirects the browser there."""
    try:
        provider = get_provider(provider_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}")

    if not provider.is_configured():
        raise HTTPException(status_code=503, detail=f"{provider_name} OAuth is not configured on the server")

    state = secrets.token_urlsafe(32)
    code_verifier = None
    code_challenge = None
    if provider.supports_pkce:
        code_verifier, code_challenge = _pkce_pair()

    redirect_uri = _redirect_uri_for(provider.name)
    authorize_url = provider.authorize_url(
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )

    # Persist state so the callback (on a different request) can validate it.
    async with user_db_manager.get_async_session() as session:
        await oauth_state_repo.create(
            session,
            state=state,
            provider=provider.name,
            code_verifier=code_verifier,
            redirect_after_login=redirect_after_login,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        await session.commit()

    return OAuthLoginStart(authorize_url=authorize_url, state=state)


@router.get("/auth/{provider_name}/callback")
async def oauth_callback(
    provider_name: str,
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """Handle the OAuth provider redirect. On success, redirects the browser to
    USERMANAGEMENT_FRONTEND_CALLBACK_URL with ?token=<jwt>&redirect=<path>."""
    if error:
        logger.warning(f"OAuth error from {provider_name}: {error} {error_description}")
        return RedirectResponse(
            _frontend_error_redirect(f"{error}: {error_description or ''}"),
            status_code=302,
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    try:
        provider = get_provider(provider_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_name}")

    async with user_db_manager.get_async_session() as session:
        await oauth_state_repo.purge_expired(session)
        state_row = await oauth_state_repo.consume(session, state)
        if state_row is None or state_row.provider != provider_name:
            await session.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired state")
        if state_row.expires_at < datetime.utcnow():
            await session.commit()
            raise HTTPException(status_code=400, detail="OAuth state expired")
        code_verifier = state_row.code_verifier
        redirect_after_login = state_row.redirect_after_login
        await session.commit()

    redirect_uri = _redirect_uri_for(provider.name)
    try:
        token_resp = await provider.exchange_code(code=code, redirect_uri=redirect_uri, code_verifier=code_verifier)
        userinfo = await provider.fetch_userinfo(access_token=token_resp.access_token, token_response=token_resp)
    except Exception as e:
        logger.exception(f"OAuth callback failed for {provider_name}")
        return RedirectResponse(_frontend_error_redirect(str(e)), status_code=302)

    if not userinfo.provider_user_id:
        return RedirectResponse(_frontend_error_redirect("provider returned no user id"), status_code=302)

    async with user_db_manager.get_async_session() as session:
        try:
            profile = await _upsert_profile_for_oauth(session, userinfo)

            # Top up profile fields the provider may have just given us.
            dirty = False
            if userinfo.orcid_id and not profile.orcid_id:
                profile.orcid_id = userinfo.orcid_id
                dirty = True
            if userinfo.github_username and not profile.github:
                profile.github = userinfo.github_username
                dirty = True
            if dirty:
                profile.updated_at = datetime.utcnow()
                await session.flush()

            jwt_user = await _ensure_jwt_user_shell(
                session,
                email=profile.email,
                full_name=profile.name or userinfo.name or profile.email,
            )

            # Default role on first login = Curator.
            existing_roles = await user_role_repo.get_user_role_names(session, profile.id)
            if not existing_roles:
                await user_role_repo.assign_role(
                    session,
                    profile_id=profile.id,
                    role=UserRoleEnum.CURATOR.value,
                    is_active=True,
                )
                existing_roles = [UserRoleEnum.CURATOR.value]

            # Upsert the oauth identity row (encrypt tokens at rest).
            token_expires_at = None
            if token_resp.expires_in:
                token_expires_at = datetime.utcnow() + timedelta(seconds=int(token_resp.expires_in))
            await oauth_identity_repo.upsert(
                session,
                provider=provider.name,
                provider_user_id=userinfo.provider_user_id,
                profile_id=profile.id,
                email=userinfo.email,
                access_token_enc=encrypt_token(token_resp.access_token),
                refresh_token_enc=encrypt_token(token_resp.refresh_token),
                token_expires_at=token_expires_at,
                raw_profile=userinfo.raw,
            )

            # Bootstrap-superadmin allowlist: if configured, elevate on first sight.
            # Seed both Admin (for permissions / page-access checks) and
            # SuperAdmin (the immutable marker that protects the account).
            if (profile.email or "").lower() in config.bootstrap_superadmin_emails:
                for role_name in (UserRoleEnum.ADMIN.value, UserRoleEnum.SUPERADMIN.value):
                    if role_name not in existing_roles:
                        await user_role_repo.assign_role(
                            session,
                            profile_id=profile.id,
                            role=role_name,
                            is_active=True,
                        )
                        existing_roles.append(role_name)

            # Log activity.
            await user_activity_repo.log_activity(
                session=session,
                profile_id=profile.id,
                activity_type=ActivityType.LOGIN,
                description=f"Login via {provider.name}",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )

            scopes = await jwt_user_repo.get_user_scopes(session, jwt_user.id) or ["read"]
            token = create_access_token_v2(
                email=profile.email,
                jwt_user_id=jwt_user.id,
                profile_id=profile.id,
                roles=existing_roles,
                scopes=scopes,
                auth_source=provider.name,
            )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.exception("Error finalizing OAuth login")
            return RedirectResponse(_frontend_error_redirect(f"finalize_failed: {e}"), status_code=302)

    qs = {"token": token}
    if redirect_after_login:
        qs["redirect"] = redirect_after_login
    return RedirectResponse(f"{config.frontend_callback_url}?{urlencode(qs)}", status_code=302)


def _frontend_error_redirect(message: str) -> str:
    return f"{config.frontend_callback_url}?{urlencode({'error': message})}"
