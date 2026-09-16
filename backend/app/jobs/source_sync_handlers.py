from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.google.calendar_sync import build_calendar_sync_service
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.connectors.mattermost.sync import build_mattermost_sync_service
from app.connectors.teams.account_store import TeamsAccountStore
from app.connectors.teams.constants import AUTH_STATUS_RECONNECT_REQUIRED
from app.connectors.teams.notifications import process_graph_notification
from app.connectors.teams.sync import build_teams_sync_service
from app.connectors.yandex.calendar_sync import build_yandex_calendar_sync_service
from app.connectors.yandex.mail_sync import build_yandex_mail_sync_service
from app.core.config import settings
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.source_sync.constants import (
    SOURCE_GMAIL,
    SOURCE_GOOGLE_CALENDAR,
    SOURCE_MATTERMOST,
    SOURCE_YANDEX_CALENDAR,
    SOURCE_YANDEX_MAIL,
)


def _gmail_sync_service(session: Session, user_id: UUID):
    history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
        user_id,
        SOURCE_GMAIL,
    )
    return build_gmail_sync_service(
        session=session,
        credential_key=settings.secretary_credential_key,
        client_file=settings.google_oauth_client_file,
        redirect_uri=settings.google_redirect_uri,
        sync_days=history_days,
        default_limit=settings.gmail_sync_default_limit,
        max_limit=settings.gmail_sync_max_limit,
    )


def _google_calendar_sync_service(session: Session, user_id: UUID):
    history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
        user_id,
        SOURCE_GOOGLE_CALENDAR,
    )
    return build_calendar_sync_service(
        session=session,
        credential_key=settings.secretary_credential_key,
        client_file=settings.google_oauth_client_file,
        redirect_uri=settings.google_redirect_uri,
        days_back=history_days,
        days_forward=settings.calendar_sync_days_forward,
        default_limit=settings.calendar_sync_default_limit,
        max_limit=settings.calendar_sync_max_limit,
        max_calendars=settings.calendar_sync_max_calendars,
    )


def _yandex_mail_sync_service(session: Session, user_id: UUID):
    history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
        user_id,
        SOURCE_YANDEX_MAIL,
    )
    return build_yandex_mail_sync_service(
        session=session,
        credential_key=settings.secretary_credential_key,
        sync_days=history_days,
        default_limit=settings.yandex_mail_sync_default_limit,
        max_limit=settings.yandex_mail_sync_max_limit,
    )


def _yandex_calendar_sync_service(session: Session, user_id: UUID):
    history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
        user_id,
        SOURCE_YANDEX_CALENDAR,
    )
    return build_yandex_calendar_sync_service(
        session=session,
        credential_key=settings.secretary_credential_key,
        days_back=history_days,
        days_forward=settings.calendar_sync_days_forward,
        default_limit=settings.calendar_sync_default_limit,
        max_limit=settings.calendar_sync_max_limit,
        max_calendars=settings.calendar_sync_max_calendars,
    )


def _mattermost_sync_service(session: Session, user_id: UUID):
    history_days = SourceSyncPreferenceService.build(session).effective_history_days_for_source(
        user_id,
        SOURCE_MATTERMOST,
    )
    return build_mattermost_sync_service(
        session=session,
        credential_key=settings.secretary_credential_key,
        sync_days=history_days,
        max_channels=settings.mattermost_sync_max_channels,
        initial_posts_per_channel=settings.mattermost_sync_initial_posts_per_channel,
        max_posts_per_run=settings.mattermost_sync_max_posts_per_run,
        overlap_seconds=settings.mattermost_sync_overlap_seconds,
    )


def _teams_sync_service(session: Session, _user_id: UUID):
    return build_teams_sync_service(
        session,
        credential_key=settings.secretary_credential_key,
    )


def handle_sync_google_gmail(
    session: Session,
    _embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    account_id = UUID(str(payload["account_id"]))
    _gmail_sync_service(session, user_id).sync_account(
        account_id,
        user_id=user_id,
        include_history_pass=True,
    )


def handle_sync_google_calendar(
    session: Session,
    _embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    account_id = UUID(str(payload["account_id"]))
    _google_calendar_sync_service(session, user_id).sync_account(
        account_id,
        user_id=user_id,
        include_history_pass=True,
    )


def handle_sync_yandex_mail(
    session: Session,
    _embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    account_id = UUID(str(payload["account_id"]))
    _yandex_mail_sync_service(session, user_id).sync_account(
        account_id,
        user_id=user_id,
        include_history_pass=True,
    )


def handle_sync_yandex_calendar(
    session: Session,
    _embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    account_id = UUID(str(payload["account_id"]))
    _yandex_calendar_sync_service(session, user_id).sync_account(
        account_id,
        user_id=user_id,
        include_history_pass=True,
    )


def handle_sync_mattermost(
    session: Session,
    _embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    account_id = UUID(str(payload["account_id"]))
    _mattermost_sync_service(session, user_id).sync_account(
        account_id,
        user_id=user_id,
        include_history_pass=True,
    )


def handle_sync_teams(
    session: Session,
    _embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    account_id = UUID(str(payload["account_id"]))
    if not settings.secretary_credential_key:
        return
    store = TeamsAccountStore(
        session,
        TeamsAccountStore.build_encryption(settings.secretary_credential_key),
    )
    account = store.get_by_id_for_user(account_id, user_id)
    if account is None or account.auth_status == AUTH_STATUS_RECONNECT_REQUIRED:
        return
    _teams_sync_service(session, user_id).sync_account(account_id, user_id=user_id)


def handle_process_teams_notification(
    session: Session,
    _embedding_service,
    payload: dict,
    user_id: UUID,
) -> None:
    process_graph_notification(session, payload, user_id)
