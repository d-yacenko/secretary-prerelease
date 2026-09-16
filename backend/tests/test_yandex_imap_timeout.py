import imaplib

from app.connectors.yandex.constants import DEFAULT_IMAP_TIMEOUT_SECONDS
from app.connectors.yandex.imap_transport import ImaplibTransport


def test_imap_ssl_connect_uses_bounded_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeImap:
        def __init__(self, host, port, timeout=None):
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def login(self, email, password) -> None:
            captured["login"] = (email, password)

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeImap)
    transport = ImaplibTransport("imap.example", 993, "user@example", "secret")
    imap = transport._connect()
    assert isinstance(imap, FakeImap)
    assert captured["timeout"] == DEFAULT_IMAP_TIMEOUT_SECONDS
    assert captured["timeout"] == 30
    assert captured["login"] == ("user@example", "secret")
