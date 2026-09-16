from __future__ import annotations

import smtplib
import ssl
import threading
from typing import Protocol

from app.connectors.yandex.constants import DEFAULT_SMTP_HOST, DEFAULT_SMTP_PORT
from app.connectors.yandex.errors import YandexSmtpError

_SECRET_TOKENS = ("password", "app_password", "app-password", "secret", "token")


def _bounded_smtp_error(exc: BaseException) -> str:
    message = str(exc).strip() or type(exc).__name__
    lowered = message.lower()
    if any(token in lowered for token in _SECRET_TOKENS):
        return "Yandex SMTP request failed"
    return message[:500]


class SmtpTransport(Protocol):
    def send_rfc822(self, *, from_addr: str, to_addrs: list[str], message_bytes: bytes) -> None:
        ...


class SmtpSslTransport:
    def __init__(
        self,
        host: str = DEFAULT_SMTP_HOST,
        port: int = DEFAULT_SMTP_PORT,
        email: str = "",
        password: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._email = email
        self._password = password

    def send_rfc822(self, *, from_addr: str, to_addrs: list[str], message_bytes: bytes) -> None:
        context = ssl.create_default_context()
        try:
            with smtplib.SMTP_SSL(self._host, self._port, context=context, timeout=30) as client:
                client.login(self._email, self._password)
                client.sendmail(from_addr, to_addrs, message_bytes)
        except smtplib.SMTPResponseException as exc:
            retryable = 400 <= int(exc.smtp_code) < 500
            raise YandexSmtpError(_bounded_smtp_error(exc), retryable=retryable) from exc
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            raise YandexSmtpError(_bounded_smtp_error(exc), retryable=True) from exc


class FakeSmtpTransport:
    def __init__(self, imap=None, sent_folder: str | None = None) -> None:
        self.send_calls: list[dict[str, object]] = []
        self.persist_on_send = True
        self.lose_send_response = False
        self.send_error: YandexSmtpError | None = None
        self.sent_messages: list[bytes] = []
        self.before_send = None
        self._imap = imap
        self._sent_folder = sent_folder
        self.strip_operation_header = False
        self.field_overrides: dict[str, str] | None = None
        self.also_store_tagged_clone = False
        self.force_incomplete_listing = False
        self.lock = threading.Lock()

    def send_rfc822(self, *, from_addr: str, to_addrs: list[str], message_bytes: bytes) -> None:
        if self.before_send is not None:
            self.before_send()
        payload = message_bytes
        if self.strip_operation_header or self.field_overrides:
            from email.parser import BytesParser
            from email.policy import default as email_default_policy

            parsed = BytesParser(policy=email_default_policy).parsebytes(message_bytes)
            if self.strip_operation_header:
                del parsed["X-Secretary-Operation-ID"]
            if self.field_overrides:
                for name, value in self.field_overrides.items():
                    if name in parsed:
                        parsed.replace_header(name, value)
                    else:
                        parsed[name] = value
            payload = parsed.as_bytes()
        self.send_calls.append(
            {"from_addr": from_addr, "to_addrs": list(to_addrs), "message_bytes": payload}
        )
        self.sent_messages.append(payload)
        if self.lose_send_response:
            self.lose_send_response = False
            raise YandexSmtpError("lost SMTP response", retryable=True)
        if self.send_error is not None:
            raise self.send_error
