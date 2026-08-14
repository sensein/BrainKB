# -*- coding: utf-8 -*-
"""RS256 single-issuer SSO tokens (auth Phase 2).

usermanagement is the sole issuer. A single login mints a short-lived REFRESH
token (``aud=brainkb-auth``); clients EXCHANGE it for narrow, short-lived
per-service ACCESS tokens (``aud=<service>``). Services verify tokens against
the published JWKS and require ``aud == <their service>``, so a token minted for
one service cannot be replayed against another — containment is enforced by the
audience claim, not by separate shared secrets.

Keys are RS256. The private key is read from ``USERMANAGEMENT_JWT_PRIVATE_KEY_PEM``
(a PEM string) or ``USERMANAGEMENT_JWT_PRIVATE_KEY_FILE`` (a path). If neither is
set, an EPHEMERAL key is generated on first use (dev only) and a warning is
logged — such tokens do not survive a process restart. Provision a persistent
key for any real deployment so the JWKS ``kid`` is stable.
"""
import base64
import hashlib
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from jose import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.configuration import config

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"
REFRESH_AUDIENCE = "brainkb-auth"  # audience of the login/refresh token
REFRESH_TYP = "refresh"
ACCESS_TYP = "access"

# Lazily initialized key material (module-level cache for the process lifetime).
_private_pem: Optional[str] = None
_public_pem: Optional[str] = None
_kid: Optional[str] = None


def _load_or_generate() -> None:
    global _private_pem, _public_pem, _kid
    if _private_pem is not None:
        return

    pem = config.jwt_private_key_pem
    if not pem and config.jwt_private_key_file:
        try:
            with open(config.jwt_private_key_file, "r") as fh:
                pem = fh.read()
        except OSError as e:
            logger.warning(f"Could not read USERMANAGEMENT_JWT_PRIVATE_KEY_FILE: {e}")

    if not pem:
        # No key configured. Fall back to a process-shared ephemeral key: persist
        # it to a file so ALL uvicorn workers (and restarts) use the SAME key —
        # otherwise each worker signs with its own key and cross-worker
        # verification fails. Production should set an explicit key instead.
        cache_path = os.getenv(
            "USERMANAGEMENT_JWT_EPHEMERAL_KEY_PATH",
            os.path.join(tempfile.gettempdir(), "brainkb_um_sso_key.pem"),
        )
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as fh:
                    pem = fh.read()
                logger.warning(
                    "Using cached EPHEMERAL RS256 key at %s. Set "
                    "USERMANAGEMENT_JWT_PRIVATE_KEY_PEM/_FILE for production.",
                    cache_path,
                )
            except OSError:
                pem = None
        if not pem:
            logger.warning(
                "No USERMANAGEMENT_JWT_PRIVATE_KEY_PEM/_FILE configured — generating "
                "an EPHEMERAL RS256 key at %s (shared across workers). Set a "
                "persistent key for production.",
                cache_path,
            )
            new_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = new_priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
            try:
                # Atomic create: if another worker won the race, read theirs.
                fd = os.open(cache_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as fh:
                    fh.write(pem)
            except FileExistsError:
                with open(cache_path, "r") as fh:
                    pem = fh.read()
            except OSError as e:
                logger.warning(f"Could not persist ephemeral key to {cache_path}: {e}")

    priv = serialization.load_pem_private_key(pem.encode(), password=None)
    pub = priv.public_key()
    _private_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    _public_pem = pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    # Stable kid derived from the public key so it changes only when the key does.
    _kid = hashlib.sha256(_public_pem.encode()).hexdigest()[:16]


def _b64u_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def jwks() -> Dict[str, Any]:
    """Public JWK Set for token verification (served at /.well-known/jwks.json)."""
    _load_or_generate()
    pub = serialization.load_pem_public_key(_public_pem.encode())
    nums = pub.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": ALGORITHM,
                "kid": _kid,
                "n": _b64u_uint(nums.n),
                "e": _b64u_uint(nums.e),
            }
        ]
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_refresh_token(
    *,
    email: str,
    profile_id: Optional[int],
    roles: List[str],
    scopes: List[str],
    auth_source: str = "password",
    expires_minutes: Optional[int] = None,
) -> str:
    """Mint the login/refresh token (aud=brainkb-auth). Not accepted by services;
    only exchangeable at /api/auth/exchange for a per-service access token.
    expires_minutes overrides the default refresh TTL (the web flow passes a longer
    one so the browser session can silently refresh over several days)."""
    _load_or_generate()
    now = _now()
    ttl = expires_minutes if (expires_minutes and expires_minutes > 0) else config.refresh_token_ttl_min
    claims = {
        "iss": config.jwt_issuer,
        "aud": REFRESH_AUDIENCE,
        "sub": email,
        "typ": REFRESH_TYP,
        "profile_id": profile_id,
        "roles": roles,
        "scopes": scopes,
        "auth_source": auth_source,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(claims, _private_pem, algorithm=ALGORITHM, headers={"kid": _kid})


def create_access_token(
    *,
    audience: str,
    email: str,
    profile_id: Optional[int],
    roles: List[str],
    scopes: List[str],
    auth_source: str = "password",
    jwt_user_id: Optional[int] = None,
) -> str:
    """Mint a narrow, short-lived access token for a single service (aud=<service>)."""
    _load_or_generate()
    now = _now()
    claims = {
        "iss": config.jwt_issuer,
        "aud": audience,
        "sub": email,
        "typ": ACCESS_TYP,
        "user_id": jwt_user_id,
        "profile_id": profile_id,
        "roles": roles,
        "scopes": scopes,
        "auth_source": auth_source,
        "iat": now,
        "exp": now + timedelta(minutes=config.access_token_ttl_min),
    }
    return jwt.encode(claims, _private_pem, algorithm=ALGORITHM, headers={"kid": _kid})


def verify_access_token(token: str, audience: str) -> Optional[Dict[str, Any]]:
    """Verify an RS256 access token for ``audience`` using our OWN public key
    (usermanagement is the issuer, so no network/JWKS fetch is needed). Returns
    the claims on success, or None if it is not a valid RS256 access token for
    this audience. Never raises — callers fall back to legacy HS256."""
    _load_or_generate()
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        return None
    if header.get("alg") != ALGORITHM:
        return None
    try:
        payload = jwt.decode(
            token, _public_pem, algorithms=[ALGORITHM],
            audience=audience, issuer=config.jwt_issuer,
        )
    except Exception:
        return None
    if payload.get("typ") not in (None, ACCESS_TYP):
        return None
    return payload


def verify_refresh_token(token: str) -> Dict[str, Any]:
    """Validate a refresh token (signature, iss, aud, exp). Raises jose errors on
    failure. Verified with our own public key (no network)."""
    _load_or_generate()
    payload = jwt.decode(
        token,
        _public_pem,
        algorithms=[ALGORITHM],
        audience=REFRESH_AUDIENCE,
        issuer=config.jwt_issuer,
    )
    if payload.get("typ") != REFRESH_TYP:
        raise ValueError("not a refresh token")
    return payload


def access_token_ttl_seconds() -> int:
    return config.access_token_ttl_min * 60


def refresh_token_ttl_seconds() -> int:
    return config.refresh_token_ttl_min * 60
