"""Shared bounded HTML-to-plain-text normalization for email connectors."""

import html as html_lib
import re
from html.parser import HTMLParser

_BLOCK_BREAK_TAGS = frozenset(
    {
        "p",
        "div",
        "li",
        "blockquote",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "hr",
        "table",
        "section",
        "article",
    }
)
_SKIP_TAGS = frozenset({"script", "style", "head", "meta", "link", "noscript"})


class _EmailHtmlToTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "br" or lowered in _BLOCK_BREAK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if lowered in _BLOCK_BREAK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._chunks.append(f"&#{name};")

    def text(self) -> str:
        return "".join(self._chunks)


def normalize_plain_email_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    compact_lines: list[str] = []
    blank_run = 0
    for line in lines:
        if not line:
            blank_run += 1
            if blank_run <= 1:
                compact_lines.append("")
            continue
        blank_run = 0
        compact_lines.append(line)
    return "\n".join(compact_lines).strip()


def html_email_to_plain_text(html: str) -> str:
    parser = _EmailHtmlToTextParser()
    parser.feed(html)
    parser.close()
    decoded = html_lib.unescape(parser.text())
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in normalized.split("\n")]
    compact_lines: list[str] = []
    blank_run = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_run += 1
            if blank_run <= 1:
                compact_lines.append("")
            continue
        blank_run = 0
        compact_lines.append(stripped)
    return "\n".join(compact_lines).strip()
