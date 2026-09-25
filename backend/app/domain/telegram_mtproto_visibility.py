"""Query-time visibility for dynamically scoped Telegram MTProto messages."""

from sqlalchemy import and_, cast, exists, or_, select
from sqlalchemy.types import String

from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection


def _owned_selection(model=Object):
    return exists(
        select(TelegramMtprotoChatSelection.id)
        .join(
            TelegramMtprotoAccount,
            TelegramMtprotoAccount.id == TelegramMtprotoChatSelection.account_id,
        )
        .where(
            TelegramMtprotoAccount.user_id == model.user_id,
            or_(
                TelegramMtprotoChatSelection.scope_active.is_(True),
                TelegramMtprotoChatSelection.manual_selected.is_(True),
            ),
            cast(TelegramMtprotoAccount.id, String) == model.metadata_["account_id"].as_string(),
            cast(TelegramMtprotoChatSelection.peer_id, String)
            == model.metadata_["peer_id"].as_string(),
        )
    )


def telegram_media_file_excluded(model=Object):
    """Telegram file children are canonical media, not model-visible messages."""
    return or_(
        model.provider.is_distinct_from("telegram"),
        model.kind.is_distinct_from("file"),
    )


def telegram_media_file_sql(alias: str) -> str:
    return (
        f"({alias}.provider IS DISTINCT FROM 'telegram' "
        f"OR {alias}.kind IS DISTINCT FROM 'file')"
    )


def telegram_mtproto_active_object_predicate(model=Object):
    """Return ordinary visibility for an owned manual or scoped selection."""
    return and_(
        telegram_media_file_excluded(model),
        or_(
        model.provider.is_distinct_from("telegram"),
        model.kind.is_distinct_from("chat_message"),
        model.metadata_["transport"].as_string().is_distinct_from("mtproto"),
        _owned_selection(model),
        ),
    )


def telegram_mtproto_scope_object_predicate(model=Object):
    """Return the fail-closed scope-only predicate used by AI policy."""
    scoped_selection = exists(
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
        )
    )
    return and_(
        telegram_media_file_excluded(model),
        or_(
            model.provider.is_distinct_from("telegram"),
            model.kind.is_distinct_from("chat_message"),
            model.metadata_["transport"].as_string().is_distinct_from("mtproto"),
            scoped_selection,
        ),
    )


def telegram_mtproto_active_sql_fragment(alias: str = "o") -> str:
    """Return ordinary visibility for raw-SQL candidate queries."""
    return f"""
    AND {telegram_media_file_sql(alias)}
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
              AND (mtcs.scope_active IS TRUE OR mtcs.manual_selected IS TRUE)
              AND mta.id::text = {alias}.metadata->>'account_id'
              AND mtcs.peer_id::text = {alias}.metadata->>'peer_id'
        )
    )
    """


def telegram_mtproto_scope_sql_fragment(alias: str = "o") -> str:
    """Return the scope-only raw-SQL predicate used by AI retrieval."""
    return f"""
    AND {telegram_media_file_sql(alias)}
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
