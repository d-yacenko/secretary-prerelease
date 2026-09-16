"""Persist bounded mechanical representations without LLM summary."""

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.content_extraction.constants import (
    MAX_REPRESENTATION_PART_BYTES,
    MAX_REPRESENTATION_PARTS,
    MAX_REPRESENTATION_TOTAL_BYTES,
)
from app.content_extraction.metadata_keys import MECHANICAL_REPRESENTATION_KINDS
from app.db.models import Representation
from app.services.errors import ValidationError
from app.services.representation_service import KIND_SUMMARY


def _utf8_byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


class MechanicalRepresentationPersistence:
    def __init__(self, session: Session) -> None:
        self._session = session

    def validate_representations(self, reps: list[Representation]) -> list[Representation]:
        if len(reps) > MAX_REPRESENTATION_PARTS:
            raise ValidationError("mechanical representations exceed max parts")
        total_bytes = 0
        for rep in reps:
            part_bytes = _utf8_byte_len(rep.text)
            if part_bytes > MAX_REPRESENTATION_PART_BYTES:
                raise ValidationError("mechanical representation part exceeds size limit")
            total_bytes += part_bytes
            if total_bytes > MAX_REPRESENTATION_TOTAL_BYTES:
                raise ValidationError("mechanical representation payload exceeds total size limit")
        return reps

    def replace_mechanical_for_object(self, object_id: UUID, reps: list[Representation]) -> int:
        validated = self.validate_representations(reps)
        kinds_to_clear = set(MECHANICAL_REPRESENTATION_KINDS) | {KIND_SUMMARY, "summary"}
        self._session.execute(
            delete(Representation).where(
                Representation.object_id == object_id,
                Representation.kind.in_(kinds_to_clear),
            )
        )
        for rep in validated:
            self._session.add(rep)
        self._session.flush()
        return len(validated)

    def clear_mechanical_for_object(self, object_id: UUID) -> None:
        kinds_to_clear = set(MECHANICAL_REPRESENTATION_KINDS) | {KIND_SUMMARY, "summary"}
        self._session.execute(
            delete(Representation).where(
                Representation.object_id == object_id,
                Representation.kind.in_(kinds_to_clear),
            )
        )
        self._session.flush()
