import json
from pathlib import Path
from typing import Any

from app.connectors.google.errors import GoogleConfigurationError


def load_oauth_client_config(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.is_file():
        raise GoogleConfigurationError("Google OAuth client file is missing")

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise GoogleConfigurationError("Google OAuth client file is malformed") from None

    web = payload.get("web")
    if not isinstance(web, dict):
        raise GoogleConfigurationError("Google OAuth client file is missing web configuration")

    client_id = web.get("client_id")
    client_secret = web.get("client_secret")
    if not client_id or not client_secret:
        raise GoogleConfigurationError("Google OAuth client file is missing required fields")

    return {
        "client_id": str(client_id),
        "client_secret": str(client_secret),
        "auth_uri": str(web.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")),
        "token_uri": str(web.get("token_uri", "https://oauth2.googleapis.com/token")),
    }
