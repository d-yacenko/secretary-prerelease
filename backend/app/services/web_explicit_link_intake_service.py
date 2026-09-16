"""Generic public web URL explicit intake via POST /intake/link."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content_extraction.constants import EXTRACTION_VERSION, MAX_REPRESENTATION_PARTS
from app.content_extraction.content_invalidation import invalidate_object_content_immediately
from app.content_extraction.extract_service import (
    apply_intake_content_metadata,
    extraction_work_needed,
)
from app.content_extraction.extraction_baseline import (
    EXTRACTION_BASELINE_METADATA_KEY,
    WEB_REVALIDATION_GENERATION_METADATA_KEY,
    derive_web_extraction_baseline,
    resolve_web_revalidation_generation,
)
from app.content_extraction.mechanical_extractors import build_bounded_text_representations
from app.content_extraction.mechanical_persistence import MechanicalRepresentationPersistence
from app.content_extraction.metadata_keys import (
    CONTENT_EXTRACTION_STATUS,
    MECHANICAL_REPRESENTATION_COUNT,
    MECHANICAL_REPRESENTATION_KINDS,
    STATUS_FAILED,
    STATUS_METADATA_ONLY,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_TOO_LARGE,
    STATUS_UNSUPPORTED,
)
from app.content_extraction.revision import (
    derive_web_content_revision,
    derive_web_remote_content_revision,
    metadata_extraction_version,
)
from app.db.models import Object, Representation
from app.domain.object_visibility import (
    restore_object_from_explicit_intake,
)
from app.resources.constants import PROVIDER_WEB
from app.resources.web_fetch import WebFetchError, WebFetchResult, fetch_web_page
from app.services.explicit_link_intake_errors import ExplicitLinkIntakeError
from app.services.explicit_link_intake_service import EXPLICIT_INTAKE_MODE, IntakeLinkResult
from app.services.pipeline_enqueue import (
    enqueue_embed_object,
    enqueue_extract_explicit_resource_content,
    enqueue_summarize_resource,
)
from app.services.web_content_invalidation import invalidate_web_page_content_immediately
from app.services.web_url_normalize import normalize_explicit_web_url

WEB_CONTENT_REVISION_PREFIX = "web:sha256:"
WEB_BODY_PREVIEW_CHARS = 500


@dataclass(frozen=True)
class WebExplicitLinkIntakeService:
    session: Session
    user_id: UUID

    def intake_link(self, url: str, account_id: UUID | None = None) -> IntakeLinkResult:
        _ = account_id
        requested_url = url.strip()
        try:
            normalized_requested = normalize_explicit_web_url(requested_url)
        except ValueError as exc:
            raise ExplicitLinkIntakeError("invalid link url") from exc

        existing = self._find_existing(normalized_requested)

        try:
            fetched = fetch_web_page(requested_url)
        except WebFetchError as exc:
            raise ExplicitLinkIntakeError(exc.message) from exc

        if fetched.is_direct_file:
            return self._intake_direct_file(
                requested_url=requested_url,
                normalized_requested=normalized_requested,
                fetched=fetched,
                existing=existing,
            )

        content_hash = fetched.content_hash or hashlib.sha256(
            fetched.text.encode("utf-8")
        ).hexdigest()
        revision = f"{WEB_CONTENT_REVISION_PREFIX}{content_hash}"

        metadata: dict[str, Any] = {
            "intake_mode": EXPLICIT_INTAKE_MODE,
            "requested_url": requested_url,
            "normalized_requested_url": normalized_requested,
            "final_url": fetched.final_url,
            "fetched_at": datetime.now(UTC).isoformat(),
            "content_revision": revision,
            "content_hash": content_hash,
        }
        if fetched.content_type:
            metadata["mime_type"] = fetched.content_type
        if fetched.content_length is not None:
            metadata["content_length"] = fetched.content_length
        if fetched.etag:
            metadata["etag"] = fetched.etag
        if fetched.last_modified:
            metadata["last_modified"] = fetched.last_modified

        created = existing is None
        obj = existing or self._create_object(
            kind="web_page",
            title=_resolve_title(fetched, normalized_requested),
            external_id=normalized_requested,
            canonical_uri=fetched.final_url,
            metadata=metadata,
        )
        if existing is not None:
            restore_object_from_explicit_intake(obj)

        prior_meta = dict(obj.metadata_ or {})
        prior_revision = prior_meta.get("content_revision")
        same_revision = prior_revision == revision

        obj.kind = "web_page"
        obj.canonical_uri = fetched.final_url
        merged = dict(prior_meta)
        merged.update(metadata)
        obj.metadata_ = merged
        if fetched.title and (
            created or obj.title == prior_meta.get("requested_url") or not obj.title.strip()
        ):
            obj.title = _resolve_title(fetched, normalized_requested)

        if same_revision and not created:
            return IntakeLinkResult(
                object_id=obj.id,
                provider=PROVIDER_WEB,
                kind=obj.kind,
                status="unchanged",
                content_status=(obj.metadata_ or {}).get(CONTENT_EXTRACTION_STATUS, STATUS_READY),
                content_jobs_enqueued=0,
            )

        if not created:
            invalidate_web_page_content_immediately(self.session, obj)

        jobs = 0
        if fetched.is_binary:
            obj.body = None
            meta = dict(obj.metadata_ or {})
            meta[CONTENT_EXTRACTION_STATUS] = STATUS_METADATA_ONLY
            meta[MECHANICAL_REPRESENTATION_COUNT] = 0
            meta["content_truncated"] = False
            obj.metadata_ = meta
            enqueue_embed_object(self.session, obj.id, self.user_id)
            jobs = 1
            status = "updated" if not created else "created"
        else:
            preview = fetched.text[:WEB_BODY_PREVIEW_CHARS] if fetched.text else None
            obj.body = preview
            reps, truncated = build_bounded_text_representations(
                obj.id,
                fetched.text,
                MAX_REPRESENTATION_PARTS,
            )
            count = MechanicalRepresentationPersistence(self.session).replace_mechanical_for_object(
                obj.id, reps
            )
            meta = dict(obj.metadata_ or {})
            meta[CONTENT_EXTRACTION_STATUS] = STATUS_READY
            meta[MECHANICAL_REPRESENTATION_COUNT] = count
            meta["content_truncated"] = truncated
            from app.services.representation_generation import (
                bump_representation_generation,
                get_representation_generation,
            )

            meta = bump_representation_generation(meta)
            obj.metadata_ = meta
            enqueue_summarize_resource(
                self.session,
                obj.id,
                self.user_id,
                revision,
                get_representation_generation(meta),
            )
            enqueue_embed_object(self.session, obj.id, self.user_id)
            jobs = 2
            status = "updated" if not created else "created"

        self.session.flush()
        content_status = (obj.metadata_ or {}).get(CONTENT_EXTRACTION_STATUS, STATUS_READY)
        return IntakeLinkResult(
            object_id=obj.id,
            provider=PROVIDER_WEB,
            kind=obj.kind,
            status=status,
            content_status=content_status,
            content_jobs_enqueued=jobs,
        )

    def _intake_direct_file(
        self,
        *,
        requested_url: str,
        normalized_requested: str,
        fetched: WebFetchResult,
        existing: Object | None,
    ) -> IntakeLinkResult:
        metadata: dict[str, Any] = {
            "intake_mode": EXPLICIT_INTAKE_MODE,
            "requested_url": requested_url,
            "normalized_requested_url": normalized_requested,
            "final_url": fetched.final_url,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        if fetched.content_type:
            metadata["mime_type"] = fetched.content_type
        if fetched.detected_suffix:
            metadata["detected_suffix"] = fetched.detected_suffix
        if fetched.content_length is not None:
            metadata["content_length"] = fetched.content_length
        if fetched.etag:
            metadata["etag"] = fetched.etag
        if fetched.last_modified:
            metadata["last_modified"] = fetched.last_modified

        title = _resolve_file_title(fetched, normalized_requested)
        created = existing is None
        obj = existing or self._create_object(
            kind="file",
            title=title,
            external_id=normalized_requested,
            canonical_uri=fetched.final_url,
            metadata=metadata,
        )
        if existing is not None:
            restore_object_from_explicit_intake(obj)

        prior_meta = dict(obj.metadata_ or {})
        prior_revision = prior_meta.get("content_revision")

        revision = derive_web_content_revision(metadata)
        if revision is not None:
            metadata["content_revision"] = revision

        same_trusted_revision = (
            revision is not None
            and prior_revision == revision
            and not created
            and not fetched.file_too_large
        )

        obj.kind = "file"
        obj.body = None
        obj.canonical_uri = fetched.final_url
        obj.title = title

        if same_trusted_revision:
            prior_status = prior_meta.get(CONTENT_EXTRACTION_STATUS)
            if prior_status in {STATUS_FAILED, STATUS_TOO_LARGE, STATUS_UNSUPPORTED}:
                merged = _merge_probe_metadata(prior_meta, metadata)
                obj.metadata_ = merged
                self.session.flush()
                return IntakeLinkResult(
                    object_id=obj.id,
                    provider=PROVIDER_WEB,
                    kind=obj.kind,
                    status="unchanged",
                    content_status=prior_status,
                    content_jobs_enqueued=0,
                )

            has_reps = _mechanical_rep_count(self.session, obj.id) > 0
            version_current = metadata_extraction_version(prior_meta) == EXTRACTION_VERSION
            if (
                prior_status == STATUS_READY
                and version_current
                and has_reps
            ):
                merged = _merge_probe_metadata(prior_meta, metadata)
                obj.metadata_ = merged
                self.session.flush()
                return IntakeLinkResult(
                    object_id=obj.id,
                    provider=PROVIDER_WEB,
                    kind=obj.kind,
                    status="unchanged",
                    content_status=STATUS_READY,
                    content_jobs_enqueued=0,
                )

        incoming_meta = apply_intake_content_metadata(
            metadata,
            PROVIDER_WEB,
            "file",
            title,
        )
        if fetched.file_too_large:
            incoming_meta[CONTENT_EXTRACTION_STATUS] = STATUS_TOO_LARGE

        merged = dict(prior_meta)
        merged.update(incoming_meta)
        obj.metadata_ = merged

        had_ready_mechanical = (
            prior_meta.get(CONTENT_EXTRACTION_STATUS) == STATUS_READY
            and _mechanical_rep_count(self.session, obj.id) > 0
        )

        revision_changed = prior_revision != revision
        no_validator_reintake = (
            not created
            and revision is None
            and derive_web_remote_content_revision(metadata) is None
        )
        needs_content_refresh = (
            not created
            and same_trusted_revision
            and (
                metadata_extraction_version(prior_meta) != EXTRACTION_VERSION
                or (
                    prior_meta.get(CONTENT_EXTRACTION_STATUS) == STATUS_READY
                    and not had_ready_mechanical
                )
            )
        )
        if revision_changed or no_validator_reintake or needs_content_refresh:
            invalidate_object_content_immediately(self.session, obj)
            merged = dict(obj.metadata_ or {})
            merged.update(incoming_meta)
            obj.metadata_ = merged
            had_ready_mechanical = False

        jobs = 0
        status = "updated" if not created else "created"
        if fetched.file_too_large:
            status = "updated" if not created else "created"
        elif (
            extraction_work_needed(
                PROVIDER_WEB,
                "file",
                title,
                prior_meta,
                merged,
                had_ready_mechanical,
            )
            or (
                no_validator_reintake
                and derive_web_remote_content_revision(merged) is None
            )
        ):
            has_remote_revision = derive_web_remote_content_revision(merged) is not None
            if not has_remote_revision:
                generation = resolve_web_revalidation_generation(
                    prior_metadata=prior_meta,
                    created=created,
                    requires_revalidation=no_validator_reintake,
                    has_remote_revision=False,
                )
                if generation is not None:
                    merged[WEB_REVALIDATION_GENERATION_METADATA_KEY] = generation
            baseline = derive_web_extraction_baseline(merged)
            merged[EXTRACTION_BASELINE_METADATA_KEY] = baseline
            obj.metadata_ = merged
            enqueue_extract_explicit_resource_content(
                self.session,
                obj.id,
                self.user_id,
                merged.get("content_revision"),
                EXTRACTION_VERSION,
                extraction_baseline=baseline,
            )
            merged[CONTENT_EXTRACTION_STATUS] = STATUS_PENDING
            obj.metadata_ = merged
            jobs = 1
        else:
            enqueue_embed_object(self.session, obj.id, self.user_id)
            jobs = 1

        self.session.flush()
        content_status = (obj.metadata_ or {}).get(CONTENT_EXTRACTION_STATUS, STATUS_PENDING)
        return IntakeLinkResult(
            object_id=obj.id,
            provider=PROVIDER_WEB,
            kind=obj.kind,
            status=status,
            content_status=content_status,
            content_jobs_enqueued=jobs,
        )

    def close(self) -> None:
        return None

    def _find_existing(self, external_id: str) -> Object | None:
        return self.session.scalar(
            select(Object).where(
                Object.user_id == self.user_id,
                Object.provider == PROVIDER_WEB,
                Object.external_id == external_id,
            )
        )

    def _create_object(
        self,
        *,
        kind: str,
        title: str,
        external_id: str,
        canonical_uri: str,
        metadata: dict[str, Any],
    ) -> Object:
        obj = Object(
            user_id=self.user_id,
            kind=kind,
            title=title,
            origin="explicit",
            state="observed",
            provider=PROVIDER_WEB,
            external_id=external_id,
            canonical_uri=canonical_uri,
            metadata_=dict(metadata),
        )
        self.session.add(obj)
        self.session.flush()
        return obj


def _resolve_title(fetched: WebFetchResult, fallback: str) -> str:
    if fetched.title and fetched.title.strip():
        return fetched.title.strip()[:200]
    return fallback[:200]


def _resolve_file_title(fetched: WebFetchResult, fallback: str) -> str:
    if fetched.detected_suffix:
        path_name = fallback.rsplit("/", maxsplit=1)[-1]
        if path_name and not path_name.endswith(fetched.detected_suffix):
            return f"{path_name}{fetched.detected_suffix}"[:200]
        if path_name:
            return path_name[:200]
        return f"web-file{fetched.detected_suffix}"[:200]
    return fallback[:200]


def _merge_probe_metadata(
    prior_meta: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(prior_meta)
    for key in (
        "intake_mode",
        "requested_url",
        "normalized_requested_url",
        "final_url",
        "fetched_at",
        "mime_type",
        "detected_suffix",
        "content_length",
        "etag",
        "last_modified",
    ):
        if key in metadata:
            merged[key] = metadata[key]
    return merged


def _mechanical_rep_count(session: Session, object_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Representation)
            .where(
                Representation.object_id == object_id,
                Representation.kind.in_(MECHANICAL_REPRESENTATION_KINDS),
            )
        )
        or 0
    )
