"""Teams A — auth, connection, sync, objects, inbox, temporal exclusion."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.config import teams_is_configured
from app.connectors.teams.constants import (
    GRAPH_API_BASE,
    TEAMS_OAUTH_SCOPES,
)
from app.connectors.teams.errors import TeamsOAuthError, TeamsSyncError
from app.connectors.teams.html_text import teams_body_to_plain_text
from app.connectors.teams.normalize import build_external_id
from app.connectors.teams.oauth_state import TeamsOAuthStateService, hash_oauth_state
from app.connectors.teams.sync import TeamsSyncService
from app.connectors.teams.transport import FakeTeamsTransport, TeamsHttpTransport
from app.db.models import Object, TeamsAccount, TeamsOAuthState, User
from app.jobs.constants import JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL
from app.main import app
from app.services.job_queue_service import JobQueueService
from app.services.personal_relevance_evidence_service import PersonalRelevanceEvidenceService
from app.services.recent_source_service import RecentSourceService
from app.services.temporal_signals_constants import TEMPORAL_ELIGIBLE_PROVIDERS
from app.services.temporal_signals_service import object_is_temporal_source_eligible
from app.source_sync.constants import SOURCE_TEAMS, SUPPORTED_SOURCE_KEYS
from app.tools.registry import TOOL_REGISTRY

TENANT_ID = "11111111-1111-1111-1111-111111111111"
TEAMS_USER_ID = "22222222-2222-2222-2222-222222222222"
OTHER_MICROSOFT_USER_ID = "33333333-3333-3333-3333-333333333333"
CHAT_ONE = "19:one-on-one@thread.v2"
CHAT_GROUP = "19:group@thread.v2"
CHAT_MEETING = "19:meeting@thread.v2"


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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _user(session: Session, name: str = "teams-user") -> User:
    user = User(id=uuid4(), display_name=name)
    session.add(user)
    session.flush()
    return user


def _store(session: Session, credential_key: str) -> TeamsAccountStore:
    return TeamsAccountStore(session, TeamsAccountStore.build_encryption(credential_key))


def _connect_account(
    session: Session,
    credential_key: str,
    user_id,
    *,
    sync_start: datetime | None = None,
) -> TeamsAccount:
    store = _store(session, credential_key)
    account = store.upsert_tokens(
        user_id,
        microsoft_user_id=TEAMS_USER_ID,
        tenant_id=TENANT_ID,
        upn="user@contoso.com",
        display_name="Secretary User",
        scopes=list(TEAMS_OAUTH_SCOPES),
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=_utcnow() + timedelta(hours=1),
    )
    if sync_start is not None:
        store.update_sync_state(
            account.id,
            user_id,
            {"sync_start_at": sync_start.isoformat(), "chats": {}},
        )
    session.flush()
    return account


def _graph_message(
    *,
    message_id: str,
    chat_id: str,
    body: str,
    created: str,
    from_id: str,
    html: bool = False,
    reply_to: str | None = None,
) -> dict:
    payload = {
        "id": message_id,
        "chatId": chat_id,
        "messageType": "message",
        "createdDateTime": created,
        "lastModifiedDateTime": created,
        "from": {"user": {"id": from_id, "displayName": "Sender"}},
        "body": {
            "contentType": "html" if html else "text",
            "content": body,
        },
    }
    if reply_to:
        payload["replyToId"] = reply_to
    return payload


def _graph_reply_with_quote(
    *,
    message_id: str,
    chat_id: str,
    body: str,
    created: str,
    from_id: str,
    quoted_message_id: str,
    reply_to_id: object = None,
    attachment_content: object | None = None,
    include_attachment: bool = True,
) -> dict:
    payload = _graph_message(
        message_id=message_id,
        chat_id=chat_id,
        body=body,
        created=created,
        from_id=from_id,
        html=True,
    )
    payload["replyToId"] = reply_to_id
    payload["body"] = {
        "contentType": "html",
        "content": f'<p>{body}</p><attachment id="quoted-message-ref"></attachment>',
    }
    if include_attachment:
        content = attachment_content
        if content is None:
            content = json.dumps({"messageId": quoted_message_id})
        payload["attachments"] = [
            {
                "id": "quoted-message-ref",
                "contentType": "messageReference",
                "content": content,
            }
        ]
    return payload


def test_migration_0040_revises_0039(db_session) -> None:
    versions = sorted(
        path.name
        for path in (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*.py")
        if path.name[0].isdigit()
    )
    assert versions[-1].startswith("0042")
    module_path = Path(__file__).resolve().parents[1] / "alembic/versions/0040_teams_accounts.py"
    text_src = module_path.read_text(encoding="utf-8")
    assert 'revision: str = "0040"' in text_src
    assert 'down_revision: str | None = "0039"' in text_src
    inspector = inspect(db_session.bind)
    tables = set(inspector.get_table_names())
    assert "teams_accounts" in tables
    assert "teams_oauth_states" in tables
    uniques = {item["name"] for item in inspector.get_unique_constraints("teams_accounts")}
    assert "uq_teams_accounts_user_id" in uniques
    assert "uq_teams_accounts_tenant_microsoft_user" in uniques
    account_cols = {col["name"] for col in inspector.get_columns("teams_accounts")}
    assert "auth_status" in account_cols
    oauth_cols = {col["name"] for col in inspector.get_columns("teams_oauth_states")}
    assert "nonce_hash" in oauth_cols


def test_unconfigured_app_boots_and_teams_unavailable(auth_client) -> None:
    assert teams_is_configured() is False
    response = auth_client.post("/auth/teams/authorization-url")
    assert response.status_code == 503
    connections = auth_client.get("/connections").json()["teams"]
    assert connections["configured"] is False
    assert connections["connected"] is False
    dumped = json.dumps(connections)
    assert "access_token" not in dumped
    assert "refresh_token" not in dumped
    assert "client_secret" not in dumped


def test_oauth_scopes_are_least_privilege() -> None:
    assert TEAMS_OAUTH_SCOPES == [
        "openid",
        "profile",
        "offline_access",
        "User.Read",
        "Chat.Read",
        "ChatMessage.Send",
    ]
    joined = " ".join(TEAMS_OAUTH_SCOPES)
    assert "ChannelMessage" not in joined
    assert "Team.Read" not in joined
    assert "Chat.ReadWrite" not in joined
    assert "Chat.Read.All" not in joined


def test_oauth_state_ttl_and_replay(db_session, teams_settings) -> None:
    user = _user(db_session)
    service = TeamsOAuthStateService(db_session)
    created = service.create_state(user.id)
    row = db_session.scalar(select(TeamsOAuthState))
    assert row is not None
    assert row.state_hash != created.state
    assert row.nonce_hash != created.nonce
    owner = service.consume_state(created.state)
    assert owner.user_id == user.id
    assert owner.nonce_hash == row.nonce_hash
    with pytest.raises(TeamsOAuthError, match="already used"):
        service.consume_state(created.state)
    expired = service.create_state(user.id)
    expired_row = db_session.scalar(
        select(TeamsOAuthState).where(TeamsOAuthState.state_hash == hash_oauth_state(expired.state))
    )
    assert expired_row is not None
    expired_row.expires_at = _utcnow() - timedelta(minutes=1)
    db_session.flush()
    with pytest.raises(TeamsOAuthError, match="expired"):
        service.consume_state(expired.state)


def test_authorization_url_uses_organizations_authority(db_session, teams_settings, issue_bearer) -> None:
    user = _user(db_session)
    bearer = issue_bearer(user.id)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.post(
            "/auth/teams/authorization-url",
            headers={"Authorization": f"Bearer {bearer}"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    assert url.startswith("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize")
    assert "Chat.Read" in url
    assert "ChatMessage.Send" in url
    assert "nonce=" in url
    assert "client-secret" not in url


def test_connections_serialize_safe_teams_fields(db_session, teams_settings, issue_bearer) -> None:
    user = _user(db_session)
    _connect_account(db_session, teams_settings, user.id)
    bearer = issue_bearer(user.id)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        response = client.get("/connections", headers={"Authorization": f"Bearer {bearer}"})
    app.dependency_overrides.clear()
    body = response.json()
    teams = body["teams"]
    assert teams["configured"] is True
    assert teams["connected"] is True
    assert teams["display_name"] == "Secretary User"
    assert teams["upn"] == "user@contoso.com"
    assert teams["tenant_id"] == TENANT_ID
    assert teams["reconnect_required"] is False
    dumped = json.dumps(body)
    assert "access-token" not in dumped
    assert "refresh-token" not in dumped
    assert "client-secret" not in dumped


def test_html_body_sanitizes_to_safe_text() -> None:
    text = teams_body_to_plain_text(
        content_type="html",
        content="<p>Hello <script>alert(1)</script><b>Ada</b></p>",
    )
    assert "script" not in text.lower()
    assert "Hello" in text
    assert "Ada" in text


def _sync_service(session, credential_key: str, fake: FakeTeamsTransport) -> TeamsSyncService:
    store = _store(session, credential_key)
    return TeamsSyncService(
        session,
        store,
        JobQueueService(session),
        transport=fake,
        now_factory=_utcnow,
    )


def test_sync_one_on_one_and_group_inbound(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.me = {"id": TEAMS_USER_ID, "displayName": "Secretary User"}
    fake.chats = [
        {
            "id": CHAT_ONE,
            "chatType": "oneOnOne",
            "members": [
                {"userId": TEAMS_USER_ID, "displayName": "Secretary User"},
                {"userId": "other", "displayName": "Petrushin"},
            ],
        },
        {
            "id": CHAT_GROUP,
            "chatType": "group",
            "topic": "Project room",
            "members": [],
        },
        {"id": CHAT_MEETING, "chatType": "meeting", "topic": "Standup"},
    ]
    fake.messages_by_chat = {
        CHAT_ONE: [
            _graph_message(
                message_id="m-one",
                chat_id=CHAT_ONE,
                body="<p>hello</p>",
                created="2026-09-13T12:01:00Z",
                from_id="other",
                html=True,
            )
        ],
        CHAT_GROUP: [
            _graph_message(
                message_id="m-group",
                chat_id=CHAT_GROUP,
                body="group hello",
                created="2026-09-13T12:02:00Z",
                from_id="other",
            )
        ],
        CHAT_MEETING: [
            _graph_message(
                message_id="m-meet",
                chat_id=CHAT_MEETING,
                body="should ignore",
                created="2026-09-13T12:03:00Z",
                from_id="other",
            )
        ],
    }
    result = _sync_service(db_session, teams_settings, fake).sync_account(account.id, user.id)
    assert result["created"] == 2
    objects = list(db_session.scalars(select(Object).where(Object.user_id == user.id)))
    assert {obj.external_id for obj in objects} == {
        build_external_id(TENANT_ID, TEAMS_USER_ID, CHAT_ONE, "m-one"),
        build_external_id(TENANT_ID, TEAMS_USER_ID, CHAT_GROUP, "m-group"),
    }
    assert all(obj.provider == "teams" and obj.kind == "chat_message" for obj in objects)
    one = next(obj for obj in objects if obj.metadata_["chat_id"] == CHAT_ONE)
    assert one.metadata_["chat_type"] == "oneOnOne"
    assert one.metadata_["chat_display_title"] == "Petrushin"
    assert "script" not in (one.body or "")
    assert "<p>" not in (one.body or "")
    dumped = json.dumps(one.metadata_)
    assert "access-token" not in dumped
    assert "raw" not in dumped
    assert fake.mark_read_calls == []


def test_meeting_and_channel_paths_are_ignored(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.chats = [
        {"id": CHAT_MEETING, "chatType": "meeting"},
        {"id": "19:channel@thread.tacv2", "chatType": "unknown"},
    ]
    fake.messages_by_chat[CHAT_MEETING] = [
        _graph_message(
            message_id="m-meet",
            chat_id=CHAT_MEETING,
            body="nope",
            created="2026-09-13T12:01:00Z",
            from_id="other",
        )
    ]
    _sync_service(db_session, teams_settings, fake).sync_account(account.id, user.id)
    assert db_session.scalars(select(Object).where(Object.user_id == user.id)).all() == []


def test_initial_connection_does_not_backfill_history(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.chats = [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]
    fake.messages_by_chat[CHAT_ONE] = [
        _graph_message(
            message_id="old",
            chat_id=CHAT_ONE,
            body="history",
            created="2026-09-13T11:59:00Z",
            from_id="other",
        ),
        _graph_message(
            message_id="new",
            chat_id=CHAT_ONE,
            body="fresh",
            created="2026-09-13T12:00:00Z",
            from_id="other",
        ),
    ]
    _sync_service(db_session, teams_settings, fake).sync_account(account.id, user.id)
    objects = list(db_session.scalars(select(Object).where(Object.user_id == user.id)))
    assert [obj.metadata_["message_id"] for obj in objects] == ["new"]


def test_overlap_repoll_is_idempotent(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.chats = [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]
    fake.messages_by_chat[CHAT_ONE] = [
        _graph_message(
            message_id="m1",
            chat_id=CHAT_ONE,
            body="hello",
            created="2026-09-13T12:01:00Z",
            from_id="other",
        )
    ]
    service = _sync_service(db_session, teams_settings, fake)
    first = service.sync_account(account.id, user.id)
    second = service.sync_account(account.id, user.id)
    assert first["created"] == 1
    assert second["created"] == 0
    objects = list(db_session.scalars(select(Object).where(Object.user_id == user.id)))
    assert len(objects) == 1


def test_own_user_outbound_materialized_but_excluded_from_inbox(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.chats = [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]
    fake.messages_by_chat[CHAT_ONE] = [
        _graph_message(
            message_id="own",
            chat_id=CHAT_ONE,
            body="I sent this",
            created="2026-09-13T12:01:00Z",
            from_id=TEAMS_USER_ID,
        ),
        _graph_message(
            message_id="in",
            chat_id=CHAT_ONE,
            body="inbound",
            created="2026-09-13T12:02:00Z",
            from_id="other",
        ),
    ]
    _sync_service(db_session, teams_settings, fake).sync_account(account.id, user.id)
    objects = list(db_session.scalars(select(Object).where(Object.user_id == user.id)))
    assert len(objects) == 2
    own = next(obj for obj in objects if obj.metadata_["message_id"] == "own")
    inbound = next(obj for obj in objects if obj.metadata_["message_id"] == "in")
    assert own.metadata_["direction"] == "outbound"
    assert inbound.metadata_["direction"] == "inbound"
    feed = RecentSourceService(db_session, user.id).list_page()
    ids = {item.id for item in feed.items}
    assert inbound.id in ids
    assert own.id not in ids


def test_teams_is_temporal_eligible_a(db_session, teams_settings) -> None:
    assert SOURCE_TEAMS in SUPPORTED_SOURCE_KEYS
    assert "teams" in TEMPORAL_ELIGIBLE_PROVIDERS
    user = _user(db_session)
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="teams",
        external_id="t|u|c|m",
        origin="source",
        state="observed",
        title="Teams",
        body="hello",
        metadata_={
            "teams_user_id": TEAMS_USER_ID,
            "sender_id": OTHER_MICROSOFT_USER_ID,
            "direction": "inbound",
        },
        occurred_at=_utcnow(),
    )
    db_session.add(obj)
    db_session.flush()
    assert object_is_temporal_source_eligible(obj) is True
    assert JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL != "sync_teams"


def test_teams_participation_uses_connected_microsoft_identity(
    db_session, teams_settings
) -> None:
    user = _user(db_session)
    account = _connect_account(db_session, teams_settings, user.id)
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="teams",
        external_id="t|u|c|participation",
        origin="source",
        state="observed",
        title="Teams",
        body="завтра в 10",
        metadata_={
            "teams_user_id": account.microsoft_user_id,
            "sender_id": OTHER_MICROSOFT_USER_ID,
            "direction": "inbound",
        },
        occurred_at=_utcnow(),
    )
    db_session.add(obj)
    db_session.flush()
    snapshot = PersonalRelevanceEvidenceService.build(db_session).build_snapshot(
        user.id, [obj.id]
    )
    assert snapshot.objects[0].user_participation_roles == ("direct_recipient",)


def test_page_bound_does_not_advance_watermark(db_session, teams_settings) -> None:
    user = _user(db_session)
    floor = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    account = _connect_account(db_session, teams_settings, user.id, sync_start=floor)
    fake = FakeTeamsTransport()
    fake.chats = [{"id": CHAT_ONE, "chatType": "oneOnOne", "members": []}]
    fake.messages_by_chat[CHAT_ONE] = [
        _graph_message(
            message_id=f"m{i}",
            chat_id=CHAT_ONE,
            body="n",
            created="2026-09-13T12:01:00Z",
            from_id="other",
        )
        for i in range(3)
    ]

    class _Paged(FakeTeamsTransport):
        def list_chat_messages(self, chat_id: str, url: str | None = None) -> dict:
            self.list_messages_calls.append(chat_id)
            return {
                "value": [dict(item) for item in self.messages_by_chat[chat_id]],
                "@odata.nextLink": f"{GRAPH_API_BASE}/chats/{chat_id}/messages?$skiptoken=1",
            }

    paged = _Paged()
    paged.chats = fake.chats
    paged.messages_by_chat = fake.messages_by_chat
    service = TeamsSyncService(
        db_session,
        _store(db_session, teams_settings),
        JobQueueService(db_session),
        transport=paged,
        max_message_pages_per_chat=1,
    )
    with pytest.raises(TeamsSyncError, match="bound"):
        service.sync_account(account.id, user.id)
    db_session.refresh(account)
    assert (account.sync_state or {}).get("chats") in (None, {})


def test_graph_http_transport_uses_v1_paths() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"method": request.method, "url": str(request.url), "body": request.read()})
        return httpx.Response(201, json={"id": "mid", "chatId": CHAT_ONE, "body": {"contentType": "text", "content": "hi"}})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    transport = TeamsHttpTransport("tok", http_client=client)
    transport.send_message(CHAT_ONE, "hi")
    transport.reply_with_quote(CHAT_ONE, "src", "reply")
    assert captured[0]["url"] == f"{GRAPH_API_BASE}/chats/19%3Aone-on-one%40thread.v2/messages"
    assert json.loads(captured[0]["body"]) == {
        "body": {"contentType": "text", "content": "hi"}
    }
    assert captured[1]["url"].endswith("/messages/replyWithQuote")
    reply_body = json.loads(captured[1]["body"])
    assert reply_body == {
        "messageIds": ["src"],
        "replyMessage": {
            "body": {"contentType": "text", "content": "reply"}
        },
    }
    assert "quotedMessageId" not in reply_body
    assert "beta" not in captured[0]["url"]


def test_no_separate_teams_assistant_tool() -> None:
    assert "teams" not in TOOL_REGISTRY
    with pytest.raises(KeyError):
        TOOL_REGISTRY["send_teams"]
