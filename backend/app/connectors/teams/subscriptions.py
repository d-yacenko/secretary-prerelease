"""Microsoft Graph change-notification subscription lifecycle."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.constants import AUTH_STATUS_RECONNECT_REQUIRED
from app.connectors.teams.errors import TeamsConnectorError, TeamsSubscriptionNotFoundError
from app.connectors.teams.normalize import parse_graph_datetime
from app.connectors.teams.transport import TeamsTransport
from app.db.models import TeamsAccount, TeamsSubscription

SUBSCRIPTION_RESOURCE_TEMPLATE = "/users/{user_id}/chats/getAllMessages"
SUBSCRIPTION_LIFETIME = timedelta(minutes=55)
SUBSCRIPTION_RENEWAL_WINDOW = timedelta(minutes=15)
STATUS_ACTIVE = "active"
STATUS_REAUTHORIZATION_REQUIRED = "reauthorization_required"
STATUS_REMOVED = "removed"
logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TeamsSubscriptionService:
    def __init__(self, session: Session, account_store: TeamsAccountStore) -> None:
        self._session = session
        self._account_store = account_store

    @staticmethod
    def resource_for(account: TeamsAccount) -> str:
        return SUBSCRIPTION_RESOURCE_TEMPLATE.format(user_id=account.microsoft_user_id)

    def ensure(
        self,
        account: TeamsAccount,
        transport: TeamsTransport,
        *,
        notification_url: str,
        now: datetime | None = None,
    ) -> TeamsSubscription | None:
        if not notification_url.strip() or account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
            return None
        now = now or utcnow()
        existing = self.get_for_account(account.id)
        if existing is None:
            return self._create(account, transport, notification_url, now)
        force_renew = existing.status == STATUS_REAUTHORIZATION_REQUIRED
        if existing.status == STATUS_ACTIVE or force_renew:
            if not force_renew and existing.expires_at > now + SUBSCRIPTION_RENEWAL_WINDOW:
                return existing
            try:
                return self._renew(account, existing, transport, notification_url, now)
            except TeamsSubscriptionNotFoundError:
                self._session.delete(existing)
                self._session.flush()
                return self._create(account, transport, notification_url, now)
        self._session.delete(existing)
        self._session.flush()
        return self._create(account, transport, notification_url, now)

    def _create(
        self,
        account: TeamsAccount,
        transport: TeamsTransport,
        notification_url: str,
        now: datetime,
    ) -> TeamsSubscription:
        client_state = secrets.token_urlsafe(32)
        expires_at = now + SUBSCRIPTION_LIFETIME
        resource = self.resource_for(account)
        payload = {
            "changeType": "created,updated",
            "notificationUrl": notification_url,
            "lifecycleNotificationUrl": notification_url,
            "resource": resource,
            "includeResourceData": False,
            "expirationDateTime": expires_at.isoformat().replace("+00:00", "Z"),
            "clientState": client_state,
        }
        remote = transport.create_subscription(payload)
        subscription_id = str(remote.get("id") or "").strip()
        remote_resource = str(remote.get("resource") or resource).strip()
        remote_expiry = parse_graph_datetime(remote.get("expirationDateTime")) or expires_at
        if not subscription_id or remote_resource != resource:
            raise TeamsConnectorError("Microsoft Graph subscription response malformed")
        row = TeamsSubscription(
            account_id=account.id,
            user_id=account.user_id,
            subscription_id=subscription_id,
            resource=resource,
            expires_at=remote_expiry,
            client_state_encrypted=self._account_store.encrypt_secret(client_state),
            status=STATUS_ACTIVE,
            last_renewed_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def _renew(
        self,
        account: TeamsAccount,
        row: TeamsSubscription,
        transport: TeamsTransport,
        notification_url: str,
        now: datetime,
    ) -> TeamsSubscription:
        expires_at = now + SUBSCRIPTION_LIFETIME
        remote = transport.renew_subscription(
            row.subscription_id,
            {
                "expirationDateTime": expires_at.isoformat().replace("+00:00", "Z"),
                "notificationUrl": notification_url,
            },
        )
        row.expires_at = parse_graph_datetime(remote.get("expirationDateTime")) or expires_at
        row.status = STATUS_ACTIVE
        row.last_renewed_at = now
        self._session.flush()
        return row

    def get_for_account(self, account_id: UUID) -> TeamsSubscription | None:
        return self._session.scalar(
            select(TeamsSubscription).where(TeamsSubscription.account_id == account_id)
        )

    def find_validated(self, subscription_id: str) -> tuple[TeamsSubscription, TeamsAccount] | None:
        row = self._session.scalar(
            select(TeamsSubscription).where(TeamsSubscription.subscription_id == subscription_id)
        )
        if row is None:
            return None
        account = self._session.get(TeamsAccount, row.account_id)
        if account is None or row.status not in {STATUS_ACTIVE, STATUS_REAUTHORIZATION_REQUIRED}:
            return None
        return row, account

    def client_state_matches(self, row: TeamsSubscription, supplied: str | None) -> bool:
        if not supplied:
            return False
        expected = self._account_store.decrypt_secret(row.client_state_encrypted)
        return compare_digest(expected, supplied)

    def delete_for_account(
        self, account: TeamsAccount, transport: TeamsTransport | None = None
    ) -> None:
        row = self.get_for_account(account.id)
        if row is None:
            return
        if transport is not None:
            try:
                transport.delete_subscription(row.subscription_id)
            except Exception:  # noqa: BLE001
                logger.info("Teams subscription cleanup could not reach Graph")
        self._session.delete(row)
        self._session.flush()
