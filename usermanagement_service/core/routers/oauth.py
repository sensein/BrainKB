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
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse

from core.configuration import config
from pydantic import BaseModel

from core import tokens_rs256
from core.database import (
    user_db_manager, user_profile_repo, jwt_user_repo,
    oauth_identity_repo, oauth_state_repo, oauth_cli_result_repo,
    user_activity_repo, provision_identity,
)
from core.models.user import ActivityType, OAuthLoginStart, UserRoleEnum
from core.models.database_models import UserProfile as UserProfileModel
from core.oauth import get_provider
from core.security import create_access_token_v2, encrypt_token

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


# Unambiguous alphabet (no I/L/O/0/1) for the paste-code shown to users.
_CLI_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 30 symbols
# Paste-code length (raw chars, before dash grouping). The code is short-LIVED
# (~10 min) and single-use, but we still make it HIGH-ENTROPY for defense in
# depth: 20 chars over a 30-symbol alphabet ≈ 98 bits (~1e29 combinations),
# infeasible to brute-force within the 10-minute window even without rate limits.
# Clamped to 24 so the dash-grouped value still fits the
# Web_oauth_cli_result.code column (String(32)); configurable via env.
_CLI_CODE_LEN = min(24, max(8, int(os.getenv("USERMANAGEMENT_CLI_CODE_LEN", "20"))))


def _gen_cli_code() -> str:
    """A long, single-use, ~10-min paste-code, grouped in 4s for readability,
    e.g. ``A3KM-7QRS-9WXY-2BCD-EFGH``. High entropy so it can't be guessed in the
    short window; it is only a handle exchanged once for the real refresh token."""
    raw = "".join(secrets.choice(_CLI_CODE_ALPHABET) for _ in range(_CLI_CODE_LEN))
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def _cli_success_page(code: str) -> str:
    """Minimal self-contained page shown after a CLI/skill OAuth login. Displays the
    one-time code the user pastes back into the skill. No SPA/frontend needed."""
    safe = (code or "").replace("<", "").replace(">", "")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>BrainKB login</title>"
        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
        "background:#0f172a;color:#e2e8f0;display:flex;min-height:100vh;align-items:center;"
        "justify-content:center;margin:0}.card{background:#1e293b;padding:2.5rem;border-radius:14px;"
        "max-width:420px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.4)}"
        "h1{font-size:1.2rem;margin:0 0 .5rem}p{color:#94a3b8;font-size:.95rem;line-height:1.5}"
        ".code{font-family:ui-monospace,Menlo,monospace;font-size:2rem;letter-spacing:.15em;"
        "background:#0f172a;color:#38bdf8;padding:1rem;border-radius:10px;margin:1.2rem 0;"
        "user-select:all}</style></head><body><div class='card'>"
        "<h1>✅ Signed in to BrainKB</h1>"
        "<p>Copy this one-time code and paste it back into your assistant "
        "(<code>brainkb_finish_login</code>):</p>"
        f"<div class='code'>{safe}</div>"
        "<p>The code expires in ~10 minutes and can be used once. "
        "You can close this tab afterward.</p>"
        "</div></body></html>"
    )


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


async def _begin_oauth(provider_name: str, redirect_after_login: Optional[str], mode: str):
    """Mint + persist OAuth state (+PKCE) and return (authorize_url, state).
    ``mode`` is 'web' (browser → SPA) or 'cli' (MCP/skill paste-code)."""
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
        redirect_uri=redirect_uri, state=state, code_challenge=code_challenge,
    )
    async with user_db_manager.get_async_session() as session:
        await oauth_state_repo.create(
            session,
            state=state,
            provider=provider.name,
            code_verifier=code_verifier,
            redirect_after_login=redirect_after_login,
            mode=mode,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        await session.commit()
    return authorize_url, state


@router.get("/auth/{provider_name}/login", response_model=OAuthLoginStart)
async def oauth_login(
    provider_name: str,
    redirect_after_login: Optional[str] = Query(None, description="Relative path to send the user to after login completes"),
):
    """Start an OAuth flow (browser/SPA). Returns the authorize URL; the UI redirects the browser there."""
    authorize_url, state = await _begin_oauth(provider_name, redirect_after_login, "web")
    return OAuthLoginStart(authorize_url=authorize_url, state=state)


class _CliStartIn(BaseModel):
    provider: str = "globus"


@router.post("/auth/cli/start", tags=["SSO"])
async def oauth_cli_start(body: _CliStartIn):
    """Start an OAuth flow for the MCP/skill (paste-code). Returns an authorize URL;
    open it in a browser, sign in with the provider, then paste the short code the
    browser shows into `brainkb_finish_login`. No web UI required."""
    authorize_url, state = await _begin_oauth(body.provider, None, "cli")
    return {
        "authorize_url": authorize_url,
        "state": state,
        "mode": "cli",
        "instructions": ("Open authorize_url in a browser and sign in. When it "
                         "shows a code, paste it into brainkb_finish_login(code)."),
    }


class _CliExchangeIn(BaseModel):
    code: str


@router.post("/auth/cli/exchange", tags=["SSO"])
async def oauth_cli_exchange(body: _CliExchangeIn):
    """Exchange the paste-code (shown after a CLI OAuth login) for an SSO refresh
    token. Single-use and short-lived."""
    code = (body.code or "").strip().upper()
    async with user_db_manager.get_async_session() as session:
        await oauth_cli_result_repo.purge_expired(session)
        row = await oauth_cli_result_repo.consume(session, code)
        # Read the token INSIDE the session — after commit the ORM attribute is
        # expired and touching it would trigger async lazy-load (MissingGreenlet).
        refresh_token = row.refresh_token if row is not None else None
        await session.commit()
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Invalid, expired, or already-used code.")
    return {
        "refresh_token": refresh_token,
        "token_type": "refresh",
        "expires_in": tokens_rs256.refresh_token_ttl_seconds(),
    }


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
        login_mode = getattr(state_row, "mode", "web") or "web"
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

    cli_code = None
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

            # Ensure a credential row linked to this profile, a default role,
            # and bootstrap elevation — all via the single provisioning path.
            # OAuth's own profile matching already ran above, so hand the
            # resolved profile through as existing_profile.
            profile, jwt_user, existing_roles = await provision_identity(
                session,
                email=profile.email,
                full_name=profile.name or userinfo.name or profile.email,
                default_role=UserRoleEnum.CURATOR.value,
                existing_profile=profile,
            )

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
                # Web-session TTL (default 12h), not the 30-min default: this token
                # lives in the NextAuth session and isn't auto-refreshed, so a short
                # TTL made the UI 401 (/api/users/me) mid-session.
                expires_minutes=config.web_session_ttl_min,
            )
            # Web flow: also mint a longer-lived REFRESH token so the UI can renew
            # its access token silently (no re-login) until this expires. Exchanged
            # by the UI at /api/auth/exchange (audience=usermanagement).
            web_refresh = None
            if login_mode != "cli":
                web_refresh = tokens_rs256.create_refresh_token(
                    email=profile.email,
                    profile_id=profile.id,
                    roles=existing_roles,
                    scopes=scopes,
                    auth_source=provider.name,
                    expires_minutes=config.web_refresh_ttl_min,
                )
            # CLI/skill (paste-code) flow: mint an SSO refresh token and stash it
            # behind a short code the browser will display for the user to paste.
            if login_mode == "cli":
                refresh = tokens_rs256.create_refresh_token(
                    email=profile.email,
                    profile_id=profile.id,
                    roles=existing_roles,
                    scopes=scopes,
                    auth_source=provider.name,
                )
                cli_code = _gen_cli_code()
                await oauth_cli_result_repo.store(
                    session,
                    code=cli_code,
                    refresh_token=refresh,
                    email=profile.email,
                    expires_at=datetime.utcnow() + timedelta(minutes=10),
                )
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.exception("Error finalizing OAuth login")
            return RedirectResponse(_frontend_error_redirect(f"finalize_failed: {e}"), status_code=302)

    # CLI/skill login: show the paste-code page instead of redirecting to the SPA.
    if login_mode == "cli":
        return HTMLResponse(_cli_success_page(cli_code))

    qs = {"token": token}
    if web_refresh:
        qs["refresh"] = web_refresh
    if redirect_after_login:
        qs["redirect"] = redirect_after_login
    return RedirectResponse(f"{config.frontend_callback_url}?{urlencode(qs)}", status_code=302)


def _frontend_error_redirect(message: str) -> str:
    return f"{config.frontend_callback_url}?{urlencode({'error': message})}"
