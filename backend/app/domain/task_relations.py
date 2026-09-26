"""Canonical Task relation vocabulary.

These names are explicit user or assistant claims. Nothing here infers a role
from names, message frequency, or a generic related_to edge.
"""

from __future__ import annotations

REQUESTED_BY = "requested_by"
DELEGATED_TO = "delegated_to"
WAITING_ON = "waiting_on"
INVOLVES = "involves"
DEPENDS_ON = "depends_on"
REFERENCES = "references"
PART_OF = "part_of"

TASK_ACTOR_ROLES = frozenset({REQUESTED_BY, DELEGATED_TO, WAITING_ON, INVOLVES})
TASK_RELATION_TYPES = frozenset({*TASK_ACTOR_ROLES, DEPENDS_ON, REFERENCES, PART_OF})

MAX_TASK_ACTOR_IDS = 8
MAX_TASK_DEPENDENCY_IDS = 8
MAX_PROFILE_ITEMS = 8
