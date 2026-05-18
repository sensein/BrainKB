"""Admin endpoints — mounted at /api/admin/*. Every route requires the Admin role.

Surfaces:
  - /roles            CRUD over Web_available_role
  - /permissions      CRUD over Web_permission
  - /roles/{id}/permissions  role ↔ permission assignment
  - /page-access      CRUD over Web_page_access (+ role/user overrides)
  - /users            list / get / delete / assign-role for UserProfiles
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func

from core.database import (
    user_db_manager, user_profile_repo, user_role_repo, user_activity_repo,
    available_role_repo, permission_repo, role_permission_repo, page_access_repo,
    oauth_identity_repo,
)
from core.models.database_models import (
    AvailableRole as AvailableRoleModel,
    Permission as PermissionModel,
    UserProfile as UserProfileModel,
    UserRole as UserRoleModel,
    OAuthIdentity as OAuthIdentityModel,
)
from core.models.user import (
    AvailableRoleInput, AvailableRole,
    PermissionInput, Permission, RolePermissionAssignment,
    PageAccessInput, PageAccess,
    AdminUserListItem, UserRoleInput, ActivityType,
)
from core.security import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# ROLES
# =============================================================================

@router.get("/roles", response_model=List[AvailableRole])
async def list_roles(_admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        result = await session.execute(select(AvailableRoleModel).order_by(AvailableRoleModel.category, AvailableRoleModel.name))
        return [AvailableRole.model_validate(r, from_attributes=True) for r in result.scalars().all()]


@router.post("/roles", response_model=AvailableRole, status_code=201)
async def create_role(role: AvailableRoleInput, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        existing = await session.execute(select(AvailableRoleModel).where(AvailableRoleModel.name == role.name))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Role '{role.name}' already exists")
        new_role = AvailableRoleModel(**role.dict())
        session.add(new_role)
        await session.commit()
        await session.refresh(new_role)
        return AvailableRole.model_validate(new_role, from_attributes=True)


@router.put("/roles/{role_id}", response_model=AvailableRole)
async def update_role(role_id: int, role: AvailableRoleInput, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        existing = await session.get(AvailableRoleModel, role_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Role not found")
        for k, v in role.dict().items():
            setattr(existing, k, v)
        existing.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(existing)
        return AvailableRole.model_validate(existing, from_attributes=True)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(role_id: int, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        existing = await session.get(AvailableRoleModel, role_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Role not found")
        if existing.name == "Admin":
            raise HTTPException(status_code=400, detail="The Admin role cannot be deleted")
        await session.delete(existing)
        await session.commit()
        return None


@router.get("/roles/{role_id}/permissions", response_model=List[Permission])
async def get_role_permissions(role_id: int, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        perms = await role_permission_repo.get_permissions_for_role(session, role_id)
        return [Permission.model_validate(p, from_attributes=True) for p in perms]


@router.put("/roles/{role_id}/permissions", response_model=List[Permission])
async def set_role_permissions(
    role_id: int,
    body: RolePermissionAssignment,
    _admin: Annotated[dict, Depends(require_admin)],
):
    async with user_db_manager.get_async_session() as session:
        existing = await session.get(AvailableRoleModel, role_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Role not found")
        await role_permission_repo.set_role_permissions(session, role_id, body.permission_ids)
        perms = await role_permission_repo.get_permissions_for_role(session, role_id)
        await session.commit()
        return [Permission.model_validate(p, from_attributes=True) for p in perms]


# =============================================================================
# PERMISSIONS
# =============================================================================

@router.get("/permissions", response_model=List[Permission])
async def list_permissions(_admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        perms = await permission_repo.list_all(session)
        return [Permission.model_validate(p, from_attributes=True) for p in perms]


@router.post("/permissions", response_model=Permission, status_code=201)
async def create_permission(body: PermissionInput, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        existing = await permission_repo.get_by_name(session, body.name)
        if existing:
            raise HTTPException(status_code=409, detail=f"Permission '{body.name}' already exists")
        new_perm = PermissionModel(**body.dict())
        session.add(new_perm)
        await session.commit()
        await session.refresh(new_perm)
        return Permission.model_validate(new_perm, from_attributes=True)


@router.put("/permissions/{permission_id}", response_model=Permission)
async def update_permission(
    permission_id: int,
    body: PermissionInput,
    _admin: Annotated[dict, Depends(require_admin)],
):
    async with user_db_manager.get_async_session() as session:
        existing = await session.get(PermissionModel, permission_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Permission not found")
        for k, v in body.dict().items():
            setattr(existing, k, v)
        existing.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(existing)
        return Permission.model_validate(existing, from_attributes=True)


@router.delete("/permissions/{permission_id}", status_code=204)
async def delete_permission(permission_id: int, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        existing = await session.get(PermissionModel, permission_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Permission not found")
        await session.delete(existing)
        await session.commit()
        return None


# =============================================================================
# PAGE ACCESS
# =============================================================================

async def _page_access_to_response(session, page) -> PageAccess:
    roles = await page_access_repo.get_allowed_roles(session, page.id)
    user_ids = await page_access_repo.get_allowed_user_profile_ids(session, page.id)
    emails: List[str] = []
    if user_ids:
        result = await session.execute(
            select(UserProfileModel.email).where(UserProfileModel.id.in_(user_ids))
        )
        emails = [row[0] for row in result.all()]
    return PageAccess(
        id=page.id,
        page_key=page.page_key,
        description=page.description,
        is_public=page.is_public,
        allowed_roles=roles,
        allowed_user_emails=emails,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


@router.get("/page-access", response_model=List[PageAccess])
async def list_page_access(_admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        pages = await page_access_repo.list_all(session)
        return [await _page_access_to_response(session, p) for p in pages]


@router.get("/page-access/{page_key}", response_model=PageAccess)
async def get_page_access(page_key: str, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        page = await page_access_repo.get_by_key(session, page_key)
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        return await _page_access_to_response(session, page)


@router.put("/page-access/{page_key}", response_model=PageAccess)
async def upsert_page_access(
    page_key: str,
    body: PageAccessInput,
    _admin: Annotated[dict, Depends(require_admin)],
):
    if body.page_key != page_key:
        raise HTTPException(status_code=400, detail="page_key in URL and body must match")
    async with user_db_manager.get_async_session() as session:
        profile_ids: List[int] = []
        for email in body.allowed_user_emails:
            p = await user_profile_repo.get_by_email(session, email)
            if not p:
                raise HTTPException(status_code=400, detail=f"No profile found for email {email}")
            profile_ids.append(p.id)
        page = await page_access_repo.upsert_with_members(
            session,
            page_key=body.page_key,
            description=body.description,
            is_public=body.is_public,
            allowed_role_names=body.allowed_roles,
            allowed_profile_ids=profile_ids,
        )
        response = await _page_access_to_response(session, page)
        await session.commit()
        return response


@router.delete("/page-access/{page_key}", status_code=204)
async def delete_page_access(page_key: str, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        ok = await page_access_repo.delete_by_key(session, page_key)
        if not ok:
            raise HTTPException(status_code=404, detail="Page not found")
        await session.commit()
        return None


# =============================================================================
# USERS
# =============================================================================

@router.get("/users", response_model=List[AdminUserListItem])
async def list_users(
    _admin: Annotated[dict, Depends(require_admin)],
    q: Optional[str] = Query(None, description="Search in name/email/orcid"),
    role: Optional[str] = Query(None, description="Filter by assigned role name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    async with user_db_manager.get_async_session() as session:
        stmt = select(UserProfileModel)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                (UserProfileModel.name.ilike(like))
                | (UserProfileModel.email.ilike(like))
                | (UserProfileModel.orcid_id.ilike(like))
            )
        if role:
            stmt = stmt.join(UserRoleModel, UserRoleModel.profile_id == UserProfileModel.id).where(
                UserRoleModel.role == role, UserRoleModel.is_active == True  # noqa: E712
            )
        stmt = stmt.order_by(UserProfileModel.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        profiles = list(result.scalars().unique().all())

        items: List[AdminUserListItem] = []
        for p in profiles:
            role_names = await user_role_repo.get_user_role_names(session, p.id)
            identities = await oauth_identity_repo.list_for_profile(session, p.id)
            items.append(AdminUserListItem(
                profile_id=p.id,
                name=p.name,
                email=p.email,
                orcid_id=p.orcid_id,
                roles=role_names,
                providers=sorted({i.provider for i in identities}),
                created_at=p.created_at,
                is_banned=bool(getattr(p, "is_banned", False)),
                banned_at=getattr(p, "banned_at", None),
                banned_by=getattr(p, "banned_by", None),
                ban_reason=getattr(p, "ban_reason", None),
            ))
        return items


@router.get("/users/count")
async def count_users(_admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        result = await session.execute(select(func.count()).select_from(UserProfileModel))
        return {"count": result.scalar_one()}


@router.delete("/users/{profile_id}", status_code=204)
async def delete_user(profile_id: int, _admin: Annotated[dict, Depends(require_admin)]):
    async with user_db_manager.get_async_session() as session:
        profile = await session.get(UserProfileModel, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        # SuperAdmin accounts are protected — they cannot be deleted via the
        # admin endpoints. Drop them from the bootstrap allowlist + restart
        # if this is genuinely needed.
        target_roles = await user_role_repo.get_user_role_names(session, profile_id)
        if "SuperAdmin" in (target_roles or []):
            raise HTTPException(
                status_code=403,
                detail="SuperAdmin accounts cannot be deleted via the admin UI.",
            )
        # Cascades delete activities, roles, contributions, countries, orgs, education, expertise, oauth_identity.
        await session.delete(profile)
        await session.commit()
        return None


@router.post("/users/{profile_id}/roles", response_model=List[str])
async def assign_role_to_user(
    profile_id: int,
    body: UserRoleInput,
    admin: Annotated[dict, Depends(require_admin)],
):
    async with user_db_manager.get_async_session() as session:
        profile = await session.get(UserProfileModel, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        await user_role_repo.assign_role(
            session=session,
            profile_id=profile_id,
            role=body.role,
            assigned_by=admin.get("profile_id"),
            is_active=body.is_active,
            expires_at=body.expires_at,
        )
        await user_activity_repo.log_activity(
            session=session,
            profile_id=profile_id,
            activity_type=ActivityType.CONTENT_CURATION,
            description=f"Role '{body.role}' assigned by admin",
        )
        roles = await user_role_repo.get_user_role_names(session, profile_id)
        await session.commit()
        return roles


@router.delete("/users/{profile_id}/roles/{role_name}", response_model=List[str])
async def remove_role_from_user(
    profile_id: int,
    role_name: str,
    _admin: Annotated[dict, Depends(require_admin)],
):
    async with user_db_manager.get_async_session() as session:
        profile = await session.get(UserProfileModel, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        # SuperAdmin role itself can never be stripped through the admin UI.
        if role_name == "SuperAdmin":
            raise HTTPException(
                status_code=403,
                detail="The SuperAdmin role cannot be removed via the admin UI.",
            )
        await user_role_repo.remove_role(session, profile_id, role_name)
        roles = await user_role_repo.get_user_role_names(session, profile_id)
        await session.commit()
        return roles


# =============================================================================
# ADMIN-MANAGED SETTINGS (shared keys, etc.)
# =============================================================================

# Stable key for the shared OpenRouter API key. New shared settings should
# follow the dotted-namespace convention.
_OPENROUTER_KEY_SETTING = "shared.openrouter_api_key"


def _redact_key(plain: Optional[str]) -> dict:
    """Return a non-sensitive summary of an API key — last 4 chars only.
    Lets the admin UI confirm the value is set without redisplaying it after
    the page is refreshed (the admin re-paste flow stays explicit)."""
    if not plain:
        return {"has_key": False, "last_4": None, "length": 0}
    plain = plain.strip()
    return {
        "has_key": bool(plain),
        "last_4": plain[-4:] if len(plain) >= 4 else None,
        "length": len(plain),
    }


@router.get("/settings/openrouter-key")
async def admin_get_openrouter_key(
    _admin: Annotated[dict, Depends(require_admin)],
    reveal: bool = Query(False, description="Return the plaintext key. Default false (returns last-4 only)."),
):
    """Inspect the shared OpenRouter key. By default returns metadata only
    (has_key, last_4, allowed_role_names, updated_at, updated_by). Pass
    `reveal=true` to retrieve the plaintext — only admins can do this."""
    from core.database import admin_setting_repo
    from core.security import decrypt_token

    async with user_db_manager.get_async_session() as session:
        row = await admin_setting_repo.get(session, _OPENROUTER_KEY_SETTING)
        if not row or not row.value_enc:
            return {
                "has_key": False,
                "last_4": None,
                "length": 0,
                "allowed_role_names": [],
                "updated_at": None,
                "updated_by": None,
                "plaintext": None,
            }
        plaintext = decrypt_token(row.value_enc)
        body = _redact_key(plaintext)
        body["allowed_role_names"] = row.allowed_role_names or []
        body["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
        body["updated_by"] = row.updated_by
        body["plaintext"] = plaintext if reveal else None
        return body


@router.put("/settings/openrouter-key")
async def admin_set_openrouter_key(
    payload: dict,
    admin: Annotated[dict, Depends(require_admin)],
):
    """Set or replace the shared OpenRouter API key.
    Body: { "api_key": str, "allowed_role_names": [str, ...] | null }.
    `allowed_role_names` controls which roles can fetch the effective key
    via the user-facing endpoint. Empty list / null means "any signed-in
    user with a profile". The plaintext is encrypted at rest with the same
    Fernet key as OAuth tokens."""
    from core.database import admin_setting_repo
    from core.security import encrypt_token

    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")
    if len(api_key) > 4000:
        raise HTTPException(status_code=400, detail="api_key looks too long; check the value")
    allowed_role_names = payload.get("allowed_role_names")
    if allowed_role_names is not None:
        if not isinstance(allowed_role_names, list) or not all(isinstance(x, str) for x in allowed_role_names):
            raise HTTPException(status_code=400, detail="allowed_role_names must be a list of strings or null")
        # Normalise: trim, drop empties, dedupe, preserve order.
        seen = set()
        normalised = []
        for r in (s.strip() for s in allowed_role_names):
            if r and r not in seen:
                seen.add(r)
                normalised.append(r)
        allowed_role_names = normalised

    async with user_db_manager.get_async_session() as session:
        # `admin` from require_admin includes a profile_id claim used as updated_by.
        updated_by = admin.get("profile_id") if isinstance(admin, dict) else None
        await admin_setting_repo.upsert(
            session,
            key=_OPENROUTER_KEY_SETTING,
            value_enc=encrypt_token(api_key),
            allowed_role_names=allowed_role_names,
            updated_by=updated_by,
        )
        await session.commit()
        return {**_redact_key(api_key), "allowed_role_names": allowed_role_names or []}


@router.delete("/settings/openrouter-key", status_code=204)
async def admin_delete_openrouter_key(_admin: Annotated[dict, Depends(require_admin)]):
    """Clear the shared OpenRouter API key. Users without their own key will
    fall back to the "no shared key" path."""
    from core.database import admin_setting_repo
    async with user_db_manager.get_async_session() as session:
        await admin_setting_repo.delete(session, _OPENROUTER_KEY_SETTING)
        await session.commit()
        return None


# =============================================================================
# USER BAN
# =============================================================================
# Banned users keep their UserProfile (so history is preserved) but every
# authenticated request returns 403 — see core.security.get_current_user
# which re-reads `is_banned` per request. To delete a user entirely use
# DELETE /api/admin/users/{profile_id}.

@router.post("/users/{profile_id}/ban")
async def ban_user(
    profile_id: int,
    payload: dict,
    admin: Annotated[dict, Depends(require_admin)],
):
    """Suspend a user. Body: { "reason": str }. Idempotent — re-banning an
    already-banned user updates the reason and timestamp.

    Refuses to ban yourself or to ban a SuperAdmin. Regular Admins are
    bannable directly — multiple admins can coexist, and one admin moderating
    another is part of the model.
    """
    reason = (payload.get("reason") or "").strip() if isinstance(payload, dict) else ""
    if not reason:
        raise HTTPException(status_code=400, detail="reason is required")
    if len(reason) > 1000:
        raise HTTPException(status_code=400, detail="reason is too long (max 1000 chars)")

    actor_id = admin.get("profile_id") if isinstance(admin, dict) else None
    if actor_id is not None and actor_id == profile_id:
        raise HTTPException(status_code=400, detail="You cannot ban yourself.")

    async with user_db_manager.get_async_session() as session:
        profile = await session.get(UserProfileModel, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")

        target_roles = await user_role_repo.get_user_role_names(session, profile_id)
        if "SuperAdmin" in (target_roles or []):
            raise HTTPException(
                status_code=403,
                detail="SuperAdmin accounts cannot be banned via the admin UI.",
            )

        profile.is_banned = True
        profile.banned_at = datetime.utcnow()
        profile.banned_by = actor_id
        profile.ban_reason = reason
        await session.flush()

        await user_activity_repo.log_activity(
            session=session,
            profile_id=actor_id if actor_id is not None else profile_id,
            activity_type=ActivityType.USER_BAN,
            description=f"Banned profile_id={profile_id}: {reason}",
            ip_address=None,
            user_agent=None,
        )
        await session.commit()
        return {
            "profile_id": profile_id,
            "is_banned": True,
            "banned_at": profile.banned_at.isoformat() if profile.banned_at else None,
            "banned_by": profile.banned_by,
            "ban_reason": profile.ban_reason,
        }


@router.delete("/users/{profile_id}/ban")
async def unban_user(
    profile_id: int,
    admin: Annotated[dict, Depends(require_admin)],
):
    """Lift a suspension. Idempotent — unbanning an already-active user is a no-op
    that still records the activity for audit."""
    actor_id = admin.get("profile_id") if isinstance(admin, dict) else None
    async with user_db_manager.get_async_session() as session:
        profile = await session.get(UserProfileModel, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        was_banned = bool(getattr(profile, "is_banned", False))
        profile.is_banned = False
        profile.banned_at = None
        profile.banned_by = None
        profile.ban_reason = None
        await session.flush()

        if was_banned:
            await user_activity_repo.log_activity(
                session=session,
                profile_id=actor_id if actor_id is not None else profile_id,
                activity_type=ActivityType.USER_UNBAN,
                description=f"Unbanned profile_id={profile_id}",
                ip_address=None,
                user_agent=None,
            )
        await session.commit()
        return {"profile_id": profile_id, "is_banned": False}
