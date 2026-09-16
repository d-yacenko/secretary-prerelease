import socket
from unittest.mock import patch

import httpx
import pytest

from app.resources.web_fetch import WebFetchError, _validate_url_target, fetch_web_page

_REAL_HTTPX_CLIENT = httpx.Client


def _public_addrinfo(host: str, *args, **kwargs):
    if host == "example.com":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    if host == "redirect.test":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    raise socket.gaierror


def _private_addrinfo(host: str, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_url_blocks_literal_localhost(_mock_resolve: object) -> None:
    with pytest.raises(WebFetchError, match="not allowed"):
        _validate_url_target("http://127.0.0.1/page")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_url_blocks_literal_private_ip(_mock_resolve: object) -> None:
    with pytest.raises(WebFetchError, match="not allowed"):
        _validate_url_target("http://192.168.1.10/page")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_private_addrinfo)
def test_web_url_blocks_hostname_resolving_to_private_ip(_mock_resolve: object) -> None:
    with pytest.raises(WebFetchError, match="not allowed"):
        _validate_url_target("http://evil.example/page")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_url_rejects_userinfo_username(_mock_resolve: object) -> None:
    with pytest.raises(WebFetchError, match="credentials are not allowed"):
        _validate_url_target("https://user@example.com/page")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_url_rejects_userinfo_username_and_password(_mock_resolve: object) -> None:
    with pytest.raises(WebFetchError, match="credentials are not allowed"):
        _validate_url_target("https://user:password@example.com/page")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_url_accepts_ordinary_https(_mock_resolve: object) -> None:
    assert _validate_url_target("https://example.com/page") == "https://example.com/page"


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_fetch_rejects_initial_userinfo_before_http(_mock_resolve: object) -> None:
    with patch("app.resources.web_fetch.httpx.Client") as mock_client:
        with pytest.raises(WebFetchError, match="credentials are not allowed"):
            fetch_web_page("https://user@example.com/page")
        mock_client.assert_not_called()


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_fetch_rejects_redirect_to_userinfo_target(_mock_resolve: object) -> None:
    requests_made: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"Location": "http://user:pass@redirect.test/secret"},
            )
        return httpx.Response(200, text="<html><body>unexpected</body></html>")

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ), pytest.raises(WebFetchError, match="credentials are not allowed"):
        fetch_web_page("http://redirect.test/start")
    assert len(requests_made) == 1


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_fetch_blocks_redirect_to_private_target(_mock_resolve: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "http://192.168.0.1/secret"})
        return httpx.Response(200, text="<html><body>unexpected</body></html>")

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ), pytest.raises(WebFetchError, match="not allowed"):
        fetch_web_page("http://redirect.test/start")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_fetch_accepts_safe_public_redirect(_mock_resolve: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"})
        if request.url.path == "/final":
            return httpx.Response(
                200,
                text="<html><title>Final</title><body>safe content</body></html>",
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ):
        result = fetch_web_page("http://redirect.test/start")
    assert result.title == "Final"
    assert "safe content" in result.text
    assert result.final_url.endswith("/final")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_fetch_redirect_loop_or_cap_raises(_mock_resolve: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/loop"})

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ), pytest.raises(WebFetchError, match="redirect limit exceeded"):
        fetch_web_page("http://redirect.test/loop")


@patch("app.resources.web_fetch.socket.getaddrinfo", side_effect=_public_addrinfo)
def test_web_fetch_wraps_request_errors(_mock_resolve: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    with patch(
        "app.resources.web_fetch.httpx.Client",
        side_effect=lambda *args, **kwargs: _REAL_HTTPX_CLIENT(
            transport=transport, follow_redirects=False
        ),
    ), pytest.raises(WebFetchError, match="request failed"):
        fetch_web_page("http://redirect.test/fail")
