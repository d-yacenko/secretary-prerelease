from typing import Literal

Origin = Literal["source", "user", "agent", "system"]
State = Literal["observed", "proposed", "confirmed", "rejected"]

ALLOWED_ORIGINS = frozenset({"source", "user", "agent", "system"})
ALLOWED_STATES = frozenset({"observed", "proposed", "confirmed", "rejected"})

AGENT_ORIGIN = "agent"
USER_ORIGIN = "user"
PROPOSED_STATE = "proposed"
CONFIRMED_STATE = "confirmed"
REJECTED_STATE = "rejected"
SOURCE_ORIGIN = "source"
SYSTEM_ORIGIN = "system"
OBSERVED_STATE = "observed"


def validate_origin(origin: str, resource: str) -> None:
    if origin not in ALLOWED_ORIGINS:
        raise ValueError(f"{resource}: origin must be one of {sorted(ALLOWED_ORIGINS)}")


def validate_state(state: str, resource: str) -> None:
    if state not in ALLOWED_STATES:
        raise ValueError(f"{resource}: state must be one of {sorted(ALLOWED_STATES)}")


def validate_confidence(confidence: float | None, resource: str) -> None:
    if confidence is None:
        return
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"{resource}: confidence must be between 0 and 1")


def default_object_state(origin: str, state: str | None = None) -> str:
    if state is not None:
        return state
    if origin == SOURCE_ORIGIN:
        return OBSERVED_STATE
    if origin == AGENT_ORIGIN:
        return PROPOSED_STATE
    return CONFIRMED_STATE


def validate_agent_proposal(
    origin: str,
    state: str,
    confidence: float | None,
    resource: str,
) -> None:
    validate_confidence(confidence, resource)
    if origin != AGENT_ORIGIN or state != PROPOSED_STATE:
        return
    if confidence is None:
        raise ValueError(f"{resource}: agent proposed items require confidence")


def validate_edge_state_transition(current_state: str, new_state: str) -> None:
    validate_state(new_state, "edge")
    if current_state != PROPOSED_STATE:
        raise ValueError("edge: only proposed edges can change state")
    if new_state not in {CONFIRMED_STATE, REJECTED_STATE}:
        raise ValueError("edge: proposed edges can only become confirmed or rejected")
