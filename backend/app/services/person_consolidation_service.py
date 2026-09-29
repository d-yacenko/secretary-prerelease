"""Explicit, reversible consolidation of two Person objects.

The user chooses the survivor. This service moves exact identities, copies
identity evidence, and preserves canonical Task actor roles. It does not infer
relationships, call a model, or delete identities.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Edge, Object, ObjectBookmark, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import (
    is_object_hidden_from_active_reads,
    restore_object_from_explicit_intake,
    tombstone_object,
)
from app.domain.person_identity import NormalizedPersonIdentity
from app.domain.task_relations import TASK_ACTOR_ROLES
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.object_bookmark_service import ObjectBookmarkService
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE
from app.services.task_relation_service import TaskRelationService

AUDIT_KEY = "person_consolidation"
MAX_IDENTITIES = 32
MAX_EVIDENCE = 64
MAX_ACTOR_EDGES = 32
_HISTORY_LIMIT = 8


class PersonConsolidationService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._people = PersonIdentityService(session, user_id)
        self._tasks = TaskRelationService(session, user_id)
        self._bookmarks = ObjectBookmarkService(session, user_id)

    def preview(self, survivor_id: UUID, duplicate_id: UUID) -> dict:
        return self._assess(survivor_id, duplicate_id).public

    def apply(self, survivor_id: UUID, duplicate_id: UUID) -> dict:
        established = self._established(survivor_id, duplicate_id)
        if established is not None:
            return established
        assessed = self._assess(survivor_id, duplicate_id)
        if not assessed.public["can_merge"]:
            raise ValidationError(assessed.public["blockers"][0])
        with self._session.begin_nested():
            self._transfer(assessed)
        return {
            "survivor_id": survivor_id,
            "duplicate_id": duplicate_id,
            "idempotent": False,
        }

    def undo(self, survivor_id: UUID, duplicate_id: UUID) -> dict:
        duplicate = self._require_known_person(duplicate_id)
        survivor = self._require_known_person(survivor_id)
        audit = self._audit(duplicate)
        if audit is None or audit.get("survivor_id") != str(survivor_id):
            raise ValidationError("person merge cannot be undone")
        if audit.get("active") is not True:
            self._require_restored(duplicate, audit)
            return {
                "survivor_id": survivor.id,
                "duplicate_id": duplicate.id,
                "idempotent": True,
            }
        self._require_undo_safe(survivor, audit)
        with self._session.begin_nested():
            self._reverse(survivor, duplicate, audit)
        return {
            "survivor_id": survivor.id,
            "duplicate_id": duplicate.id,
            "idempotent": False,
        }

    def history_for(self, survivor_id: UUID) -> list[dict]:
        rows = self._session.scalars(
            select(Object)
            .where(
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.deleted_at.is_not(None),
                Object.metadata_[AUDIT_KEY]["active"].astext == "true",
                Object.metadata_[AUDIT_KEY]["survivor_id"].astext == str(survivor_id),
            )
            .order_by(Object.deleted_at.desc(), Object.id)
            .limit(_HISTORY_LIMIT)
        )
        return [
            {
                "duplicate_id": row.id,
                "duplicate_title": row.title,
                "undo_available": True,
            }
            for row in rows
        ]

    def _assess(self, survivor_id: UUID, duplicate_id: UUID) -> _Assessment:
        if survivor_id == duplicate_id:
            raise ValidationError("merge requires two different people")
        survivor = self._require_active_person(survivor_id)
        duplicate = self._require_active_person(duplicate_id)
        identities = self._active_identities(duplicate.id)
        evidence = self._active_evidence(duplicate.id)
        edges = self._incident_edges(duplicate.id)
        actor_edges = []
        blockers: list[str] = []
        for edge in edges:
            if self._is_actor_edge(edge, duplicate.id):
                actor_edges.append(edge)
            else:
                blockers.append("duplicate has an unsupported graph edge")
                break
        if len(identities) > MAX_IDENTITIES:
            blockers.append("duplicate has too many identities")
        if len(evidence) > MAX_EVIDENCE:
            blockers.append("duplicate has too many evidence rows")
        if len(actor_edges) > MAX_ACTOR_EDGES:
            blockers.append("duplicate has too many task roles")
        bookmark = self._session.get(ObjectBookmark, (self._user_id, duplicate.id))
        counts = {role: 0 for role in sorted(TASK_ACTOR_ROLES)}
        for edge in actor_edges:
            counts[edge.type] += 1
        shown = identities if not blockers else []
        public = {
            "survivor_id": survivor.id,
            "duplicate_id": duplicate.id,
            "survivor": self._side(survivor),
            "duplicate": self._side(duplicate),
            "identities": [_tuple_payload(row) for row in shown],
            "identity_count": len(identities),
            "actor_counts": counts,
            "evidence_count": len(evidence),
            "duplicate_bookmarked": bookmark is not None,
            "blockers": blockers,
            "can_merge": not blockers,
        }
        return _Assessment(
            public=public,
            survivor=survivor,
            duplicate=duplicate,
            identities=identities,
            evidence=evidence,
            actor_edges=actor_edges,
            bookmark_color=bookmark.color if bookmark is not None else None,
        )

    def _transfer(self, assessed: _Assessment) -> None:
        moved: list[dict] = []
        identity_ids: dict[tuple[str, str, str, str], UUID] = {}
        for row in assessed.identities:
            attached = self._people.reassign(row.id, assessed.survivor.id)
            key = _tuple_key(attached)
            identity_ids[key] = attached.id
            payload = _tuple_payload(attached)
            payload["survivor_identity_id"] = str(attached.id)
            moved.append(payload)
        if self._active_identities(assessed.duplicate.id):
            raise ConflictError("person identity could not be moved")
        created_evidence: list[str] = []
        preexisting_evidence = [
            str(row.id)
            for row in self._active_evidence(assessed.survivor.id)
            if _tuple_key(row) in identity_ids
        ]
        for row in assessed.evidence:
            key = _tuple_key(row)
            existing = self._matching_evidence(assessed.survivor.id, row)
            if existing is not None:
                continue
            copy = PersonIdentityEvidence(
                user_id=self._user_id,
                person_object_id=assessed.survivor.id,
                person_identity_id=identity_ids.get(key),
                provider=row.provider,
                identity_type=row.identity_type,
                realm=row.realm,
                canonical_value=row.canonical_value,
                evidence_type=row.evidence_type,
                polarity=row.polarity,
                weight=row.weight,
                provenance_kind=row.provenance_kind,
                provenance_key=row.provenance_key,
                source_object_id=row.source_object_id,
                explanation=row.explanation,
                details=dict(row.details or {}),
                state="active",
            )
            self._session.add(copy)
            self._session.flush()
            created_evidence.append(str(copy.id))
        created_edges: list[dict] = []
        for edge in assessed.actor_edges:
            if self._actor_fact_exists(edge.source_id, assessed.survivor.id, edge.type):
                continue
            task = self._session.get(Object, edge.source_id)
            if (
                task is None
                or task.user_id != self._user_id
                or task.kind != "task"
                or is_object_hidden_from_active_reads(task)
            ):
                continue
            created_edge, created = self._tasks.add_actor(
                edge.source_id,
                assessed.survivor.id,
                edge.type,
                origin=edge.origin,
                state=edge.state,
                confidence=edge.confidence,
            )
            if created:
                created_edges.append(
                    {
                        "id": str(created_edge.id),
                        "task_id": str(created_edge.source_id),
                        "role": created_edge.type,
                        "state": created_edge.state,
                    }
                )
        when = datetime.now(UTC)
        tombstone_object(assessed.duplicate, when=when)
        if assessed.bookmark_color is not None:
            self._bookmarks.delete_for_object(assessed.duplicate.id)
        self._write_audit(
            assessed.duplicate,
            {
                "active": True,
                "survivor_id": str(assessed.survivor.id),
                "merged_at": when.isoformat(),
                "identities": moved,
                "evidence_ids": created_evidence,
                "preexisting_evidence_ids": preexisting_evidence,
                "actor_edges": created_edges,
                "bookmark": {
                    "present": assessed.bookmark_color is not None,
                    "color": assessed.bookmark_color,
                },
            },
        )

    def _reverse(self, survivor: Object, duplicate: Object, audit: dict) -> None:
        restore_object_from_explicit_intake(duplicate)
        if duplicate.state != CONFIRMED_STATE:
            duplicate.state = CONFIRMED_STATE
        for item in audit.get("identities") or []:
            row = self._session.get(PersonIdentity, UUID(item["survivor_identity_id"]))
            if row is None:
                raise ValidationError("person merge cannot be undone")
            self._people.reassign(row.id, duplicate.id)
        for evidence_id in audit.get("evidence_ids") or []:
            row = self._session.get(PersonIdentityEvidence, UUID(evidence_id))
            if row is None or row.state != "active" or row.person_object_id != survivor.id:
                raise ValidationError("person merge cannot be undone")
            row.state = "retracted"
            row.retracted_at = datetime.now(UTC)
        for item in audit.get("actor_edges") or []:
            edge = self._session.get(Edge, UUID(item["id"]))
            if edge is None or edge.state == REJECTED_STATE:
                raise ValidationError("person merge cannot be undone")
            self._tasks.remove_actor(UUID(item["task_id"]), edge.id)
        bookmark = audit.get("bookmark") or {}
        if bookmark.get("present") and bookmark.get("color"):
            self._bookmarks.upsert(duplicate.id, bookmark["color"])
        closed = dict(audit)
        closed["active"] = False
        closed["undone_at"] = datetime.now(UTC).isoformat()
        self._write_audit(duplicate, closed)
        self._session.flush()

    def _require_undo_safe(self, survivor: Object, audit: dict) -> None:
        if is_object_hidden_from_active_reads(survivor) or survivor.state == REJECTED_STATE:
            raise ValidationError("person merge cannot be undone")
        allowed_evidence = {
            str(item)
            for item in (
                list(audit.get("evidence_ids") or [])
                + list(audit.get("preexisting_evidence_ids") or [])
            )
        }
        for item in audit.get("identities") or []:
            row = self._session.get(PersonIdentity, UUID(item["survivor_identity_id"]))
            if (
                row is None
                or row.user_id != self._user_id
                or row.state == REJECTED_STATE
                or row.person_object_id != survivor.id
                or row.provider != item["provider"]
                or row.identity_type != item["identity_type"]
                or row.realm != item["realm"]
                or row.canonical_value != item["canonical_value"]
            ):
                raise ValidationError("person merge cannot be undone")
            later = self._session.scalars(
                select(PersonIdentityEvidence.id).where(
                    PersonIdentityEvidence.user_id == self._user_id,
                    PersonIdentityEvidence.person_object_id == survivor.id,
                    PersonIdentityEvidence.state == "active",
                    PersonIdentityEvidence.provider == row.provider,
                    PersonIdentityEvidence.identity_type == row.identity_type,
                    PersonIdentityEvidence.realm == row.realm,
                    PersonIdentityEvidence.canonical_value == row.canonical_value,
                )
            )
            if any(str(evidence_id) not in allowed_evidence for evidence_id in later):
                raise ValidationError("person merge cannot be undone")
        for item in audit.get("actor_edges") or []:
            edge = self._session.get(Edge, UUID(item["id"]))
            if (
                edge is None
                or edge.user_id != self._user_id
                or edge.state != item["state"]
                or edge.type != item["role"]
                or edge.target_id != survivor.id
                or str(edge.source_id) != item["task_id"]
            ):
                raise ValidationError("person merge cannot be undone")

    def _require_restored(self, duplicate: Object, audit: dict) -> None:
        if is_object_hidden_from_active_reads(duplicate):
            raise ValidationError("person merge cannot be undone")
        for item in audit.get("identities") or []:
            owner = self._people.resolve(_identity_from_audit(item))
            if owner is None or owner.id != duplicate.id:
                raise ValidationError("person merge cannot be undone")

    def _established(self, survivor_id: UUID, duplicate_id: UUID) -> dict | None:
        if survivor_id == duplicate_id:
            raise ValidationError("merge requires two different people")
        duplicate = self._session.get(Object, duplicate_id)
        if duplicate is None or duplicate.user_id != self._user_id or duplicate.kind != PERSON_KIND:
            return None
        audit = self._audit(duplicate)
        if audit is None or audit.get("active") is not True:
            return None
        if audit.get("survivor_id") != str(survivor_id):
            raise ConflictError("person is already merged")
        self._require_active_person(survivor_id)
        return {
            "survivor_id": survivor_id,
            "duplicate_id": duplicate_id,
            "idempotent": True,
        }

    def _require_active_person(self, person_id: UUID) -> Object:
        person = self._require_known_person(person_id)
        if person.state == REJECTED_STATE or is_object_hidden_from_active_reads(person):
            raise NotFoundError("person", person_id)
        return person

    def _require_known_person(self, person_id: UUID) -> Object:
        person = self._session.get(Object, person_id)
        if person is None or person.user_id != self._user_id or person.kind != PERSON_KIND:
            raise NotFoundError("person", person_id)
        return person

    def _active_identities(self, person_id: UUID) -> list[PersonIdentity]:
        return list(
            self._session.scalars(
                select(PersonIdentity)
                .where(
                    PersonIdentity.user_id == self._user_id,
                    PersonIdentity.person_object_id == person_id,
                    PersonIdentity.state != REJECTED_STATE,
                )
                .order_by(
                    PersonIdentity.provider,
                    PersonIdentity.identity_type,
                    PersonIdentity.canonical_value,
                    PersonIdentity.id,
                )
            )
        )

    def _active_evidence(self, person_id: UUID) -> list[PersonIdentityEvidence]:
        return list(
            self._session.scalars(
                select(PersonIdentityEvidence)
                .where(
                    PersonIdentityEvidence.user_id == self._user_id,
                    PersonIdentityEvidence.person_object_id == person_id,
                    PersonIdentityEvidence.state == "active",
                )
                .order_by(PersonIdentityEvidence.id)
            )
        )

    def _incident_edges(self, person_id: UUID) -> list[Edge]:
        return list(
            self._session.scalars(
                select(Edge)
                .where(
                    Edge.user_id == self._user_id,
                    Edge.state != REJECTED_STATE,
                    or_(Edge.source_id == person_id, Edge.target_id == person_id),
                )
                .order_by(Edge.id)
            )
        )

    def _is_actor_edge(self, edge: Edge, person_id: UUID) -> bool:
        if edge.target_id != person_id or edge.type not in TASK_ACTOR_ROLES:
            return False
        source = self._session.get(Object, edge.source_id)
        return source is not None and source.user_id == self._user_id and source.kind == "task"

    def _matching_evidence(
        self,
        person_id: UUID,
        row: PersonIdentityEvidence,
    ) -> PersonIdentityEvidence | None:
        return self._session.scalar(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.provider == row.provider,
                PersonIdentityEvidence.identity_type == row.identity_type,
                PersonIdentityEvidence.realm == row.realm,
                PersonIdentityEvidence.canonical_value == row.canonical_value,
                PersonIdentityEvidence.evidence_type == row.evidence_type,
                PersonIdentityEvidence.polarity == row.polarity,
                PersonIdentityEvidence.provenance_key == row.provenance_key,
            )
        )

    def _actor_fact_exists(self, task_id: UUID, person_id: UUID, role: str) -> bool:
        return (
            self._session.scalar(
                select(Edge.id).where(
                    Edge.user_id == self._user_id,
                    Edge.source_id == task_id,
                    Edge.target_id == person_id,
                    Edge.type == role,
                    Edge.state != REJECTED_STATE,
                )
            )
            is not None
        )

    def _side(self, person: Object) -> dict:
        cues = []
        for row in self._active_identities(person.id):
            cues.append(row.display_value or row.canonical_value)
            if len(cues) == 3:
                break
        return {"person_id": person.id, "title": person.title, "cues": cues}

    def _audit(self, person: Object) -> dict | None:
        raw = (person.metadata_ or {}).get(AUDIT_KEY)
        return raw if isinstance(raw, dict) else None

    def _write_audit(self, person: Object, audit: dict) -> None:
        metadata = dict(person.metadata_ or {})
        metadata[AUDIT_KEY] = audit
        person.metadata_ = metadata
        flag_modified(person, "metadata_")
        self._session.flush()


class _Assessment:
    def __init__(
        self,
        *,
        public: dict,
        survivor: Object,
        duplicate: Object,
        identities: list[PersonIdentity],
        evidence: list[PersonIdentityEvidence],
        actor_edges: list[Edge],
        bookmark_color: str | None,
    ) -> None:
        self.public = public
        self.survivor = survivor
        self.duplicate = duplicate
        self.identities = identities
        self.evidence = evidence
        self.actor_edges = actor_edges
        self.bookmark_color = bookmark_color


def _tuple_key(row: PersonIdentity | PersonIdentityEvidence) -> tuple[str, str, str, str]:
    return (row.provider, row.identity_type, row.realm, row.canonical_value)


def _tuple_payload(row: PersonIdentity) -> dict:
    return {
        "provider": row.provider,
        "identity_type": row.identity_type,
        "realm": row.realm,
        "canonical_value": row.canonical_value,
        "display_value": row.display_value,
    }


def _identity_from_audit(item: dict) -> NormalizedPersonIdentity:
    return NormalizedPersonIdentity(
        identity_type=item["identity_type"],
        provider=item["provider"],
        realm=item["realm"],
        canonical_value=item["canonical_value"],
        display_value=item.get("display_value"),
    )
