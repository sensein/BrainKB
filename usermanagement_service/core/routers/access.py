"""Page access check — used by the UI to decide if the current user can view a page.

The UI calls GET /api/access/page/{page_key}:
  - if the page is public, returns {allowed: true, reason: "public"} even for anon
  - otherwise requires Bearer auth and checks the user's roles + per-user overrides

The UI can also call POST /api/access/pages with a list of page_keys to batch-check
(e.g. to decide which nav items to render)."""

from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends

from core.database import user_db_manager, page_access_repo
from core.models.user import PageAccessCheck
from core.security import get_current_user_optional

router = APIRouter()


@router.get("/access/page/{page_key}", response_model=PageAccessCheck)
async def check_page_access(
    page_key: str,
    current_user: Annotated[Optional[dict], Depends(get_current_user_optional)] = None,
):
    profile_id = current_user.get("profile_id") if current_user else None
    roles = current_user.get("roles", []) if current_user else []
    async with user_db_manager.get_async_session() as session:
        allowed, reason = await page_access_repo.check_access(
            session, page_key=page_key, profile_id=profile_id, role_names=roles
        )
    return PageAccessCheck(page_key=page_key, allowed=allowed, reason=reason)


@router.post("/access/pages", response_model=List[PageAccessCheck])
async def check_page_access_batch(
    page_keys: List[str],
    current_user: Annotated[Optional[dict], Depends(get_current_user_optional)] = None,
):
    profile_id = current_user.get("profile_id") if current_user else None
    roles = current_user.get("roles", []) if current_user else []
    results: List[PageAccessCheck] = []
    async with user_db_manager.get_async_session() as session:
        for key in page_keys:
            allowed, reason = await page_access_repo.check_access(
                session, page_key=key, profile_id=profile_id, role_names=roles
            )
            results.append(PageAccessCheck(page_key=key, allowed=allowed, reason=reason))
    return results


# =============================================================================
# Effective shared-key fetch for the UI.
# =============================================================================
# The admin sets a shared OpenRouter API key via /api/admin/settings/openrouter-key
# (encrypted at rest). Any signed-in user whose role is in the setting's
# allowed_role_names list (or any signed-in user, if the list is empty/null) can
# fetch the *plaintext* via this endpoint so their browser can use the key for
# OpenRouter calls. We deliberately do NOT echo the plaintext to the user UI —
# the dashboard input shows it masked. Plaintext is only retrievable by:
#   - admins, via the admin endpoint (with `reveal=true`)
#   - users with an allowed role, via this endpoint (used to make calls,
#     never displayed)

from core.database import admin_setting_repo
from core.security import decrypt_token, get_current_user

_OPENROUTER_KEY_SETTING = "shared.openrouter_api_key"


@router.get("/settings/openrouter-key/effective")
async def get_effective_openrouter_key(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return the effective shared OpenRouter key for the calling user.
    Response shape:
      { "source": "shared" | "none",
        "api_key": str | null,
        "last_4": str | null }
    `source=none` means there is no shared key the caller may use — they
    should fall back to their own personal key. `api_key` is included so
    the browser can use it for tool calls; the UI is expected to never
    render it as plaintext to non-admins."""
    async with user_db_manager.get_async_session() as session:
        row = await admin_setting_repo.get(session, _OPENROUTER_KEY_SETTING)
        if not row or not row.value_enc:
            return {"source": "none", "api_key": None, "last_4": None}
        allowed: List[str] = row.allowed_role_names or []
        user_roles: List[str] = current_user.get("roles", []) or []
        # Admins always pass; otherwise the user must have at least one role
        # in the allowed list. Empty allowed list = open to any signed-in user.
        is_admin = "Admin" in user_roles
        if not is_admin and allowed and not (set(user_roles) & set(allowed)):
            return {"source": "none", "api_key": None, "last_4": None}
        plaintext = decrypt_token(row.value_enc)
        return {
            "source": "shared",
            "api_key": plaintext,
            "last_4": plaintext[-4:] if plaintext and len(plaintext) >= 4 else None,
        }
