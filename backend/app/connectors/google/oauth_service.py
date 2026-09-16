from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.google.constants import GOOGLE_AUTH_URL, GOOGLE_OAUTH_SCOPES, GOOGLE_TOKEN_URL
from app.connectors.google.errors import GoogleOAuthError
from app.connectors.google.oauth_config import load_oauth_client_config


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_token_expiry(expires_in: int | None) -> datetime | None:
    if expires_in is None:
        return None
    return utcnow() + timedelta(seconds=int(expires_in))


class GoogleOAuthService:
    def __init__(
        self,
        client_file: str,
        redirect_uri: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = load_oauth_client_config(client_file)
        self._redirect_uri = redirect_uri
        self._http = http_client or httpx.Client(timeout=30.0)

    def build_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self._config["client_id"],
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_OAUTH_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = self._http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._config["client_id"],
                "client_secret": self._config["client_secret"],
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code >= 400:
            raise GoogleOAuthError("failed to exchange authorization code")
        payload = response.json()
        if "access_token" not in payload:
            raise GoogleOAuthError("token response missing access token")
        return payload

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        response = self._http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self._config["client_id"],
                "client_secret": self._config["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code >= 400:
            raise GoogleOAuthError("failed to refresh access token")
        payload = response.json()
        if "access_token" not in payload:
            raise GoogleOAuthError("refresh response missing access token")
        return payload
