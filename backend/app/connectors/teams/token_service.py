from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.constants import (
    AUTH_STATUS_RECONNECT_REQUIRED,
    TOKEN_REFRESH_SKEW_SECONDS,
)
from app.connectors.teams.errors import TeamsReconnectRequiredError
from app.connectors.teams.oauth_service import TeamsOAuthService, parse_token_expiry
from app.core.config import settings
from app.db.models import TeamsAccount


def utcnow() -> datetime:
    return datetime.now(UTC)


class TeamsTokenService:
    def __init__(
        self,
        session: Session,
        account_store: TeamsAccountStore,
        oauth_service: TeamsOAuthService | None = None,
        *,
        now_factory=None,
    ) -> None:
        self._session = session
        self._account_store = account_store
        self._oauth_service = oauth_service
        self._now_factory = now_factory or utcnow

    def acquire_access_token(self, account: TeamsAccount) -> str:
        if account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
            raise TeamsReconnectRequiredError("Microsoft Teams reconnect is required")
        now = self._now_factory()
        expiry = account.token_expiry
        if expiry is not None and expiry - timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS) > now:
            return self._account_store.get_access_token(account)
        return self._refresh(account)

    def _refresh(self, account: TeamsAccount) -> str:
        refresh_token = self._account_store.get_refresh_token(account)
        oauth = self._oauth_service or TeamsOAuthService(
            settings.microsoft_oauth_client_id,
            settings.microsoft_oauth_client_secret,
            settings.microsoft_redirect_uri,
        )
        try:
            payload = oauth.refresh_access_token(refresh_token)
        except TeamsReconnectRequiredError:
            self._account_store.mark_reconnect_required(account)
            self._session.commit()
            raise
        access_token = str(payload["access_token"])
        new_refresh = payload.get("refresh_token")
        self._account_store.update_tokens_from_refresh(
            account,
            access_token,
            str(new_refresh) if new_refresh else None,
            parse_token_expiry(payload.get("expires_in")),
        )
        self._session.commit()
        return access_token
