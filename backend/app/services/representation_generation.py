"""Representation generation concurrency token for mechanical representation refresh."""

from __future__ import annotations

REPRESENTATION_GENERATION_KEY = "representation_generation"


def get_representation_generation(metadata: dict | None) -> int:
    if not metadata:
        return 0
    value = metadata.get(REPRESENTATION_GENERATION_KEY)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def initialize_representation_generation(metadata: dict) -> dict:
    updated = dict(metadata)
    if get_representation_generation(updated) <= 0:
        updated[REPRESENTATION_GENERATION_KEY] = 1
    return updated


def bump_representation_generation(metadata: dict) -> dict:
    updated = dict(metadata)
    updated[REPRESENTATION_GENERATION_KEY] = get_representation_generation(updated) + 1
    return updated


def representation_generation_matches(
    metadata: dict | None,
    expected_revision: str | None,
    expected_generation: int | None,
) -> bool:
    current = dict(metadata or {})
    if expected_revision is not None and current.get("content_revision") != expected_revision:
        return False
    if expected_generation is not None:
        if get_representation_generation(current) != expected_generation:
            return False
    return True
