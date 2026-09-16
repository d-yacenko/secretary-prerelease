"""Validation and targeted processing for Microsoft Graph chat notifications."""

import re
from contextlib import nullcontext
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.constants import AUTH_STATUS_RECONNECT_REQUIRED
from app.connectors.teams.errors import TeamsSecurityError
from app.connectors.teams.materialize import TeamsMaterializeResult, TeamsObjectMaterializer
from app.connectors.teams.normalize import accepted_chat_type, display_title_for_chat
from app.connectors.teams.subscriptions import (
    STATUS_REAUTHORIZATION_REQUIRED,
    STATUS_REMOVED,
    TeamsSubscriptionService,
)
from app.connectors.teams.token_service import TeamsTokenService
from app.connectors.teams.transport import TeamsHttpTransport, TeamsTransport
from app.core.config import settings
from app.jobs.constants import JOB_TYPE_PROCESS_TEAMS_NOTIFICATION, JOB_TYPE_SYNC_TEAMS
from app.services.job_queue_service import JobQueueService

_RESOURCE_RE = re.compile(
    r"^(?:/)?(?:users/([^/]+)/)?chats\('([^/'\"]+)'\)/messages\('([^/'\"]+)'\)$",
    re.IGNORECASE,
)
_ACCEPTED_CHANGE_TYPES = frozenset({"created", "updated"})


def parse_chat_message_resource(resource: object) -> tuple[str | None, str, str] | None:
    if not isinstance(resource, str):
        return None
    match = _RESOURCE_RE.fullmatch(resource.strip())
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3)


def enqueue_graph_notifications(session: Session, payload: object) -> int:
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        return 0
    queued = 0
    seen_in_batch: set[tuple[str, str, str, str]] = set()
    jobs = JobQueueService(session)
    for notification in payload["value"]:
        if not isinstance(notification, dict):
            continue
        subscription_id = str(notification.get("subscriptionId") or "").strip()
        if not subscription_id:
            continue
        store = TeamsAccountStore(
            session,
            TeamsAccountStore.build_encryption(settings.secretary_credential_key),
        )
        subscriptions = TeamsSubscriptionService(session, store)
        found = subscriptions.find_validated(subscription_id)
        if found is None:
            continue
        row, account = found
        if not subscriptions.client_state_matches(row, notification.get("clientState")):
            continue
        tenant_id = notification.get("tenantId")
        if tenant_id is not None and str(tenant_id).lower() != account.tenant_id.lower():
            continue
        lifecycle = str(notification.get("lifecycleEvent") or "").strip()
        if lifecycle in {"missed", "reauthorizationRequired", "subscriptionRemoved"}:
            if lifecycle == "subscriptionRemoved":
                row.status = STATUS_REMOVED
            elif lifecycle == "reauthorizationRequired":
                row.status = STATUS_REAUTHORIZATION_REQUIRED
            jobs.trigger_recurring_source_job(
                account.user_id,
                JOB_TYPE_SYNC_TEAMS,
                account.id,
            )
            queued += 1
            continue
        change_type = _sanitized_change_type(notification.get("changeType"))
        if change_type is None:
            continue
        resource = notification.get("resource")
        parsed = parse_chat_message_resource(resource)
        if parsed is None:
            continue
        user_id, chat_id, message_id = parsed
        if user_id is not None and user_id.lower() != account.microsoft_user_id.lower():
            continue
        expected_resource = subscriptions.resource_for(account)
        if row.resource != expected_resource:
            continue
        batch_key = (subscription_id, chat_id, message_id, change_type)
        if batch_key in seen_in_batch:
            continue
        seen_in_batch.add(batch_key)
        jobs.enqueue(
            JOB_TYPE_PROCESS_TEAMS_NOTIFICATION,
            {
                "account_id": str(account.id),
                "subscription_id": subscription_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "change_type": change_type,
            },
            account.user_id,
        )
        queued += 1
    return queued


def _sanitized_change_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    change_type = value.strip().lower()
    if change_type not in _ACCEPTED_CHANGE_TYPES:
        return None
    return change_type


def process_graph_notification(
    session: Session,
    payload: dict[str, Any],
    user_id: UUID,
    *,
    transport: TeamsTransport | None = None,
) -> TeamsMaterializeResult | None:
    account_id = UUID(str(payload["account_id"]))
    account_store = TeamsAccountStore(
        session,
        TeamsAccountStore.build_encryption(settings.secretary_credential_key),
    )
    account = account_store.get_by_id_for_user(account_id, user_id)
    if account is None or account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
        return None
    subscriptions = TeamsSubscriptionService(session, account_store)
    row = subscriptions.get_for_account(account.id)
    if row is None or row.subscription_id != str(payload["subscription_id"]):
        return None
    if row.resource != subscriptions.resource_for(account):
        raise TeamsSecurityError("Teams subscription resource mismatch")
    chat_id = str(payload["chat_id"])
    message_id = str(payload["message_id"])
    owned_transport = None
    if transport is None:
        token_service = TeamsTokenService(session, account_store)
        token = token_service.acquire_access_token(account)
        owned_transport = TeamsHttpTransport(token)
    with (owned_transport if owned_transport is not None else nullcontext(transport)) as graph:
        assert graph is not None
        state = dict(account.sync_state or {})
        chats_state = dict(state.get("chats") or {})
        cached = chats_state.get(chat_id)
        if isinstance(cached, dict) and accepted_chat_type({"chatType": cached.get("chat_type")}):
            chat_type = str(cached["chat_type"])
            title = str(cached.get("display_title") or "") or None
        else:
            chat = graph.get_chat(chat_id)
            chat_type = accepted_chat_type(chat)
            if chat_type is None:
                return None
            title = display_title_for_chat(chat, self_user_id=account.microsoft_user_id)
            chats_state[chat_id] = {
                **(cached if isinstance(cached, dict) else {}),
                "chat_type": chat_type,
                "display_title": title,
            }
            account.sync_state = {**state, "chats": chats_state}
        message = graph.get_chat_message(chat_id, message_id)
    return TeamsObjectMaterializer(session).upsert_message(
        user_id=account.user_id,
        account_id=account.id,
        tenant_id=account.tenant_id,
        microsoft_user_id=account.microsoft_user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        chat_display_title=title,
        message=message,
    )
