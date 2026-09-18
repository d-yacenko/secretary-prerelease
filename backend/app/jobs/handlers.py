from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_audit.constants import (
    WORKLOAD_BACKGROUND_CORRELATION,
    WORKLOAD_BACKGROUND_SUMMARY,
    WORKLOAD_EMBEDDING,
)
from app.ai_audit.context import ai_trace_session
from app.content_extraction.extract_service import build_explicit_resource_content_extractor
from app.core.assistant_openai_config import AssistantOpenAIConfigError
from app.core.config import settings
from app.db.models import Object
from app.db.session import SessionLocal
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.telegram_mtproto_ai import telegram_mtproto_ai_eligible
from app.jobs.constants import (
    JOB_TYPE_AUTO_LABEL_OBJECT,
    JOB_TYPE_CORRELATE_OBJECT,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
    JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL,
    JOB_TYPE_INGEST_LOCAL_FILE,
    JOB_TYPE_PROACTIVE_REVIEW,
    JOB_TYPE_PROCESS_TEAMS_NOTIFICATION,
    JOB_TYPE_RECONCILE_TEMPORAL_HINTS,
    JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
    JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
    JOB_TYPE_SUMMARIZE_RESOURCE,
    JOB_TYPE_SYNC_GOOGLE_CALENDAR,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    JOB_TYPE_SYNC_MATTERMOST,
    JOB_TYPE_SYNC_TEAMS,
    JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
    JOB_TYPE_SYNC_YANDEX_CALENDAR,
    JOB_TYPE_SYNC_YANDEX_MAIL,
)
from app.jobs.scheduled_activity_handler import handle_run_scheduled_activity
from app.jobs.source_sync_handlers import (
    handle_process_teams_notification,
    handle_sync_google_calendar,
    handle_sync_google_gmail,
    handle_sync_mattermost,
    handle_sync_teams,
    handle_sync_telegram_mtproto,
    handle_sync_yandex_calendar,
    handle_sync_yandex_mail,
)
from app.jobs.types import JobHandler
from app.llm.correlation_judge import create_correlation_judge_from_effective
from app.llm.embedding_service import (
    OpenAIEmbeddingService,
    create_embedding_service_for_api_key,
)
from app.llm.embedding_text import canonical_embedding_text, embedding_input_signature
from app.llm.openai_summarizer import create_openai_summarizer_from_effective
from app.local.constants import POLICY_UPLOAD_COPY
from app.local.paths import LocalPathResolver
from app.resources.constants import (
    CONTENT_INGESTED_POLICY_KEY,
    CONTENT_INGESTED_REVISION_KEY,
)
from app.services.auto_label_service import enqueue_auto_label_object
from app.services.background_ai_errors import BackgroundAIConfigurationError
from app.services.correlation_input import correlation_input_signature
from app.services.correlation_service import CorrelationService
from app.services.effective_user_settings_service import (
    EffectiveUserSettings,
    EffectiveUserSettingsService,
)
from app.services.embedding_index import (
    assign_object_embedding,
    object_has_current_embedding_provenance,
)
from app.services.local_file_sync_service import copy_local_file_to_upload
from app.services.openai_daily_budget import OpenAIDailyBudgetGuard
from app.services.pipeline_enqueue import (
    enqueue_correlate_object,
    enqueue_embed_object,
    enqueue_summarize_resource,
)
from app.services.proactive_review_service import ProactiveReviewService
from app.services.representation_embedding_worker import (
    load_unembedded_chunk_targets,
    store_representation_embeddings,
)
from app.services.representation_generation import representation_generation_matches
from app.services.representation_service import RepresentationService
from app.services.semantic_summary_service import SemanticSummaryService


def _store_object_embedding_if_current(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    embedding: list[float],
    payload_sig: str,
) -> bool:
    obj = session.scalar(
        select(Object)
        .where(Object.id == object_id, Object.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise ValueError(f"object ownership mismatch: {object_id}")
    if embedding_input_signature(obj) != payload_sig:
        return False
    assign_object_embedding(obj, embedding, payload_sig)
    session.flush()
    return True


def _ingest_already_complete(
    metadata: dict,
    expected_revision: str | None,
    expected_policy: str | None,
) -> bool:
    if metadata.get(CONTENT_INGESTED_REVISION_KEY) != expected_revision:
        return False
    if metadata.get(CONTENT_INGESTED_POLICY_KEY) != expected_policy:
        return False
    if expected_policy == POLICY_UPLOAD_COPY:
        upload_path = metadata.get("upload_path")
        return bool(upload_path and Path(upload_path).is_file())
    return True


def _revision_and_policy_match(
    metadata: dict,
    expected_revision: str | None,
    expected_policy: str | None,
) -> bool:
    if expected_revision is not None and metadata.get("content_revision") != expected_revision:
        return False
    return not (expected_policy is not None and metadata.get("indexing_policy") != expected_policy)


def _load_user_object(session: Session, object_id: UUID, user_id: UUID) -> Object | None:
    return session.scalar(
        select(Object).where(Object.id == object_id, Object.user_id == user_id)
    )


def _background_effective_settings(session: Session, user_id: UUID) -> EffectiveUserSettings:
    try:
        return EffectiveUserSettingsService.build(session).get_effective_settings(user_id)
    except AssistantOpenAIConfigError as exc:
        raise BackgroundAIConfigurationError(str(exc)) from exc


def _parent_trace_id_from_payload(payload: dict) -> UUID | None:
    raw = payload.get("parent_trace_id")
    if not raw:
        return None
    return UUID(str(raw))


def _object_is_active(session: Session, object_id: UUID, user_id: UUID) -> bool:
    obj = session.scalar(
        select(Object).where(Object.id == object_id, Object.user_id == user_id)
    )
    return (
        obj is not None
        and not is_object_hidden_from_active_reads(obj)
        and telegram_mtproto_ai_eligible(session, obj)
    )


def handle_embed_object(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    object_id = UUID(str(payload["object_id"]))
    if not _object_is_active(session, object_id, user_id):
        return
    obj = _load_user_object(session, object_id, user_id)
    if obj is None:
        return
    current_sig = embedding_input_signature(obj)
    payload_sig = str(payload.get("embedding_input_signature") or "")
    parent_trace_id = _parent_trace_id_from_payload(payload)
    if not payload_sig or payload_sig != current_sig:
        enqueue_embed_object(session, object_id, user_id)
        return
    if object_has_current_embedding_provenance(obj, current_sig):
        _embed_unembedded_chunks(session, embedding_service, object_id, user_id, parent_trace_id)
        _enqueue_embed_downstream(
            session, object_id, user_id, obj, parent_trace_id=parent_trace_id
        )
        return
    embed_trace_id = None
    with ai_trace_session(
        user_id,
        WORKLOAD_EMBEDDING,
        object_id=object_id,
        parent_trace_id=parent_trace_id,
    ) as embed_trace:
        embed_trace_id = embed_trace.trace_id
        live = _load_user_object(session, object_id, user_id)
        if live is None:
            return
        if embedding_input_signature(live) != payload_sig:
            enqueue_embed_object(session, object_id, user_id)
            return
        service = _resolve_embedding_service(session, user_id, embedding_service)
        embedding = service.embed(canonical_embedding_text(live))
        stored = _store_object_embedding_if_current(
            session, object_id, user_id, embedding, payload_sig
        )
        if not stored:
            enqueue_embed_object(session, object_id, user_id)
            return
        _embed_chunk_targets(service, object_id, user_id)
    live = _load_user_object(session, object_id, user_id)
    if live is None:
        return
    _enqueue_embed_downstream(
        session, object_id, user_id, live, parent_trace_id=embed_trace_id
    )


def _resolve_embedding_service(session: Session, user_id: UUID, embedding_service):
    if embedding_service is not None:
        return embedding_service
    settings_service = EffectiveUserSettingsService.build(session)
    api_key = settings_service.resolve_openai_api_key(user_id)
    service = create_embedding_service_for_api_key(api_key)
    if not isinstance(service, OpenAIEmbeddingService):
        return service
    return OpenAIDailyBudgetGuard.build(session, user_id).guard_embedding_service(service)


def _enqueue_embed_downstream(
    session: Session,
    object_id: UUID,
    user_id: UUID,
    obj: Object,
    *,
    parent_trace_id: UUID | None,
) -> None:
    enqueue_correlate_object(session, object_id, user_id, obj.kind)
    enqueue_auto_label_object(
        session,
        object_id,
        user_id,
        parent_trace_id=parent_trace_id,
    )
    from app.services.temporal_signals_service import (
        enqueue_extract_temporal_signal,
        enqueue_reconcile_temporal_hints,
    )

    enqueue_extract_temporal_signal(
        session,
        object_id,
        user_id,
        parent_trace_id=parent_trace_id,
    )
    enqueue_reconcile_temporal_hints(
        session,
        object_id,
        user_id,
        parent_trace_id=parent_trace_id,
    )


def _embed_chunk_targets(service, object_id: UUID, user_id: UUID) -> None:
    chunk_targets = load_unembedded_chunk_targets(object_id, user_id)
    if not chunk_targets:
        return
    chunk_embeddings = [
        (target.representation_id, service.embed(target.text))
        for target in chunk_targets
    ]
    store_representation_embeddings(object_id, user_id, chunk_embeddings)


def _embed_unembedded_chunks(
    session: Session,
    embedding_service,
    object_id: UUID,
    user_id: UUID,
    parent_trace_id: UUID | None,
) -> None:
    chunk_targets = load_unembedded_chunk_targets(object_id, user_id)
    if not chunk_targets:
        return
    with ai_trace_session(
        user_id,
        WORKLOAD_EMBEDDING,
        object_id=object_id,
        parent_trace_id=parent_trace_id,
    ):
        service = _resolve_embedding_service(session, user_id, embedding_service)
        chunk_embeddings = [
            (target.representation_id, service.embed(target.text))
            for target in chunk_targets
        ]
        store_representation_embeddings(object_id, user_id, chunk_embeddings)


def handle_summarize_resource(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    object_id = UUID(str(payload["object_id"]))
    if not _object_is_active(session, object_id, user_id):
        return
    expected_revision = payload.get("expected_revision")
    expected_generation = payload.get("expected_representation_generation")
    parent_trace_id = _parent_trace_id_from_payload(payload)
    with ai_trace_session(
        user_id,
        WORKLOAD_BACKGROUND_SUMMARY,
        object_id=object_id,
        parent_trace_id=parent_trace_id,
    ):
        lookup_session = SessionLocal()
        try:
            obj = lookup_session.scalar(
                select(Object).where(Object.id == object_id, Object.user_id == user_id)
            )
            if obj is None:
                raise ValueError(f"object ownership mismatch: {object_id}")
            metadata = obj.metadata_ or {}
            if not representation_generation_matches(
                metadata,
                expected_revision,
                expected_generation,
            ):
                return
            effective = _background_effective_settings(lookup_session, user_id)
            summarizer = OpenAIDailyBudgetGuard.build(
                lookup_session, user_id
            ).guard_summarizer(create_openai_summarizer_from_effective(effective))
            summary = SemanticSummaryService(
                lookup_session, user_id, summarizer=summarizer
            ).update_summary_for_object(
                object_id,
                expected_revision=expected_revision,
                expected_representation_generation=expected_generation,
            )
            if summary is not None:
                enqueue_embed_object(lookup_session, object_id, user_id)
            lookup_session.commit()
        finally:
            lookup_session.close()


def handle_summarize_conversation_stack(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    object_ids = [UUID(str(item)) for item in payload.get("object_ids") or []]
    if object_ids:
        objects = list(
            session.scalars(
                select(Object).where(
                    Object.user_id == user_id,
                    Object.id.in_(object_ids),
                )
            )
        )
        if len(objects) != len(object_ids) or any(
            not telegram_mtproto_ai_eligible(session, obj) for obj in objects
        ):
            return
    from app.llm.openai_summarizer import (
        create_openai_conversation_stack_summarizer_from_effective,
    )
    from app.services.conversation_stack_summary import ConversationStackSummaryService

    parent_trace_id = _parent_trace_id_from_payload(payload)
    with ai_trace_session(
        user_id,
        WORKLOAD_BACKGROUND_SUMMARY,
        object_id=None,
        parent_trace_id=parent_trace_id,
    ):
        lookup_session = SessionLocal()
        try:
            effective = _background_effective_settings(lookup_session, user_id)
            summarizer = OpenAIDailyBudgetGuard.build(
                lookup_session, user_id
            ).guard_summarizer(
                create_openai_conversation_stack_summarizer_from_effective(effective)
            )
            ConversationStackSummaryService(
                lookup_session, user_id, summarizer=summarizer
            ).generate_for_payload(payload)
            lookup_session.commit()
        finally:
            lookup_session.close()


def handle_correlate_object(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    object_id = UUID(str(payload["object_id"]))
    if not _object_is_active(session, object_id, user_id):
        return
    obj = session.scalar(
        select(Object).where(Object.id == object_id, Object.user_id == user_id)
    )
    if obj is None:
        return
    payload_sig = str(payload.get("correlation_input_signature") or "")
    current_sig = correlation_input_signature(obj)
    if current_sig != payload_sig:
        enqueue_correlate_object(session, object_id, user_id, obj.kind)
        return
    parent_trace_id = _parent_trace_id_from_payload(payload)
    with ai_trace_session(
        user_id,
        WORKLOAD_BACKGROUND_CORRELATION,
        object_id=object_id,
        parent_trace_id=parent_trace_id,
    ):
        work_session = SessionLocal()
        try:
            live = work_session.scalar(
                select(Object).where(Object.id == object_id, Object.user_id == user_id)
            )
            if live is None or correlation_input_signature(live) != payload_sig:
                enqueue_correlate_object(session, object_id, user_id, obj.kind)
                return
            effective = _background_effective_settings(session, user_id)
            judge = OpenAIDailyBudgetGuard.build(
                work_session, user_id
            ).guard_correlation_judge(create_correlation_judge_from_effective(effective))
            CorrelationService(work_session, user_id, judge).run_correlation(object_id)
            work_session.commit()
        finally:
            work_session.close()


def handle_ingest_local_file(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    object_id = UUID(str(payload["object_id"]))
    if not _object_is_active(session, object_id, user_id):
        return
    expected_revision = payload.get("expected_revision")
    expected_policy = payload.get("expected_policy")
    path_resolver = LocalPathResolver(Path(settings.local_files_root))
    upload_root = Path(settings.resource_upload_root)

    lookup_session = SessionLocal()
    try:
        obj = _load_user_object(lookup_session, object_id, user_id)
        if obj is None:
            raise ValueError(f"object ownership mismatch: {object_id}")

        metadata = dict(obj.metadata_ or {})
        device_key = metadata.get("device_key")
        root_path = metadata.get("local_root_path")
        relative_path = metadata.get("local_relative_path")
        if not device_key or not root_path or not relative_path:
            raise ValueError("local object missing path metadata")

        if not _revision_and_policy_match(metadata, expected_revision, expected_policy):
            return

        if expected_policy and _ingest_already_complete(
            metadata, expected_revision, expected_policy
        ):
            return
    finally:
        lookup_session.close()

    source_path = path_resolver.resolve_file_path(
        user_id,
        str(device_key),
        str(root_path),
        str(relative_path),
    )
    if not source_path.is_file():
        raise ValueError(f"local file not found: {relative_path}")

    ingest_session = SessionLocal()
    try:
        obj = _load_user_object(ingest_session, object_id, user_id)
        if obj is None:
            raise ValueError(f"object ownership mismatch: {object_id}")

        metadata = dict(obj.metadata_ or {})
        if not _revision_and_policy_match(metadata, expected_revision, expected_policy):
            return

        policy = expected_policy or metadata.get("indexing_policy")
        pending_upload_path: str | None = None
        pending_content_hash: str | None = None

        if policy == POLICY_UPLOAD_COPY:
            copied, content_hash, _ = copy_local_file_to_upload(
                source_path,
                upload_root,
                user_id,
                object_id,
            )
            pending_upload_path = str(copied)
            pending_content_hash = content_hash

        ingest_session.refresh(obj)
        metadata = dict(obj.metadata_ or {})
        if not _revision_and_policy_match(metadata, expected_revision, expected_policy):
            return

        representation_service = RepresentationService(ingest_session, user_id)
        representation_service.ingest_file(object_id, source_path)

        ingest_session.refresh(obj)
        metadata = dict(obj.metadata_ or {})
        if not _revision_and_policy_match(metadata, expected_revision, expected_policy):
            ingest_session.rollback()
            return

        merged = dict(metadata)
        if pending_upload_path is not None:
            merged["upload_path"] = pending_upload_path
        if pending_content_hash is not None:
            merged["content_hash"] = pending_content_hash
        if expected_revision is not None:
            merged[CONTENT_INGESTED_REVISION_KEY] = expected_revision
        if expected_policy is not None:
            merged[CONTENT_INGESTED_POLICY_KEY] = expected_policy
        from app.services.representation_generation import (
            bump_representation_generation,
            get_representation_generation,
        )

        merged = bump_representation_generation(merged)
        obj.metadata_ = merged
        ingest_session.flush()

        revision = merged.get("content_revision")
        enqueue_summarize_resource(
            ingest_session,
            obj.id,
            user_id,
            revision,
            get_representation_generation(merged),
        )
        ingest_session.commit()
    except Exception:
        ingest_session.rollback()
        raise
    finally:
        ingest_session.close()


def handle_extract_explicit_resource_content(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    object_id = UUID(str(payload["object_id"]))
    if not _object_is_active(session, object_id, user_id):
        return
    expected_revision = payload.get("expected_content_revision")
    extraction_version = payload.get("extraction_version")
    expected_baseline = payload.get("extraction_baseline")

    work_session = SessionLocal()
    extractor = build_explicit_resource_content_extractor(work_session, user_id)
    try:
        extractor.run(object_id, expected_revision, extraction_version, expected_baseline)
        work_session.commit()
    except Exception:
        work_session.rollback()
        raise
    finally:
        extractor.close()
        work_session.close()


def handle_proactive_review(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    ProactiveReviewService(session, user_id).run(payload)


def handle_auto_label_object(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    from app.services.auto_label_service import AutoLabelService

    AutoLabelService(session, user_id).run_job(payload)


def handle_extract_temporal_signal(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    from app.services.temporal_signals_service import TemporalSignalService

    TemporalSignalService(session, user_id).run_extract_job(payload)


def handle_reconcile_temporal_hints(
    session: Session,
    embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    from app.services.temporal_signals_service import TemporalSignalService

    TemporalSignalService(session, user_id).run_reconcile_job(payload)


HANDLERS: dict[str, JobHandler] = {
    JOB_TYPE_EMBED_OBJECT: handle_embed_object,
    JOB_TYPE_INGEST_LOCAL_FILE: handle_ingest_local_file,
    JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT: handle_extract_explicit_resource_content,
    JOB_TYPE_SUMMARIZE_RESOURCE: handle_summarize_resource,
    JOB_TYPE_SUMMARIZE_CONVERSATION_STACK: handle_summarize_conversation_stack,
    JOB_TYPE_CORRELATE_OBJECT: handle_correlate_object,
    JOB_TYPE_AUTO_LABEL_OBJECT: handle_auto_label_object,
    JOB_TYPE_EXTRACT_TEMPORAL_SIGNAL: handle_extract_temporal_signal,
    JOB_TYPE_RECONCILE_TEMPORAL_HINTS: handle_reconcile_temporal_hints,
    JOB_TYPE_SYNC_GOOGLE_GMAIL: handle_sync_google_gmail,
    JOB_TYPE_SYNC_GOOGLE_CALENDAR: handle_sync_google_calendar,
    JOB_TYPE_SYNC_YANDEX_MAIL: handle_sync_yandex_mail,
    JOB_TYPE_SYNC_YANDEX_CALENDAR: handle_sync_yandex_calendar,
    JOB_TYPE_SYNC_MATTERMOST: handle_sync_mattermost,
    JOB_TYPE_SYNC_TEAMS: handle_sync_teams,
    JOB_TYPE_SYNC_TELEGRAM_MTPROTO: handle_sync_telegram_mtproto,
    JOB_TYPE_PROCESS_TEAMS_NOTIFICATION: handle_process_teams_notification,
    JOB_TYPE_RUN_SCHEDULED_ACTIVITY: handle_run_scheduled_activity,
    JOB_TYPE_PROACTIVE_REVIEW: handle_proactive_review,
}


def get_handler(job_type: str) -> JobHandler | None:
    return HANDLERS.get(job_type)
