"""Canonical generic relation types for human and tool writes.

Task actor roles stay on typed Task fields and are not part of this set.
"""

from typing import Literal

from app.domain.task_relations import DEPENDS_ON, PART_OF, REFERENCES

RELATED_TO = "related_to"

GENERIC_RELATION_TYPE_VALUES: tuple[str, ...] = (
    RELATED_TO,
    REFERENCES,
    DEPENDS_ON,
    PART_OF,
)
GENERIC_RELATION_TYPES = frozenset(GENERIC_RELATION_TYPE_VALUES)

GenericRelationType = Literal["related_to", "references", "depends_on", "part_of"]

assert set(GenericRelationType.__args__) == GENERIC_RELATION_TYPES
