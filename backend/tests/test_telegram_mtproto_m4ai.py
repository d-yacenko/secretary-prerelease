"""M4AI read-path error taxonomy regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from telethon.errors import AuthKeyError
from telethon.errors.common import AuthKeyNotFound
from telethon.sessions import StringSession

from app.api.telegram_mtproto import _provider_response
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoProviderUnavailableError,
)
from app.connectors.telegram.mtproto_transport import TelethonMtprotoTransport

SESSION = StringSession().save()
REFERENCE = '{"entity_type":"chat","id":123}'


class _ReadClient:
    def __init__(self, *, iterator_error: Exception | None = None, call_error: Exception | None = None):
        self.iterator_error = iterator_error
        self.call_error = call_error
        self.disconnect_calls = 0

    async def connect(self) -> None:
        return None

    async def is_user_authorized(self) -> bool:
        return True

    def iter_messages(self, *args, **kwargs):
        async def iterator():
            if self.iterator_error is not None:
                raise self.iterator_error
            if False:
                yield None

        return iterator()

    def iter_dialogs(self, **kwargs):
        async def iterator():
            if self.iterator_error is not None:
                raise self.iterator_error
            if False:
                yield None

        return iterator()

    async def __call__(self, request):
        if self.call_error is not None:
            raise self.call_error
        return SimpleNamespace(filters=[])

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _ReadClient) -> None:
    monkeypatch.setattr(
        "app.connectors.telegram.mtproto_transport.TelegramClient",
        lambda *args: client,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [AuthKeyNotFound(), AuthKeyError(None, "auth key failure")])
async def test_history_real_auth_key_errors_remain_authorization_invalid(monkeypatch, error) -> None:
    client = _ReadClient(iterator_error=error)
    _patch_client(monkeypatch, client)

    with pytest.raises(TelegramMtprotoAuthorizationInvalidError):
        await TelethonMtprotoTransport(123, "hash").fetch_history(
            SESSION, REFERENCE, limit=1
        )
    assert client.disconnect_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("conversion"), TypeError("conversion")])
async def test_history_non_auth_conversion_errors_are_provider_unavailable(monkeypatch, error) -> None:
    client = _ReadClient(iterator_error=error)
    _patch_client(monkeypatch, client)

    with pytest.raises(TelegramMtprotoProviderUnavailableError) as caught:
        await TelethonMtprotoTransport(123, "hash").fetch_history(
            SESSION, REFERENCE, limit=1
        )
    assert str(caught.value) == "Telegram history provider is temporarily unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("discover_groups", {"limit": 10}),
        ("discover_folders", {"limit": 10}),
    ],
)
@pytest.mark.parametrize("error", [ValueError("read"), TypeError("read")])
async def test_discovery_non_auth_read_errors_are_provider_unavailable(
    monkeypatch, method, kwargs, error
) -> None:
    client = _ReadClient(iterator_error=error, call_error=error)
    _patch_client(monkeypatch, client)

    with pytest.raises(TelegramMtprotoProviderUnavailableError):
        await getattr(TelethonMtprotoTransport(123, "hash"), method)(SESSION, **kwargs)
    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_discovery_auth_key_error_is_authorization_invalid(monkeypatch) -> None:
    client = _ReadClient(iterator_error=AuthKeyError(None, "auth key failure"))
    _patch_client(monkeypatch, client)

    with pytest.raises(TelegramMtprotoAuthorizationInvalidError):
        await TelethonMtprotoTransport(123, "hash").discover_groups(SESSION, 10)


def test_provider_response_is_neutral_and_preserves_retry_after() -> None:
    response = _provider_response(TelegramMtprotoProviderUnavailableError("hidden", 37))
    assert response.status_code == 503
    assert response.detail == "Telegram provider is temporarily unavailable"
    assert response.headers == {"Retry-After": "37"}
