"""Teams A-R1 — OIDC, uniqueness, token lifecycle, Graph contracts, 429."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.connectors.teams.constants import (
    AUTH_STATUS_RECONNECT_REQUIRED,
    CONSUMER_TENANT_ID,
    GRAPH_API_BASE,
    MICROSOFT_TOKEN_URL,
    TEAMS_OAUTH_SCOPES,
)
from app.connectors.teams.errors import (
    TeamsIdentityConflictError,
    TeamsIdentitySwitchError,
    TeamsOAuthError,
    TeamsRateLimitedError,
    TeamsReconnectRequiredError,
    TeamsWriteDefiniteError,
)
from app.connectors.teams.id_token import MicrosoftIdTokenValidator, ResolvedSigningKey
from app.connectors.teams.oauth_service import TeamsOAuthService
from app.connectors.teams.oauth_state import hash_oauth_secret
from app.connectors.teams.sync import TeamsSyncService
from app.connectors.teams.token_service import TeamsTokenService
from app.connectors.teams.transport import (
    FakeTeamsTransport,
    TeamsHttpTransport,
    parse_retry_after_seconds,
)
from app.db.models import Job, Object, TeamsAccount
from app.jobs.constants import JOB_STATUS_PENDING, JOB_TYPE_SYNC_TEAMS
from app.jobs.handlers import HANDLERS
from app.jobs.source_sync_handlers import handle_sync_teams
from app.jobs.worker import process_one_job
from app.main import app
from app.services.communication_external_action_service import CommunicationExternalActionService
from app.services.job_queue_service import JobQueueService, utcnow
from app.tools.schemas import SendMessageInput
from tests.test_teams_a import (
    CHAT_ONE,
    OTHER_MICROSOFT_USER_ID,
    TEAMS_USER_ID,
    TENANT_ID,
    _connect_account,
    _graph_message,
    _store,
    _sync_service,
    _user,
)
from tests.test_teams_a_send import _SessionProxy, _teams_object


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def teams_settings(monkeypatch: pytest.MonkeyPatch, credential_key: str) -> str:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_id", "client-id")
    monkeypatch.setattr("app.core.config.settings.microsoft_oauth_client_secret", "client-secret")
    monkeypatch.setattr(
        "app.core.config.settings.microsoft_redirect_uri",
        "http://localhost:18080/auth/teams/callback",
    )
    return credential_key


class _StubSigningKeys:
    def __init__(self, public_key, issuer: str | None = None) -> None:
        self._public_key = public_key
        self._issuer = issuer or "https://login.microsoftonline.com/{tenantid}/v2.0"

    def resolve_signing_key(self, token: str):
        return ResolvedSigningKey(key=self._public_key, issuer=self._issuer)


@pytest.fixture
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _signed_id_token(
    private_key,
    *,
    aud: str,
    tid: str,
    oid: str,
    nonce: str,
    exp: datetime | None = None,
    nbf: datetime | None = None,
    extra: dict | None = None,
    omit: set[str] | None = None,
    headers: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "aud": aud,
        "iss": f"https://login.microsoftonline.com/{tid}/v2.0",
        "tid": tid,
        "oid": oid,
        "nonce": nonce,
        "exp": int((exp or (now + timedelta(hours=1))).timestamp()),
        "nbf": int((nbf or (now - timedelta(minutes=1))).timestamp()),
        "iat": int(now.timestamp()),
    }
    if extra:
        claims.update(extra)
    for key in omit or set():
        claims.pop(key, None)
    encode_kwargs: dict = {}
    if headers:
        encode_kwargs["headers"] = headers
    return jwt.encode(claims, private_key, algorithm="RS256", **encode_kwargs)


def _validator(public_key, issuer: str | None = None) -> MicrosoftIdTokenValidator:
    return MicrosoftIdTokenValidator(_StubSigningKeys(public_key, issuer=issuer))


def test_signed_id_token_and_me_binding_succeeds(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "nonce-one"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )
    identity = _validator(public_key).validate(
        token,
        audience="client-id",
        nonce_hash=hash_oauth_secret(nonce),
    )
    assert identity.tenant_id == TENANT_ID
    assert identity.oid == TEAMS_USER_ID

    class _Me:
        def get_me(self):
            return {
                "id": TEAMS_USER_ID,
                "displayName": "Ada",
                "userPrincipalName": "ada@contoso.com",
            }

        def close(self):
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == MICROSOFT_TOKEN_URL
        return httpx.Response(
            200,
            json={
                "access_token": "access-ok",
                "refresh_token": "refresh-ok",
                "id_token": token,
                "expires_in": 3600,
                "scope": "User.Read Chat.Read ChatMessage.Send",
            },
        )

    service = TeamsOAuthService(
        "client-id",
        "client-secret",
        "http://localhost/callback",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        id_token_validator=_validator(public_key),
        graph_transport_factory=lambda _access: _Me(),
    )
    login = service.complete_login("code", nonce_hash=hash_oauth_secret(nonce))
    assert login["microsoft_user_id"] == TEAMS_USER_ID
    assert login["tenant_id"] == TENANT_ID
    assert login["display_name"] == "Ada"
    assert login["upn"] == "ada@contoso.com"


def test_id_token_rejects_wrong_signature(rsa_keys) -> None:
    _, public_key = rsa_keys
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nonce = "n"
    token = _signed_id_token(
        other,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )
    with pytest.raises(TeamsOAuthError, match="invalid"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_id_token_rejects_wrong_audience(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="other-client",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )
    with pytest.raises(TeamsOAuthError, match="audience"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_id_token_rejects_expired(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
        exp=datetime.now(UTC) - timedelta(minutes=5),
    )
    with pytest.raises(TeamsOAuthError, match="expired"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_id_token_rejects_nonce_mismatch(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce="expected",
    )
    with pytest.raises(TeamsOAuthError, match="nonce"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret("other")
        )


def test_id_token_rejects_alg_none_as_invalid(rsa_keys) -> None:
    _, public_key = rsa_keys
    import base64

    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = _b64(b'{"alg":"none"}')
    payload = _b64(
        json.dumps(
            {
                "aud": "client-id",
                "iss": f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
                "tid": TENANT_ID,
                "oid": TEAMS_USER_ID,
                "nonce": "n",
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            }
        ).encode()
    )
    token = f"{header}.{payload}."
    with pytest.raises(TeamsOAuthError, match="invalid"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret("n")
        )


def test_id_token_rejects_consumer_tenant(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=CONSUMER_TENANT_ID,
        oid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        nonce=nonce,
    )
    with pytest.raises(TeamsOAuthError, match="personal"):
        _validator(public_key).validate(
            token, audience="client-id", nonce_hash=hash_oauth_secret(nonce)
        )


def test_complete_login_rejects_me_identity_mismatch(rsa_keys) -> None:
    private_key, public_key = rsa_keys
    nonce = "n"
    token = _signed_id_token(
        private_key,
        aud="client-id",
        tid=TENANT_ID,
        oid=TEAMS_USER_ID,
        nonce=nonce,
    )

    class _Me:
        def get_me(self):
            return {"id": OTHER_MICROSOFT_USER_ID, "displayName": "Ada"}

        def close(self):
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-ok",
                "refresh_token": "refresh-ok",
                "id_token": token,
                "expires_in": 3600,
                "scope": "User.Read Chat.Read ChatMessage.Send",
            },
        )

    service = TeamsOAuthService(
        "client-id",
        "client-secret",
        "http://localhost/callback",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        id_token_validator=_validator(public_key),
        graph_transport_factory=lambda _access: _Me(),
    )
    with pytest.raises(TeamsOAuthError, match="does not match"):
        service.complete_login("code", nonce_hash=hash_oauth_secret(nonce))


def test_same_external_identity_cannot_bind_two_users(db_session, teams_settings) -> None:
    first = _user(db_session, "one")
    second = _user(db_session, "two")
    _connect_account(db_session, teams_settings, first.id)
    with pytest.raises(TeamsIdentityConflictError):
        _connect_account(db_session, teams_settings, second.id)


def test_different_identity_cannot_silently_overwrite(db_session, teams_settings) -> None:
    user = _user(db_session)
    account = _connect_account(
        db_session,
        teams_settings,
        user.id,
        sync_start=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )
    original_start = account.sync_state["sync_start_at"]
    store = _store(db_session, teams_settings)
    with pytest.raises(TeamsIdentitySwitchError, match="disconnect"):
        store.upsert_tokens(
            user.id,
            microsoft_user_id=OTHER_MICROSOFT_USER_ID,
            tenant_id=TENANT_ID,
            upn="other@contoso.com",
            display_name="Other",
            scopes=list(TEAMS_OAUTH_SCOPES),
            access_token="new-access",
            refresh_token="new-refresh",
            token_expiry=datetime.now(UTC) + timedelta(hours=1),
        )
    db_session.refresh(account)
    assert account.microsoft_user_id == TEAMS_USER_ID
    assert account.sync_state["sync_start_at"] == original_start


def test_same_identity_reconnect_preserves_sync_state(db_session, teams_settings) -> None:
    user = _user(db_session)
    account = _connect_account(
        db_session,
        teams_settings,
        user.id,
        sync_start=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
    )
    store = _store(db_session, teams_settings)
    store.mark_reconnect_required(account)
    preserved = dict(account.sync_state)
    store.upsert_tokens(
        user.id,
        microsoft_user_id=TEAMS_USER_ID,
        tenant_id=TENANT_ID,
        upn="user@contoso.com",
        display_name="Secretary User",
        scopes=list(TEAMS_OAUTH_SCOPES),
        access_token="rotated-access",
        refresh_token="rotated-refresh",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.refresh(account)
    assert account.auth_status != AUTH_STATUS_RECONNECT_REQUIRED
    assert account.sync_state == preserved
    assert store.get_access_token(account) == "rotated-access"
    assert store.get_refresh_token(account) == "rotated-refresh"


def test_disconnect_preserves_objects_and_disables_sync(
    db_session, teams_settings, issue_bearer
) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.chats = [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]
    fake.messages_by_chat[CHAT_ONE] = [
        _graph_message(
            message_id="keep-me",
            chat_id=CHAT_ONE,
            body="hello",
            created="2026-09-13T12:01:00Z",
            from_id="other",
        )
    ]
    _sync_service(db_session, teams_settings, fake).sync_account(account.id, user.id)
    objects_before = list(db_session.scalars(select(Object).where(Object.user_id == user.id)))
    assert len(objects_before) == 1
    JobQueueService(db_session).ensure_recurring_source_job(
        JOB_TYPE_SYNC_TEAMS, account.id, user.id
    )
    old_start = account.sync_state["sync_start_at"]
    bearer = issue_bearer(user.id)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.post(
            "/auth/teams/disconnect",
            headers={"Authorization": f"Bearer {bearer}"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert db_session.scalar(select(TeamsAccount).where(TeamsAccount.user_id == user.id)) is None
    objects_after = list(db_session.scalars(select(Object).where(Object.user_id == user.id)))
    assert {obj.id for obj in objects_after} == {obj.id for obj in objects_before}
    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_TEAMS))
    assert job is None or job.status == "done"
    fresh = _connect_account(db_session, teams_settings, user.id)
    assert not fresh.sync_state.get("chats")
    assert fresh.sync_state["sync_start_at"] != old_start


class _CountingOAuth:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.calls = 0
        self.payload = payload or {
            "access_token": "new-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        }
        self.error = error

    def refresh_access_token(self, refresh_token: str) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.payload)


def test_sync_and_send_refresh_expired_token_through_same_service(
    db_session, teams_settings, monkeypatch
) -> None:
    user = _user(db_session)
    account = _connect_account(db_session, teams_settings, user.id)
    account.token_expiry = datetime.now(UTC) - timedelta(minutes=5)
    db_session.flush()
    store = _store(db_session, teams_settings)
    oauth = _CountingOAuth()
    token_service = TeamsTokenService(db_session, store, oauth)
    first = token_service.acquire_access_token(account)
    assert first == "new-access"
    assert oauth.calls == 1
    assert store.get_refresh_token(account) == "rotated-refresh"
    account.token_expiry = datetime.now(UTC) - timedelta(minutes=5)
    db_session.flush()
    inbound = _teams_object(db_session, user.id, account)
    captured_tokens: list[str] = []

    class _CaptureTransport(FakeTeamsTransport):
        def __init__(self, access_token: str, http_client=None) -> None:
            super().__init__()
            captured_tokens.append(access_token)
            self.send_message_response = _graph_message(
                message_id="out-refresh",
                chat_id=CHAT_ONE,
                body="hi",
                created="2026-09-13T14:00:00Z",
                from_id=TEAMS_USER_ID,
            )

    monkeypatch.setattr(
        "app.services.communication_external_action_service.TeamsHttpTransport",
        _CaptureTransport,
    )
    service = CommunicationExternalActionService(
        db_session,
        user.id,
        teams_oauth_service=oauth,  # type: ignore[arg-type]
        attempt_session_factory=lambda: _SessionProxy(db_session),
    )
    frozen = service.prepare_send_message(
        SendMessageInput(body="hi", conversation_object_id=inbound.id)
    )
    result = service.send_message(frozen)
    assert result.delivery_status == "sent"
    assert captured_tokens == ["new-access"]
    assert oauth.calls == 2


def test_invalid_grant_marks_reconnect_and_does_not_hammer_token_endpoint(
    db_session, teams_settings
) -> None:
    user = _user(db_session)
    account = _connect_account(db_session, teams_settings, user.id)
    account.token_expiry = datetime.now(UTC) - timedelta(minutes=5)
    db_session.flush()
    store = _store(db_session, teams_settings)
    oauth = _CountingOAuth(error=TeamsReconnectRequiredError("revoked"))
    token_service = TeamsTokenService(db_session, store, oauth)
    with pytest.raises(TeamsReconnectRequiredError):
        token_service.acquire_access_token(account)
    db_session.refresh(account)
    assert account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED
    assert oauth.calls == 1
    with pytest.raises(TeamsReconnectRequiredError):
        token_service.acquire_access_token(account)
    assert oauth.calls == 1
    fake = FakeTeamsTransport()
    result = TeamsSyncService(
        db_session,
        store,
        JobQueueService(db_session),
        transport=fake,
        oauth_service=oauth,  # type: ignore[arg-type]
    ).sync_account(account.id, user.id)
    assert result["synchronized"] == 0
    assert fake.list_chats_calls == 0
    handle_sync_teams(db_session, None, {"account_id": str(account.id)}, user.id)
    assert oauth.calls == 1
    assert fake.list_chats_calls == 0


def test_connections_expose_reconnect_required(db_session, teams_settings, issue_bearer) -> None:
    user = _user(db_session)
    account = _connect_account(db_session, teams_settings, user.id)
    _store(db_session, teams_settings).mark_reconnect_required(account)
    db_session.flush()
    bearer = issue_bearer(user.id)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.get("/connections", headers={"Authorization": f"Bearer {bearer}"})
    app.dependency_overrides.clear()
    teams = response.json()["teams"]
    assert teams["connected"] is True
    assert teams["reconnect_required"] is True
    dumped = json.dumps(teams)
    assert "access-token" not in dumped
    assert "refresh-token" not in dumped


def test_message_list_orders_by_created_and_follows_nextlink(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    captured: list[str] = []
    next_link = f"{GRAPH_API_BASE}/chats/{CHAT_ONE}/messages?$skiptoken=page2"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        captured.append(url)
        if request.url.path.endswith("/me/chats") or request.url.path.endswith("/chats"):
            return httpx.Response(
                200,
                json={"value": [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]},
            )
        if "skiptoken=page2" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        _graph_message(
                            message_id="newer-created",
                            chat_id=CHAT_ONE,
                            body="page2",
                            created="2026-09-13T12:02:00Z",
                            from_id="other",
                        )
                    ]
                },
            )
        query = parse_qs(urlparse(url).query)
        if query.get("$orderby") == ["createdDateTime desc"] and query.get("$top") == ["50"]:
            return httpx.Response(
                200,
                json={
                    "value": [
                        _graph_message(
                            message_id="newest-created",
                            chat_id=CHAT_ONE,
                            body="page1",
                            created="2026-09-13T12:03:00Z",
                            from_id="other",
                        )
                    ],
                    "@odata.nextLink": next_link,
                },
            )
        # Provider default lastModifiedDateTime order would surface an old edited message first.
        return httpx.Response(
            200,
            json={
                "value": [
                    _graph_message(
                        message_id="old-edited",
                        chat_id=CHAT_ONE,
                        body="stale",
                        created="2026-09-13T11:00:00Z",
                        from_id="other",
                    )
                ],
                "@odata.nextLink": next_link,
            },
        )

    transport = TeamsHttpTransport(
        "tok",
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    result = TeamsSyncService(
        db_session,
        _store(db_session, teams_settings),
        JobQueueService(db_session),
        transport=transport,
    ).sync_account(account.id, user.id)
    assert result["created"] == 2
    ids = {
        obj.metadata_["message_id"]
        for obj in db_session.scalars(select(Object).where(Object.user_id == user.id))
    }
    assert ids == {"newest-created", "newer-created"}
    assert "old-edited" not in ids
    first_messages = next(url for url in captured if "/messages" in url and "skiptoken" not in url)
    query = parse_qs(urlparse(first_messages).query)
    assert query["$orderby"] == ["createdDateTime desc"]
    assert query["$top"] == ["50"]
    assert any("skiptoken=page2" in url for url in captured)


def test_429_read_does_not_advance_watermark_or_hot_loop(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/messages" in url:
            calls["count"] += 1
            return httpx.Response(429, headers={"Retry-After": "32"}, json={"error": {"code": "TooManyRequests"}})
        return httpx.Response(
            200,
            json={"value": [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]},
        )

    transport = TeamsHttpTransport(
        "tok",
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    with pytest.raises(TeamsRateLimitedError) as exc:
        TeamsSyncService(
            db_session,
            _store(db_session, teams_settings),
            JobQueueService(db_session),
            transport=transport,
        ).sync_account(account.id, user.id)
    assert exc.value.retry_after_seconds == 32
    assert calls["count"] == 1
    db_session.refresh(account)
    assert (account.sync_state or {}).get("chats") in (None, {})


def test_429_write_is_definite_and_does_not_loop() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429, headers={"Retry-After": "9"}, json={"error": {"code": "TooManyRequests"}})

    transport = TeamsHttpTransport(
        "tok",
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    with pytest.raises(TeamsWriteDefiniteError, match="rate limited"):
        transport.send_message(CHAT_ONE, "hi")
    assert calls["count"] == 1


def test_retry_after_parsing_and_mark_retry_schedule(db_session) -> None:
    assert parse_retry_after_seconds("15") == 15
    assert parse_retry_after_seconds("7200") == 3600
    assert parse_retry_after_seconds("not-a-date") is None
    user = _user(db_session)
    queue = JobQueueService(db_session)
    job = queue.enqueue(JOB_TYPE_SYNC_TEAMS, {"account_id": str(uuid4())}, user.id)
    job.attempts = 1
    db_session.flush()
    run_after = utcnow() + timedelta(seconds=45)
    queue.mark_retry(job.id, "Microsoft Graph rate limited", retryable=True, run_after=run_after)
    db_session.refresh(job)
    assert job.status == JOB_STATUS_PENDING
    assert job.run_after == run_after


def test_worker_schedules_retry_after_without_hot_loop(monkeypatch) -> None:
    from sqlalchemy import delete
    from sqlalchemy.orm import Session as SASession

    from app.db.engine import engine
    from app.db.models import Job as JobModel
    from app.users.bootstrap import BOOTSTRAP_USER_ID

    conn = engine.connect()
    trans = conn.begin()
    session = SASession(bind=conn)
    session.execute(
        delete(JobModel).where(
            JobModel.type == JOB_TYPE_SYNC_TEAMS,
            JobModel.status == JOB_STATUS_PENDING,
        )
    )
    job_id = JobQueueService(session).enqueue(
        JOB_TYPE_SYNC_TEAMS, {"account_id": str(uuid4())}, BOOTSTRAP_USER_ID
    ).id
    trans.commit()
    conn.close()

    def boom(*_args, **_kwargs):
        raise TeamsRateLimitedError("Microsoft Graph rate limited", retry_after_seconds=41)

    monkeypatch.setitem(HANDLERS, JOB_TYPE_SYNC_TEAMS, boom)
    before = datetime.now(UTC)
    assert process_one_job(include_types={JOB_TYPE_SYNC_TEAMS}) is True
    conn = engine.connect()
    session = SASession(bind=conn)
    stored = session.get(JobModel, job_id)
    assert stored is not None
    assert stored.status == JOB_STATUS_PENDING
    assert stored.run_after is not None
    assert stored.run_after >= before + timedelta(seconds=40)
    conn.close()
    assert process_one_job(include_types={JOB_TYPE_SYNC_TEAMS}) is False
    conn = engine.connect()
    trans = conn.begin()
    session = SASession(bind=conn)
    session.execute(delete(JobModel).where(JobModel.id == job_id))
    trans.commit()
    conn.close()
