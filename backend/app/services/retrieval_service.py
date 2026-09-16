from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Object
from app.services.errors import ValidationError
from app.services.evidence_snippet import (
    build_query_centered_snippet,
    representation_evidence_rank_key,
)
from app.services.retrieval_constants import (
    ANCHOR_KIND_BOOST,
    ANCHOR_KINDS,
    BODY_FTS_WEIGHT,
    CLOUD_CURRENT_REPRESENTATION_GATE_SQL,
    CLOUD_CURRENT_REPRESENTATION_SQL,
    DEFAULT_FINAL_HITS,
    FTS_BRANCH_LIMIT,
    FTS_DOCUMENT_SQL,
    MAX_CANDIDATE_POOL,
    MAX_FINAL_HITS,
    MIN_BODY_FTS_THRESHOLD,
    MIN_TITLE_QUALIFY_THRESHOLD,
    MIN_TRIGRAM_QUALIFY_THRESHOLD,
    RECENCY_BONUS,
    RECENCY_WINDOW,
    RECENT_HORIZON_DAYS,
    RELAXED_FALLBACK_QUOTA,
    RELAXED_RUSSIAN_FTS_PER_ATOM,
    RELAXED_SIMPLE_FTS_PER_ATOM,
    RELAXED_TRIGRAM_PER_ATOM,
    REPRESENTATION_FTS_WEIGHT,
    RETRIEVAL_MODE_RELAXED,
    RETRIEVAL_MODE_STRICT,
    RETRIEVAL_REPRESENTATION_KINDS_SQL,
    RUSSIAN_FTS_DOCUMENT_SQL,
    SHORT_EXCERPT_MAX_CHARS,
    STRICT_FALLBACK_QUOTA,
    STRONG_TITLE_FTS_THRESHOLD,
    STRONG_TRIGRAM_THRESHOLD,
    TERM_COVERAGE_BONUS,
    TIME_SCOPE_ALL,
    TIME_SCOPE_AUTO,
    TIME_SCOPE_RECENT,
    TIME_SENSITIVE_SOURCE_KINDS,
    TITLE_FTS_WEIGHT,
    TRIGRAM_BRANCH_LIMIT,
    TRIGRAM_WEIGHT,
    YEAR_HORIZON_DAYS,
)
from app.services.retrieval_models import RetrievalHit, RetrievalResult
from app.services.retrieval_query_atoms import (
    extract_query_atoms,
    is_cyrillic_atom,
    is_technical_atom,
    select_selective_atoms,
)

_BASE_WHERE = """
    o.user_id = :user_id
    AND o.deleted_at IS NULL
    AND (o.status IS NULL OR o.status != 'deleted')
    AND o.state != 'rejected'
    AND (o.kind != 'label' OR :include_labels)
"""


def _build_filter_suffix(
    kind: str | None,
    provider: str | None,
    project_id: UUID | None,
    horizon_cutoff: datetime | None,
    date_from: datetime | None,
    date_to: datetime | None,
    apply_horizon: bool,
    label_id: UUID | None = None,
) -> str:
    filters: list[str] = []
    if kind is not None:
        filters.append("AND o.kind = :kind")
    if provider is not None:
        filters.append("AND o.provider = :provider")
    if label_id is not None:
        filters.append(
            """
            AND EXISTS (
                SELECT 1
                FROM edges le
                INNER JOIN objects lo ON lo.id = le.target_id
                WHERE le.user_id = :user_id
                  AND le.source_id = o.id
                  AND le.target_id = :label_id
                  AND le.type = 'labeled_with'
                  AND le.state != 'rejected'
                  AND lo.user_id = :user_id
                  AND lo.kind = 'label'
                  AND lo.state != 'rejected'
                  AND lo.deleted_at IS NULL
                  AND (lo.status IS NULL OR lo.status != 'deleted')
            )
            """
        )
    if project_id is not None:
        filters.append(
            """
            AND o.id IN (
                SELECT e.target_id FROM edges e
                WHERE e.user_id = :user_id AND e.source_id = :project_id
                UNION
                SELECT e.source_id FROM edges e
                WHERE e.user_id = :user_id AND e.target_id = :project_id
            )
            """
        )
    if apply_horizon and horizon_cutoff is not None:
        filters.append(
            """
            AND (
                o.kind NOT IN ('email', 'event', 'chat_message')
                OR (o.occurred_at IS NOT NULL AND o.occurred_at >= :horizon_cutoff)
            )
            """
        )
    if date_from is not None and date_to is not None:
        filters.append(
            """
            AND (
                o.kind NOT IN ('email', 'event', 'chat_message')
                OR (
                    o.occurred_at IS NOT NULL
                    AND o.occurred_at >= :date_from
                    AND o.occurred_at <= :date_to
                )
            )
            """
        )
    elif date_from is not None:
        filters.append(
            """
            AND (
                o.kind NOT IN ('email', 'event', 'chat_message')
                OR (o.occurred_at IS NOT NULL AND o.occurred_at >= :date_from)
            )
            """
        )
    elif date_to is not None:
        filters.append(
            """
            AND (
                o.kind NOT IN ('email', 'event', 'chat_message')
                OR (o.occurred_at IS NOT NULL AND o.occurred_at <= :date_to)
            )
            """
        )
    return "\n".join(filters)


def _build_fts_candidate_sql(filter_suffix: str) -> str:
    return f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {filter_suffix}
      AND ({FTS_DOCUMENT_SQL}) @@ plainto_tsquery('simple', :query)
    ORDER BY
      ts_rank(
        ({FTS_DOCUMENT_SQL}),
        plainto_tsquery('simple', :query)
      ) DESC,
      o.id
    LIMIT :branch_limit
    """


def _build_trigram_candidate_sql(filter_suffix: str) -> str:
    return f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {filter_suffix}
      AND o.title % :query
    ORDER BY
      similarity(coalesce(o.title, ''), :query) DESC,
      o.id
    LIMIT :branch_limit
    """


def _build_representation_fts_candidate_sql(filter_suffix: str, ts_config: str) -> str:
    return f"""
    SELECT o.id
    FROM representations r
    INNER JOIN objects o ON o.id = r.object_id
    WHERE {_BASE_WHERE}
      {filter_suffix}
      {CLOUD_CURRENT_REPRESENTATION_SQL}
      AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
      AND to_tsvector('{ts_config}', coalesce(r.text, ''))
          @@ plainto_tsquery('{ts_config}', :query)
    GROUP BY o.id
    ORDER BY
      MAX(
        ts_rank(
          to_tsvector('{ts_config}', coalesce(r.text, '')),
          plainto_tsquery('{ts_config}', :query)
        )
      ) DESC,
      o.id
    LIMIT :branch_limit
    """


def _build_atom_simple_fts_sql(filter_suffix: str) -> str:
    return f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {filter_suffix}
      AND ({FTS_DOCUMENT_SQL}) @@ plainto_tsquery('simple', :atom)
    ORDER BY
      ts_rank(
        ({FTS_DOCUMENT_SQL}),
        plainto_tsquery('simple', :atom)
      ) DESC,
      o.id
    LIMIT :branch_limit
    """


def _build_atom_russian_fts_sql(filter_suffix: str) -> str:
    return f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {filter_suffix}
      AND ({RUSSIAN_FTS_DOCUMENT_SQL}) @@ plainto_tsquery('russian', :atom)
    ORDER BY
      ts_rank(
        ({RUSSIAN_FTS_DOCUMENT_SQL}),
        plainto_tsquery('russian', :atom)
      ) DESC,
      o.id
    LIMIT :branch_limit
    """


def _build_atom_trigram_sql(filter_suffix: str) -> str:
    return f"""
    SELECT o.id
    FROM objects o
    WHERE {_BASE_WHERE}
      {filter_suffix}
      AND o.title % :atom
    ORDER BY
      similarity(coalesce(o.title, ''), :atom) DESC,
      o.id
    LIMIT :branch_limit
    """


def _build_atom_representation_simple_fts_sql(filter_suffix: str) -> str:
    return f"""
    SELECT o.id
    FROM representations r
    INNER JOIN objects o ON o.id = r.object_id
    WHERE {_BASE_WHERE}
      {filter_suffix}
      {CLOUD_CURRENT_REPRESENTATION_SQL}
      AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
      AND to_tsvector('simple', coalesce(r.text, ''))
          @@ plainto_tsquery('simple', :atom)
    GROUP BY o.id
    ORDER BY
      MAX(
        ts_rank(
          to_tsvector('simple', coalesce(r.text, '')),
          plainto_tsquery('simple', :atom)
        )
      ) DESC,
      o.id
    LIMIT :branch_limit
    """


def _build_atom_representation_russian_fts_sql(filter_suffix: str) -> str:
    return f"""
    SELECT o.id
    FROM representations r
    INNER JOIN objects o ON o.id = r.object_id
    WHERE {_BASE_WHERE}
      {filter_suffix}
      {CLOUD_CURRENT_REPRESENTATION_SQL}
      AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
      AND to_tsvector('russian', coalesce(r.text, ''))
          @@ plainto_tsquery('russian', :atom)
    GROUP BY o.id
    ORDER BY
      MAX(
        ts_rank(
          to_tsvector('russian', coalesce(r.text, '')),
          plainto_tsquery('russian', :atom)
        )
      ) DESC,
      o.id
    LIMIT :branch_limit
    """


def _bounded_round_robin_merge(branches: list[list[UUID]], limit: int) -> list[UUID]:
    seen: set[UUID] = set()
    merged: list[UUID] = []
    indices = [0] * len(branches)
    while len(merged) < limit:
        progressed = False
        for branch_index, branch in enumerate(branches):
            while indices[branch_index] < len(branch):
                object_id = branch[indices[branch_index]]
                indices[branch_index] += 1
                if object_id in seen:
                    continue
                seen.add(object_id)
                merged.append(object_id)
                progressed = True
                if len(merged) >= limit:
                    return merged
                break
        if not progressed:
            break
    return merged


_RANK_QUERY = text(
    f"""
    SELECT
        o.id,
        o.title,
        o.kind,
        o.provider,
        o.state,
        o.status,
        o.occurred_at,
        o.body,
        o.created_at,
        GREATEST(
            ts_rank(
                to_tsvector('simple', coalesce(o.title, '')),
                plainto_tsquery('simple', :query)
            ),
            ts_rank(
                to_tsvector('russian', coalesce(o.title, '')),
                plainto_tsquery('russian', :query)
            )
        ) AS title_rank,
        GREATEST(
            ts_rank(
                to_tsvector('simple', coalesce(o.body, '')),
                plainto_tsquery('simple', :query)
            ),
            ts_rank(
                to_tsvector('russian', coalesce(o.body, '')),
                plainto_tsquery('russian', :query)
            )
        ) AS body_rank,
        similarity(coalesce(o.title, ''), :query) AS title_sim,
        (
            SELECT MAX(
                GREATEST(
                    ts_rank(
                        to_tsvector('simple', coalesce(r.text, '')),
                        plainto_tsquery('simple', :query)
                    ),
                    ts_rank(
                        to_tsvector('russian', coalesce(r.text, '')),
                        plainto_tsquery('russian', :query)
                    )
                )
            )
            FROM representations r
            WHERE r.object_id = o.id
              AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
              AND (
                {CLOUD_CURRENT_REPRESENTATION_GATE_SQL}
              )
        ) AS rep_rank,
        (
            SELECT r.text
            FROM representations r
            WHERE r.object_id = o.id
              AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
              AND (
                {CLOUD_CURRENT_REPRESENTATION_GATE_SQL}
              )
            ORDER BY
              GREATEST(
                ts_rank(
                  to_tsvector('simple', coalesce(r.text, '')),
                  plainto_tsquery('simple', :query)
                ),
                ts_rank(
                  to_tsvector('russian', coalesce(r.text, '')),
                  plainto_tsquery('russian', :query)
                )
              ) DESC
            LIMIT 1
        ) AS rep_excerpt
    FROM objects o
    WHERE o.user_id = :user_id
      AND o.id = ANY(:candidate_ids)
    """
)

_TERM_RANK_QUERY = text(
    f"""
    SELECT
        o.id,
        (
            SELECT MAX(
                GREATEST(
                    ts_rank(
                        to_tsvector('simple', coalesce(o.title, '')),
                        plainto_tsquery('simple', atom)
                    ),
                    ts_rank(
                        to_tsvector('russian', coalesce(o.title, '')),
                        plainto_tsquery('russian', atom)
                    )
                )
            )
            FROM unnest(CAST(:atoms AS text[])) AS atom
        ) AS best_atom_title_rank,
        (
            SELECT MAX(
                GREATEST(
                    ts_rank(
                        to_tsvector('simple', coalesce(o.body, '')),
                        plainto_tsquery('simple', atom)
                    ),
                    ts_rank(
                        to_tsvector('russian', coalesce(o.body, '')),
                        plainto_tsquery('russian', atom)
                    )
                )
            )
            FROM unnest(CAST(:atoms AS text[])) AS atom
        ) AS best_atom_body_rank,
        (
            SELECT MAX(similarity(coalesce(o.title, ''), atom))
            FROM unnest(CAST(:atoms AS text[])) AS atom
        ) AS best_atom_title_sim,
        (
            SELECT COUNT(*)::float
            FROM unnest(CAST(:atoms AS text[])) AS atom
            WHERE
                to_tsvector('simple', coalesce(o.title, ''))
                    @@ plainto_tsquery('simple', atom)
                OR to_tsvector('russian', coalesce(o.title, ''))
                    @@ plainto_tsquery('russian', atom)
                OR to_tsvector('simple', coalesce(o.body, ''))
                    @@ plainto_tsquery('simple', atom)
                OR to_tsvector('russian', coalesce(o.body, ''))
                    @@ plainto_tsquery('russian', atom)
                OR o.title % atom
                OR EXISTS (
                    SELECT 1
                    FROM representations r
                    WHERE r.object_id = o.id
                      AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
                      AND (
                        {CLOUD_CURRENT_REPRESENTATION_GATE_SQL}
                      )
                      AND (
                        to_tsvector('simple', coalesce(r.text, ''))
                            @@ plainto_tsquery('simple', atom)
                        OR to_tsvector('russian', coalesce(r.text, ''))
                            @@ plainto_tsquery('russian', atom)
                      )
                )
        ) AS atom_match_count,
        (
            SELECT MAX(
                GREATEST(
                    ts_rank(
                        to_tsvector('simple', coalesce(r.text, '')),
                        plainto_tsquery('simple', atom)
                    ),
                    ts_rank(
                        to_tsvector('russian', coalesce(r.text, '')),
                        plainto_tsquery('russian', atom)
                    )
                )
            )
            FROM representations r
            CROSS JOIN unnest(CAST(:atoms AS text[])) AS atom
            WHERE r.object_id = o.id
              AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
              AND (
                {CLOUD_CURRENT_REPRESENTATION_GATE_SQL}
              )
        ) AS best_atom_rep_rank
    FROM objects o
    WHERE o.user_id = :user_id
      AND o.id = ANY(:candidate_ids)
    """
)

_REPRESENTATIONS_FOR_OBJECTS = text(
    f"""
    SELECT r.object_id, r.text, r.kind, r.part_index, r.id
    FROM representations r
    INNER JOIN objects o ON o.id = r.object_id
    WHERE o.user_id = :user_id
      AND r.object_id = ANY(:object_ids)
      AND r.kind IN ({RETRIEVAL_REPRESENTATION_KINDS_SQL})
      AND (
        {CLOUD_CURRENT_REPRESENTATION_GATE_SQL}
      )
    ORDER BY r.object_id, r.part_index NULLS LAST, r.id
    """
)


class RetrievalService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def retrieve(
        self,
        query: str,
        *,
        kind: str | None = None,
        provider: str | None = None,
        project_id: UUID | None = None,
        time_scope: str = TIME_SCOPE_AUTO,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = DEFAULT_FINAL_HITS,
        hits_cap: int | None = None,
        label_id: UUID | None = None,
    ) -> RetrievalResult:
        normalized_query = query.strip()
        if not normalized_query:
            return RetrievalResult(
                hits=[],
                query=normalized_query,
                time_scope_used=time_scope,
                horizon_days=None,
            )

        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValidationError("date_from must be before or equal to date_to")

        final_limit = max(1, min(limit, hits_cap if hits_cap is not None else MAX_FINAL_HITS))
        now = datetime.now(UTC)
        recency_cutoff = now - RECENCY_WINDOW
        explicit_dates = date_from is not None or date_to is not None

        if explicit_dates:
            horizons: list[int | None] = [None]
            effective_scope = TIME_SCOPE_ALL
        elif time_scope == TIME_SCOPE_ALL:
            horizons = [None]
            effective_scope = TIME_SCOPE_ALL
        elif time_scope == TIME_SCOPE_RECENT:
            horizons = [RECENT_HORIZON_DAYS]
            effective_scope = TIME_SCOPE_RECENT
        else:
            horizons = [RECENT_HORIZON_DAYS, YEAR_HORIZON_DAYS, None]
            effective_scope = TIME_SCOPE_AUTO

        last_hits: list[RetrievalHit] = []
        last_horizon: int | None = None
        last_candidate_count = 0
        last_mode = RETRIEVAL_MODE_STRICT
        last_query_atom_count = 0
        last_selected_atom_count = 0

        for horizon_days in horizons:
            horizon_cutoff = None
            if horizon_days is not None:
                horizon_cutoff = now - timedelta(days=horizon_days)

            (
                last_hits,
                last_candidate_count,
                last_mode,
                last_query_atom_count,
                last_selected_atom_count,
            ) = self._score_and_rank(
                query=normalized_query,
                kind=kind,
                provider=provider,
                project_id=project_id,
                horizon_cutoff=horizon_cutoff,
                date_from=date_from,
                date_to=date_to,
                apply_horizon=not explicit_dates,
                recency_cutoff=recency_cutoff,
                label_id=label_id,
            )
            last_horizon = horizon_days

            if horizon_days is None:
                break
            if self._should_stop_horizon_expansion(last_hits):
                break

        trimmed = self._trim_to_limit(last_hits, final_limit)
        return RetrievalResult(
            hits=trimmed,
            query=normalized_query,
            time_scope_used=effective_scope,
            horizon_days=last_horizon,
            candidate_count=last_candidate_count,
            retrieval_mode=last_mode,
            query_atom_count=last_query_atom_count,
            selected_atom_count=last_selected_atom_count,
        )

    def _collect_candidate_ids(
        self,
        query: str,
        kind: str | None,
        provider: str | None,
        project_id: UUID | None,
        horizon_cutoff: datetime | None,
        date_from: datetime | None,
        date_to: datetime | None,
        apply_horizon: bool,
        label_id: UUID | None = None,
    ) -> list[UUID]:
        return self._collect_strict_candidate_ids(
            query=query,
            kind=kind,
            provider=provider,
            project_id=project_id,
            horizon_cutoff=horizon_cutoff,
            date_from=date_from,
            date_to=date_to,
            apply_horizon=apply_horizon,
            label_id=label_id,
        )

    def _collect_strict_candidate_ids(
        self,
        query: str,
        kind: str | None,
        provider: str | None,
        project_id: UUID | None,
        horizon_cutoff: datetime | None,
        date_from: datetime | None,
        date_to: datetime | None,
        apply_horizon: bool,
        label_id: UUID | None = None,
    ) -> list[UUID]:
        filter_suffix = _build_filter_suffix(
            kind=kind,
            provider=provider,
            project_id=project_id,
            horizon_cutoff=horizon_cutoff,
            date_from=date_from,
            date_to=date_to,
            apply_horizon=apply_horizon,
            label_id=label_id,
        )
        params = {
            "query": query,
            "user_id": self._user_id,
            "kind": kind,
            "provider": provider,
            "project_id": project_id,
            "horizon_cutoff": horizon_cutoff,
            "date_from": date_from,
            "date_to": date_to,
            "include_labels": kind == "label",
            "label_id": label_id,
        }

        fts_ids = self._session.execute(
            text(_build_fts_candidate_sql(filter_suffix)),
            {**params, "branch_limit": FTS_BRANCH_LIMIT},
        ).scalars()
        trigram_ids = self._session.execute(
            text(_build_trigram_candidate_sql(filter_suffix)),
            {**params, "branch_limit": TRIGRAM_BRANCH_LIMIT},
        ).scalars()
        rep_simple_ids = self._session.execute(
            text(_build_representation_fts_candidate_sql(filter_suffix, "simple")),
            {**params, "branch_limit": FTS_BRANCH_LIMIT},
        ).scalars()
        rep_russian_ids = self._session.execute(
            text(_build_representation_fts_candidate_sql(filter_suffix, "russian")),
            {**params, "branch_limit": FTS_BRANCH_LIMIT},
        ).scalars()

        return _bounded_round_robin_merge(
            [
                list(fts_ids),
                list(trigram_ids),
                list(rep_simple_ids),
                list(rep_russian_ids),
            ],
            MAX_CANDIDATE_POOL,
        )

    def _collect_relaxed_candidate_ids(
        self,
        atoms: list[str],
        kind: str | None,
        provider: str | None,
        project_id: UUID | None,
        horizon_cutoff: datetime | None,
        date_from: datetime | None,
        date_to: datetime | None,
        apply_horizon: bool,
        existing_ids: set[UUID],
        max_new_candidates: int = RELAXED_FALLBACK_QUOTA,
        label_id: UUID | None = None,
    ) -> list[UUID]:
        if not atoms:
            return []

        filter_suffix = _build_filter_suffix(
            kind=kind,
            provider=provider,
            project_id=project_id,
            horizon_cutoff=horizon_cutoff,
            date_from=date_from,
            date_to=date_to,
            apply_horizon=apply_horizon,
            label_id=label_id,
        )
        base_params = {
            "user_id": self._user_id,
            "kind": kind,
            "provider": provider,
            "project_id": project_id,
            "horizon_cutoff": horizon_cutoff,
            "date_from": date_from,
            "date_to": date_to,
            "include_labels": kind == "label",
            "label_id": label_id,
        }

        seen = set(existing_ids)
        candidate_ids: list[UUID] = []
        simple_sql = _build_atom_simple_fts_sql(filter_suffix)
        russian_sql = _build_atom_russian_fts_sql(filter_suffix)
        trigram_sql = _build_atom_trigram_sql(filter_suffix)
        rep_simple_sql = _build_atom_representation_simple_fts_sql(filter_suffix)
        rep_russian_sql = _build_atom_representation_russian_fts_sql(filter_suffix)

        for atom in atoms:
            atom_params = {**base_params, "atom": atom}
            if is_cyrillic_atom(atom):
                for object_id in self._session.execute(
                    text(russian_sql),
                    {
                        **atom_params,
                        "branch_limit": RELAXED_RUSSIAN_FTS_PER_ATOM,
                    },
                ).scalars():
                    _append_candidate(
                        object_id,
                        seen,
                        candidate_ids,
                        max_candidates=max_new_candidates,
                    )
                for object_id in self._session.execute(
                    text(rep_russian_sql),
                    {
                        **atom_params,
                        "branch_limit": RELAXED_RUSSIAN_FTS_PER_ATOM,
                    },
                ).scalars():
                    _append_candidate(
                        object_id,
                        seen,
                        candidate_ids,
                        max_candidates=max_new_candidates,
                    )

            if is_technical_atom(atom) or not is_cyrillic_atom(atom):
                for object_id in self._session.execute(
                    text(simple_sql),
                    {
                        **atom_params,
                        "branch_limit": RELAXED_SIMPLE_FTS_PER_ATOM,
                    },
                ).scalars():
                    _append_candidate(
                        object_id,
                        seen,
                        candidate_ids,
                        max_candidates=max_new_candidates,
                    )
                for object_id in self._session.execute(
                    text(rep_simple_sql),
                    {
                        **atom_params,
                        "branch_limit": RELAXED_SIMPLE_FTS_PER_ATOM,
                    },
                ).scalars():
                    _append_candidate(
                        object_id,
                        seen,
                        candidate_ids,
                        max_candidates=max_new_candidates,
                    )

            for object_id in self._session.execute(
                text(trigram_sql),
                {
                    **atom_params,
                    "branch_limit": RELAXED_TRIGRAM_PER_ATOM,
                },
            ).scalars():
                _append_candidate(
                    object_id,
                    seen,
                    candidate_ids,
                    max_candidates=max_new_candidates,
                )

        return candidate_ids

    def _score_and_rank(
        self,
        query: str,
        kind: str | None,
        provider: str | None,
        project_id: UUID | None,
        horizon_cutoff: datetime | None,
        date_from: datetime | None,
        date_to: datetime | None,
        apply_horizon: bool,
        recency_cutoff: datetime,
        label_id: UUID | None = None,
    ) -> tuple[list[RetrievalHit], int, str, int, int]:
        query_atoms = extract_query_atoms(query)
        filter_suffix = _build_filter_suffix(
            kind=kind,
            provider=provider,
            project_id=project_id,
            horizon_cutoff=horizon_cutoff,
            date_from=date_from,
            date_to=date_to,
            apply_horizon=apply_horizon,
            label_id=label_id,
        )
        filter_params = {
            "user_id": self._user_id,
            "kind": kind,
            "provider": provider,
            "project_id": project_id,
            "horizon_cutoff": horizon_cutoff,
            "date_from": date_from,
            "date_to": date_to,
            "include_labels": kind == "label",
            "label_id": label_id,
        }

        strict_ids = self._collect_strict_candidate_ids(
            query=query,
            kind=kind,
            provider=provider,
            project_id=project_id,
            horizon_cutoff=horizon_cutoff,
            date_from=date_from,
            date_to=date_to,
            apply_horizon=apply_horizon,
            label_id=label_id,
        )

        retrieval_mode = RETRIEVAL_MODE_STRICT
        selected_atoms: list[str] = []

        if strict_ids:
            strict_hits = self._rank_candidates(
                query=query,
                candidate_ids=strict_ids,
                selected_atoms=None,
                recency_cutoff=recency_cutoff,
            )
            if _has_strong_qualified_hits(strict_hits):
                return (
                    strict_hits,
                    len(strict_ids),
                    RETRIEVAL_MODE_STRICT,
                    len(query_atoms),
                    0,
                )

        selected_atoms = select_selective_atoms(
            self._session,
            self._user_id,
            query_atoms,
            filter_suffix,
            filter_params,
        )
        strict_for_pool = strict_ids[:STRICT_FALLBACK_QUOTA]
        seen_ids = set(strict_for_pool)
        candidate_ids = list(strict_for_pool)
        relaxed_ids = self._collect_relaxed_candidate_ids(
            atoms=selected_atoms,
            kind=kind,
            provider=provider,
            project_id=project_id,
            horizon_cutoff=horizon_cutoff,
            date_from=date_from,
            date_to=date_to,
            apply_horizon=apply_horizon,
            existing_ids=seen_ids,
            max_new_candidates=RELAXED_FALLBACK_QUOTA,
            label_id=label_id,
        )
        for object_id in relaxed_ids:
            if object_id in seen_ids:
                continue
            seen_ids.add(object_id)
            candidate_ids.append(object_id)

        if selected_atoms and relaxed_ids:
            retrieval_mode = RETRIEVAL_MODE_RELAXED

        if not candidate_ids:
            return [], 0, retrieval_mode, len(query_atoms), len(selected_atoms)

        hits = self._rank_candidates(
            query=query,
            candidate_ids=candidate_ids,
            selected_atoms=selected_atoms if selected_atoms else None,
            recency_cutoff=recency_cutoff,
        )
        return (
            hits,
            len(candidate_ids),
            retrieval_mode,
            len(query_atoms),
            len(selected_atoms),
        )

    def _rank_candidates(
        self,
        query: str,
        candidate_ids: list[UUID],
        selected_atoms: list[str] | None,
        recency_cutoff: datetime,
    ) -> list[RetrievalHit]:
        rows = self._session.execute(
            _RANK_QUERY,
            {
                "query": query,
                "user_id": self._user_id,
                "candidate_ids": candidate_ids,
            },
        ).mappings()
        row_map = {row["id"]: dict(row) for row in rows}

        term_map: dict[UUID, dict] = {}
        if selected_atoms:
            term_rows = self._session.execute(
                _TERM_RANK_QUERY,
                {
                    "user_id": self._user_id,
                    "candidate_ids": candidate_ids,
                    "atoms": selected_atoms,
                },
            ).mappings()
            term_map = {row["id"]: dict(row) for row in term_rows}

        rep_rows_by_object = self._representation_rows_by_object(candidate_ids)

        atom_count = len(selected_atoms or [])
        hits: list[RetrievalHit] = []
        for object_id in candidate_ids:
            row = row_map.get(object_id)
            if row is None:
                continue

            title_rank = float(row["title_rank"] or 0.0)
            body_rank = float(row["body_rank"] or 0.0)
            title_sim = float(row["title_sim"] or 0.0)
            rep_rank = float(row["rep_rank"] or 0.0)
            rep_excerpt = row.get("rep_excerpt")

            best_atom_title_rank = 0.0
            best_atom_body_rank = 0.0
            best_atom_title_sim = 0.0
            best_atom_rep_rank = 0.0
            coverage = 0.0
            term_row = term_map.get(object_id)
            if term_row is not None and atom_count > 0:
                best_atom_title_rank = float(term_row["best_atom_title_rank"] or 0.0)
                best_atom_body_rank = float(term_row["best_atom_body_rank"] or 0.0)
                best_atom_title_sim = float(term_row["best_atom_title_sim"] or 0.0)
                best_atom_rep_rank = float(term_row.get("best_atom_rep_rank") or 0.0)
                coverage = float(term_row["atom_match_count"] or 0.0) / atom_count

            strict_quality = (
                TITLE_FTS_WEIGHT * title_rank
                + BODY_FTS_WEIGHT * body_rank
                + TRIGRAM_WEIGHT * title_sim
                + REPRESENTATION_FTS_WEIGHT * rep_rank
            )
            term_quality = (
                TITLE_FTS_WEIGHT * best_atom_title_rank
                + BODY_FTS_WEIGHT * best_atom_body_rank
                + TRIGRAM_WEIGHT * best_atom_title_sim
                + REPRESENTATION_FTS_WEIGHT * best_atom_rep_rank
                + TERM_COVERAGE_BONUS * coverage
            )
            match_quality = (
                max(strict_quality, term_quality)
                if selected_atoms
                else strict_quality
            )

            effective_title_rank = max(title_rank, best_atom_title_rank)
            effective_body_rank = max(body_rank, best_atom_body_rank)
            effective_title_sim = max(title_sim, best_atom_title_sim)
            effective_rep_rank = max(rep_rank, best_atom_rep_rank)

            kind_value = str(row["kind"])
            occurred_at = row["occurred_at"]
            created_at = row["created_at"]
            recency_signal = _recency_signal(
                kind_value, occurred_at, created_at, recency_cutoff
            )
            ranking_score = match_quality
            if kind_value in ANCHOR_KINDS:
                ranking_score += ANCHOR_KIND_BOOST
            if recency_signal:
                ranking_score += RECENCY_BONUS

            reasons = _build_reasons(
                title_rank=effective_title_rank,
                body_rank=effective_body_rank,
                title_sim=effective_title_sim,
                rep_rank=effective_rep_rank,
                kind=kind_value,
                recency_signal=recency_signal,
            )

            excerpt = _evidence_short_excerpt(
                title=str(row["title"]),
                body=row["body"],
                rep_excerpt=rep_excerpt,
                rep_rows=rep_rows_by_object.get(object_id, []),
                query=query,
                selected_atoms=selected_atoms,
                max_chars=SHORT_EXCERPT_MAX_CHARS,
            )

            hits.append(
                RetrievalHit(
                    object_id=object_id,
                    title=str(row["title"]),
                    kind=kind_value,
                    provider=row["provider"],
                    state=str(row["state"]),
                    status=row["status"],
                    occurred_at=occurred_at,
                    relevance=ranking_score,
                    reasons=reasons,
                    short_excerpt=excerpt,
                )
            )

        hits.sort(key=lambda item: (-item.relevance, str(item.object_id)))
        return hits

    def _representation_rows_by_object(
        self, object_ids: list[UUID]
    ) -> dict[UUID, list[dict]]:
        if not object_ids:
            return {}
        rows = self._session.execute(
            _REPRESENTATIONS_FOR_OBJECTS,
            {
                "user_id": self._user_id,
                "object_ids": object_ids,
            },
        ).mappings()
        rows_by_object: dict[UUID, list[dict]] = {}
        for row in rows:
            text_value = row["text"] or ""
            if not text_value.strip():
                continue
            rows_by_object.setdefault(row["object_id"], []).append(dict(row))
        return rows_by_object

    def _should_stop_horizon_expansion(self, hits: list[RetrievalHit]) -> bool:
        qualified = [hit for hit in hits if _hit_is_qualified(hit)]
        if not qualified:
            return False
        return any(_is_strong_textual_hit(hit) for hit in qualified)

    def _trim_to_limit(self, hits: list[RetrievalHit], limit: int) -> list[RetrievalHit]:
        qualified = [hit for hit in hits if _hit_is_qualified(hit)]
        return qualified[:limit]


def _append_candidate(
    object_id: UUID,
    seen: set[UUID],
    candidate_ids: list[UUID],
    max_candidates: int | None = None,
) -> None:
    if object_id in seen:
        return
    pool_limit = max_candidates if max_candidates is not None else MAX_CANDIDATE_POOL
    if len(candidate_ids) >= pool_limit:
        return
    seen.add(object_id)
    candidate_ids.append(object_id)


def _has_strong_qualified_hits(hits: list[RetrievalHit]) -> bool:
    qualified = [hit for hit in hits if _hit_is_qualified(hit)]
    return any(_is_strong_textual_hit(hit) for hit in qualified)


def _recency_signal(
    kind: str,
    occurred_at: datetime | None,
    created_at: datetime | None,
    recency_cutoff: datetime,
) -> bool:
    if kind in TIME_SENSITIVE_SOURCE_KINDS:
        if occurred_at is None:
            return False
        return occurred_at >= recency_cutoff
    reference_time = occurred_at or created_at
    if reference_time is None:
        return False
    return reference_time >= recency_cutoff


def _hit_is_qualified(hit: RetrievalHit) -> bool:
    return any(
        reason in hit.reasons
        for reason in (
            "title_match",
            "title_candidate",
            "body_match",
            "representation_match",
            "fuzzy_title",
            "fuzzy_title_candidate",
        )
    )


def _is_strong_textual_hit(hit: RetrievalHit) -> bool:
    return (
        "title_match" in hit.reasons
        or "fuzzy_title" in hit.reasons
        or "representation_match" in hit.reasons
    )


def _build_reasons(
    title_rank: float,
    body_rank: float,
    title_sim: float,
    kind: str,
    recency_signal: bool,
    rep_rank: float = 0.0,
) -> list[str]:
    reasons: list[str] = []
    if title_rank >= STRONG_TITLE_FTS_THRESHOLD:
        reasons.append("title_match")
    elif title_rank >= MIN_TITLE_QUALIFY_THRESHOLD:
        reasons.append("title_candidate")
    if body_rank >= MIN_BODY_FTS_THRESHOLD:
        reasons.append("body_match")
    if rep_rank >= MIN_BODY_FTS_THRESHOLD:
        reasons.append("representation_match")
    if title_sim >= STRONG_TRIGRAM_THRESHOLD:
        reasons.append("fuzzy_title")
    elif title_sim >= MIN_TRIGRAM_QUALIFY_THRESHOLD:
        reasons.append("fuzzy_title_candidate")
    if kind in ANCHOR_KINDS:
        reasons.append("anchor_kind")
    if recency_signal:
        reasons.append("recent")
    return reasons


def _best_representation_row(
    rep_rows: list[dict],
    query: str,
    selected_atoms: list[str] | None,
) -> dict | None:
    best_row: dict | None = None
    best_key: tuple[float, float, int, int, int, str] | None = None
    for row in rep_rows:
        text_value = row.get("text") or ""
        if not text_value.strip():
            continue
        key = representation_evidence_rank_key(
            text=text_value,
            query=query,
            atoms=selected_atoms,
            kind=str(row.get("kind") or ""),
            part_index=row.get("part_index"),
            rep_id=str(row.get("id")),
        )
        if best_key is None or key > best_key:
            best_key = key
            best_row = row
    return best_row


def _evidence_short_excerpt(
    *,
    title: str,
    body: str | None,
    rep_excerpt: str | None,
    rep_rows: list[dict],
    query: str,
    selected_atoms: list[str] | None,
    max_chars: int,
) -> str:
    if rep_rows:
        best_row = _best_representation_row(rep_rows, query, selected_atoms)
        if best_row is not None:
            return build_query_centered_snippet(
                str(best_row.get("text") or ""),
                query,
                max_chars,
                selected_atoms,
            )
    if rep_excerpt and rep_excerpt.strip():
        return build_query_centered_snippet(
            rep_excerpt,
            query,
            max_chars,
            selected_atoms,
        )
    return _short_excerpt(
        title=title,
        body=body,
        rep_excerpt=None,
        max_chars=max_chars,
    )


def _short_excerpt(
    title: str,
    body: str | None,
    max_chars: int,
    rep_excerpt: str | None = None,
) -> str:
    source = (rep_excerpt or "").strip() or (body or "").strip() or title.strip()
    if len(source) <= max_chars:
        return source
    return source[:max_chars].rstrip() + "…"


def load_objects_ordered(
    session: Session,
    user_id: UUID,
    hits: list[RetrievalHit],
) -> list[Object]:
    if not hits:
        return []
    from sqlalchemy import select

    object_ids = [hit.object_id for hit in hits]
    rows = session.scalars(
        select(Object).where(Object.user_id == user_id, Object.id.in_(object_ids))
    ).all()
    by_id = {obj.id: obj for obj in rows}
    return [by_id[object_id] for object_id in object_ids if object_id in by_id]
