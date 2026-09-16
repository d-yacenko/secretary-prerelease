"""Classify Google Drive files.get metadata failures for explicit link intake."""

import logging

from app.connectors.google.errors import GoogleApiError, GoogleConfigurationError
from app.services.explicit_link_intake_errors import ExplicitLinkIntakeError

logger = logging.getLogger(__name__)

_DEPLOYMENT_CONFIG_REASONS = frozenset(
    {
        "accessNotConfigured",
        "notConfigured",
        "serviceDisabled",
    }
)

_AUTH_REASONS = frozenset(
    {
        "authError",
        "insufficientPermissions",
    }
)

_AUTH_API_STATUSES = frozenset(
    {
        "UNAUTHENTICATED",
    }
)

_DEPLOYMENT_CONFIG_MESSAGE = "google drive api is not enabled for this deployment"


def log_drive_metadata_error(exc: GoogleApiError) -> None:
    logger.warning(
        "%s: status=%s reason=%s api_status=%s",
        exc.operation or "get_file_metadata",
        exc.status_code,
        exc.reason or "",
        exc.api_status or "",
    )


def raise_for_drive_metadata_error(exc: GoogleApiError) -> None:
    log_drive_metadata_error(exc)
    status_code = exc.status_code
    reason = (exc.reason or "").strip()
    api_status = (exc.api_status or "").strip()

    if status_code == 404 or reason == "notFound" or api_status == "NOT_FOUND":
        raise ExplicitLinkIntakeError("google drive resource unavailable") from exc

    if (
        status_code == 401
        or reason in _AUTH_REASONS
        or api_status in _AUTH_API_STATUSES
    ):
        raise ExplicitLinkIntakeError(
            "google drive authorization requires reconnect"
        ) from exc

    if status_code == 403:
        if reason in _DEPLOYMENT_CONFIG_REASONS:
            raise GoogleConfigurationError(_DEPLOYMENT_CONFIG_MESSAGE) from exc
        if reason == "domainPolicy":
            raise ExplicitLinkIntakeError(
                "google drive access blocked by organization policy"
            ) from exc
        if exc.retryable:
            raise exc
        raise ExplicitLinkIntakeError("google drive resource permission denied") from exc

    raise exc
