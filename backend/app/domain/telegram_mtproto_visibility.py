"""Query-time visibility for dynamically scoped Telegram MTProto messages."""

from sqlalchemy import cast, exists, or_, select
from sqlalchemy.types import String

from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection


def telegram_mtproto_active_object_predicate(model=Object):
    """Return the fail-closed active-scope predicate for an Object query."""
    active_selection = exists(
        select(TelegramMtprotoChatSelection.id)
        .join(
            TelegramMtprotoAccount,
            TelegramMtprotoAccount.id == TelegramMtprotoChatSelection.account_id,
        )
        .where(
            TelegramMtprotoAccount.user_id == model.user_id,
            TelegramMtprotoChatSelection.scope_active.is_(True),
            cast(TelegramMtprotoAccount.id, String)
            == model.metadata_["account_id"].as_string(),
            cast(TelegramMtprotoChatSelection.peer_id, String)
            == model.metadata_["peer_id"].as_string(),
        )
    )
    return or_(
        model.provider.is_distinct_from("telegram"),
        model.kind.is_distinct_from("chat_message"),
        model.metadata_["transport"].as_string().is_distinct_from("mtproto"),
        active_selection,
    )


def telegram_mtproto_active_sql_fragment(alias: str = "o") -> str:
    """Return the equivalent safe raw-SQL predicate for retrieval candidates."""
    return f"""
    AND (
        {alias}.provider IS DISTINCT FROM 'telegram'
        OR {alias}.kind IS DISTINCT FROM 'chat_message'
        OR {alias}.metadata->>'transport' IS DISTINCT FROM 'mtproto'
        OR EXISTS (
            SELECT 1
            FROM telegram_mtproto_chat_selections mtcs
            INNER JOIN telegram_mtproto_accounts mta
                ON mta.id = mtcs.account_id
            WHERE mta.user_id = {alias}.user_id
              AND mtcs.scope_active IS TRUE
              AND mta.id::text = {alias}.metadata->>'account_id'
              AND mtcs.peer_id::text = {alias}.metadata->>'peer_id'
        )
    )
    """
