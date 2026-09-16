from __future__ import annotations

import argparse
import sys

from app.connectors.telegram.constants import TELEGRAM_ALLOWED_UPDATES
from app.connectors.telegram.errors import TelegramConfigurationError
from app.connectors.telegram.transport import TelegramHttpTransport
from app.connectors.telegram.webhook_service import telegram_is_configured
from app.core.config import settings


def configure_webhook(transport: TelegramHttpTransport | None = None) -> int:
    if not telegram_is_configured():
        print("telegram webhook is not fully configured", file=sys.stderr)
        return 1
    expected_username = settings.telegram_bot_username.strip().lstrip("@")
    owns_transport = transport is None
    client = transport or TelegramHttpTransport(settings.telegram_bot_token)
    try:
        me = client.get_me()
        username = str(me.get("username") or "").strip().lstrip("@")
        if username.lower() != expected_username.lower():
            print("configured telegram bot username does not match getMe", file=sys.stderr)
            return 1
        can_connect = me.get("can_connect_to_business")
        if can_connect is False:
            print("telegram bot cannot connect to Business/Secretary Mode", file=sys.stderr)
            return 1
        client.set_webhook(
            url=settings.telegram_webhook_url.strip(),
            secret_token=settings.telegram_webhook_secret.strip(),
            allowed_updates=TELEGRAM_ALLOWED_UPDATES,
        )
        print(f"telegram webhook configured for @{username}")
        return 0
    except TelegramConfigurationError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    finally:
        if owns_transport:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configure the Telegram Bot API webhook")
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure", help="Call getMe and setWebhook once")
    configure.set_defaults(func=lambda _args: configure_webhook())
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
