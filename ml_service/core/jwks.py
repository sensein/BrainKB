# -*- coding: utf-8 -*-
"""JWKS-based verification of Phase 2 SSO access tokens (RS256).

Verifies tokens minted by usermanagement (the single issuer). The signature is
checked against the issuer's published JWKS (fetched + cached), and the token's
`aud` MUST equal this service's audience — a token minted for another service is
rejected here (containment enforced by `aud`, not shared secrets).

Synchronous on purpose: the sync `require_scopes` dependency must be able to call
it. The network fetch only happens on a cache miss / key rotation (10-min TTL).
"""
import logging
import threading
import time
from typing import Dict, Optional

import httpx
from jose import jwt

from core.configuration import load_environment

logger = logging.getLogger(__name__)

_env = load_environment()
JWKS_URL = _env["SSO_JWKS_URL"]
SSO_ISSUER = _env["SSO_ISSUER"]
SSO_AUDIENCE = _env["SSO_AUDIENCE"]

_CACHE_TTL = 600  # seconds
_keys: Dict[str, dict] = {}
_fetched_at: float = 0.0
_lock = threading.Lock()


def _refresh(force: bool = False) -> None:
    global _keys, _fetched_at
    with _lock:
        if not force and _keys and (time.monotonic() - _fetched_at) < _CACHE_TTL:
            return
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(JWKS_URL)
                resp.raise_for_status()
                data = resp.json()
            _keys = {k["kid"]: k for k in data.get("keys", []) if k.get("kid")}
            _fetched_at = time.monotonic()
        except Exception as e:
            logger.warning(f"JWKS fetch failed from {JWKS_URL}: {e}")


def _get_key(kid: Optional[str]) -> Optional[dict]:
    if not kid:
        return None
    if kid in _keys and (time.monotonic() - _fetched_at) < _CACHE_TTL:
        return _keys[kid]
    _refresh()
    if kid not in _keys:
        _refresh(force=True)
    return _keys.get(kid)


def verify_access_token(token: str) -> Optional[Dict]:
    """Verify an RS256 SSO access token. Returns claims on success, or None if the
    token is not RS256 / fails verification / issuer unreachable. Never raises —
    callers fall back to legacy HS256."""
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        return None
    if header.get("alg") != "RS256":
        return None
    key = _get_key(header.get("kid"))
    if not key:
        return None
    try:
        payload = jwt.decode(
            token, key, algorithms=["RS256"],
            audience=SSO_AUDIENCE, issuer=SSO_ISSUER,
        )
    except Exception as e:
        logger.info(f"RS256 token rejected: {e}")
        return None
    if payload.get("typ") not in (None, "access"):
        return None
    return payload
