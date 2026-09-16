from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.teams.constants import (
    MICROSOFT_AUTH_URL,
    MICROSOFT_TOKEN_URL,
    REQUIRED_GRAPH_SCOPES,
    TEAMS_OAUTH_SCOPES,
)
from app.connectors.teams.errors import (
    TeamsConfigurationError,
    TeamsOAuthError,
    TeamsReconnectRequiredError,
)
from app.connectors.teams.id_token import (
    MicrosoftIdTokenValidator,
    TeamsSigningKeyResolver,
    canonicalize_microsoft_guid,
)
from app.connectors.teams.transport import TeamsHttpTransport, TeamsTransport


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_token_expiry(expires_in: int | None) -> datetime | None:
    if expires_in is None:
        return None
    return utcnow() + timedelta(seconds=int(expires_in))


def normalize_scope_tokens(raw: object) -> set[str]:
    if isinstance(raw, list):
        parts = [str(item) for item in raw]
    else:
        parts = str(raw or "").split()
    normalized: set[str] = set()
    for part in parts:
        token = part.strip()
        if not token:
            continue
        normalized.add(token.rsplit("/", 1)[-1])
    return normalized


def granted_graph_scopes_sufficient(payload: dict[str, Any], claims_scp: object = None) -> bool:
    granted = normalize_scope_tokens(payload.get("scope"))
    granted.update(normalize_scope_tokens(claims_scp))
    return REQUIRED_GRAPH_SCOPES <= granted


def classify_token_error_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, str):
        return None
    return error.strip().lower() or None


class TeamsOAuthService:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http_client: httpx.Client | None = None,
        *,
        id_token_validator: MicrosoftIdTokenValidator | None = None,
        jwks_client: TeamsSigningKeyResolver | None = None,
        graph_transport_factory=None,
    ) -> None:
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._redirect_uri = redirect_uri.strip()
        if not self._client_id or not self._client_secret or not self._redirect_uri:
            raise TeamsConfigurationError("Microsoft Teams OAuth is not configured")
        self._http = http_client or httpx.Client(timeout=30.0)
        self._validator = id_token_validator or MicrosoftIdTokenValidator(jwks_client)
        self._graph_transport_factory = graph_transport_factory or (
            lambda access_token: TeamsHttpTransport(access_token, http_client=self._http)
        )

    def build_authorization_url(self, state: str, nonce: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": " ".join(TEAMS_OAUTH_SCOPES),
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
        }
        return f"{MICROSOFT_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = self._http.post(
            MICROSOFT_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
                "scope": " ".join(TEAMS_OAUTH_SCOPES),
            },
        )
        if response.status_code >= 400:
            self._raise_token_error(response, "failed to exchange authorization code")
        payload = self._token_payload(response)
        if not payload.get("refresh_token"):
            raise TeamsOAuthError("token response missing refresh token")
        if not payload.get("id_token"):
            raise TeamsOAuthError("token response missing id_token")
        return payload

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        response = self._http.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": " ".join(TEAMS_OAUTH_SCOPES),
            },
        )
        if response.status_code >= 400:
            self._raise_token_error(response, "failed to refresh access token")
        return self._token_payload(response)

    def complete_login(self, code: str, *, nonce_hash: str) -> dict[str, Any]:
        payload = self.exchange_code(code)
        identity = self._validator.validate(
            str(payload["id_token"]),
            audience=self._client_id,
            nonce_hash=nonce_hash,
        )
        if not granted_graph_scopes_sufficient(payload):
            raise TeamsOAuthError("Microsoft Teams scopes are insufficient")
        access_token = str(payload["access_token"])
        transport: TeamsTransport = self._graph_transport_factory(access_token)
        try:
            me = transport.get_me()
        finally:
            close = getattr(transport, "close", None)
            if callable(close) and transport is not self._http:
                close()
        try:
            me_id = canonicalize_microsoft_guid(me.get("id"), claim="user id")
        except TeamsOAuthError as exc:
            raise TeamsOAuthError("Microsoft Graph identity does not match") from exc
        if me_id != identity.oid:
            raise TeamsOAuthError("Microsoft Graph identity does not match")
        granted_scope = payload.get("scope")
        scopes = str(granted_scope).split() if granted_scope else list(TEAMS_OAUTH_SCOPES)
        return {
            "tenant_id": identity.tenant_id,
            "microsoft_user_id": me_id,
            "upn": str(me.get("userPrincipalName") or "").strip() or None,
            "display_name": str(me.get("displayName") or "").strip() or None,
            "scopes": scopes,
            "access_token": access_token,
            "refresh_token": str(payload["refresh_token"]),
            "token_expiry": parse_token_expiry(payload.get("expires_in")),
        }

    def _token_payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise TeamsOAuthError("token response missing access token") from exc
        if not isinstance(payload, dict) or "access_token" not in payload:
            raise TeamsOAuthError("token response missing access token")
        return payload

    def _raise_token_error(self, response: httpx.Response, fallback: str) -> None:
        error = None
        try:
            error = classify_token_error_payload(response.json())
        except ValueError:
            error = None
        if error == "invalid_grant":
            raise TeamsReconnectRequiredError("Microsoft Teams authorization was revoked")
        raise TeamsOAuthError(fallback)
