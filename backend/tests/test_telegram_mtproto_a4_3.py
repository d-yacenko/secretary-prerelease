"""Telegram Depth A4.3 — active retrieval scope enforcement."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.core.config import settings
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
from app.services.conversation_member_read import list_conversation_members_page
from app.services.errors import NotFoundError
from app.services.graph_service import GraphService
from app.services.label_service import LabelService
from app.services.object_query_service import ObjectQueryService
from app.services.recent_source_service import RecentSourceService, inbox_feed_at
from app.services.retrieval_service import RetrievalService
from app.services.search_service import SearchService


@pytest.fixture(autouse=True)
def _enable_mtproto_ai_for_legacy_a43_regressions(monkeypatch):
    monkeypatch.setattr(settings, "telegram_mtproto_ai_enabled", True)


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
            "chat_id": "42",
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
    db_session.add(
        Representation(
            id=uuid4(), object_id=inactive.id, kind="full", text="retained target representation"
        )
    )
    db_session.flush()
    graph = GraphService(db_session, user.id)
    anchor = graph.create_object(ObjectCreate(kind="note", title="anchor", origin="user"))
    graph.create_edge(EdgeCreate(
        source_id=anchor.id, target_id=inactive.id, type="related_to",
        origin="system", state="observed"
    ))
    assert graph.get_neighbors(anchor.id) == []
    context = ContextService(db_session, user.id).build_context(object_id=anchor.id)
    assert inactive.id not in {item.object_id for item in context.items}
    retained_context = ContextService(db_session, user.id).build_context(object_id=inactive.id)
    assert inactive.id in {item.object_id for item in retained_context.items}
    assert graph.get_object(inactive.id).id == inactive.id
    with pytest.raises(NotFoundError):
        graph.get_neighbors(inactive.id)


@pytest.mark.parametrize(
    ("peer_kind", "peer_id"),
    [("private", 42), ("group", -42), ("supergroup", -1000000000042)],
)
def test_all_supported_peer_kinds_toggle_active_visibility(db_session, peer_kind, peer_id):
    user, _, selection, obj = _scope_fixture(db_session)
    selection.peer_kind = peer_kind
    selection.peer_id = peer_id
    obj.metadata_ = {**obj.metadata_, "peer_id": str(peer_id)}
    db_session.flush()
    query = ObjectQueryService(db_session, user.id)
    assert obj in query.query(kinds=["chat_message"], providers=["telegram"])
    selection.scope_active = False
    selection.manual_selected = True
    db_session.flush()
    assert obj not in query.query(kinds=["chat_message"], providers=["telegram"])
    selection.scope_active = True
    db_session.flush()
    assert obj in query.query(kinds=["chat_message"], providers=["telegram"])


def test_scope_metadata_and_ownership_matrix_fails_closed(db_session):
    user, account, _, valid = _scope_fixture(db_session)
    other_user = User(id=uuid4(), display_name="different owner")
    db_session.add(other_user)
    db_session.flush()
    other_account = TelegramMtprotoAccount(
        id=uuid4(), user_id=other_user.id, telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(other_account)
    db_session.flush()
    foreign_owner = User(id=uuid4(), display_name="foreign account owner")
    db_session.add(foreign_owner)
    db_session.flush()
    foreign_account = TelegramMtprotoAccount(
        id=uuid4(), user_id=foreign_owner.id, telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(foreign_account)
    db_session.flush()
    db_session.add_all([
        TelegramMtprotoChatSelection(
            id=uuid4(), account_id=other_account.id, peer_id=42, peer_kind="private",
            provider_peer_reference_encrypted="encrypted", title="Other account", scope_active=True,
        ),
        TelegramMtprotoChatSelection(
            id=uuid4(), account_id=foreign_account.id, peer_id=42, peer_kind="private",
            provider_peer_reference_encrypted="encrypted", title="Foreign account", scope_active=True,
        ),
    ])
    cases = [
        {"transport": "mtproto", "peer_id": "42"},
        {"transport": "mtproto", "account_id": str(account.id)},
        {"transport": "mtproto", "account_id": {"id": str(account.id)}, "peer_id": "42"},
        {"transport": "mtproto", "account_id": str(account.id), "peer_id": [42]},
        {"transport": "mtproto", "account_id": str(uuid4()), "peer_id": "42"},
        {"transport": "mtproto", "account_id": str(account.id), "peer_id": "999"},
        {"transport": "mtproto", "account_id": str(other_account.id), "peer_id": "42"},
        {"transport": "mtproto", "account_id": str(foreign_account.id), "peer_id": "42"},
    ]
    objects = []
    for metadata in cases:
        obj = Object(
            id=uuid4(), user_id=user.id, kind="chat_message", provider="telegram",
            origin="source", state="confirmed", external_id=f"matrix-{uuid4()}",
            title="matrix", metadata_=metadata,
        )
        objects.append(obj)
    db_session.add_all(objects)
    db_session.flush()
    visible = ObjectQueryService(db_session, user.id).query(
        kinds=["chat_message"], providers=["telegram"]
    )
    assert valid in visible
    assert not set(objects) & set(visible)


def test_retrieval_candidate_families_and_search_facade_are_scope_gated(db_session):
    user, _, selection, obj = _scope_fixture(db_session)
    obj.title = "distinctive title trigram qzx"
    obj.body = "distinctive body lexical phrase"
    db_session.add(Representation(
        id=uuid4(), object_id=obj.id, kind="full", text="distinctive representation phrase"
    ))
    db_session.flush()
    retrieval = RetrievalService(db_session, user.id)
    search = SearchService(db_session, user.id)
    queries = ["distinctive body lexical", "distinctive title qzx", "distinctive representation"]
    for query in queries:
        assert obj.id in {hit.object_id for hit in retrieval.retrieve(query, time_scope="all").hits}
    assert obj.id in {item.id for item in search.search("distinctive body lexical", sort="relevance")}
    assert obj.id in {item.id for item in search.search("distinctive body lexical", sort="newest")}
    assert obj.id in {item.id for item in search.search("distinctive body lexical", sort="oldest")}
    selection.scope_active = False
    db_session.flush()
    for query in queries:
        assert obj.id not in {hit.object_id for hit in retrieval.retrieve(query, time_scope="all").hits}
    assert obj.id not in {item.id for item in search.search("distinctive body lexical")}


def test_object_query_filters_and_recent_review_paths_are_scope_gated(db_session):
    user, _, selection, obj = _scope_fixture(db_session)
    recent = RecentSourceService(db_session, user.id)
    query = ObjectQueryService(db_session, user.id)
    occurred = obj.occurred_at
    assert obj in query.query(
        providers=["telegram"], kinds=["chat_message"], states=["confirmed"],
        occurred_from=occurred - timedelta(seconds=1), occurred_to=occurred + timedelta(seconds=1),
    )
    assert obj in recent.list_page(limit=50).items
    assert recent.get_inbox_eligible(obj.id) is obj
    feed_at = inbox_feed_at(obj)
    assert obj in recent.list_review_window(
        anchor_feed_at=feed_at - timedelta(seconds=1), anchor_object_id=uuid4(),
        snapshot_top_feed_at=feed_at + timedelta(seconds=1), snapshot_top_object_id=uuid4(),
        after_feed_at=None, after_object_id=None, limit=50,
    ).items
    selection.scope_active = False
    db_session.flush()
    assert obj not in query.query(providers=["telegram"], kinds=["chat_message"], states=["confirmed"])
    assert obj not in recent.list_page(limit=50).items
    assert recent.get_inbox_eligible(obj.id) is None
    assert obj not in recent.list_review_window(
        anchor_feed_at=feed_at - timedelta(seconds=1), anchor_object_id=uuid4(),
        snapshot_top_feed_at=feed_at + timedelta(seconds=1), snapshot_top_object_id=uuid4(),
        after_feed_at=None, after_object_id=None, limit=50,
    ).items


def test_context_query_and_conversation_member_paths_do_not_bypass_scope(db_session):
    user, _, selection, inactive = _scope_fixture(db_session, active=False)
    context = ContextService(db_session, user.id).build_context(
        query="A4.3 unique scope phrase"
    )
    assert inactive.id not in {item.object_id for item in context.items}
    with pytest.raises(NotFoundError):
        list_conversation_members_page(db_session, user.id, object_id=inactive.id, limit=20, cursor=None)
    selection.scope_active = True
    db_session.flush()
    page = list_conversation_members_page(
        db_session, user.id, object_id=inactive.id, limit=20, cursor=None
    )
    assert inactive.id in [item.id for item in page["members"]]


def test_same_user_wrong_account_selection_does_not_grant_visibility(db_session):
    user, account_a, selection, obj = _scope_fixture(db_session, active=False)
    other_user = User(id=uuid4(), display_name="second account owner")
    db_session.add(other_user)
    db_session.flush()
    account_b = TelegramMtprotoAccount(
        id=uuid4(), user_id=other_user.id, telegram_user_id=uuid4().int % 2_000_000_000,
        session_encrypted="encrypted",
    )
    db_session.add(account_b)
    db_session.flush()
    selection.account_id = account_b.id
    db_session.flush()
    query = ObjectQueryService(db_session, user.id)
    assert obj not in query.query(kinds=["chat_message"], providers=["telegram"])
    selection.account_id = account_a.id
    selection.scope_active = True
    db_session.flush()
    assert obj in query.query(kinds=["chat_message"], providers=["telegram"])


def test_title_trigram_filtered_retrieval_and_search_sorts_stay_hidden(db_session):
    user, _, selection, obj = _scope_fixture(db_session)
    obj.title = "CandidateBranchUnique Mark"
    obj.body = "ordinary body without title token"
    db_session.flush()
    retrieval = RetrievalService(db_session, user.id)
    search = SearchService(db_session, user.id)
    filtered = retrieval.retrieve(
        "CandidateBranchUniqueMarker", provider="telegram", kind="chat_message", time_scope="all"
    )
    assert obj.id in {hit.object_id for hit in filtered.hits}
    selection.scope_active = False
    db_session.flush()
    assert obj.id not in {
        hit.object_id for hit in retrieval.retrieve(
            "CandidateBranchUniqueMarker", provider="telegram", kind="chat_message", time_scope="all"
        ).hits
    }
    for sort in ("relevance", "newest", "oldest"):
        assert obj.id not in {item.id for item in search.search("CandidateBranchUniqueMarker", sort=sort)}
    selection.scope_active = True
    db_session.flush()
    assert obj.id in {item.id for item in search.search("CandidateBranchUniqueMarker", sort="relevance")}


def test_object_query_status_and_label_filters_follow_scope(db_session):
    user, _, selection, obj = _scope_fixture(db_session)
    obj.status = "queued"
    label = LabelService(db_session, user.id).create_label("A4.3 label").label
    LabelService(db_session, user.id).assign_label(obj.id, label.id)
    db_session.flush()
    query = ObjectQueryService(db_session, user.id)
    kwargs = {"kinds": ["chat_message"], "providers": ["telegram"], "statuses": ["queued"], "label_ids": [label.id]}
    assert obj in query.query(**kwargs)
    selection.scope_active = False
    db_session.flush()
    assert obj not in query.query(**kwargs)
    selection.scope_active = True
    db_session.flush()
    assert obj in query.query(**kwargs)


def test_recent_review_count_paths_follow_scope(db_session):
    user, _, selection, obj = _scope_fixture(db_session)
    recent = RecentSourceService(db_session, user.id)
    feed = inbox_feed_at(obj)
    anchor_feed = feed - timedelta(seconds=1)
    snapshot_feed = feed + timedelta(seconds=1)
    kwargs = {
        "anchor_feed_at": anchor_feed,
        "anchor_object_id": uuid4(),
        "snapshot_top_feed_at": snapshot_feed,
        "snapshot_top_object_id": uuid4(),
    }
    assert recent.count_review_window(**kwargs) == 1
    assert recent.count_older_in_review_window(**kwargs, last_feed_at=snapshot_feed, last_object_id=uuid4()) == 1
    assert recent.count_newer_in_review_window(**kwargs, last_feed_at=feed, last_object_id=obj.id) == 0
    selection.scope_active = False
    db_session.flush()
    assert recent.count_review_window(**kwargs) == 0
    assert recent.count_older_in_review_window(**kwargs, last_feed_at=snapshot_feed, last_object_id=uuid4()) == 0
    assert recent.count_newer_in_review_window(**kwargs, last_feed_at=feed, last_object_id=obj.id) == 0
    selection.scope_active = True
    db_session.flush()
    assert recent.count_review_window(**kwargs) == 1


def test_context_pinned_and_folder_expansion_hide_inactive_representations(db_session):
    user, _, selection, scoped = _scope_fixture(db_session, active=False)
    graph = GraphService(db_session, user.id)
    folder = graph.create_object(ObjectCreate(kind="folder", title="Scope folder", origin="user"))
    graph.create_edge(EdgeCreate(
        source_id=folder.id, target_id=scoped.id, type="contains", origin="user", state="confirmed",
    ))
    pinned = graph.create_object(ObjectCreate(kind="note", title="Pinned anchor", origin="user"))
    graph.create_edge(EdgeCreate(
        source_id=pinned.id, target_id=scoped.id, type="references", origin="user", state="confirmed",
        metadata={"context_role": "user_pinned", "added_by": "user"},
    ))
    db_session.add(Representation(id=uuid4(), object_id=scoped.id, kind="full", text="hidden unique representation"))
    db_session.flush()
    service = ContextService(db_session, user.id)
    inactive_context = service.build_context(object_id=folder.id)
    assert scoped.id not in {item.object_id for item in inactive_context.items}
    assert all("hidden unique representation" not in item.content for item in inactive_context.items)
    pinned_context = service.build_context(object_id=pinned.id)
    assert scoped.id not in {item.object_id for item in pinned_context.items}
    selection.scope_active = True
    db_session.flush()
    assert scoped.id in {item.object_id for item in service.build_context(object_id=folder.id).items}
    assert scoped.id in {item.object_id for item in service.build_context(object_id=pinned.id).items}


def test_visibility_toggle_has_no_persistent_or_enqueue_side_effects(db_session):
    user, _, selection, obj = _scope_fixture(db_session)
    rep = Representation(id=uuid4(), object_id=obj.id, kind="full", text="stable representation")
    db_session.add(rep)
    db_session.flush()
    before = (obj.id, obj.body, obj.metadata_, obj.updated_at, rep.id, rep.text)
    db_session.expire_all()
    selection = db_session.get(TelegramMtprotoChatSelection, selection.id)
    selection.scope_active = False
    db_session.flush()
    _ = ObjectQueryService(db_session, user.id).query(kinds=["chat_message"], providers=["telegram"])
    selection.scope_active = True
    db_session.flush()
    db_session.refresh(obj)
    db_session.refresh(rep)
    after = (obj.id, obj.body, obj.metadata_, obj.updated_at, rep.id, rep.text)
    assert after == before
    assert db_session.get(Object, obj.id) is not None
    assert db_session.get(Representation, rep.id) is not None
