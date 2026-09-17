"""Telegram Depth A4.3 — active retrieval scope enforcement."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import (
    Object,
    Representation,
    TelegramMtprotoAccount,
    TelegramMtprotoChatSelection,
    User,
)
from app.domain.telegram_mtproto_visibility import (
    telegram_mtproto_active_object_predicate,
)
from app.services.context_service import ContextService
from app.services.errors import NotFoundError
from app.services.graph_service import GraphService
from app.services.object_query_service import ObjectQueryService
from app.services.recent_source_service import RecentSourceService
from app.services.retrieval_service import RetrievalService


def _scope_fixture(db_session, *, active=True):
    user = User(id=uuid4(), display_name="A4.3 user")
    db_session.add(user)
    db_session.flush()
    account = TelegramMtprotoAccount(
        id=uuid4(),
        user_id=user.id,
        telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(account)
    db_session.flush()
    selection = TelegramMtprotoChatSelection(
        id=uuid4(),
        account_id=account.id,
        peer_id=42,
        peer_kind="private",
        provider_peer_reference_encrypted="encrypted-reference",
        title="Scoped peer",
        username="scoped",
        scope_active=active,
        manual_selected=False,
    )
    db_session.add(selection)
    obj = Object(
        id=uuid4(),
        user_id=user.id,
        kind="chat_message",
        title="A4.3 unique scope phrase",
        body="A4.3 unique scope phrase in body",
        provider="telegram",
        external_id=f"a4.3-{uuid4()}",
        origin="source",
        state="confirmed",
        occurred_at=datetime.now(UTC),
        metadata_={
            "transport": "mtproto",
            "account_id": str(account.id),
            "peer_id": "42",
            "direction": "inbound",
        },
    )
    db_session.add(obj)
    db_session.flush()
    return user, account, selection, obj


def test_active_predicate_hides_inactive_and_reactivates_same_object(db_session):
    user, _, selection, obj = _scope_fixture(db_session)
    rep = Representation(
        id=uuid4(), object_id=obj.id, kind="full", text="retained representation"
    )
    db_session.add(rep)
    db_session.flush()
    snapshot = (obj.id, obj.body, obj.metadata_, rep.id, rep.text)

    assert db_session.scalar(
        select(Object).where(Object.id == obj.id, telegram_mtproto_active_object_predicate())
    ) is obj
    selection.scope_active = False
    selection.manual_selected = True
    db_session.flush()
    assert db_session.scalar(
        select(Object).where(Object.id == obj.id, telegram_mtproto_active_object_predicate())
    ) is None
    selection.scope_active = True
    db_session.flush()
    assert db_session.scalar(
        select(Object).where(Object.id == obj.id, telegram_mtproto_active_object_predicate())
    ) is obj
    assert (obj.id, obj.body, obj.metadata_, rep.id, rep.text) == snapshot
    assert ObjectQueryService(db_session, user.id).query(
        kinds=["chat_message"], providers=["telegram"]
    ) == [obj]
    assert obj.id in {
        hit.object_id
        for hit in RetrievalService(db_session, user.id).retrieve(
            "retained representation", time_scope="all", limit=20
        ).hits
    }
    selection.scope_active = False
    db_session.flush()
    assert obj.id not in {
        hit.object_id
        for hit in RetrievalService(db_session, user.id).retrieve(
            "retained representation", time_scope="all", limit=20
        ).hits
    }


def test_active_read_services_apply_scope_gate_and_preserve_legacy_telegram(db_session):
    user, _, selection, obj = _scope_fixture(db_session, active=False)
    legacy = Object(
        id=uuid4(), user_id=user.id, kind="chat_message", title="legacy telegram",
        body="legacy telegram body", provider="telegram", origin="source", state="confirmed",
        occurred_at=datetime.now(UTC), metadata_={}, external_id=f"legacy-{uuid4()}",
    )
    other = Object(
        id=uuid4(), user_id=user.id, kind="note", title="ordinary note", body="ordinary",
        origin="user", state="confirmed", external_id=f"note-{uuid4()}", metadata_={},
    )
    db_session.add_all([legacy, other])
    db_session.flush()

    assert obj not in ObjectQueryService(db_session, user.id).query(
        providers=["telegram"], kinds=["chat_message"]
    )
    assert legacy in ObjectQueryService(db_session, user.id).query(
        providers=["telegram"], kinds=["chat_message"]
    )
    assert obj not in RecentSourceService(db_session, user.id).list_recent(limit=50)
    assert obj.id not in {
        hit.object_id
        for hit in RetrievalService(db_session, user.id).retrieve(
            "A4.3 unique scope phrase", provider="telegram", kind="chat_message",
            time_scope="all", limit=20
        ).hits
    }
    selection.scope_active = True
    db_session.flush()
    assert obj in ObjectQueryService(db_session, user.id).query(
        providers=["telegram"], kinds=["chat_message"]
    )
    assert obj in RecentSourceService(db_session, user.id).list_recent(limit=50)


def test_malformed_scope_metadata_fails_closed_without_cast_error(db_session):
    user, _, _, _ = _scope_fixture(db_session, active=True)
    malformed = Object(
        id=uuid4(), user_id=user.id, kind="chat_message", title="malformed mtproto",
        provider="telegram", origin="source", state="confirmed", external_id=f"bad-{uuid4()}",
        metadata_={"transport": "mtproto", "account_id": {"bad": True}, "peer_id": []},
    )
    db_session.add(malformed)
    db_session.flush()
    assert malformed not in ObjectQueryService(db_session, user.id).query(
        kinds=["chat_message"], providers=["telegram"]
    )


def test_wrong_user_selection_does_not_grant_visibility(db_session):
    user, _, _, _ = _scope_fixture(db_session, active=False)
    other = User(id=uuid4(), display_name="other")
    db_session.add(other)
    db_session.flush()
    other_account = TelegramMtprotoAccount(
        id=uuid4(), user_id=other.id, telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(other_account)
    db_session.flush()
    db_session.add(TelegramMtprotoChatSelection(
        id=uuid4(), account_id=other_account.id, peer_id=42, peer_kind="private",
        provider_peer_reference_encrypted="encrypted-reference", title="Other",
        scope_active=True, manual_selected=True,
    ))
    db_session.flush()
    assert ObjectQueryService(db_session, user.id).query(
        kinds=["chat_message"], providers=["telegram"]
    ) == []


def test_neighbors_and_context_expansion_exclude_inactive_but_exact_target_remains(db_session):
    user, _, _, inactive = _scope_fixture(db_session, active=False)
    graph = GraphService(db_session, user.id)
    anchor = graph.create_object(ObjectCreate(kind="note", title="anchor", origin="user"))
    graph.create_edge(EdgeCreate(
        source_id=anchor.id, target_id=inactive.id, type="related_to",
        origin="system", state="observed"
    ))
    assert graph.get_neighbors(anchor.id) == []
    context = ContextService(db_session, user.id).build_context(object_id=anchor.id)
    assert inactive.id not in {item.object_id for item in context.items}
    assert graph.get_object(inactive.id).id == inactive.id
    with pytest.raises(NotFoundError):
        graph.get_neighbors(inactive.id)
