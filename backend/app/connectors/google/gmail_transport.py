import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.connectors.google.api_errors import raise_for_google_response
from app.connectors.google.constants import GMAIL_API_BASE
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.errors import GoogleApiError, GoogleConnectorError, GoogleOAuthError
from app.connectors.google.oauth_service import GoogleOAuthService, parse_token_expiry


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class GmailMessagePage:
    message_ids: list[str]
    next_page_token: str | None


class GmailTransport:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http = http_client or httpx.Client(timeout=30.0)

    def list_message_ids_page(
        self,
        access_token: str,
        user_id: str,
        query: str,
        max_results: int,
        page_token: str | None = None,
    ) -> GmailMessagePage:
        params: dict[str, object] = {
            "q": query,
            "maxResults": max_results,
            "includeSpamTrash": False,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        response = self._http.get(
            f"{GMAIL_API_BASE}/users/{user_id}/messages",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            raise GoogleApiError("failed to list gmail messages")
        payload = response.json()
        messages = payload.get("messages", [])
        message_ids = [str(item["id"]) for item in messages if item.get("id")]
        next_token = payload.get("nextPageToken")
        return GmailMessagePage(
            message_ids=message_ids,
            next_page_token=str(next_token) if next_token else None,
        )

    def list_message_ids(
        self,
        access_token: str,
        user_id: str,
        query: str,
        max_results: int,
    ) -> list[str]:
        return self.list_message_ids_page(
            access_token=access_token,
            user_id=user_id,
            query=query,
            max_results=max_results,
        ).message_ids

    def get_message(self, access_token: str, user_id: str, message_id: str) -> dict[str, Any]:
        response = self._http.get(
            f"{GMAIL_API_BASE}/users/{user_id}/messages/{message_id}",
            params={"format": "full"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            raise GoogleApiError(f"failed to fetch gmail message {message_id}")
        return response.json()

    def send_message(self, access_token: str, user_id: str, raw: str) -> dict[str, Any]:
        response = self._http.post(
            f"{GMAIL_API_BASE}/users/{user_id}/messages/send",
            json={"raw": raw},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        raise_for_google_response(response, "send_message")
        payload = _json_object_payload(response, "send_message")
        message_id = payload.get("id")
        if not isinstance(message_id, str) or not message_id.strip():
            raise GoogleApiError(
                "send_message returned a malformed response",
                operation="send_message",
                status_code=response.status_code,
                retryable=True,
            )
        return payload

    def get_attachment(
        self,
        access_token: str,
        user_id: str,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        response = self._http.get(
            f"{GMAIL_API_BASE}/users/{user_id}/messages/{message_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            raise GoogleApiError(f"failed to fetch gmail attachment {attachment_id}")
        payload = response.json()
        data = payload.get("data")
        if not data:
            return b""
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))

    def fetch_account_email(self, access_token: str, user_id: str = "me") -> str:
        response = self._http.get(
            f"{GMAIL_API_BASE}/users/{user_id}/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            raise GoogleApiError("failed to fetch gmail profile")
        payload = response.json()
        email = payload.get("emailAddress")
        if not email:
            raise GoogleApiError("gmail profile missing email address")
        return str(email)


def _json_object_payload(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        raise GoogleApiError(
            f"{operation} returned a malformed response",
            operation=operation,
            status_code=response.status_code,
            retryable=True,
        )
    return payload


class GoogleTokenManager:
    def __init__(
        self,
        session: Session,
        account_store: GoogleAccountStore,
        oauth_service: GoogleOAuthService,
    ) -> None:
        self._session = session
        self._account_store = account_store
        self._oauth_service = oauth_service

    def get_valid_access_token(self, account_id: UUID, user_id: UUID) -> str:
        snapshot = self._account_store.load_credential_snapshot(account_id, user_id)
        if snapshot is None:
            raise GoogleConnectorError("google account not found")

        if (
            snapshot.access_token
            and snapshot.token_expiry
            and snapshot.token_expiry > utcnow() + timedelta(seconds=60)
        ):
            return snapshot.access_token

        if snapshot.refresh_token is None:
            raise GoogleOAuthError("google account is missing refresh token")

        self._session.commit()

        payload = self._oauth_service.refresh_access_token(snapshot.refresh_token)
        new_access = str(payload["access_token"])
        new_refresh = payload.get("refresh_token")
        new_expiry = parse_token_expiry(payload.get("expires_in"))

        account = self._account_store.get_by_id_for_user(account_id, user_id)
        if account is None:
            raise GoogleConnectorError("google account not found")
        self._account_store.update_tokens_from_refresh(
            account,
            access_token=new_access,
            refresh_token=str(new_refresh) if new_refresh else None,
            token_expiry=new_expiry,
        )
        self._session.flush()
        return new_access
