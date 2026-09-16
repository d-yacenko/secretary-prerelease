from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import UserIdentityProfile, UserSemanticContext
from app.services.auto_label_constants import (
    AUTO_LABEL_MAX_IDENTITY_ITEM_CHARS,
    AUTO_LABEL_MAX_IDENTITY_ORGANIZATIONS,
    AUTO_LABEL_MAX_IDENTITY_ROLES,
    MAX_PERSONAL_SEMANTIC_CONTEXT_CHARS,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.user_identity_profile_parser import parse_profile_text
from app.services.user_serialization_gate import lock_user_serialization_row


def normalize_personal_semantic_context(text: str) -> str:
    if not isinstance(text, str):
        raise ValidationError("context_text is required")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > MAX_PERSONAL_SEMANTIC_CONTEXT_CHARS:
        raise ValidationError(
            f"context_text must be at most {MAX_PERSONAL_SEMANTIC_CONTEXT_CHARS} characters"
        )
    return normalized


def bound_identity_semantic_items(
    values: list[str],
    *,
    max_items: int,
    max_item_chars: int,
) -> tuple[str, ...]:
    bounded: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()[:max_item_chars]
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        bounded.append(normalized)
        if len(bounded) >= max_items:
            break
    return tuple(bounded)


def bound_identity_semantic_projection(
    roles: list[str],
    organizations: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        bound_identity_semantic_items(
            roles,
            max_items=AUTO_LABEL_MAX_IDENTITY_ROLES,
            max_item_chars=AUTO_LABEL_MAX_IDENTITY_ITEM_CHARS,
        ),
        bound_identity_semantic_items(
            organizations,
            max_items=AUTO_LABEL_MAX_IDENTITY_ORGANIZATIONS,
            max_item_chars=AUTO_LABEL_MAX_IDENTITY_ITEM_CHARS,
        ),
    )


@dataclass(frozen=True)
class PersonalSemanticContext:
    context_text: str = ""
    roles: tuple[str, ...] = ()
    organizations: tuple[str, ...] = ()

    def to_classifier_dict(self) -> dict:
        return {
            "context_text": self.context_text,
            "roles": list(self.roles),
            "organizations": list(self.organizations),
        }


def lock_semantic_context_row(session: Session, user_id: UUID) -> UserSemanticContext | None:
    return session.scalar(
        select(UserSemanticContext)
        .where(UserSemanticContext.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_identity_profile_row(session: Session, user_id: UUID) -> UserIdentityProfile | None:
    return session.scalar(
        select(UserIdentityProfile)
        .where(UserIdentityProfile.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def load_personal_semantic_context(
    session: Session,
    user_id: UUID,
    *,
    lock_rows: bool = False,
) -> PersonalSemanticContext:
    if lock_rows:
        ctx_row = lock_semantic_context_row(session, user_id)
        ident = lock_identity_profile_row(session, user_id)
    else:
        ctx_row = session.get(UserSemanticContext, user_id)
        ident = session.get(UserIdentityProfile, user_id)
    context_text = ""
    if ctx_row is not None:
        context_text = (ctx_row.context_text or "")[:MAX_PERSONAL_SEMANTIC_CONTEXT_CHARS]
    roles: tuple[str, ...] = ()
    organizations: tuple[str, ...] = ()
    if ident is not None:
        parsed = parse_profile_text(ident.profile_text)
        roles, organizations = bound_identity_semantic_projection(
            list(parsed.roles),
            list(parsed.organizations),
        )
    return PersonalSemanticContext(
        context_text=context_text,
        roles=roles,
        organizations=organizations,
    )


class PersonalSemanticContextService:
    def __init__(self, session: Session) -> None:
        self._session = session

    @classmethod
    def build(cls, session: Session) -> PersonalSemanticContextService:
        return cls(session)

    def get_context_text(self, user_id: UUID) -> str:
        row = self._session.get(UserSemanticContext, user_id)
        if row is None:
            return ""
        return row.context_text

    def upsert_context(self, user_id: UUID, context_text: str) -> str:
        user = lock_user_serialization_row(self._session, user_id)
        if user is None:
            raise NotFoundError("user", user_id)
        normalized = normalize_personal_semantic_context(context_text)
        row = self._session.get(UserSemanticContext, user_id)
        if row is None:
            row = UserSemanticContext(user_id=user_id, context_text=normalized)
            self._session.add(row)
        else:
            row.context_text = normalized
        self._session.flush()
        return row.context_text
