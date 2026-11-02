"""Who the caller is (core.security.identity_from_token): the fix that makes review
ownership and admin checks work — the identity was an asyncpg Record (or False),
so owner_email was always empty and admins were never recognised.

    pytest ml_service/test/test_identity.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import security  # noqa: E402


def _identity(payload, is_sso, row):
    async def get_user(email):
        return row
    with patch.object(security, "get_user", get_user):
        return asyncio.run(security.identity_from_token(payload, is_sso))


def test_identity_is_a_dict_with_token_roles():
    user = _identity({"sub": "a@x.org", "roles": ["Admin"], "scopes": ["admin"]}, True, {"id": 7, "password": "h"})
    assert user["email"] == "a@x.org" and user["roles"] == ["Admin"] and user["id"] == 7
    assert "password" not in user


def test_sso_user_without_an_active_local_row_is_still_the_caller():
    assert _identity({"sub": "oauth@x.org"}, True, False)["email"] == "oauth@x.org"


def test_legacy_token_still_needs_an_active_row():
    assert _identity({"sub": "old@x.org"}, False, False) is None
