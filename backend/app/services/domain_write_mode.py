"""Deterministic provenance mode for DomainToolService writes."""

from enum import Enum


class DomainWriteMode(str, Enum):
    """Agent proposals stay proposed until explicit user approval."""

    AGENT_PROPOSED = "agent_proposed"
    APPROVED_CONFIRMED = "approved_confirmed"
