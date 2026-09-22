"""MTProto temporal participation: private addressing vs group/supergroup."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
    UserSettings,
)
from app.domain.temporal_hint import RESULT_EXACT_TEMPORAL_SIGNAL
from app.llm.temporal_match_judge import FakeTemporalMatchJudge
from app.llm.temporal_signal_extractor import FakeTemporalSignalExtractor
from app.services.temporal_signals_service import TemporalSignalService, source_extraction_signature
from app.services.user_participation_evidence_service import (
    ParticipationIdentity,
    current_user_participation,
)

SELF_ID = "500"
OTHER_ID = "900"


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture(autouse=True)
def _share_test_session_for_traces(db_session, monkeypatch):
    def proxy():
        return _SessionProxy(db_session)

    monkeypatch.setattr("app.ai_audit.context.SessionLocal", proxy)


def _identity() -> ParticipationIdentity:
    return ParticipationIdentity(
        emails=frozenset(),
        mattermost_user_ids=frozenset(),
        mattermost_usernames=frozenset(),
        has_google_account=False,
        has_yandex_calendar_account=False,
        telegram_user_ids=frozenset({SELF_ID}),
    )


def _message(*, peer_kind: str | None, direction: str, sender: str | int) -> SimpleNamespace:
    metadata = {
        "transport": "mtproto",
        "direction": direction,
        "sender_peer_id": sender,
    }
    if peer_kind is not None:
        metadata["peer_kind"] = peer_kind
    return SimpleNamespace(
        provider="telegram",
        kind="chat_message",
        origin="source",
        metadata_=metadata,
    )


def test_private_inbound_is_direct_recipient_and_groups_are_not() -> None:
    identity = _identity()
    assert current_user_participation(
        _message(peer_kind="private", direction="inbound", sender=OTHER_ID), identity
    ).roles == ("direct_recipient",)
    assert current_user_participation(
        _message(peer_kind="private", direction="outbound", sender=int(SELF_ID)), identity
    ).roles == ("sender",)
    assert (
        current_user_participation(
            _message(peer_kind="group", direction="inbound", sender=OTHER_ID), identity
        ).roles
        == ()
    )
    assert (
        current_user_participation(
            _message(peer_kind="supergroup", direction="inbound", sender=OTHER_ID), identity
        ).roles
        == ()
    )
    assert (
        current_user_participation(
            _message(peer_kind=None, direction="inbound", sender=OTHER_ID), identity
        ).roles
        == ()
    )
    assert (
        current_user_participation(
            _message(peer_kind="channel", direction="inbound", sender=OTHER_ID), identity
        ).roles
        == ()
    )


def _persist(session, *, peer_kind: str | None, sender: str) -> Object:
    user = User(id=uuid4(), display_name=f"participation-{uuid4()}")
    session.add(user)
    session.flush()
    session.add(
        UserSettings(user_id=user.id, timezone="Europe/Moscow", temporal_signals_enabled=True)
    )
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=uuid4().int % 1_000_000_000 + 1_000,
        session_encrypted="encrypted",
    )
    session.add(account)
    session.flush()
    session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=10,
            peer_kind=peer_kind or "private",
            provider_peer_reference_encrypted="encrypted",
            title="peer",
            manual_selected=False,
            scope_active=True,
        )
    )
    metadata = {
        "transport": "mtproto",
        "account_id": str(account.id),
        "peer_id": 10,
        "direction": "inbound",
        "sender_peer_id": sender,
    }
    if peer_kind is not None:
        metadata["peer_kind"] = peer_kind
    obj = Object(
        user_id=user.id,
        kind="chat_message",
        provider="telegram",
        external_id=f"mtproto|{uuid4()}",
        origin="source",
        state="observed",
        title="Созвон",
        body="Созвон завтра в 11",
        metadata_=metadata,
        occurred_at=datetime.now(UTC),
    )
    session.add(obj)
    session.flush()
    return obj


def _extract(session, source: Object):
    return TemporalSignalService(
        session,
        source.user_id,
        extractor=FakeTemporalSignalExtractor(
            payload={
                "result_class": RESULT_EXACT_TEMPORAL_SIGNAL,
                "concise_title": "Созвон",
                "start_date_kind": "relative_day",
                "start_relative_day_offset": 1,
                "start_local_time": "11:00",
                "end_precision": "exact",
                "end_kind": "duration_minutes",
                "end_duration_minutes": 30,
                "participation": "expected",
                "extraction_confidence": 0.92,
                "semantic_subject": "созвон",
            }
        ),
        match_judge=FakeTemporalMatchJudge(),
    )


def test_group_request_uses_channel_semantics_and_stays_possible(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    group = _persist(db_session, peer_kind="group", sender=OTHER_ID)
    service = _extract(db_session, group)
    request = service._build_request(group)
    assert request.is_channel_message is True
    assert "direct_recipient" not in request.participation_roles
    outcome = service.run_extract_job(
        {"object_id": str(group.id), "source_signature": source_extraction_signature(group)}
    )
    assert outcome.hint_id is not None, outcome
    hint = db_session.get(Object, outcome.hint_id)
    assert hint.metadata_["participation"] == "possible"

    supergroup = _persist(db_session, peer_kind="supergroup", sender=OTHER_ID)
    super_request = _extract(db_session, supergroup)._build_request(supergroup)
    assert super_request.is_channel_message is True
    assert "direct_recipient" not in super_request.participation_roles


def test_private_inbound_can_stay_personally_expected(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)
    source = _persist(db_session, peer_kind="private", sender=OTHER_ID)
    service = _extract(db_session, source)
    request = service._build_request(source)
    assert request.is_channel_message is False
    assert request.participation_roles == ("direct_recipient",)
    outcome = service.run_extract_job(
        {"object_id": str(source.id), "source_signature": source_extraction_signature(source)}
    )
    assert outcome.hint_id is not None, outcome
    hint = db_session.get(Object, outcome.hint_id)
    assert hint.metadata_["participation"] == "expected"


def test_mtproto_identity_fields_change_temporal_signature() -> None:
    source = _message(peer_kind="private", direction="inbound", sender=OTHER_ID)
    source.id = uuid4()
    source.kind = "chat_message"
    source.title = "Созвон"
    source.body = "завтра"
    source.occurred_at = datetime(2026, 9, 22, tzinfo=UTC)
    original = source_extraction_signature(source)
    source.metadata_ = {**source.metadata_, "peer_kind": "group"}
    grouped = source_extraction_signature(source)
    assert grouped != original
    source.metadata_ = {**source.metadata_, "sender_peer_id": "901"}
    assert source_extraction_signature(source) != grouped

    legacy = SimpleNamespace(
        id=source.id,
        kind="chat_message",
        provider="telegram",
        title=source.title,
        body=source.body,
        occurred_at=source.occurred_at,
        metadata_={"direction": "inbound", "from_user_id": OTHER_ID},
    )
    legacy_sig = source_extraction_signature(legacy)
    legacy.metadata_ = {**legacy.metadata_, "peer_kind": "group", "sender_peer_id": "1"}
    assert source_extraction_signature(legacy) == legacy_sig
