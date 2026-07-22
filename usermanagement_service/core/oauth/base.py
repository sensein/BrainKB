"""OAuth provider abstraction. Each provider knows:
  - how to build its authorize URL (with PKCE when supported)
  - how to exchange an authorization code for tokens
  - how to fetch user info and normalize it into OAuthUserInfo

The router (core/routers/oauth.py) is provider-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None  # seconds
    id_token: Optional[str] = None
    scope: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OAuthUserInfo:
    """Normalized user profile from an OAuth provider."""
    provider: str
    provider_user_id: str
    email: Optional[str]
    name: Optional[str]
    # Provider-specific identifiers we want to persist to UserProfile.
    orcid_id: Optional[str] = None
    github_username: Optional[str] = None
    # Any other raw fields; stored in Web_oauth_identity.raw_profile.
    raw: Dict[str, Any] = field(default_factory=dict)


class OAuthProvider:
    """Base class. Subclasses override the four hooks below."""

    name: str = ""
    supports_pkce: bool = False
    default_scopes: str = ""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: Optional[str] = None) -> str:
        raise NotImplementedError

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: Optional[str] = None) -> TokenResponse:
        raise NotImplementedError

    async def fetch_userinfo(self, *, access_token: str, token_response: TokenResponse) -> OAuthUserInfo:
        raise NotImplementedError
