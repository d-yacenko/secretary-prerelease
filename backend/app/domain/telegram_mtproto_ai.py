"""AI eligibility policy for Telegram MTProto message objects."""

from sqlalchemy import and_, cast, exists, or_, select
from sqlalchemy.types import String

from app.connectors.telegram.constants import TELEGRAM_KIND, TELEGRAM_PROVIDER
from app.core.config import settings
from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.domain.telegram_mtproto_visibility import (
    telegram_media_file_excluded,
    telegram_media_file_sql,
    telegram_mtproto_scope_object_predicate,
    telegram_mtproto_scope_sql_fragment,
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


def _self_authored_scope_exists(model=Object):
    """Owned active-scope outbound message authored by the connected Telegram user."""
    sender = model.metadata_["sender_peer_id"].as_string()
    return exists(
        select(TelegramMtprotoChatSelection.id)
        .join(
            TelegramMtprotoAccount,
            TelegramMtprotoAccount.id == TelegramMtprotoChatSelection.account_id,
        )
        .where(
            TelegramMtprotoAccount.user_id == model.user_id,
            TelegramMtprotoChatSelection.scope_active.is_(True),
            cast(TelegramMtprotoAccount.id, String) == model.metadata_["account_id"].as_string(),
            cast(TelegramMtprotoChatSelection.peer_id, String)
            == model.metadata_["peer_id"].as_string(),
            model.metadata_["direction"].as_string() == "outbound",
            sender.is_not(None),
            sender != "",
            TelegramMtprotoAccount.telegram_user_id.is_not(None),
            cast(TelegramMtprotoAccount.telegram_user_id, String) == sender,
        )
    )


def telegram_mtproto_ai_predicate(model=Object):
    """Return the AI-only gate; transport visibility remains a separate policy."""
    if not settings.telegram_mtproto_ai_enabled:
        return and_(
            telegram_media_file_excluded(model),
            or_(
                model.provider.is_distinct_from(TELEGRAM_PROVIDER),
                and_(
                    model.kind == TELEGRAM_KIND,
                    model.metadata_["transport"].as_string().is_not_distinct_from("mtproto"),
                    _self_authored_scope_exists(model),
                ),
            ),
        )
    return telegram_mtproto_scope_object_predicate(model)


def telegram_mtproto_ai_sql_fragment(alias: str = "o") -> str:
    """Return the raw-SQL equivalent used by retrieval candidate queries."""
    if settings.telegram_mtproto_ai_enabled:
        return telegram_mtproto_scope_sql_fragment(alias)
    return f"""
    AND {telegram_media_file_sql(alias)}
    AND (
        {alias}.provider IS DISTINCT FROM 'telegram'
        OR (
            {alias}.kind IS NOT DISTINCT FROM 'chat_message'
            AND {alias}.metadata->>'transport' IS NOT DISTINCT FROM 'mtproto'
            AND EXISTS (
            SELECT 1
            FROM telegram_mtproto_chat_selections mtcs
            INNER JOIN telegram_mtproto_accounts mta
                ON mta.id = mtcs.account_id
            WHERE mta.user_id = {alias}.user_id
              AND mtcs.scope_active IS TRUE
              AND mta.id::text = {alias}.metadata->>'account_id'
              AND mtcs.peer_id::text = {alias}.metadata->>'peer_id'
              AND {alias}.metadata->>'direction' = 'outbound'
              AND NULLIF({alias}.metadata->>'sender_peer_id', '') IS NOT NULL
              AND mta.telegram_user_id IS NOT NULL
              AND mta.telegram_user_id::text = {alias}.metadata->>'sender_peer_id'
            )
        )
    )
    """


def telegram_mtproto_ai_eligible(session, obj: Object) -> bool:
    """Check one object against the current AI flag and owned active scope."""
    if not settings.telegram_mtproto_ai_enabled:
        if obj.provider != TELEGRAM_PROVIDER:
            return True
    elif not is_canonical_telegram_mtproto_object(obj):
        return True
    return (
        session.scalar(
            select(Object.id).where(
                Object.id == obj.id,
                Object.user_id == obj.user_id,
                telegram_mtproto_ai_predicate(),
            )
        )
        is not None
    )
