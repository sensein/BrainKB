"""Startup bootstrap: seed baseline roles, permissions, and page access rows, and
promote configured superadmin emails to the SuperAdmin + Admin roles.

Idempotent — safe to run on every startup."""

from __future__ import annotations

import logging
from typing import List

from sqlalchemy import select

from core.configuration import config
from core.database import (
    user_db_manager, user_profile_repo, user_role_repo,
    available_role_repo, permission_repo, page_access_repo, role_permission_repo,
)
from core.models.database_models import AvailableRole, Permission
from core.models.user import UserRoleEnum

logger = logging.getLogger(__name__)


# Baseline roles. Mirrors UserRoleEnum but adds the category so the admin UI can group them.
_BASELINE_ROLES: list[tuple[str, str, str]] = [
    ("SuperAdmin", "Admin", "Super administrator — protected. Cannot be banned, deleted, or have this role stripped via the UI/API."),
    ("Admin", "Admin", "Platform administrator — manages roles, permissions, users, and page access."),
    ("Submitter", "Content", "Submits new content for curation."),
    ("Annotator", "Content", "Annotates submitted content."),
    ("Mapper", "Content", "Maps entities across ontologies."),
    ("Curator", "Content", "Default role for scientific contributors."),
    ("Reviewer", "Quality", "Reviews submitted content."),
    ("Validator", "Quality", "Validates curated content."),
    ("Conflict Resolver", "Quality", "Resolves conflicting curations."),
    ("Knowledge Contributor", "Knowledge", "Contributes knowledge artifacts."),
    ("Evidence Tracer", "Knowledge", "Links evidence to claims."),
    ("Provenance Tracker", "Knowledge", "Tracks provenance metadata."),
    ("Moderator", "Community", "Moderates community discussions."),
    ("Ambassador", "Community", "Community ambassador."),
]

# Baseline permissions — resource:action. Fine-grained permissions used by admin endpoints.
_BASELINE_PERMISSIONS: list[tuple[str, str, str, str]] = [
    ("user.read", "user", "read", "View user profiles"),
    ("user.update", "user", "update", "Update user profiles"),
    ("user.delete", "user", "delete", "Delete user profiles"),
    ("user.list", "user", "list", "List all users"),
    ("role.read", "role", "read", "View roles"),
    ("role.manage", "role", "manage", "Create/update/delete roles"),
    ("role.assign", "role", "assign", "Assign roles to users"),
    ("permission.read", "permission", "read", "View permissions"),
    ("permission.manage", "permission", "manage", "Create/update/delete permissions"),
    ("page_access.read", "page_access", "read", "View page access rules"),
    ("page_access.manage", "page_access", "manage", "Create/update/delete page access rules"),
    ("oauth.identity.read", "oauth_identity", "read", "View OAuth identities"),
]


async def seed_roles() -> None:
    async with user_db_manager.get_async_session() as session:
        existing = await available_role_repo.get_active_roles(session)
        existing_names = {r.name for r in existing}
        for name, category, description in _BASELINE_ROLES:
            if name in existing_names:
                continue
            session.add(AvailableRole(name=name, category=category, description=description, is_active=True))
        await session.commit()


async def seed_permissions() -> None:
    async with user_db_manager.get_async_session() as session:
        existing = await permission_repo.list_all(session)
        existing_names = {p.name for p in existing}
        for name, resource, action, description in _BASELINE_PERMISSIONS:
            if name in existing_names:
                continue
            session.add(Permission(name=name, resource=resource, action=action, description=description))
        await session.commit()


async def grant_admin_all_permissions() -> None:
    """Ensure the Admin and SuperAdmin roles each own every permission
    currently in the registry. SuperAdmin shadows Admin for permissions —
    its only extra power is being un-bannable / un-deletable."""
    async with user_db_manager.get_async_session() as session:
        perms = await permission_repo.list_all(session)
        perm_ids = [p.id for p in perms]
        for role_name in ("Admin", "SuperAdmin"):
            result = await session.execute(select(AvailableRole).where(AvailableRole.name == role_name))
            role = result.scalar_one_or_none()
            if not role:
                logger.warning(f"{role_name} role missing during permission grant bootstrap")
                continue
            await role_permission_repo.set_role_permissions(session, role.id, perm_ids)
        await session.commit()


async def seed_default_page_access() -> None:
    """Seed a couple of sensible defaults so the UI has something to reference.
    The admin can edit these via the admin UI afterward."""
    defaults = [
        {"page_key": "admin.dashboard", "description": "Admin dashboard", "is_public": False, "allowed_roles": ["Admin"], "allowed_emails": []},
        {"page_key": "admin.users", "description": "User management", "is_public": False, "allowed_roles": ["Admin"], "allowed_emails": []},
        {"page_key": "admin.roles", "description": "Role & permission management", "is_public": False, "allowed_roles": ["Admin"], "allowed_emails": []},
        {"page_key": "admin.page_access", "description": "Page access management", "is_public": False, "allowed_roles": ["Admin"], "allowed_emails": []},
        {"page_key": "curate.submit", "description": "Submit content for curation", "is_public": False, "allowed_roles": ["Admin", "Submitter", "Curator"], "allowed_emails": []},
        {"page_key": "curate.review", "description": "Review submitted content", "is_public": False, "allowed_roles": ["Admin", "Reviewer", "Validator"], "allowed_emails": []},
        # SynthScholar (PRISMA literature review). Seeded for Curator (the
        # default role assigned at first OAuth login) so any signed-in user
        # can run a review without an extra admin-grant step. Tighten this
        # in /admin/page-access if access should be more restrictive.
        {"page_key": "tools.synth-scholar", "description": "SynthScholar — PRISMA literature review", "is_public": False, "allowed_roles": ["Admin", "Curator"], "allowed_emails": []},
        {"page_key": "home", "description": "Public landing page", "is_public": True, "allowed_roles": [], "allowed_emails": []},
    ]
    async with user_db_manager.get_async_session() as session:
        existing = await page_access_repo.list_all(session)
        existing_keys = {p.page_key for p in existing}
        for d in defaults:
            if d["page_key"] in existing_keys:
                continue
            profile_ids: List[int] = []
            for email in d["allowed_emails"]:
                p = await user_profile_repo.get_by_email(session, email)
                if p:
                    profile_ids.append(p.id)
            await page_access_repo.upsert_with_members(
                session,
                page_key=d["page_key"],
                description=d["description"],
                is_public=d["is_public"],
                allowed_role_names=d["allowed_roles"],
                allowed_profile_ids=profile_ids,
            )
        await session.commit()


async def promote_bootstrap_superadmins() -> None:
    """Assign the SuperAdmin and Admin roles to every email in
    USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS that already has a UserProfile.
    Emails without a profile are ignored — the require_admin dependency honors
    the bootstrap list too, so they can log in and create their profile first.

    SuperAdmin is the immutable marker; Admin grants the actual permissions.
    Seeding both keeps the page-access RBAC (which checks for "Admin") working
    without special-casing SuperAdmin everywhere."""
    emails = config.bootstrap_superadmin_emails
    if not emails:
        return
    async with user_db_manager.get_async_session() as session:
        for email in emails:
            profile = await user_profile_repo.get_by_email(session, email)
            if not profile:
                logger.info(f"Bootstrap superadmin {email} has no profile yet — require_admin will still accept them via env allowlist.")
                continue
            for role in ("Admin", "SuperAdmin"):
                await user_role_repo.assign_role(session, profile_id=profile.id, role=role, is_active=True)
        await session.commit()


async def apply_inline_schema_migrations() -> None:
    """Idempotent ALTER TABLE migrations for columns that were added after
    the initial create_all(). create_all(checkfirst=True) only creates
    *missing tables*, never adds columns to existing ones — so any new
    column on an existing model needs an explicit ALTER here.

    Each migration uses ADD COLUMN IF NOT EXISTS (Postgres ≥ 9.6) so
    re-running on an already-migrated DB is a no-op.

    When you bump the schema, append a one-liner here. Don't drop or
    rename existing columns from this function — those are destructive and
    belong in a real migration tool with versioning."""
    from sqlalchemy import text as _text
    statements = [
        # User ban support (per-user only; IP bans deferred until a WAF
        # decision is made — see brainkb-ui/README.md).
        'ALTER TABLE "Web_user_profile" ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE',
        'ALTER TABLE "Web_user_profile" ADD COLUMN IF NOT EXISTS banned_at TIMESTAMP',
        'ALTER TABLE "Web_user_profile" ADD COLUMN IF NOT EXISTS banned_by INTEGER REFERENCES "Web_user_profile"(id) ON DELETE SET NULL',
        'ALTER TABLE "Web_user_profile" ADD COLUMN IF NOT EXISTS ban_reason TEXT',
    ]
    async with user_db_manager.get_async_session() as session:
        for stmt in statements:
            try:
                await session.execute(_text(stmt))
            except Exception as e:
                # Don't abort other migrations because one failed — log and
                # continue. A failure here typically means the column type
                # changed and the running schema disagrees with the model;
                # surface that in the logs without bringing the boot down.
                logger.warning(f"Inline migration failed (continuing): {stmt!r} → {e}")
        await session.commit()


async def run_bootstrap() -> None:
    """Run all bootstrap steps. Order matters: schema migrations before
    seeding (later code may reference the new columns), roles before
    role_permissions, admins last."""
    try:
        await apply_inline_schema_migrations()
        await seed_roles()
        await seed_permissions()
        await grant_admin_all_permissions()
        await seed_default_page_access()
        await promote_bootstrap_superadmins()
        logger.info("Bootstrap complete")
    except Exception as e:
        logger.error(f"Bootstrap failed: {e}")
