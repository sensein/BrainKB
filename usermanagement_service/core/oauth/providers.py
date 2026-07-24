"""Concrete OAuth providers: GitHub, ORCID, Globus.

All three follow the OAuth 2.0 authorization-code flow. ORCID and Globus also
support OIDC userinfo endpoints and PKCE; GitHub does not support PKCE and
uses its own /user endpoint for profile data."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Optional, Dict

import httpx

from core.configuration import config
from core.oauth.base import OAuthProvider, TokenResponse, OAuthUserInfo

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class GitHubProvider(OAuthProvider):
    name = "github"
    supports_pkce = False
    default_scopes = "read:user user:email"

    AUTHORIZE = "https://github.com/login/oauth/authorize"
    TOKEN = "https://github.com/login/oauth/access_token"
    USER = "https://api.github.com/user"
    EMAILS = "https://api.github.com/user/emails"

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: Optional[str] = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.default_scopes,
            "state": state,
            "allow_signup": "true",
        }
        return f"{self.AUTHORIZE}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: Optional[str] = None) -> TokenResponse:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {"Accept": "application/json"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(self.TOKEN, data=data, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        if "access_token" not in payload:
            raise ValueError(f"GitHub token exchange failed: {payload}")
        return TokenResponse(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_in=payload.get("expires_in"),
            scope=payload.get("scope"),
            raw=payload,
        )

    async def fetch_userinfo(self, *, access_token: str, token_response: TokenResponse) -> OAuthUserInfo:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            u = await client.get(self.USER, headers=headers)
            u.raise_for_status()
            user = u.json()
            email = user.get("email")
            if not email:
                # user.email can be null if hidden; fetch verified primary from /user/emails
                e = await client.get(self.EMAILS, headers=headers)
                if e.status_code == 200:
                    for row in e.json():
                        if row.get("primary") and row.get("verified"):
                            email = row.get("email")
                            break
        return OAuthUserInfo(
            provider=self.name,
            provider_user_id=str(user["id"]),
            email=email,
            name=user.get("name") or user.get("login"),
            github_username=user.get("login"),
            raw=user,
        )


class ORCIDProvider(OAuthProvider):
    """ORCID OIDC. Uses openid+email+profile scopes to get the userinfo endpoint."""

    name = "orcid"
    supports_pkce = True
    default_scopes = "openid email profile"

    def __init__(self, client_id: str, client_secret: str, base_url: str = "https://orcid.org"):
        super().__init__(client_id, client_secret)
        self.base_url = base_url.rstrip("/")

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.base_url}/oauth/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.base_url}/oauth/token"

    @property
    def userinfo_endpoint(self) -> str:
        return f"{self.base_url}/oauth/userinfo"

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: Optional[str] = None) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": self.default_scopes,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.authorize_endpoint}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: Optional[str] = None) -> TokenResponse:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(self.token_endpoint, data=data, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        if "access_token" not in payload:
            raise ValueError(f"ORCID token exchange failed: {payload}")
        return TokenResponse(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_in=payload.get("expires_in"),
            id_token=payload.get("id_token"),
            scope=payload.get("scope"),
            raw=payload,
        )

    async def fetch_userinfo(self, *, access_token: str, token_response: TokenResponse) -> OAuthUserInfo:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(self.userinfo_endpoint, headers=headers)
            resp.raise_for_status()
            user = resp.json()
        # ORCID userinfo returns `sub` = the ORCID iD
        orcid = user.get("sub")
        given = user.get("given_name") or ""
        family = user.get("family_name") or ""
        full_name = user.get("name") or (f"{given} {family}".strip() or None)
        return OAuthUserInfo(
            provider=self.name,
            provider_user_id=orcid,
            email=user.get("email"),
            name=full_name,
            orcid_id=orcid,
            raw=user,
        )


class GlobusProvider(OAuthProvider):
    """Globus Auth. Uses OIDC with PKCE."""

    name = "globus"
    supports_pkce = True
    default_scopes = "openid email profile"

    AUTHORIZE = "https://auth.globus.org/v2/oauth2/authorize"
    TOKEN = "https://auth.globus.org/v2/oauth2/token"
    USERINFO = "https://auth.globus.org/v2/oauth2/userinfo"

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: Optional[str] = None) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": self.default_scopes,
            "redirect_uri": redirect_uri,
            "state": state,
            "access_type": "online",
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.AUTHORIZE}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: Optional[str] = None) -> TokenResponse:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        auth = (self.client_id, self.client_secret)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(self.TOKEN, data=data, auth=auth)
            resp.raise_for_status()
            payload = resp.json()
        if "access_token" not in payload:
            raise ValueError(f"Globus token exchange failed: {payload}")
        return TokenResponse(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_in=payload.get("expires_in"),
            id_token=payload.get("id_token"),
            scope=payload.get("scope"),
            raw=payload,
        )

    async def fetch_userinfo(self, *, access_token: str, token_response: TokenResponse) -> OAuthUserInfo:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(self.USERINFO, headers=headers)
            resp.raise_for_status()
            user = resp.json()
        return OAuthUserInfo(
            provider=self.name,
            provider_user_id=user.get("sub"),
            email=user.get("email") or user.get("preferred_username"),
            name=user.get("name"),
            raw=user,
        )


def _build_registry() -> Dict[str, OAuthProvider]:
    return {
        "github": GitHubProvider(
            client_id=config.github_client_id or "",
            client_secret=config.github_client_secret or "",
        ),
        "orcid": ORCIDProvider(
            client_id=config.orcid_client_id or "",
            client_secret=config.orcid_client_secret or "",
            base_url=config.orcid_base_url,
        ),
        "globus": GlobusProvider(
            client_id=config.globus_client_id or "",
            client_secret=config.globus_client_secret or "",
        ),
    }


REGISTRY: Dict[str, OAuthProvider] = _build_registry()


def get_provider(name: str) -> OAuthProvider:
    p = REGISTRY.get(name.lower())
    if p is None:
        raise KeyError(f"Unknown OAuth provider: {name}")
    return p
