from app.core.config import settings


def teams_is_configured() -> bool:
    return bool(
        settings.microsoft_oauth_client_id.strip()
        and settings.microsoft_oauth_client_secret.strip()
        and settings.microsoft_redirect_uri.strip()
        and settings.secretary_credential_key.strip()
    )
