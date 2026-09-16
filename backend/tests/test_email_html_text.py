
from app.connectors.email_html_text import html_email_to_plain_text, normalize_plain_email_text


def test_html_email_preserves_paragraph_breaks() -> None:
    html = (
        "<p>Коллеги, добрый день!</p>"
        "<p>Получил ответ от Сергея.</p>"
        "<p>Во вторник он написал,<br>что согласовал встречу.</p>"
    )
    body = html_email_to_plain_text(html)
    assert "Коллеги, добрый день!" in body
    assert "Получил ответ от Сергея." in body
    assert "Во вторник он написал," in body
    assert "что согласовал встречу." in body
    assert "\n\n" in body


def test_plain_email_preserves_line_breaks() -> None:
    text = "Первая строка\n\nВторой абзац\nТретья строка"
    body = normalize_plain_email_text(text)
    assert body == "Первая строка\n\nВторой абзац\nТретья строка"


def test_html_ignores_script_style() -> None:
    html = "<style>body{}</style><script>alert(1)</script><p>Visible</p>"
    body = html_email_to_plain_text(html)
    assert "Visible" in body
    assert "alert" not in body
