"""Telegram voice/audio transcription stays on the parent AI eligibility boundary."""

from __future__ import annotations

import hashlib
import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.assistant.transcription_constants import MAX_TRANSCRIPTION_AUDIO_BYTES
from app.connectors.telegram.mtproto_errors import TelegramMtprotoProviderUnavailableError
from app.connectors.telegram.mtproto_transport import (
    TelegramMtprotoMediaHint,
    TelethonMtprotoTransport,
    select_voice_audio_hint,
)
from app.core.config import settings
from app.db.engine import engine
from app.db.models import (
    Job,
    Notification,
    Object,
    Representation,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
)
from app.domain.communication_media import CommunicationMediaDescriptor
from app.domain.object_visibility import tombstone_object
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_predicate
from app.jobs.constants import (
    JOB_STATUS_PENDING,
    JOB_TYPE_TRANSCRIBE_COMMUNICATION_MEDIA,
    RECURRING_SOURCE_JOB_TYPES,
)
from app.jobs.handlers import HANDLERS, handle_transcribe_communication_media
from app.jobs.worker import process_one_job
from app.services.communication_media_processing_service import (
    TRANSCRIPT_KIND,
    CommunicationMediaProcessingService,
    MediaProcessingPermanentError,
)
from app.services.communication_media_service import CommunicationMediaService
from app.services.job_queue_service import (
    ClaimedJob,
    JobQueueService,
    is_job_error_retryable,
    utcnow,
)
from app.services.openai_daily_budget import (
    OPENAI_DAILY_BUDGET_PARKED_ERROR,
    OpenAIDailyBudgetExhaustedError,
    OpenAIDailyBudgetStatus,
)
from app.services.recent_source_service import RecentSourceService
from app.users.bootstrap import BOOTSTRAP_USER_ID

PEER_ID = 10
OWNER_ID = 424242


class _Provider:
    def __init__(self) -> None:
        self.model = "test-transcribe"
        self.calls: list[bytes] = []

    def transcribe(self, audio_bytes: bytes, filename: str, content_type: str | None) -> str:
        self.calls.append(audio_bytes)
        return f"said {audio_bytes.decode()}"


class _Fetcher:
    def __init__(self, audio: bytes = b"voice-bytes") -> None:
        self.audio = audio
        self.calls = 0

    def fetch(self, parent: Object, child: Object) -> bytes:
        del parent, child
        self.calls += 1
        return self.audio


def _user(session) -> User:
    user = User(id=uuid.uuid4(), display_name="media processing")
    session.add(user)
    session.flush()
    return user


def _account(session, user: User) -> TelegramMtprotoAccount:
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=OWNER_ID,
        session_encrypted="encrypted",
    )
    session.add(account)
    session.flush()
    return account


def _selection(session, account: TelegramMtprotoAccount, *, active: bool = True) -> TelegramMtprotoChatSelection:
    row = TelegramMtprotoChatSelection(
        account_id=account.id,
        peer_id=PEER_ID,
        peer_kind="group",
        provider_peer_reference_encrypted="encrypted",
        title="owned chat",
        manual_selected=False,
        scope_active=active,
    )
    session.add(row)
    session.flush()
    return row


def _parent(session, user: User, account: TelegramMtprotoAccount, *, direction: str, sender: str) -> Object:
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{uuid.uuid4()}",
        origin="source",
        state="observed",
        title="parent title",
        body="parent body",
        metadata_={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": str(PEER_ID),
            "direction": direction,
            "sender_peer_id": sender,
        },
        occurred_at=datetime.now(UTC),
    )
    session.add(obj)
    session.flush()
    return obj


def _media(session, user: User, parent: Object, *, kind: str = "voice", media_id: str = "9001") -> Object:
    children = CommunicationMediaService(session, user.id).materialize(
        parent,
        [
            CommunicationMediaDescriptor(
                provider="telegram",
                descriptor_key=f"{kind}:{media_id}",
                media_kind=kind,
                provider_media_id=media_id,
                filename="note.ogg",
                mime_type="audio/ogg",
                provenance={
                    "account_id": str(parent.metadata_["account_id"]),
                    "peer_id": str(PEER_ID),
                    "message_id": "41",
                    "media_category": kind,
                },
            )
        ],
    )
    assert len(children) == 1
    return children[0]


def _jobs(session, user_id) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == JOB_TYPE_TRANSCRIBE_COMMUNICATION_MEDIA,
            )
        )
    )


def _transcripts(session, object_id) -> list[Representation]:
    return list(
        session.scalars(
            select(Representation).where(
                Representation.object_id == object_id,
                Representation.kind == TRANSCRIPT_KIND,
            )
        )
    )


def _process(session, user, child, fetcher, provider):
    return CommunicationMediaProcessingService(
        session, user.id, fetcher=fetcher, provider=provider
    ).process(child.id)


def test_eligible_voice_and_audio_persist_one_transcript(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account)
    parent = _parent(db_session, user, account, direction="inbound", sender="7")
    provider = _Provider()
    for kind in ("voice", "audio"):
        child = _media(db_session, user, parent, kind=kind, media_id=kind)
        fetcher = _Fetcher(b"hello")
        result = _process(db_session, user, child, fetcher, provider)
        rows = _transcripts(db_session, child.id)
        assert result.status == "transcribed"
        assert fetcher.calls == 1
        assert len(rows) == 1
        assert rows[0].text == "said hello"
        assert rows[0].metadata_["model"] == "test-transcribe"
        assert rows[0].metadata_["content_hash"]
        assert rows[0].metadata_["source"] == "communication_media"
        assert set(rows[0].metadata_) == {"model", "content_hash", "source"}
        assert parent.title == "parent title"
        assert parent.body == "parent body"
        assert RecentSourceService(db_session, user.id).get_inbox_eligible(child.id) is None
        assert (
            db_session.scalar(select(Object.id).where(Object.id == child.id, telegram_mtproto_ai_predicate()))
            is None
        )


def test_replay_is_idempotent_and_changed_bytes_replace_transcript(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account)
    parent = _parent(db_session, user, account, direction="inbound", sender="7")
    child = _media(db_session, user, parent)
    provider = _Provider()
    fetcher = _Fetcher(b"one")
    _process(db_session, user, child, fetcher, provider)
    again = _process(db_session, user, child, fetcher, provider)
    assert again.status == "unchanged"
    assert provider.calls == [b"one"]
    assert len(_transcripts(db_session, child.id)) == 1
    fetcher.audio = b"two"
    replaced = _process(db_session, user, child, fetcher, provider)
    rows = _transcripts(db_session, child.id)
    assert replaced.status == "transcribed"
    assert provider.calls == [b"one", b"two"]
    assert len(rows) == 1
    assert rows[0].text == "said two"
    assert rows[0].metadata_["content_hash"] != hashlib.sha256(b"one").hexdigest()


def test_empty_oversized_and_mismatch_fail_before_transcription(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account)
    parent = _parent(db_session, user, account, direction="inbound", sender="7")
    child = _media(db_session, user, parent)
    provider = _Provider()
    empty = _Fetcher(b"")
    with pytest.raises(MediaProcessingPermanentError):
        _process(db_session, user, child, empty, provider)
    oversized = _Fetcher(b"x" * (MAX_TRANSCRIPTION_AUDIO_BYTES + 1))
    with pytest.raises(MediaProcessingPermanentError):
        _process(db_session, user, child, oversized, provider)
    assert provider.calls == []

    class _Mismatch:
        def fetch(self, parent_obj, child_obj):
            del parent_obj, child_obj
            raise MediaProcessingPermanentError("communication media does not match descriptor")

    with pytest.raises(MediaProcessingPermanentError):
        _process(db_session, user, child, _Mismatch(), provider)
    assert provider.calls == []
    hint = TelegramMtprotoMediaHint(media_kind="voice", provider_media_id="9001")
    assert select_voice_audio_hint((hint,), provider_media_id="9001", media_kind="voice") == hint
    assert select_voice_audio_hint((hint,), provider_media_id="other", media_kind="voice") is None
    assert select_voice_audio_hint((hint,), provider_media_id="9001", media_kind="photo") is None
    source = inspect.getsource(TelethonMtprotoTransport.download_voice_audio)
    assert "BytesIO" in source
    assert "NamedTemporaryFile" not in source


def test_cross_user_deleted_and_rejected_are_not_transcribed(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user = _user(db_session)
    other = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account)
    parent = _parent(db_session, user, account, direction="inbound", sender="7")
    child = _media(db_session, user, parent)
    fetcher = _Fetcher()
    provider = _Provider()
    with pytest.raises(MediaProcessingPermanentError):
        CommunicationMediaProcessingService(
            db_session, other.id, fetcher=fetcher, provider=provider
        ).process(child.id)
    assert fetcher.calls == 0
    tombstone_object(parent)
    db_session.flush()
    assert _process(db_session, user, child, fetcher, provider).status == "skipped"
    parent.deleted_at = None
    child.state = "rejected"
    db_session.flush()
    assert _process(db_session, user, child, fetcher, provider).status == "skipped"
    assert fetcher.calls == 0
    assert provider.calls == []


def test_gate_blocks_inbound_and_allows_self_authored_and_scoped_inbound(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", False)
    user = _user(db_session)
    account = _account(db_session, user)
    selection = _selection(db_session, account, active=True)
    inbound = _parent(db_session, user, account, direction="inbound", sender="7")
    inbound_child = _media(db_session, user, inbound, media_id="inbound")
    fetcher = _Fetcher()
    provider = _Provider()
    assert _jobs(db_session, user.id) == []
    assert _process(db_session, user, inbound_child, fetcher, provider).status == "skipped"
    assert fetcher.calls == 0
    outbound = _parent(db_session, user, account, direction="outbound", sender=str(OWNER_ID))
    outbound_child = _media(db_session, user, outbound, media_id="outbound")
    assert len(_jobs(db_session, user.id)) == 1
    assert _process(db_session, user, outbound_child, fetcher, provider).status == "transcribed"
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    scoped = _parent(db_session, user, account, direction="inbound", sender="7")
    scoped_child = _media(db_session, user, scoped, media_id="scoped")
    assert _process(db_session, user, scoped_child, fetcher, provider).status == "transcribed"
    selection.scope_active = False
    db_session.flush()
    recheck = _Fetcher()
    assert _process(db_session, user, scoped_child, recheck, provider).status == "skipped"
    assert recheck.calls == 0


def test_enqueue_is_deduped_and_skips_non_audio(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    user = _user(db_session)
    account = _account(db_session, user)
    _selection(db_session, account)
    parent = _parent(db_session, user, account, direction="inbound", sender="7")
    child = _media(db_session, user, parent)
    _media(db_session, user, parent)
    _media(db_session, user, parent, kind="document", media_id="doc")
    jobs = _jobs(db_session, user.id)
    assert len(jobs) == 1
    assert jobs[0].payload["media_object_id"] == str(child.id)
    assert "dedupe_key" in jobs[0].payload
    assert JOB_TYPE_TRANSCRIBE_COMMUNICATION_MEDIA not in RECURRING_SOURCE_JOB_TYPES
    assert is_job_error_retryable(MediaProcessingPermanentError("mismatch")) is False
    assert is_job_error_retryable(TelegramMtprotoProviderUnavailableError("temporary")) is True
    assert "mattermost" not in inspect.getsource(CommunicationMediaProcessingService)
    assert "WORKLOAD_TRANSCRIPTION" in inspect.getsource(handle_transcribe_communication_media)


def test_daily_budget_exhaustion_parks_media_job(monkeypatch) -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    job_id = JobQueueService(session).enqueue(
        JOB_TYPE_TRANSCRIBE_COMMUNICATION_MEDIA,
        {"media_object_id": str(uuid.uuid4()), "descriptor_key": "voice:1", "model": "test"},
        BOOTSTRAP_USER_ID,
    ).id
    trans.commit()
    conn.close()

    def _claim(self, **kwargs):
        del kwargs
        job = self._session.get(Job, job_id)
        if job is None or job.status != JOB_STATUS_PENDING:
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_at = utcnow()
        self._session.flush()
        return ClaimedJob(
            id=job.id,
            type=job.type,
            payload=dict(job.payload),
            attempts=job.attempts,
            user_id=job.user_id,
        )

    def _boom(*args, **kwargs):
        del args, kwargs
        now = datetime.now(UTC)
        raise OpenAIDailyBudgetExhaustedError(
            OpenAIDailyBudgetStatus(
                daily_token_limit=1,
                tokens_used_today=1,
                exhausted=True,
                day_start=now,
                reset_at=now + timedelta(hours=1),
            )
        )

    monkeypatch.setattr(JobQueueService, "claim_next", _claim)
    monkeypatch.setitem(HANDLERS, JOB_TYPE_TRANSCRIBE_COMMUNICATION_MEDIA, _boom)
    try:
        assert process_one_job() is True
        conn = engine.connect()
        session = Session(bind=conn)
        stored = session.get(Job, job_id)
        assert stored is not None
        assert stored.status == JOB_STATUS_PENDING
        assert stored.last_error == OPENAI_DAILY_BUDGET_PARKED_ERROR
        assert stored.run_after > datetime.now(UTC)
        session.close()
        conn.close()
    finally:
        conn = engine.connect()
        trans = conn.begin()
        session = Session(bind=conn)
        session.execute(delete(Job).where(Job.id == job_id))
        session.execute(
            delete(Notification).where(
                Notification.user_id == BOOTSTRAP_USER_ID,
                Notification.title == "Дневной лимит OpenAI исчерпан",
                Notification.created_at >= datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        trans.commit()
        conn.close()


def test_unsupported_provider_is_permanent(db_session) -> None:
    user = _user(db_session)
    parent = Object(
        user_id=user.id,
        kind="chat_message",
        provider="mattermost",
        external_id=f"mm|{uuid.uuid4()}",
        origin="source",
        state="observed",
        title="mm",
        body="mm",
        metadata_={"parent": "no"},
        occurred_at=datetime.now(UTC),
    )
    db_session.add(parent)
    db_session.flush()
    child = Object(
        user_id=user.id,
        kind="file",
        provider="mattermost",
        external_id=f"mm-file|{uuid.uuid4()}",
        origin="source",
        state="observed",
        title="voice",
        metadata_={
            "parent_communication_id": str(parent.id),
            "media_kind": "voice",
            "descriptor_key": "voice:1",
            "provider_media_id": "1",
            "provenance": {},
        },
        occurred_at=datetime.now(UTC),
    )
    db_session.add(child)
    db_session.flush()
    fetcher = _Fetcher()
    with pytest.raises(MediaProcessingPermanentError):
        CommunicationMediaProcessingService(
            db_session, user.id, fetcher=fetcher, provider=_Provider()
        ).process(child.id)
    assert fetcher.calls == 0
    assert db_session.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id)) == 0
