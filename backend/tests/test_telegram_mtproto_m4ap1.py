"""M4AP1 regressions for numeric Telethon history bounds."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from telethon.sessions import StringSession

from app.connectors.telegram.mtproto_errors import TelegramMtprotoProviderUnavailableError
from app.connectors.telegram.mtproto_transport import TelethonMtprotoTransport

SESSION = StringSession().save()
REFERENCE = '{"entity_type":"chat","id":123}'


@dataclass
class _BoundsClient:
    bounds: dict[str, object] | None = None
    reject_none: bool = False

    async def connect(self) -> None:
        return None

    async def is_user_authorized(self) -> bool:
        return True

    def iter_messages(self, *args, **kwargs):
        self.bounds = kwargs
        if self.reject_none and (kwargs["min_id"] is None or kwargs["max_id"] is None):
            raise TypeError("history bound must be numeric")

        async def iterator():
            if False:
                yield None

        return iterator()

    async def disconnect(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("min_message_id", "max_message_id", "reverse", "expected_min", "expected_max"),
    [
        (None, None, False, 0, 0),
        (42, None, True, 42, 0),
        (None, 99, False, 0, 99),
    ],
)
async def test_fetch_history_normalizes_absent_bounds(
    monkeypatch,
    min_message_id,
    max_message_id,
    reverse,
    expected_min,
    expected_max,
) -> None:
    client = _BoundsClient(reject_none=True)
    monkeypatch.setattr(
        "app.connectors.telegram.mtproto_transport.TelegramClient",
        lambda *args: client,
    )

    page = await TelethonMtprotoTransport(123, "hash").fetch_history(
        SESSION,
        REFERENCE,
        limit=1,
        min_message_id=min_message_id,
        max_message_id=max_message_id,
        reverse=reverse,
    )

    assert page.entries == ()
    assert client.bounds is not None
    assert client.bounds["min_id"] == expected_min
    assert client.bounds["max_id"] == expected_max
    assert client.bounds["reverse"] is reverse


@pytest.mark.asyncio
async def test_none_bounds_would_fail_iterator_initialization_but_numeric_sentinels_pass(
    monkeypatch,
) -> None:
    client = _BoundsClient(reject_none=True)
    monkeypatch.setattr(
        "app.connectors.telegram.mtproto_transport.TelegramClient",
        lambda *args: client,
    )

    page = await TelethonMtprotoTransport(123, "hash").fetch_history(SESSION, REFERENCE, limit=1)

    assert page.entries == ()
    assert client.bounds["min_id"] == 0
    assert client.bounds["max_id"] == 0


@pytest.mark.asyncio
async def test_provider_type_error_taxonomy_remains_provider_unavailable(monkeypatch) -> None:
    class _FailingClient(_BoundsClient):
        def iter_messages(self, *args, **kwargs):
            self.bounds = kwargs
            raise TypeError("provider iterator failure")

    client = _FailingClient()
    monkeypatch.setattr(
        "app.connectors.telegram.mtproto_transport.TelegramClient",
        lambda *args: client,
    )

    with pytest.raises(TelegramMtprotoProviderUnavailableError):
        await TelethonMtprotoTransport(123, "hash").fetch_history(SESSION, REFERENCE, limit=1)
