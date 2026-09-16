from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Edge, Object
from app.domain.labels import (
    EDGE_TYPE_LABELED_WITH,
    KIND_LABEL,
    LABEL_DESCRIPTION_MAX_CHARS,
    LABEL_NAME_MAX_CHARS,
    LABEL_SCHEMA_VERSION,
    LABELS_BY_OBJECTS_MAX,
    LIST_LABELS_MAX,
)
from app.domain.object_visibility import (
    is_object_hidden_from_active_reads,
    object_is_active,
    tombstone_object,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.provenance import (
    CONFIRMED_STATE,
    REJECTED_STATE,
    USER_ORIGIN,
)
from app.services.user_serialization_gate import lock_user_serialization_row

_RESERVED_LABEL_CREATE = "labels must be created through LabelService"
_RESERVED_LABELED_WITH = "labeled_with assignments must use assign_label/remove_label"


def normalize_label_description(description: str | None) -> str | None:
    if description is None:
        return None
    if not isinstance(description, str):
        raise ValidationError("label description must be a string")
    normalized = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    if len(normalized) > LABEL_DESCRIPTION_MAX_CHARS:
        raise ValidationError(
            f"label description must be at most {LABEL_DESCRIPTION_MAX_CHARS} characters"
        )
    return normalized


def label_description(label: Object) -> str | None:
    raw = label.body
    if not isinstance(raw, str):
        return None
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    return normalized[:LABEL_DESCRIPTION_MAX_CHARS]


def normalize_label_name(name: str) -> tuple[str, str]:
    if not isinstance(name, str):
        raise ValidationError("label name is required")
    display = " ".join(unicodedata.normalize("NFKC", name).split())
    if not display:
        raise ValidationError("label name is required")
    if len(display) > LABEL_NAME_MAX_CHARS:
        raise ValidationError(f"label name must be at most {LABEL_NAME_MAX_CHARS} characters")
    return display, display.casefold()


def reserved_label_create_reason(kind: str) -> str | None:
    if kind == KIND_LABEL:
        return _RESERVED_LABEL_CREATE
    return None


def reserved_labeled_with_reason(edge_type: str) -> str | None:
    if edge_type == EDGE_TYPE_LABELED_WITH:
        return _RESERVED_LABELED_WITH
    return None


def reserved_label_update_reason(kind: str) -> str | None:
    if kind == KIND_LABEL:
        return "labels must be updated through LabelService"
    return None


@dataclass(frozen=True)
class LabelRecord:
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    object_count: int = 0


@dataclass(frozen=True)
class CreateLabelResult:
    label: Object
    created: bool


@dataclass(frozen=True)
class RenameLabelResult:
    label: Object
    changed: bool


UpdateLabelResult = RenameLabelResult


@dataclass(frozen=True)
class DeleteLabelResult:
    label: Object
    changed: bool


@dataclass(frozen=True)
class AssignLabelResult:
    edge: Edge
    created: bool


@dataclass(frozen=True)
class BackgroundAssignResult:
    edge: Edge | None
    created: int = 0
    already_present: int = 0
    suppressed_rejected: int = 0


@dataclass(frozen=True)
class RemoveLabelResult:
    edge: Edge | None
    changed: bool


class LabelService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        *,
        origin: str = USER_ORIGIN,
        state: str = CONFIRMED_STATE,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._origin = origin
        self._state = state

    def list_labels(self, *, limit: int = 100) -> list[LabelRecord]:
        row_limit = max(1, min(int(limit), LIST_LABELS_MAX))
        labels = list(
            self._session.scalars(
                select(Object)
                .where(*self._active_label_filters())
                .order_by(Object.metadata_["label_key"].as_string().asc(), Object.id.asc())
                .limit(row_limit)
            )
        )
        counts = self._object_counts([item.id for item in labels])
        return [
            LabelRecord(
                id=item.id,
                title=item.title,
                created_at=item.created_at,
                updated_at=item.updated_at,
                description=label_description(item),
                object_count=counts.get(item.id, 0),
            )
            for item in labels
        ]

    def create_label(self, name: str, description: str | None = None) -> CreateLabelResult:
        display, key = normalize_label_name(name)
        body = normalize_label_description(description)
        self._lock_user()
        existing = self._active_by_key(key)
        if existing is not None:
            return CreateLabelResult(label=existing, created=False)
        label = Object(
            user_id=self._user_id,
            kind=KIND_LABEL,
            title=display,
            origin=self._origin,
            state=self._state,
            body=body,
            provider=None,
            external_id=None,
            canonical_uri=None,
            status=None,
            metadata_={
                "label_key": key,
                "label_schema_version": LABEL_SCHEMA_VERSION,
            },
        )
        self._session.add(label)
        self._session.flush()
        return CreateLabelResult(label=label, created=True)

    def rename_label(self, label_id: UUID, name: str) -> RenameLabelResult:
        return self.update_label(label_id, name=name)

    def update_label(
        self,
        label_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        name_set: bool = False,
        description_set: bool = False,
    ) -> UpdateLabelResult:
        if not name_set and not description_set:
            if name is not None:
                name_set = True
            else:
                raise ValidationError("no fields to update")
        display = key = None
        if name_set:
            if name is None:
                raise ValidationError("label name is required")
            display, key = normalize_label_name(name)
        body = None
        if description_set:
            body = normalize_label_description(description)
        self._lock_user()
        label = self._require_active_label(label_id)
        changed = False
        if name_set:
            other = self._active_by_key(key or "")
            if other is not None and other.id != label.id:
                raise ConflictError("an active label with this name already exists")
            if label.title != display:
                label.title = display
                changed = True
            metadata = dict(label.metadata_ or {})
            if metadata.get("label_key") != key:
                metadata["label_key"] = key
                metadata["label_schema_version"] = LABEL_SCHEMA_VERSION
                label.metadata_ = metadata
                changed = True
        if description_set and label.body != body:
            label.body = body
            changed = True
        if changed:
            self._session.flush()
        return UpdateLabelResult(label=label, changed=changed)

    def delete_label(self, label_id: UUID) -> DeleteLabelResult:
        self._lock_user()
        label = self._owned_label(label_id)
        if is_object_hidden_from_active_reads(label):
            return DeleteLabelResult(label=label, changed=False)
        tombstone_object(label)
        self._session.flush()
        return DeleteLabelResult(label=label, changed=True)

    def list_labels_by_objects(self, object_ids: list[UUID]) -> dict[UUID, list[LabelRecord]]:
        unique: list[UUID] = []
        seen: set[UUID] = set()
        for object_id in object_ids:
            if object_id in seen:
                continue
            seen.add(object_id)
            unique.append(object_id)
        if len(unique) > LABELS_BY_OBJECTS_MAX:
            raise ValidationError(
                f"at most {LABELS_BY_OBJECTS_MAX} object_ids are allowed"
            )
        if not unique:
            return {}
        source = aliased(Object)
        label = aliased(Object)
        rows = self._session.execute(
            select(Edge.source_id, label)
            .select_from(Edge)
            .join(source, source.id == Edge.source_id)
            .join(label, label.id == Edge.target_id)
            .where(
                Edge.user_id == self._user_id,
                Edge.type == EDGE_TYPE_LABELED_WITH,
                Edge.state != REJECTED_STATE,
                Edge.source_id.in_(unique),
                source.user_id == self._user_id,
                source.state != REJECTED_STATE,
                object_is_active(source),
                label.user_id == self._user_id,
                label.kind == KIND_LABEL,
                label.state != REJECTED_STATE,
                object_is_active(label),
            )
            .order_by(func.lower(label.title), label.id)
        ).all()
        grouped: dict[UUID, list[LabelRecord]] = {}
        for source_id, item in rows:
            grouped.setdefault(source_id, []).append(
                LabelRecord(
                    id=item.id,
                    title=item.title,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    description=label_description(item),
                )
            )
        return grouped

    def get_object_labels(self, object_id: UUID) -> list[LabelRecord]:
        source = self._require_visible_object(object_id)
        labels = list(
            self._session.scalars(
                select(Object)
                .join(Edge, Edge.target_id == Object.id)
                .where(
                    *self._active_label_filters(),
                    *self._active_assignment_filters(source.id),
                )
                .order_by(Object.id.asc())
            )
        )
        labels.sort(key=lambda item: (item.title.casefold(), item.id))
        return [
            LabelRecord(
                id=item.id,
                title=item.title,
                created_at=item.created_at,
                updated_at=item.updated_at,
                description=label_description(item),
            )
            for item in labels
        ]

    def assign_label(self, object_id: UUID, label_id: UUID) -> AssignLabelResult:
        self._lock_objects(object_id, label_id)
        source = self._require_visible_object(object_id)
        label = self._require_active_label(label_id)
        if source.kind == KIND_LABEL:
            raise ValidationError("a label cannot be labeled")
        existing = self._active_assignment(source.id, label.id)
        if existing is not None:
            return AssignLabelResult(edge=existing, created=False)
        edge = Edge(
            user_id=self._user_id,
            source_id=source.id,
            target_id=label.id,
            type=EDGE_TYPE_LABELED_WITH,
            origin=self._origin,
            state=self._state,
            confidence=None,
            metadata_={},
        )
        self._session.add(edge)
        self._session.flush()
        return AssignLabelResult(edge=edge, created=True)

    def assign_label_background(
        self,
        object_id: UUID,
        label_id: UUID,
        *,
        confidence: float | None,
        metadata: dict,
    ) -> BackgroundAssignResult:
        self._lock_objects(object_id, label_id)
        source = self._require_visible_object(object_id)
        label = self._require_active_label(label_id)
        if source.kind == KIND_LABEL:
            raise ValidationError("a label cannot be labeled")
        existing = self._active_assignment(source.id, label.id)
        if existing is not None:
            return BackgroundAssignResult(edge=existing, already_present=1)
        if self._rejected_assignment(source.id, label.id) is not None:
            return BackgroundAssignResult(edge=None, suppressed_rejected=1)
        edge = Edge(
            user_id=self._user_id,
            source_id=source.id,
            target_id=label.id,
            type=EDGE_TYPE_LABELED_WITH,
            origin=self._origin,
            state=self._state,
            confidence=confidence,
            metadata_=dict(metadata),
        )
        self._session.add(edge)
        self._session.flush()
        return BackgroundAssignResult(edge=edge, created=1)

    def remove_label(self, object_id: UUID, label_id: UUID) -> RemoveLabelResult:
        self._lock_objects(object_id, label_id)
        source = self._owned_object(object_id)
        self._owned_label(label_id)
        existing = self._active_assignment(source.id, label_id)
        if existing is None:
            return RemoveLabelResult(edge=None, changed=False)
        existing.state = REJECTED_STATE
        self._session.flush()
        return RemoveLabelResult(edge=existing, changed=True)

    def require_active_labels(self, label_ids: list[UUID]) -> list[Object]:
        labels = []
        seen: set[UUID] = set()
        for label_id in label_ids:
            if label_id in seen:
                continue
            seen.add(label_id)
            labels.append(self._require_active_label(label_id))
        return labels

    def _lock_user(self) -> None:
        row = lock_user_serialization_row(self._session, self._user_id)
        if row is None:
            raise NotFoundError("user", self._user_id)

    def _lock_objects(self, first_id: UUID, second_id: UUID) -> None:
        for object_id in sorted((first_id, second_id), key=lambda item: item.bytes):
            row = self._session.scalar(
                select(Object)
                .where(Object.id == object_id, Object.user_id == self._user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise NotFoundError("object", object_id)

    def _active_label_filters(self) -> list:
        return [
            Object.user_id == self._user_id,
            Object.kind == KIND_LABEL,
            Object.state != REJECTED_STATE,
            object_is_active(),
        ]

    def _active_assignment_filters(self, source_id: UUID) -> list:
        return [
            Edge.user_id == self._user_id,
            Edge.source_id == source_id,
            Edge.type == EDGE_TYPE_LABELED_WITH,
            Edge.state != REJECTED_STATE,
        ]

    def _active_by_key(self, key: str) -> Object | None:
        return self._session.scalar(
            select(Object).where(
                *self._active_label_filters(),
                Object.metadata_["label_key"].as_string() == key,
            )
        )

    def _owned_object(self, object_id: UUID) -> Object:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise NotFoundError("object", object_id)
        return obj

    def _owned_label(self, label_id: UUID) -> Object:
        obj = self._owned_object(label_id)
        if obj.kind != KIND_LABEL:
            raise ValidationError("object is not a label")
        return obj

    def _require_active_label(self, label_id: UUID) -> Object:
        label = self._owned_label(label_id)
        if is_object_hidden_from_active_reads(label) or label.state == REJECTED_STATE:
            raise ValidationError("label is not active")
        return label

    def _require_visible_object(self, object_id: UUID) -> Object:
        obj = self._owned_object(object_id)
        if is_object_hidden_from_active_reads(obj) or obj.state == REJECTED_STATE:
            raise ValidationError("object is not active")
        return obj

    def _active_assignment(self, source_id: UUID, label_id: UUID) -> Edge | None:
        return self._session.scalar(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.source_id == source_id,
                Edge.target_id == label_id,
                Edge.type == EDGE_TYPE_LABELED_WITH,
                Edge.state != REJECTED_STATE,
            )
        )

    def _rejected_assignment(self, source_id: UUID, label_id: UUID) -> Edge | None:
        return self._session.scalar(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.source_id == source_id,
                Edge.target_id == label_id,
                Edge.type == EDGE_TYPE_LABELED_WITH,
                Edge.state == REJECTED_STATE,
            )
        )

    def _object_counts(self, label_ids: list[UUID]) -> dict[UUID, int]:
        if not label_ids:
            return {}
        source = aliased(Object)
        rows = self._session.execute(
            select(Edge.target_id, func.count())
            .select_from(Edge)
            .join(source, source.id == Edge.source_id)
            .where(
                Edge.user_id == self._user_id,
                Edge.target_id.in_(label_ids),
                Edge.type == EDGE_TYPE_LABELED_WITH,
                Edge.state != REJECTED_STATE,
                source.user_id == self._user_id,
                source.state != REJECTED_STATE,
                object_is_active(source),
            )
            .group_by(Edge.target_id)
        ).all()
        return {label_id: int(count) for label_id, count in rows}
