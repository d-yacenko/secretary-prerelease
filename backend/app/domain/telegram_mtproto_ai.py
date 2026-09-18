"""AI eligibility policy for Telegram MTProto message objects."""

from sqlalchemy import and_, not_, select

from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.core.config import settings
from app.db.models import Object
from app.domain.telegram_mtproto_visibility import (
    telegram_mtproto_active_object_predicate,
    telegram_mtproto_active_sql_fragment,
)


def is_canonical_telegram_mtproto_object(obj: Object) -> bool:
    metadata = obj.metadata_ or {}
    return (
        obj.provider == TELEGRAM_PROVIDER
        and obj.kind == TELEGRAM_KIND
        and metadata.get("transport") == "mtproto"
    )


def telegram_mtproto_ai_enabled() -> bool:
    return settings.telegram_mtproto_ai_enabled


def telegram_mtproto_ai_predicate(model=Object):
    """Return the AI-only gate; transport visibility remains a separate policy."""
    canonical = and_(
        model.provider == TELEGRAM_PROVIDER,
        model.kind == TELEGRAM_KIND,
        model.metadata_["transport"].as_string().is_not_distinct_from("mtproto"),
    )
    if not settings.telegram_mtproto_ai_enabled:
        return not_(canonical)
    return telegram_mtproto_active_object_predicate(model)


def telegram_mtproto_ai_sql_fragment(alias: str = "o") -> str:
    """Return the raw-SQL equivalent used by retrieval candidate queries."""
    if settings.telegram_mtproto_ai_enabled:
        return telegram_mtproto_active_sql_fragment(alias)
    return f"""
    AND (
        {alias}.provider IS DISTINCT FROM 'telegram'
        OR {alias}.kind IS DISTINCT FROM 'chat_message'
        OR {alias}.metadata->>'transport' IS DISTINCT FROM 'mtproto'
    )
    """


def telegram_mtproto_ai_eligible(session, obj: Object) -> bool:
    """Check one object against the current AI flag and owned active scope."""
    if not is_canonical_telegram_mtproto_object(obj):
        return True
    if not settings.telegram_mtproto_ai_enabled:
        return False
    return session.scalar(
        select(Object.id).where(
            Object.id == obj.id,
            Object.user_id == obj.user_id,
            telegram_mtproto_ai_predicate(),
        )
    ) is not None
