"""Telegram Depth A1 — isolated encrypted MTProto account authorization."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoChallengeExpiredError,
    TelegramMtprotoIdentityConflictError,
    TelegramMtprotoInvalidCodeError,
    TelegramMtprotoInvalidPasswordError,
    TelegramMtprotoProviderUnavailableError,
)
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoAuthorizationResult,
    TelegramMtprotoAuthState,
    TelegramMtprotoIdentity,
    TelethonMtprotoTransport,
)
from app.core.config import settings
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoAuthChallenge, User
from app.services.telegram_mtproto_auth_service import TelegramMtprotoAuthService

KEY = Fernet.generate_key().decode()
PHONE = "+79991234567"
PHONE_CODE_HASH = "provider-phone-code-hash"
TEMP_SESSION = "temporary-string-session"
FINAL_SESSION = "final-string-session"


class FakeMtprotoTransport:
    def __init__(self) -> None:
        self.code_error: Exception | None = None
        self.password_error: Exception | None = None
        self.password_required = False
        self.identity = TelegramMtprotoIdentity(telegram_user_id=987654321, username="alice", display_name="Alice")
        self.start_calls: list[str] = []

    async def send_login_code(self, phone: str) -> TelegramMtprotoAuthState:
        self.start_calls.append(phone)
        return TelegramMtprotoAuthState(PHONE, PHONE_CODE_HASH, TEMP_SESSION)

    async def submit_code(
        self, state: TelegramMtprotoAuthState, code: str
    ) -> TelegramMtprotoAuthorizationResult:
        if self.code_error is not None:
            raise self.code_error
        if self.password_required:
            return TelegramMtprotoAuthorizationResult(
                TelegramMtprotoAuthState(state.phone, state.phone_code_hash, "temp-2fa-session"),
                None,
                password_required=True,
            )
        return TelegramMtprotoAuthorizationResult(
            TelegramMtprotoAuthState(state.phone, state.phone_code_hash, FINAL_SESSION),
            self.identity,
        )

    async def submit_password(
        self, state: TelegramMtprotoAuthState, password: str
    ) -> TelegramMtprotoAuthorizationResult:
        if self.password_error is not None:
            raise self.password_error
        return TelegramMtprotoAuthorizationResult(
            TelegramMtprotoAuthState(state.phone, state.phone_code_hash, FINAL_SESSION),
            self.identity,
        )


def _user(db_session, name: str) -> User:
    user = User(id=uuid4(), display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _service(db_session, fake: FakeMtprotoTransport) -> TelegramMtprotoAuthService:
    return TelegramMtprotoAuthService(
        db_session,
        transport_factory=lambda: fake,
        encryption=CredentialEncryption(KEY),
    )


@pytest.fixture(autouse=True)
def configured_mtproto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_api_id", 123456)
    monkeypatch.setattr(settings, "telegram_api_hash", "api-hash-secret")
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)


async def test_auth_start_persists_only_encrypted_challenge_material(db_session) -> None:
    user = _user(db_session, "start")
    fake = FakeMtprotoTransport()
    challenge = await _service(db_session, fake).start(user.id, " +7 999-123-4567 ")

    row = db_session.get(TelegramMtprotoAuthChallenge, challenge.id)
    assert row is not None
    assert fake.start_calls == [PHONE]
    assert PHONE not in row.auth_state_encrypted
    assert PHONE_CODE_HASH not in row.auth_state_encrypted
    assert TEMP_SESSION not in row.auth_state_encrypted
    state = json.loads(CredentialEncryption(KEY).decrypt(row.auth_state_encrypted))
    assert state == {"phone": PHONE, "phone_code_hash": PHONE_CODE_HASH, "session": TEMP_SESSION}
    assert "code" not in state
    assert "password" not in state


async def test_only_one_active_challenge_per_user(db_session) -> None:
    user = _user(db_session, "replace")
    fake = FakeMtprotoTransport()
    service = _service(db_session, fake)

    first = await service.start(user.id, PHONE)
    second = await service.start(user.id, PHONE)

    assert db_session.get(TelegramMtprotoAuthChallenge, first.id) is None
    assert db_session.get(TelegramMtprotoAuthChallenge, second.id) is not None
    assert db_session.scalar(
        select(func.count()).select_from(TelegramMtprotoAuthChallenge).where(
            TelegramMtprotoAuthChallenge.user_id == user.id
        )
    ) == 1


async def test_expired_challenge_fails_closed(db_session) -> None:
    user = _user(db_session, "expired")
    fake = FakeMtprotoTransport()
    service = _service(db_session, fake)
    challenge = await service.start(user.id, PHONE)
    row = db_session.get(TelegramMtprotoAuthChallenge, challenge.id)
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    with pytest.raises(TelegramMtprotoChallengeExpiredError):
        await service.submit_code(user.id, challenge.id, "12345")
    assert db_session.get(TelegramMtprotoAuthChallenge, challenge.id) is None


async def test_code_authorization_persists_encrypted_final_session(db_session) -> None:
    user = _user(db_session, "authorized")
    fake = FakeMtprotoTransport()
    service = _service(db_session, fake)
    challenge = await service.start(user.id, PHONE)

    result = await service.submit_code(user.id, challenge.id, "12345")

    assert result.status == "authorized"
    account = db_session.scalar(
        select(TelegramMtprotoAccount).where(TelegramMtprotoAccount.user_id == user.id)
    )
    assert account is not None
    assert account.telegram_user_id == fake.identity.telegram_user_id
    assert FINAL_SESSION not in account.session_encrypted
    assert CredentialEncryption(KEY).decrypt(account.session_encrypted) == FINAL_SESSION
    assert db_session.get(TelegramMtprotoAuthChallenge, challenge.id) is None


async def test_password_required_preserves_only_updated_encrypted_state(db_session) -> None:
    user = _user(db_session, "password")
    fake = FakeMtprotoTransport()
    fake.password_required = True
    service = _service(db_session, fake)
    challenge = await service.start(user.id, PHONE)

    result = await service.submit_code(user.id, challenge.id, "login-code-secret")

    assert result.status == "password_required"
    assert result.account is None
    row = db_session.get(TelegramMtprotoAuthChallenge, challenge.id)
    assert row is not None
    raw = CredentialEncryption(KEY).decrypt(row.auth_state_encrypted)
    assert "login-code-secret" not in raw
    assert "password" not in raw
    assert PHONE_CODE_HASH not in row.auth_state_encrypted
    assert "temp-2fa-session" not in row.auth_state_encrypted
    assert json.loads(raw)["phone_code_hash"] == PHONE_CODE_HASH
    assert json.loads(raw)["session"] == "temp-2fa-session"


async def test_password_completion_persists_account_and_consumes_challenge(db_session) -> None:
    user = _user(db_session, "2fa")
    fake = FakeMtprotoTransport()
    fake.password_required = True
    service = _service(db_session, fake)
    challenge = await service.start(user.id, PHONE)
    await service.submit_code(user.id, challenge.id, "12345")

    account = await service.submit_password(user.id, challenge.id, "two-factor-password")

    assert account.telegram_user_id == fake.identity.telegram_user_id
    assert db_session.get(TelegramMtprotoAuthChallenge, challenge.id) is None
    stored = db_session.scalar(
        select(TelegramMtprotoAccount).where(TelegramMtprotoAccount.user_id == user.id)
    )
    assert stored is not None
    assert "two-factor-password" not in stored.session_encrypted


@pytest.mark.parametrize(
    ("attribute", "error"),
    [
        ("code_error", TelegramMtprotoInvalidCodeError("invalid")),
        ("password_error", TelegramMtprotoInvalidPasswordError("invalid")),
    ],
)
async def test_provider_auth_errors_are_typed_without_raw_payloads(
    db_session, attribute: str, error: Exception
) -> None:
    user = _user(db_session, "invalid")
    fake = FakeMtprotoTransport()
    service = _service(db_session, fake)
    challenge = await service.start(user.id, PHONE)
    setattr(fake, attribute, error)

    with pytest.raises(type(error)) as exc_info:
        if attribute == "code_error":
            await service.submit_code(user.id, challenge.id, "secret-code")
        else:
            await service.submit_password(user.id, challenge.id, "secret-password")
    assert "secret" not in str(exc_info.value)


async def test_telegram_identity_cannot_bind_to_two_users(db_session) -> None:
    first = _user(db_session, "first")
    second = _user(db_session, "second")
    fake = FakeMtprotoTransport()
    first_service = _service(db_session, fake)
    first_challenge = await first_service.start(first.id, PHONE)
    await first_service.submit_code(first.id, first_challenge.id, "12345")

    second_challenge = await _service(db_session, fake).start(second.id, PHONE)
    with pytest.raises(TelegramMtprotoIdentityConflictError):
        await _service(db_session, fake).submit_code(second.id, second_challenge.id, "12345")


async def test_only_one_mtproto_account_per_user(db_session) -> None:
    user = _user(db_session, "one-account")
    fake = FakeMtprotoTransport()
    service = _service(db_session, fake)
    first_challenge = await service.start(user.id, PHONE)
    await service.submit_code(user.id, first_challenge.id, "12345")

    fake.identity = TelegramMtprotoIdentity(telegram_user_id=123, username="other", display_name="Other")
    second_challenge = await service.start(user.id, PHONE)
    with pytest.raises(TelegramMtprotoIdentityConflictError):
        await service.submit_code(user.id, second_challenge.id, "12345")


def test_mtproto_config_absent_returns_controlled_503(auth_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_api_id", 0)
    monkeypatch.setattr(settings, "telegram_api_hash", "")
    response = auth_client.post("/telegram/mtproto/auth/start", json={"phone": PHONE})
    assert response.status_code == 503
    assert response.json() == {"detail": "Telegram MTProto is not configured"}
    assert PHONE not in response.text


@pytest.mark.parametrize(
    ("path", "payload", "secret"),
    [
        (
            "/telegram/mtproto/auth/start",
            {"phone": "+" + "7" * 32},
            "+" + "7" * 32,
        ),
        (
            "/telegram/mtproto/auth/code",
            {"challenge_id": str(uuid4()), "code": "1" * 33},
            "1" * 33,
        ),
        (
            "/telegram/mtproto/auth/password",
            {"challenge_id": str(uuid4()), "password": "p" * 257},
            "p" * 257,
        ),
    ],
)
def test_overlength_mtproto_fields_have_sanitized_422(
    auth_client, path: str, payload: dict, secret: str
) -> None:
    response = auth_client.post(path, json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid Telegram MTProto request"}
    assert secret not in response.text


@pytest.mark.parametrize(
    ("path", "payload", "secret"),
    [
        (
            "/telegram/mtproto/auth/start",
            {"phone": 79991234567},
            "79991234567",
        ),
        (
            "/telegram/mtproto/auth/code",
            {"challenge_id": str(uuid4()), "code": 12345},
            "12345",
        ),
        (
            "/telegram/mtproto/auth/password",
            {"challenge_id": str(uuid4()), "password": 123456},
            "123456",
        ),
    ],
)
def test_nonstring_mtproto_fields_have_sanitized_422(
    auth_client, path: str, payload: dict, secret: str
) -> None:
    response = auth_client.post(path, json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid Telegram MTProto request"}
    assert secret not in response.text


def test_malformed_phone_is_a_nonsensitive_400(auth_client) -> None:
    malformed_phone = "+not-a-phone-79991234567"
    response = auth_client.post(
        "/telegram/mtproto/auth/start", json={"phone": malformed_phone}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Telegram phone number is invalid"}
    assert malformed_phone not in response.text


def test_api_responses_are_sanitized_for_authorization_and_status(
    auth_client, monkeypatch
) -> None:
    fake = FakeMtprotoTransport()
    fake.password_required = True
    monkeypatch.setattr(
        "app.services.telegram_mtproto_auth_service._build_transport", lambda: fake
    )

    start = auth_client.post("/telegram/mtproto/auth/start", json={"phone": PHONE})
    assert start.status_code == 200
    challenge_id = start.json()["challenge_id"]
    code = auth_client.post(
        "/telegram/mtproto/auth/code",
        json={"challenge_id": challenge_id, "code": "login-code-secret"},
    )
    assert code.status_code == 200
    assert code.json() == {"status": "password_required", "account": None}
    password = auth_client.post(
        "/telegram/mtproto/auth/password",
        json={"challenge_id": challenge_id, "password": "two-factor-password"},
    )
    assert password.status_code == 200
    status_response = auth_client.get("/telegram/mtproto/status")
    assert status_response.status_code == 200

    for response in (start, code, password, status_response):
        for secret in (
            PHONE,
            PHONE_CODE_HASH,
            TEMP_SESSION,
            FINAL_SESSION,
            "login-code-secret",
            "two-factor-password",
            "api-hash-secret",
        ):
            assert secret not in response.text


def test_migration_0043_is_the_single_alembic_head() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0046"]


@pytest.mark.asyncio
async def test_telethon_transport_disconnects_after_success(monkeypatch) -> None:
    clients: list[_FakeTelethonClient] = []

    def factory(*args):
        client = _FakeTelethonClient()
        clients.append(client)
        return client

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", factory)
    result = await TelethonMtprotoTransport(123, "api-hash-secret").send_login_code(PHONE)
    assert result.phone == PHONE
    assert clients[0].disconnect_calls == 1


@pytest.mark.asyncio
async def test_telethon_transport_disconnects_after_failure(monkeypatch) -> None:
    clients: list[_FakeTelethonClient] = []

    def factory(*args):
        client = _FakeTelethonClient(fail=True)
        clients.append(client)
        return client

    monkeypatch.setattr("app.connectors.telegram.mtproto_transport.TelegramClient", factory)
    with pytest.raises(TelegramMtprotoProviderUnavailableError) as exc_info:
        await TelethonMtprotoTransport(123, "api-hash-secret").send_login_code(PHONE)
    assert clients[0].disconnect_calls == 1
    assert "provider payload" not in str(exc_info.value)


class _FakeTelethonClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.session = SimpleNamespace(save=lambda: TEMP_SESSION)
        self.disconnect_calls = 0

    async def connect(self) -> None:
        return None

    async def send_code_request(self, phone: str):
        if self.fail:
            raise RuntimeError("provider payload must not escape")
        return SimpleNamespace(phone_code_hash=PHONE_CODE_HASH)

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
