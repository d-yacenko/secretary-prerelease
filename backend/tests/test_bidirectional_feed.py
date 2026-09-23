"""Inbox and conversation detail keep both inbound and outbound chat messages."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.models import (
    Notification,
    Object,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
)
from app.notifications.constants import NOTIFICATION_STATUS_NEW
from app.services.conversation_member_read import list_conversation_members_page
from app.services.notification_service import NotificationService
from app.services.recent_source_service import RecentSourceService


def _user(session) -> User:
    user = User(id=uuid4(), display_name="bidirectional feed")
    session.add(user)
    session.flush()
    return user


def _chat(session, user, *, provider, direction, when, metadata, kind="chat_message"):
    obj = Object(
        user_id=user.id,
        kind=kind,
        provider=provider,
        external_id=f"{provider}|{uuid4()}",
        origin="source",
        state="observed",
        title=f"{provider} {direction}",
        body=f"{provider} {direction} body",
        metadata_=metadata,
        occurred_at=when,
    )
    session.add(obj)
    session.flush()
    return obj


def _telegram_pair(session):
    user = _user(session)
    account = TelegramMtprotoAccount(
        user_id=user.id,
        telegram_user_id=424242,
        session_encrypted="encrypted",
    )
    session.add(account)
    session.flush()
    session.add(
        TelegramMtprotoChatSelection(
            account_id=account.id,
            peer_id=10,
            peer_kind="group",
            provider_peer_reference_encrypted="encrypted",
            title="chat",
            manual_selected=False,
            scope_active=True,
        )
    )
    session.flush()
    start = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    common = {"transport": "mtproto", "account_id": str(account.id), "peer_id": "10"}
    inbound = _chat(
        session,
        user,
        provider="telegram",
        direction="inbound",
        when=start,
        metadata={**common, "direction": "inbound", "sender_peer_id": "900"},
    )
    outbound = _chat(
        session,
        user,
        provider="telegram",
        direction="outbound",
        when=start + timedelta(minutes=1),
        metadata={**common, "direction": "outbound", "sender_peer_id": "424242"},
    )
    return user, inbound, outbound


def _assert_both_visible_and_ordered(session, user, inbound, outbound):
    feed_ids = {item.id for item in RecentSourceService(session, user.id).list_page().items}
    assert inbound.id in feed_ids
    assert outbound.id in feed_ids
    page = list_conversation_members_page(
        session, user.id, object_id=inbound.id, limit=20, cursor=None
    )
    member_ids = [item.id for item in page["members"]]
    assert member_ids.index(inbound.id) < member_ids.index(outbound.id)


def test_telegram_feed_and_detail_include_both_directions(db_session) -> None:
    user, inbound, outbound = _telegram_pair(db_session)
    _assert_both_visible_and_ordered(db_session, user, inbound, outbound)


def test_teams_feed_and_detail_include_both_directions(db_session) -> None:
    user = _user(db_session)
    start = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    common = {"chat_id": "chat-1", "account_id": "teams-account"}
    inbound = _chat(
        db_session,
        user,
        provider="teams",
        direction="inbound",
        when=start,
        metadata={**common, "direction": "inbound", "sender_id": "other"},
    )
    outbound = _chat(
        db_session,
        user,
        provider="teams",
        direction="outbound",
        when=start + timedelta(minutes=1),
        metadata={**common, "direction": "outbound", "sender_id": "self"},
    )
    _assert_both_visible_and_ordered(db_session, user, inbound, outbound)


def test_mattermost_gmail_and_yandex_feed_behavior_stays(db_session) -> None:
    user = _user(db_session)
    when = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    mattermost_in = _chat(
        db_session,
        user,
        provider="mattermost",
        direction="inbound",
        when=when,
        metadata={"channel_id": "town", "direction": "inbound", "author_user_id": "other"},
    )
    mattermost_out = _chat(
        db_session,
        user,
        provider="mattermost",
        direction="outbound",
        when=when + timedelta(minutes=1),
        metadata={"channel_id": "town", "direction": "outbound", "author_user_id": "self"},
    )
    gmail = _chat(
        db_session,
        user,
        provider="gmail",
        direction="inbound",
        when=when,
        metadata={"labels": ["INBOX"]},
        kind="email",
    )
    gmail_noise = _chat(
        db_session,
        user,
        provider="gmail",
        direction="inbound",
        when=when,
        metadata={"labels": ["SPAM"]},
        kind="email",
    )
    yandex = _chat(
        db_session,
        user,
        provider="yandex_mail",
        direction="inbound",
        when=when,
        metadata={"labels": ["INBOX"]},
        kind="email",
    )
    feed_ids = {item.id for item in RecentSourceService(db_session, user.id).list_page().items}
    assert mattermost_in.id in feed_ids
    assert mattermost_out.id in feed_ids
    assert gmail.id in feed_ids
    assert yandex.id in feed_ids
    assert gmail_noise.id not in feed_ids


def test_visible_outbound_does_not_become_inbox_attention(db_session) -> None:
    user, inbound, outbound = _telegram_pair(db_session)
    note = Notification(
        user_id=user.id,
        title="created",
        priority="normal",
        status=NOTIFICATION_STATUS_NEW,
        source_object_id=outbound.id,
        proposal_={
            "type": "transport_event",
            "provider": "telegram",
            "transport": "mtproto",
            "event_type": "message_created",
        },
    )
    db_session.add(note)
    db_session.flush()
    feed_ids = {item.id for item in RecentSourceService(db_session, user.id).list_page().items}
    assert outbound.id in feed_ids
    assert inbound.id in feed_ids
    attention_ids = {
        item.source_object_id
        for item in NotificationService(db_session, user.id).list_inbox_attention()
    }
    assert outbound.id not in attention_ids
