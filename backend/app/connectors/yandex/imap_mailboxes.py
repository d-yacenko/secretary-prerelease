from __future__ import annotations

import re
from dataclasses import dataclass

from app.connectors.yandex.errors import YandexImapError

_LIST_LINE_RE = re.compile(
    r"""^\((?P<flags>.*)\)\s+(?P<delim>"."|NIL)\s+(?P<name>.+)$"""
)


@dataclass(frozen=True)
class ImapMailbox:
    flags: frozenset[str]
    name: str


def _decode_list_item(raw: object) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    if isinstance(raw, tuple):
        return " ".join(_decode_list_item(part) for part in raw if part is not None)
    return str(raw)


def _unquote_mailbox_name(name: str) -> str:
    stripped = name.strip()
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        return stripped[1:-1].replace('\\"', '"')
    return stripped


def parse_imap_list_line(raw: object) -> ImapMailbox | None:
    line = _decode_list_item(raw).strip()
    if not line:
        return None
    match = _LIST_LINE_RE.match(line)
    if match is None:
        raise YandexImapError("malformed imap LIST response")
    flags_raw = match.group("flags") or ""
    flags = frozenset(token.strip("\\").upper() for token in flags_raw.split() if token.strip())
    name = _unquote_mailbox_name(match.group("name"))
    if not name:
        raise YandexImapError("malformed imap LIST mailbox name")
    return ImapMailbox(flags=flags, name=name)


def sent_folder_from_mailboxes(mailboxes: list[ImapMailbox]) -> str:
    sent = [
        mailbox
        for mailbox in mailboxes
        if "SENT" in mailbox.flags and "NOSELECT" not in mailbox.flags
    ]
    if len(sent) != 1:
        raise YandexImapError("could not discover imap Sent folder")
    return sent[0].name
