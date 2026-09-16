from typing import Any, Protocol, Self

import httpx

from app.connectors.telegram.constants import TELEGRAM_API_HOST
from app.connectors.telegram.errors import (
    TelegramConfigurationError,
    TelegramWriteDefiniteError,
    TelegramWriteUncertainError,
)


class TelegramTransport(Protocol):
    def get_me(self) -> dict[str, Any]:
        ...

    def set_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        allowed_updates: tuple[str, ...],
    ) -> bool:
        ...

    def send_message(
        self,
        *,
        business_connection_id: str,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


class TelegramHttpTransport:
    def __init__(
        self,
        bot_token: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        token = bot_token.strip()
        if not token:
            raise TelegramConfigurationError("telegram bot token is not configured")
        self._bot_token = token
        owns_client = http_client is None
        self._http_client = http_client or httpx.Client(follow_redirects=False, timeout=30.0)
        self._owns_client = owns_client

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def get_me(self) -> dict[str, Any]:
        payload = self._request_json("getMe")
        if not isinstance(payload, dict):
            raise TelegramConfigurationError("telegram getMe response malformed")
        return payload

    def set_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        allowed_updates: tuple[str, ...],
    ) -> bool:
        payload = self._request_json(
            "setWebhook",
            json_body={
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": list(allowed_updates),
            },
        )
        if payload is not True:
            raise TelegramConfigurationError("telegram setWebhook response malformed")
        return True

    def send_message(
        self,
        *,
        business_connection_id: str,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "business_connection_id": business_connection_id,
            "chat_id": _telegram_chat_id_value(chat_id),
            "text": text,
        }
        if reply_to_message_id is not None:
            body["reply_parameters"] = {
                "message_id": _telegram_message_id_value(reply_to_message_id),
            }
        payload = self._request_write_json("sendMessage", json_body=body)
        if not isinstance(payload, dict):
            raise TelegramWriteUncertainError("telegram sendMessage response malformed")
        return payload

    def _api_url(self, method: str) -> str:
        return f"{TELEGRAM_API_HOST}/bot{self._bot_token}/{method}"

    def _request_json(self, method: str, json_body: dict[str, Any] | None = None) -> Any:
        try:
            response = self._http_client.post(self._api_url(method), json=json_body)
        except httpx.RequestError as exc:
            raise TelegramConfigurationError("telegram request failed") from exc
        return self._parse_ok_payload(response, write=False)

    def _request_write_json(self, method: str, json_body: dict[str, Any]) -> Any:
        try:
            response = self._http_client.post(self._api_url(method), json=json_body)
        except httpx.RequestError as exc:
            raise TelegramWriteUncertainError("telegram write request failed") from exc
        return self._parse_ok_payload(response, write=True)

    def _parse_ok_payload(self, response: httpx.Response, *, write: bool) -> Any:
        if 300 <= response.status_code < 400:
            if write:
                raise TelegramWriteDefiniteError("telegram redirect rejected")
            raise TelegramConfigurationError("telegram redirect rejected")
        if 400 <= response.status_code < 500:
            if write:
                raise TelegramWriteDefiniteError("telegram write rejected")
            raise TelegramConfigurationError("telegram request rejected")
        if response.status_code >= 500:
            if write:
                raise TelegramWriteUncertainError("telegram write response uncertain")
            raise TelegramConfigurationError("telegram request failed")
        if not response.content:
            if write:
                raise TelegramWriteUncertainError("telegram sendMessage response malformed")
            raise TelegramConfigurationError("telegram response malformed")
        try:
            payload = response.json()
        except ValueError as exc:
            if write:
                raise TelegramWriteUncertainError("telegram sendMessage response malformed") from exc
            raise TelegramConfigurationError("telegram response malformed") from exc
        if not isinstance(payload, dict):
            if write:
                raise TelegramWriteUncertainError("telegram sendMessage response malformed")
            raise TelegramConfigurationError("telegram response malformed")
        if payload.get("ok") is not True:
            error_code = payload.get("error_code")
            if write:
                if isinstance(error_code, int) and 400 <= error_code < 500:
                    raise TelegramWriteDefiniteError("telegram write rejected")
                raise TelegramWriteUncertainError("telegram write response uncertain")
            raise TelegramConfigurationError("telegram request rejected")
        return payload.get("result")


class FakeTelegramTransport:
    def __init__(self) -> None:
        self.get_me_response: dict[str, Any] = {
            "id": 1000,
            "is_bot": True,
            "username": "secretary_bot",
            "first_name": "Secretary",
            "can_connect_to_business": True,
        }
        self.send_message_calls: list[dict[str, Any]] = []
        self.send_message_response: dict[str, Any] | None = None
        self.send_message_error: Exception | None = None
        self.set_webhook_calls: list[dict[str, Any]] = []

    def get_me(self) -> dict[str, Any]:
        return dict(self.get_me_response)

    def set_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        allowed_updates: tuple[str, ...],
    ) -> bool:
        self.set_webhook_calls.append(
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": list(allowed_updates),
            }
        )
        return True

    def send_message(
        self,
        *,
        business_connection_id: str,
        chat_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "business_connection_id": business_connection_id,
            "chat_id": chat_id,
            "text": text,
        }
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        self.send_message_calls.append(payload)
        if self.send_message_error is not None:
            raise self.send_message_error
        if self.send_message_response is not None:
            return dict(self.send_message_response)
        message_id = 9000 + len(self.send_message_calls)
        result: dict[str, Any] = {
            "message_id": message_id,
            "business_connection_id": business_connection_id,
            "chat": {"id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id, "type": "private"},
            "text": text,
            "date": 1_700_000_000,
        }
        if reply_to_message_id is not None:
            result["reply_to_message"] = {"message_id": int(reply_to_message_id)}
        return result

    def close(self) -> None:
        return None


def _telegram_chat_id_value(chat_id: str) -> int | str:
    text = str(chat_id).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def _telegram_message_id_value(message_id: str) -> int:
    text = str(message_id).strip()
    if not text.lstrip("-").isdigit():
        raise TelegramWriteDefiniteError("telegram message_id is invalid")
    return int(text)
