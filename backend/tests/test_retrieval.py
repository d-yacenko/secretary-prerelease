import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api.schemas import ObjectCreate
from app.db.models import Object, User
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import REJECTED_STATE
from app.services.retrieval_constants import (
    FTS_DOCUMENT_SQL,
    MAX_CANDIDATE_POOL,
    MAX_FINAL_HITS,
    TIME_SCOPE_ALL,
    TIME_SCOPE_AUTO,
    TIME_SCOPE_RECENT,
)
from app.services.retrieval_service import (
    RetrievalService,
    _build_fts_candidate_sql,
    _build_trigram_candidate_sql,
)
from app.services.search_service import SearchService
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def user_b_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="User B"))
    db_session.flush()
    return user_id


@pytest.fixture
def nornickel_user_id(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Nornickel corpus user"))
    db_session.flush()
    return user_id


def _create_object(
    db_session,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str | None = None,
    provider: str | None = None,
    occurred_at: datetime | None = None,
    state: str = "confirmed",
    status: str | None = None,
) -> Object:
    graph = GraphService(db_session, user_id, None)
    obj = graph.create_object(
        ObjectCreate(
            kind=kind,
            title=title,
            body=body,
            origin="source",
            provider=provider,
            state=state,
            status=status,
        )
    )
    if occurred_at is not None:
        obj.occurred_at = occurred_at
    db_session.flush()
    return obj


def test_retrieval_user_isolation(db_session, user_b_id) -> None:
    user_a_object = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="event",
        title="Isolation unique Norilsk marker A",
        occurred_at=datetime.now(UTC),
    )
    user_b_object = _create_object(
        db_session,
        user_b_id,
        kind="event",
        title="Isolation unique Norilsk marker B",
        occurred_at=datetime.now(UTC),
    )

    service = RetrievalService(db_session, BOOTSTRAP_USER_ID)
    hits = service.retrieve(
        "Isolation unique Norilsk marker",
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    hit_ids = {hit.object_id for hit in hits}
    assert user_a_object.id in hit_ids
    assert user_b_object.id not in hit_ids


def test_retrieval_top_k_is_maximum_not_target(db_session) -> None:
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="event",
        title="Unique anchor title marker",
        occurred_at=datetime.now(UTC),
    )
    for index in range(10):
        _create_object(
            db_session,
            BOOTSTRAP_USER_ID,
            kind="email",
            title=f"Noise newsletter {index}",
            body="random unrelated newsletter body",
            provider="gmail",
            occurred_at=datetime.now(UTC),
        )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Unique anchor title marker",
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    assert len(hits) == 1


def test_retrieval_nornickel_fixture(db_session) -> None:
    now = datetime.now(UTC)
    event = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="event",
        title="Вопрос по Норникелю",
        body="Обсуждение активности",
        provider="google_calendar",
        occurred_at=now - timedelta(days=3),
    )
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="Re: Норникель quarterly update",
        body="Норникель activity summary for the team",
        provider="gmail",
        occurred_at=now - timedelta(days=2),
    )
    for index in range(12):
        _create_object(
            db_session,
            BOOTSTRAP_USER_ID,
            kind="email",
            title=f"Server status newsletter {index}",
            body="automated server monitoring message",
            provider="gmail",
            occurred_at=now - timedelta(days=1),
        )
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="task",
        title="Тестовая задача из Linux клиента",
        body="linux client smoke marker",
        occurred_at=None,
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "активность по норникелю",
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits

    assert len(hits) <= MAX_FINAL_HITS
    assert hits[0].object_id == event.id
    titles = {hit.title for hit in hits}
    assert "Тестовая задача из Linux клиента" not in titles
    assert all("Server status newsletter" not in title for title in titles)


def test_retrieval_recent_horizon_excludes_old_source_noise(db_session) -> None:
    now = datetime.now(UTC)
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="event",
        title="Recent Norilsk planning session",
        occurred_at=now - timedelta(days=5),
    )
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="Old Norilsk archive email",
        body="Norilsk historical mention",
        provider="gmail",
        occurred_at=now - timedelta(days=400),
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Norilsk",
        time_scope=TIME_SCOPE_RECENT,
        limit=5,
    ).hits
    titles = {hit.title for hit in hits}
    assert "Recent Norilsk planning session" in titles
    assert "Old Norilsk archive email" not in titles


def test_retrieval_old_history_fallback(db_session) -> None:
    now = datetime.now(UTC)
    old_email = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="Ancient exact subject Norilsk archive",
        body="little else",
        provider="gmail",
        occurred_at=now - timedelta(days=800),
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Ancient exact subject Norilsk archive",
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits
    assert any(hit.object_id == old_email.id for hit in hits)


def test_retrieval_explicit_all_history(db_session) -> None:
    now = datetime.now(UTC)
    old_email = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="Legacy mailbox Norilsk note",
        provider="gmail",
        occurred_at=now - timedelta(days=500),
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Legacy mailbox Norilsk",
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    assert any(hit.object_id == old_email.id for hit in hits)


def test_retrieval_occurred_at_not_created_at_for_recency(db_session) -> None:
    now = datetime.now(UTC)
    old_occurred = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="Historical Norilsk import today",
        provider="gmail",
        occurred_at=now - timedelta(days=600),
    )
    old_occurred.created_at = now
    db_session.flush()

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Historical Norilsk import today",
        time_scope=TIME_SCOPE_RECENT,
        limit=5,
    ).hits
    assert hits == []


def test_retrieval_unknown_source_time_not_recent(db_session) -> None:
    now = datetime.now(UTC)
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="Unknown-time Norilsk email",
        body="Norilsk unknown timestamp",
        provider="gmail",
        occurred_at=None,
    )
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="event",
        title="Known recent Norilsk event",
        occurred_at=now - timedelta(days=2),
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Norilsk",
        time_scope=TIME_SCOPE_RECENT,
        limit=5,
    ).hits
    titles = {hit.title for hit in hits}
    assert "Known recent Norilsk event" in titles
    assert "Unknown-time Norilsk email" not in titles


def test_retrieval_does_not_call_embedding_service(db_session) -> None:
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="note",
        title="Embedding isolation marker",
        body="embedding isolation body",
    )
    RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Embedding isolation marker",
        time_scope=TIME_SCOPE_ALL,
    )
    SearchService(db_session, BOOTSTRAP_USER_ID).search("Embedding isolation marker")


def test_retrieval_excludes_deleted_and_rejected(db_session) -> None:
    active = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="note",
        title="Retrieval visibility marker",
        body="visible",
    )
    deleted = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="note",
        title="Retrieval visibility marker deleted",
        body="hidden deleted",
        status="deleted",
    )
    rejected = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="note",
        title="Retrieval visibility marker rejected",
        body="hidden rejected",
        state=REJECTED_STATE,
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Retrieval visibility marker",
        time_scope=TIME_SCOPE_ALL,
        limit=10,
    ).hits
    ids = {hit.object_id for hit in hits}
    assert active.id in ids
    assert deleted.id not in ids
    assert rejected.id not in ids


def test_retrieval_candidate_bounds(db_session) -> None:
    now = datetime.now(UTC)
    for index in range(MAX_CANDIDATE_POOL + 25):
        _create_object(
            db_session,
            BOOTSTRAP_USER_ID,
            kind="email",
            title=f"Bound noise email {index}",
            body="bound noise keyword",
            provider="gmail",
            occurred_at=now - timedelta(days=1),
        )
    _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="event",
        title="Bound noise keyword anchor event",
        occurred_at=now,
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "Bound noise keyword",
        time_scope=TIME_SCOPE_ALL,
        limit=MAX_FINAL_HITS,
    ).hits
    assert len(hits) <= MAX_FINAL_HITS


def test_retrieval_candidate_sql_uses_indexed_operators() -> None:
    fts_sql = _build_fts_candidate_sql("")
    trigram_sql = _build_trigram_candidate_sql("")
    fts_where = fts_sql.split("ORDER BY")[0]
    trigram_where = trigram_sql.split("ORDER BY")[0]

    assert FTS_DOCUMENT_SQL in fts_sql
    assert "@@ plainto_tsquery" in fts_where
    assert "ts_rank" in fts_sql
    assert "ORDER BY" in fts_sql
    assert "similarity(" not in fts_where
    assert "o.title % :query" in trigram_where
    assert "similarity(" not in trigram_where
    assert "ORDER BY" in trigram_sql
    assert "similarity(" in trigram_sql


def test_retrieval_candidate_branches_rank_and_do_not_starve(db_session) -> None:
    now = datetime.now(UTC)
    query = "CandidateBranchUniqueMarker"
    trigram_title = "CandidateBranchUnique Mark"
    for index in range(MAX_CANDIDATE_POOL + 50):
        _create_object(
            db_session,
            BOOTSTRAP_USER_ID,
            kind="email",
            title=f"Noise email {index}",
            body=f"{query} filler noise token {index}",
            provider="gmail",
            occurred_at=now,
        )
    strong_title = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title=query,
        body="brief",
        provider="gmail",
        occurred_at=now,
    )
    strong_trigram = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="task",
        title=trigram_title,
        body="unrelated body text",
        occurred_at=None,
    )

    service = RetrievalService(db_session, BOOTSTRAP_USER_ID)
    candidate_ids = service._collect_candidate_ids(
        query=query,
        kind=None,
        provider=None,
        project_id=None,
        horizon_cutoff=None,
        date_from=None,
        date_to=None,
        apply_horizon=False,
    )
    assert len(candidate_ids) <= MAX_CANDIDATE_POOL
    assert strong_title.id in candidate_ids
    assert strong_trigram.id in candidate_ids

    hits = service.retrieve(query, time_scope=TIME_SCOPE_ALL, limit=5).hits
    hit_ids = {hit.object_id for hit in hits}
    assert strong_title.id in hit_ids
    assert strong_trigram.id in hit_ids
    assert hits[0].object_id == strong_title.id


def test_retrieval_weak_recent_anchors_do_not_stop_horizon(db_session) -> None:
    now = datetime.now(UTC)
    marker = "HorizonWidenUniqueMarkerPhrase"
    old_email = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title=marker,
        body="little else",
        provider="gmail",
        occurred_at=now - timedelta(days=800),
    )
    for index in range(6):
        _create_object(
            db_session,
            BOOTSTRAP_USER_ID,
            kind="task",
            title="HorizonWide",
            occurred_at=now - timedelta(days=2),
        )
        _create_object(
            db_session,
            BOOTSTRAP_USER_ID,
            kind="event",
            title="HorizonWide",
            occurred_at=now - timedelta(days=1),
        )
    for index in range(4):
        _create_object(
            db_session,
            BOOTSTRAP_USER_ID,
            kind="email",
            title=f"Random unrelated newsletter {index}",
            body="automated unrelated monitoring",
            provider="gmail",
            occurred_at=now - timedelta(days=1),
        )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        marker,
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits
    assert any(hit.object_id == old_email.id for hit in hits)


def test_retrieval_unknown_time_email_all_history_no_recent_reason(db_session) -> None:
    now = datetime.now(UTC)
    email = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="UnknownTimeAllHistory Norilsk marker",
        body="Norilsk unknown timestamp body",
        provider="gmail",
        occurred_at=None,
    )
    email.created_at = now
    db_session.flush()

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "UnknownTimeAllHistory Norilsk",
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    matched = [hit for hit in hits if hit.object_id == email.id]
    assert matched
    assert "recent" not in matched[0].reasons


def test_retrieval_unknown_time_email_no_recency_bonus_in_score(db_session) -> None:
    now = datetime.now(UTC)
    title = "RecencyCompare Norilsk marker"
    unknown = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title=title,
        body="Norilsk score check",
        provider="gmail",
        occurred_at=None,
    )
    unknown.created_at = now
    known = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title=title,
        body="Norilsk score check",
        provider="gmail",
        occurred_at=now,
    )
    db_session.flush()

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "RecencyCompare Norilsk",
        time_scope=TIME_SCOPE_ALL,
        limit=5,
    ).hits
    by_id = {hit.object_id: hit for hit in hits}
    assert unknown.id in by_id
    assert known.id in by_id
    assert "recent" not in by_id[unknown.id].reasons
    assert "recent" in by_id[known.id].reasons
    assert by_id[unknown.id].relevance < by_id[known.id].relevance


def test_retrieval_explicit_date_from_only(db_session) -> None:
    now = datetime.now(UTC)
    early = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="DateFromOnly Norilsk marker",
        provider="gmail",
        occurred_at=now - timedelta(days=120),
    )
    late = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="DateFromOnly Norilsk marker recent",
        provider="gmail",
        occurred_at=now - timedelta(days=5),
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "DateFromOnly Norilsk",
        date_from=now - timedelta(days=30),
        limit=10,
    ).hits
    ids = {hit.object_id for hit in hits}
    assert late.id in ids
    assert early.id not in ids


def test_retrieval_explicit_date_to_only(db_session) -> None:
    now = datetime.now(UTC)
    early = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="DateToOnly Norilsk marker",
        provider="gmail",
        occurred_at=now - timedelta(days=120),
    )
    late = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="DateToOnly Norilsk marker recent",
        provider="gmail",
        occurred_at=now - timedelta(days=5),
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "DateToOnly Norilsk",
        date_to=now - timedelta(days=30),
        limit=10,
    ).hits
    ids = {hit.object_id for hit in hits}
    assert early.id in ids
    assert late.id not in ids


def test_retrieval_explicit_date_range_both(db_session) -> None:
    now = datetime.now(UTC)
    too_early = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="DateRange Norilsk marker",
        provider="gmail",
        occurred_at=now - timedelta(days=200),
    )
    in_range = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="DateRange Norilsk marker mid",
        provider="gmail",
        occurred_at=now - timedelta(days=60),
    )
    too_late = _create_object(
        db_session,
        BOOTSTRAP_USER_ID,
        kind="email",
        title="DateRange Norilsk marker recent",
        provider="gmail",
        occurred_at=now - timedelta(days=2),
    )

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(
        "DateRange Norilsk",
        date_from=now - timedelta(days=90),
        date_to=now - timedelta(days=30),
        limit=10,
    ).hits
    ids = {hit.object_id for hit in hits}
    assert in_range.id in ids
    assert too_early.id not in ids
    assert too_late.id not in ids


def _seed_nornickel_corpus(db_session, user_id: uuid.UUID) -> dict[str, Object]:
    now = datetime.now(UTC)
    event = _create_object(
        db_session,
        user_id,
        kind="event",
        title="Вопрос по Норникелю",
        body="Обсуждение активности",
        provider="google_calendar",
        occurred_at=now - timedelta(days=3),
    )
    task = _create_object(
        db_session,
        user_id,
        kind="task",
        title="Подготовить и провести семинар ADC для Норникеля",
        body="Семинар ADC DQF",
        occurred_at=None,
    )
    email_adc = _create_object(
        db_session,
        user_id,
        kind="email",
        title="Fwd: Обучающий семинар ADC DQF Норникель",
        body="Обучающий семинар для Норникеля",
        provider="yandex_mail",
        occurred_at=now - timedelta(days=4),
    )
    email_training = _create_object(
        db_session,
        user_id,
        kind="email",
        title="Re: Семинары по обучению сотрудников Норникеля",
        body="План обучения сотрудников",
        provider="yandex_mail",
        occurred_at=now - timedelta(days=2),
    )
    linux_task = _create_object(
        db_session,
        user_id,
        kind="task",
        title="Тестовая задача из Linux клиента",
        body="linux client smoke marker",
        occurred_at=None,
    )
    for index in range(12):
        _create_object(
            db_session,
            user_id,
            kind="email",
            title=f"Server status newsletter {index}",
            body="automated server monitoring message",
            provider="gmail",
            occurred_at=now - timedelta(days=1),
        )
    _create_object(
        db_session,
        user_id,
        kind="email",
        title="Random unrelated quarterly bulletin",
        body="unrelated corporate newsletter",
        provider="gmail",
        occurred_at=now - timedelta(days=1),
    )
    return {
        "event": event,
        "task": task,
        "email_adc": email_adc,
        "email_training": email_training,
        "linux_task": linux_task,
    }


def test_retrieval_nornickel_morphology(db_session, nornickel_user_id) -> None:
    corpus = _seed_nornickel_corpus(db_session, nornickel_user_id)
    service = RetrievalService(db_session, nornickel_user_id)
    anchor_ids = {corpus["event"].id, corpus["task"].id}

    for query in ("норникель", "норникелю", "норникеля"):
        hits = service.retrieve(query, time_scope=TIME_SCOPE_AUTO, limit=5).hits
        hit_ids = {hit.object_id for hit in hits}
        assert anchor_ids & hit_ids


def test_retrieval_kursy_po_nornikelyu(db_session, nornickel_user_id) -> None:
    corpus = _seed_nornickel_corpus(db_session, nornickel_user_id)
    hits = RetrievalService(db_session, nornickel_user_id).retrieve(
        "курсы по норникелю",
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits
    assert hits
    hit_ids = {hit.object_id for hit in hits}
    assert corpus["event"].id in hit_ids or corpus["task"].id in hit_ids


def test_retrieval_nl_phrase_nornickel(db_session, nornickel_user_id) -> None:
    corpus = _seed_nornickel_corpus(db_session, nornickel_user_id)
    hits = RetrievalService(db_session, nornickel_user_id).retrieve(
        "посмотри по всем объектам что у нас связано с курсами по норникелю",
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits
    assert hits
    hit_ids = {hit.object_id for hit in hits}
    assert corpus["event"].id in hit_ids or corpus["task"].id in hit_ids
    titles = {hit.title for hit in hits}
    assert "Тестовая задача из Linux клиента" not in titles


LIVE_NL_PHRASE = (
    "Посмотри по всем объектам. У нас есть что-то связанное "
    "с курсами по норникелю? и собери из этого задачу"
)


def test_retrieval_live_nl_phrase_exact_nornickel(db_session, nornickel_user_id) -> None:
    corpus = _seed_nornickel_corpus(db_session, nornickel_user_id)
    hits = RetrievalService(db_session, nornickel_user_id).retrieve(
        LIVE_NL_PHRASE,
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits
    assert hits
    assert len(hits) <= 5
    hit_ids = {hit.object_id for hit in hits}
    anchor_ids = {
        corpus["event"].id,
        corpus["task"].id,
        corpus["email_adc"].id,
        corpus["email_training"].id,
    }
    assert hit_ids & anchor_ids
    titles = {hit.title for hit in hits}
    assert "Тестовая задача из Linux клиента" not in titles
    assert all("Server status newsletter" not in title for title in titles)


def test_retrieval_relaxed_survives_when_strict_pool_full(
    db_session, nornickel_user_id
) -> None:
    now = datetime.now(UTC)
    flood_token = "WeakStrictFloodToken"
    survivor_token = "RelaxedSurvivorMarker"
    generic_body = (
        f"посмотри объект связанное курсами {flood_token}"
    )
    for index in range(110):
        _create_object(
            db_session,
            nornickel_user_id,
            kind="email",
            title=f"{flood_token} noise email {index}",
            body=f"{generic_body} filler {index}",
            provider="gmail",
            occurred_at=now - timedelta(days=1),
        )
    survivor = _create_object(
        db_session,
        nornickel_user_id,
        kind="event",
        title=f"{survivor_token} anchor event",
        body="little else",
        occurred_at=now,
    )
    query = (
        "посмотри по всем объектам что связанное курсами "
        f"{flood_token} {survivor_token}"
    )
    result = RetrievalService(db_session, nornickel_user_id).retrieve(
        query,
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    )
    assert result.candidate_count <= MAX_CANDIDATE_POOL
    assert result.retrieval_mode == "relaxed"
    hit_ids = {hit.object_id for hit in result.hits}
    assert survivor.id in hit_ids
    assert result.hits[0].object_id == survivor.id


def test_retrieval_adc_nornickel(db_session, nornickel_user_id) -> None:
    corpus = _seed_nornickel_corpus(db_session, nornickel_user_id)
    hits = RetrievalService(db_session, nornickel_user_id).retrieve(
        "ADC норникель",
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits
    hit_ids = {hit.object_id for hit in hits}
    assert corpus["task"].id in hit_ids or corpus["email_adc"].id in hit_ids


def test_retrieval_generic_terms_do_not_starve_distinctive(
    db_session, nornickel_user_id
) -> None:
    corpus = _seed_nornickel_corpus(db_session, nornickel_user_id)
    hits = RetrievalService(db_session, nornickel_user_id).retrieve(
        "посмотри по всем объектам что у нас связано с курсами по норникелю",
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    ).hits
    assert hits
    assert hits[0].object_id != corpus["linux_task"].id
    titles = {hit.title for hit in hits}
    assert "Тестовая задача из Linux клиента" not in titles


def test_retrieval_relaxed_mode_telemetry_fields(db_session, nornickel_user_id) -> None:
    _seed_nornickel_corpus(db_session, nornickel_user_id)
    result = RetrievalService(db_session, nornickel_user_id).retrieve(
        "посмотри по всем объектам что у нас связано с курсами по норникелю",
        time_scope=TIME_SCOPE_AUTO,
        limit=5,
    )
    assert result.retrieval_mode == "relaxed"
    assert result.query_atom_count > 0
    assert result.selected_atom_count > 0


def test_search_retrieve_consistency(db_session, nornickel_user_id) -> None:
    _seed_nornickel_corpus(db_session, nornickel_user_id)
    query = "норникель"
    retrieval_ids = {
        hit.object_id
        for hit in RetrievalService(db_session, nornickel_user_id).retrieve(
            query,
            time_scope=TIME_SCOPE_ALL,
            limit=5,
        ).hits
    }
    search_ids = {
        obj.id
        for obj in SearchService(db_session, nornickel_user_id).search(query, limit=5)
    }
    assert retrieval_ids == search_ids


def test_retrieval_rejects_invalid_date_range(db_session) -> None:
    now = datetime.now(UTC)
    service = RetrievalService(db_session, BOOTSTRAP_USER_ID)
    with pytest.raises(ValidationError, match="date_from"):
        service.retrieve(
            "anything",
            date_from=now,
            date_to=now - timedelta(days=1),
        )
