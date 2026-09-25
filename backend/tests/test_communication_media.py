"""Provider-neutral communication media children stay metadata and provenance only."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.connectors.mattermost.materialize import MattermostObjectMaterializer
from app.connectors.mattermost.normalize import MattermostChannelContext, normalize_mattermost_post
from app.connectors.teams.materialize import TeamsObjectMaterializer
from app.connectors.telegram.materialize import TelegramObjectMaterializer
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoHistoryEntry,
    TelegramMtprotoMediaHint,
    _history_entry_from_message,
    _media_hints,
)
from app.core.config import settings
from app.db.models import Edge, Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_predicate
from app.services.communication_media_service import CommunicationMediaService
from app.services.errors import NotFoundError
from app.services.recent_source_service import RecentSourceService
from app.services.telegram_mtproto_history_service import _normalize_entry

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
TENANT = "11111111-1111-1111-1111-111111111111"
TEAMS_USER = "22222222-2222-2222-2222-222222222222"
SERVER = "https://mm.example.com"


def test_telegram_voice_child_is_idempotent_and_not_model_visible(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user_id = _user(db_session)
    account_id = uuid.uuid4()
    parent = _telegram_parent(
        db_session, user_id, message_id=41, kind="voice", media_id="9001", account_id=account_id
    )
    files = _files(db_session, user_id)
    edges = _contains(db_session, parent.id)
    assert len(files) == 1
    assert files[0].kind == "file"
    assert files[0].body is None
    assert files[0].metadata_["media_kind"] == "voice"
    assert files[0].metadata_["provider_media_id"] == "9001"
    assert files[0].metadata_["provenance"]["message_id"] == "41"
    assert files[0].body is None
    assert len(edges) == 1
    replay = _telegram_parent(
        db_session, user_id, message_id=41, kind="voice", media_id="9001", account_id=account_id
    )
    assert replay.id == parent.id
    assert len(_files(db_session, user_id)) == 1
    assert len(_contains(db_session, parent.id)) == 1
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    assert _ai_visible(db_session, files[0].id) is None
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    assert _ai_visible(db_session, files[0].id) is None
    assert RecentSourceService(db_session, user_id).get_inbox_eligible(files[0].id) is None
    tombstone_object(parent)
    db_session.flush()
    assert files[0].deleted_at is None


def test_telegram_media_categories_keep_safe_provenance(db_session) -> None:
    user_id = _user(db_session)
    hints = (
        ("audio", "11", "audio/ogg", 3),
        ("document", "12", "application/pdf", None),
        ("photo", "13", "image/jpeg", None),
        ("video", "14", "video/mp4", 8),
    )
    for kind, media_id, mime, duration in hints:
        _telegram_parent(
            db_session,
            user_id,
            message_id=int(media_id),
            kind=kind,
            media_id=media_id,
            mime_type=mime,
            duration=duration,
        )
    by_kind = {row.metadata_["media_kind"]: row.metadata_ for row in _files(db_session, user_id)}
    assert set(by_kind) == {"audio", "document", "photo", "video"}
    assert by_kind["audio"]["mime_type"] == "audio/ogg"
    assert by_kind["audio"]["duration_seconds"] == 3
    assert by_kind["video"]["duration_seconds"] == 8
    assert "access_hash" not in str(by_kind)


def test_media_materialization_does_not_download_or_transcribe() -> None:
    service_source = inspect.getsource(CommunicationMediaService)
    hint_source = inspect.getsource(_media_hints)
    history_source = inspect.getsource(_history_entry_from_message)
    folded = f"{service_source}\n{hint_source}\n{history_source}".casefold()
    assert "download_media" not in folded
    assert "transcribe" not in folded
    assert "openai" not in folded

    class _Message:
        id = 7
        message = "hello"
        date = NOW
        action = None
        out = False
        media = None

        def download_media(self):
            raise AssertionError("media bytes were requested")

    entry = _history_entry_from_message(_Message())
    assert entry is not None
    assert entry.media == ()


def test_mattermost_file_ids_materialize_separate_children(db_session) -> None:
    user_id = _user(db_session)
    post = {
        "id": "post-1",
        "message": "files",
        "create_at": 1,
        "update_at": 1,
        "user_id": "author",
        "file_ids": ["file-a", "file-b"],
        "metadata": {
            "files": [
                {"id": "file-a", "name": "notes.txt", "mime_type": "text/plain", "size": 12}
            ]
        },
    }
    parent = _mattermost_parent(db_session, user_id, post)
    _mattermost_parent(db_session, user_id, post)
    files = _files(db_session, user_id)
    assert {row.metadata_["provider_media_id"] for row in files} == {"file-a", "file-b"}
    named = next(row for row in files if row.metadata_["provider_media_id"] == "file-a")
    assert named.metadata_["filename"] == "notes.txt"
    assert named.metadata_["mime_type"] == "text/plain"
    assert named.metadata_["size"] == 12
    assert named.metadata_["provenance"]["server_url"] == SERVER
    assert len(_contains(db_session, parent.id)) == 2
    assert len(files) == 2


def test_teams_file_attachment_is_kept_and_reference_is_not(db_session) -> None:
    user_id = _user(db_session)
    message = {
        "id": "message-1",
        "messageType": "message",
        "createdDateTime": "2026-09-24T12:00:00Z",
        "body": {"contentType": "text", "content": "see file"},
        "from": {"user": {"id": TEAMS_USER, "displayName": "Olga"}},
        "attachments": [
            {
                "id": "quoted-message-ref",
                "contentType": "messageReference",
                "content": "{\"messageId\": \"earlier\"}",
            },
            {
                "id": "file-1",
                "contentType": "application/vnd.microsoft.teams.file.download.info",
                "name": "agenda.docx",
                "contentUrl": "https://files.example/agenda?access_token=secret",
            },
        ],
    }
    parent = _teams_parent(db_session, user_id, message)
    _teams_parent(db_session, user_id, message)
    files = _files(db_session, user_id)
    assert len(files) == 1
    assert files[0].metadata_["filename"] == "agenda.docx"
    assert files[0].metadata_["media_kind"] == "document"
    dumped = f"{parent.metadata_}{files[0].metadata_}"
    assert "access_token" not in dumped
    assert "secret" not in dumped
    assert len(_contains(db_session, parent.id)) == 1


def test_cross_user_media_parent_fails_closed(db_session) -> None:
    owner = _user(db_session)
    other = _user(db_session)
    parent = _telegram_parent(db_session, owner, message_id=8, kind="voice", media_id="3")
    with pytest.raises(NotFoundError):
        CommunicationMediaService(db_session, other).materialize_stored(parent)


def _telegram_parent(
    db_session,
    user_id,
    *,
    message_id: int,
    kind: str,
    media_id: str,
    mime_type=None,
    duration=None,
    account_id=None,
):
    account = SimpleNamespace(id=account_id or uuid.uuid4())
    selection = SimpleNamespace(
        peer_id=10, title="Olga", username=None, peer_kind="private", is_forum=False
    )
    entry = TelegramMtprotoHistoryEntry(
        message_id=message_id,
        occurred_at=NOW,
        text=None,
        sender_peer_id=10,
        reply_to_message_id=None,
        topic_id=None,
        edited_at=None,
        is_service=False,
        outgoing=False,
        media=(
            TelegramMtprotoMediaHint(
                media_kind=kind,
                provider_media_id=media_id,
                mime_type=mime_type,
                duration_seconds=duration,
            ),
        ),
    )
    normalized = _normalize_entry(account, selection, entry, datetime.min.replace(tzinfo=UTC))
    assert normalized is not None
    result = TelegramObjectMaterializer(db_session).upsert_mtproto_message(
        user_id=user_id, normalized=normalized
    )
    assert result.obj is not None
    return result.obj


def _mattermost_parent(db_session, user_id, post: dict):
    channel = MattermostChannelContext(
        channel_id="dm-1",
        channel_name=None,
        channel_display_name="Olga",
        channel_type="D",
        team_id=None,
        team_name=None,
        team_display_name=None,
    )
    normalized = normalize_mattermost_post(
        post=post,
        normalized_server_url=SERVER,
        account_id=uuid.uuid4(),
        channel=channel,
        author={"username": "olga", "display_name": "Olga"},
    )
    assert normalized is not None
    result = MattermostObjectMaterializer(db_session).upsert_post(
        user_id=user_id,
        normalized_server_url=SERVER,
        account_id=uuid.uuid4(),
        channel=channel,
        post=post,
        author={"username": "olga"},
    )
    assert result.obj is not None
    return result.obj


def _teams_parent(db_session, user_id, message: dict):
    result = TeamsObjectMaterializer(db_session).upsert_message(
        user_id=user_id,
        account_id=uuid.uuid4(),
        tenant_id=TENANT,
        microsoft_user_id="33333333-3333-3333-3333-333333333333",
        chat_id="chat-1",
        chat_type="oneOnOne",
        chat_display_title="Olga",
        message=message,
    )
    assert result.obj is not None
    return result.obj


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    return user_id


def _files(db_session, user_id) -> list[Object]:
    return list(
        db_session.scalars(
            select(Object).where(Object.user_id == user_id, Object.kind == "file")
        ).all()
    )


def _contains(db_session, parent_id) -> list[Edge]:
    return list(
        db_session.scalars(
            select(Edge).where(Edge.source_id == parent_id, Edge.type == "contains")
        ).all()
    )


def _ai_visible(db_session, object_id):
    return db_session.scalar(
        select(Object.id).where(Object.id == object_id, telegram_mtproto_ai_predicate())
    )
