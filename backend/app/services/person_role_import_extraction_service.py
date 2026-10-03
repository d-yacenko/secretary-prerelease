"""Proposal-only role extraction. The result is not stored."""

from contextlib import contextmanager
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.ai_audit.constants import (
    EVENT_MODEL_ROUND,
    EVENT_TRACE_FINISHED,
    EVENT_TRACE_STARTED,
    WORKLOAD_ROLE_IMPORT_EXTRACTION,
)
from app.ai_audit.context import ActiveTrace, _active_trace, get_active_trace
from app.ai_audit.trace_service import AITraceService
from app.services.person_role_import_source_service import (
    PersonRoleImportSourceService,
    RoleImportSource,
)

MAX_ROLE_IMPORT_ITEMS = 32
_NAME_MAX = 160
_ROLE_MAX = 120
_CONTEXT_MAX = 200
_EVIDENCE_MAX = 240
_LOCATOR_MAX = 80

ROLE_IMPORT_AUDIT_KEYS = frozenset(
    {
        "workload",
        "model",
        "source_kind",
        "source_bytes",
        "source_text_chars",
        "source_revision",
        "item_count",
        "source_truncated",
        "items_truncated",
        "input_tokens",
        "output_tokens",
    }
)


class RoleImportItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    person_name: str
    role: str
    context: str | None = None
    evidence_text: str
    source_locator: str | None = None


class RoleImportProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_object_id: UUID
    source_revision: str
    source_kind: str
    source_truncated: bool
    items: list[RoleImportItem]
    items_truncated: bool


class RoleImportProviderResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[Any]
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class RoleImportExtractionProvider(Protocol):
    def extract_image(self, image_bytes: bytes, mime_type: str) -> RoleImportProviderResult: ...

    def extract_text(self, text: str) -> RoleImportProviderResult: ...


def record_role_import_audit(metadata: dict[str, object]) -> None:
    active = get_active_trace()
    if active is None:
        return
    safe = {key: metadata[key] for key in ROLE_IMPORT_AUDIT_KEYS if key in metadata}
    active.record_event(EVENT_MODEL_ROUND, safe)


def normalize_role_import_items(raw_items: list) -> tuple[list[RoleImportItem], bool]:
    kept: list[RoleImportItem] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for raw in raw_items:
        item = _normalize_item(raw)
        if item is None:
            continue
        key = (
            item.person_name,
            item.role,
            item.context or "",
            item.evidence_text,
            item.source_locator or "",
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    truncated = len(kept) > MAX_ROLE_IMPORT_ITEMS
    return kept[:MAX_ROLE_IMPORT_ITEMS], truncated


class PersonRoleImportExtractionService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        provider: RoleImportExtractionProvider,
        upload_root,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._provider = provider
        self._sources = PersonRoleImportSourceService(session, user_id, upload_root)

    def extract(self, source_object_id: UUID) -> RoleImportProposal:
        source = self._sources.load(source_object_id)
        with _role_import_trace(self._session, self._user_id, source.object_id):
            if source.source_kind == "image":
                result = self._provider.extract_image(
                    source.image_bytes or b"", source.mime_type or ""
                )
            else:
                result = self._provider.extract_text(source.text or "")
            items, items_truncated = normalize_role_import_items(result.items)
            proposal = RoleImportProposal(
                source_object_id=source.object_id,
                source_revision=source.source_revision,
                source_kind=source.source_kind,
                source_truncated=source.source_truncated,
                items=items,
                items_truncated=items_truncated,
            )
            record_role_import_audit(_audit_metadata(source, result, proposal))
            return proposal


@contextmanager
def _role_import_trace(session: Session, user_id: UUID, object_id: UUID):
    """Record a role-import trace on the request session without committing it."""
    trace = AITraceService(session).start_trace(
        user_id=user_id,
        workload=WORKLOAD_ROLE_IMPORT_EXTRACTION,
        object_id=object_id,
    )
    active = ActiveTrace(
        trace_id=trace.id,
        user_id=user_id,
        workload=WORKLOAD_ROLE_IMPORT_EXTRACTION,
        session=session,
    )
    active.record_event(
        EVENT_TRACE_STARTED,
        {"workload": WORKLOAD_ROLE_IMPORT_EXTRACTION, "object_id": str(object_id)},
    )
    token = _active_trace.set(active)
    try:
        yield active
        active.record_event(EVENT_TRACE_FINISHED, {"success": True, "error_category": None})
    except Exception as exc:
        active.record_event(
            EVENT_TRACE_FINISHED,
            {"success": False, "error_category": type(exc).__name__},
        )
        raise
    finally:
        _active_trace.reset(token)


def _audit_metadata(
    source: RoleImportSource,
    result: RoleImportProviderResult,
    proposal: RoleImportProposal,
) -> dict[str, object]:
    return {
        "workload": WORKLOAD_ROLE_IMPORT_EXTRACTION,
        "model": result.model,
        "source_kind": source.source_kind,
        "source_bytes": len(source.image_bytes) if source.image_bytes is not None else None,
        "source_text_chars": len(source.text) if source.text is not None else None,
        "source_revision": source.source_revision,
        "item_count": len(proposal.items),
        "source_truncated": proposal.source_truncated,
        "items_truncated": proposal.items_truncated,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def _normalize_item(raw: object) -> RoleImportItem | None:
    if not isinstance(raw, dict):
        return None
    person_name = _collapse(raw.get("person_name"))
    role = _collapse(raw.get("role"))
    evidence = _collapse(raw.get("evidence_text"))
    context = _collapse(raw.get("context"))
    locator = _collapse(raw.get("source_locator"))
    if not person_name or not role or not evidence:
        return None
    if len(person_name) > _NAME_MAX or len(role) > _ROLE_MAX:
        return None
    if context is not None and len(context) > _CONTEXT_MAX:
        return None
    if len(evidence) > _EVIDENCE_MAX:
        evidence = evidence[:_EVIDENCE_MAX]
    if locator is not None and len(locator) > _LOCATOR_MAX:
        locator = locator[:_LOCATOR_MAX]
    return RoleImportItem(
        person_name=person_name,
        role=role,
        context=context,
        evidence_text=evidence,
        source_locator=locator,
    )


def _collapse(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    return collapsed or None
