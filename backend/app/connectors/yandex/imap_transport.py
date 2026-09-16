import imaplib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default as email_default_policy
from email.utils import parsedate_to_datetime
from typing import Protocol

from app.connectors.yandex.constants import DEFAULT_IMAP_TIMEOUT_SECONDS, DEFAULT_MAIL_FOLDER
from app.connectors.yandex.errors import YandexImapError
from app.connectors.yandex.imap_mailboxes import (
    ImapMailbox,
    parse_imap_list_line,
    sent_folder_from_mailboxes,
)

_INTERNALDATE_RE = re.compile(r'INTERNALDATE\s+"([^"]+)"', re.IGNORECASE)


@dataclass(frozen=True)
class YandexMailHistoryUidPage:
    uids: list[int]
    next_before_uid: int | None
    complete: bool


def normalize_history_search_uids(
    search_data: bytes | str | None,
    before_uid: int,
) -> list[int]:
    if not search_data:
        return []
    if isinstance(search_data, bytes):
        search_data = search_data.decode("ascii", errors="replace")
    unique: set[int] = set()
    for token in search_data.split():
        try:
            uid = int(token)
        except ValueError as exc:
            raise YandexImapError("malformed imap uid search response") from exc
        if uid <= 0:
            continue
        if uid >= before_uid:
            continue
        unique.add(uid)
    return sorted(unique)


def _imap_payload_text(raw: object) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    if isinstance(raw, tuple):
        return " ".join(_imap_payload_text(part) for part in raw if part is not None)
    if isinstance(raw, list):
        return " ".join(_imap_payload_text(part) for part in raw if part is not None)
    return str(raw)


def parse_imap_internaldate(raw: object) -> datetime:
    text = _imap_payload_text(raw)
    match = _INTERNALDATE_RE.search(text)
    if match is None:
        raise YandexImapError("malformed imap INTERNALDATE")
    try:
        parsed = parsedate_to_datetime(match.group(1))
    except (TypeError, ValueError, IndexError) as exc:
        raise YandexImapError("malformed imap INTERNALDATE") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def history_uids_page_from_search(
    search_data: bytes | str | None,
    before_uid: int,
    max_results: int,
) -> YandexMailHistoryUidPage:
    if max_results <= 0:
        raise ValueError("max_results must be positive")
    if before_uid <= 1:
        return YandexMailHistoryUidPage(uids=[], next_before_uid=None, complete=True)

    uids = normalize_history_search_uids(search_data, before_uid)
    if not uids:
        return YandexMailHistoryUidPage(uids=[], next_before_uid=None, complete=True)

    if len(uids) <= max_results:
        return YandexMailHistoryUidPage(uids=uids, next_before_uid=None, complete=True)

    page_uids = uids[-max_results:]
    return YandexMailHistoryUidPage(
        uids=page_uids,
        next_before_uid=page_uids[0],
        complete=False,
    )


def read_uidvalidity_from_response(imap: imaplib.IMAP4_SSL) -> int:
    try:
        response = imap.response("UIDVALIDITY")
    except (TimeoutError, OSError) as exc:
        raise YandexImapError(
            "failed to read imap UIDVALIDITY",
            failure_kind="transient",
            retryable=True,
        ) from exc
    except imaplib.IMAP4.abort as exc:
        raise YandexImapError(
            "failed to read imap UIDVALIDITY",
            failure_kind="transient",
            retryable=True,
        ) from exc
    except imaplib.IMAP4.error as exc:
        raise YandexImapError(
            "failed to read imap UIDVALIDITY",
            failure_kind="unknown",
            retryable=False,
        ) from exc
    if response is None:
        raise YandexImapError("imap UIDVALIDITY response missing")
    try:
        response_code, data = response
    except (TypeError, ValueError) as exc:
        raise YandexImapError("imap UIDVALIDITY response malformed") from exc
    if response_code != "UIDVALIDITY":
        raise YandexImapError("imap UIDVALIDITY response missing")
    if not data or data[0] is None:
        raise YandexImapError("imap UIDVALIDITY response missing")
    raw = data[0]
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    value = str(raw).strip()
    if not value.isdigit() or int(value) <= 0:
        raise YandexImapError("imap UIDVALIDITY response malformed")
    return int(value)


def incremental_uids_from_search_result(
    search_data: bytes | str | None,
    after_uid: int,
    max_results: int,
) -> list[int]:
    if not search_data:
        return []
    if isinstance(search_data, bytes):
        search_data = search_data.decode("ascii", errors="replace")
    uids = sorted(int(uid) for uid in search_data.split() if int(uid) > after_uid)
    if len(uids) > max_results:
        return uids[:max_results]
    return uids


class ImapTransport(Protocol):
    def select_folder(self, folder: str) -> int:
        ...

    def search_uids_initial(
        self,
        folder: str,
        since_date: datetime,
        max_results: int,
    ) -> list[int]:
        ...

    def search_uids_incremental(
        self,
        folder: str,
        after_uid: int,
        max_results: int,
    ) -> list[int]:
        ...

    def search_uids_history_page(
        self,
        folder: str,
        since_date: datetime,
        before_date: datetime,
        before_uid: int,
        max_results: int,
    ) -> YandexMailHistoryUidPage:
        ...

    def list_mailboxes(self) -> list[ImapMailbox]:
        ...

    def search_uids_since_before(
        self,
        folder: str,
        since_date: datetime,
        before_date: datetime,
        max_results: int,
    ) -> tuple[list[int], bool]:
        ...

    def fetch_message(self, folder: str, uid: int) -> bytes:
        ...

    def fetch_internaldate(self, folder: str, uid: int) -> datetime:
        ...


class ImaplibTransport:
    def __init__(self, host: str, port: int, email: str, password: str) -> None:
        self._host = host
        self._port = port
        self._email = email
        self._password = password
        self._imap: imaplib.IMAP4_SSL | None = None
        self._selected_folder: str | None = None
        self._uidvalidity: int | None = None

    def _connect(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            try:
                imap = imaplib.IMAP4_SSL(
                    self._host,
                    self._port,
                    timeout=DEFAULT_IMAP_TIMEOUT_SECONDS,
                )
            except (TimeoutError, OSError) as exc:
                raise YandexImapError(
                    "failed to connect to yandex imap",
                    failure_kind="transient",
                    retryable=True,
                ) from exc
            except imaplib.IMAP4.abort as exc:
                raise YandexImapError(
                    "failed to connect to yandex imap",
                    failure_kind="transient",
                    retryable=True,
                ) from exc
            except imaplib.IMAP4.error as exc:
                raise YandexImapError(
                    "failed to connect to yandex imap",
                    failure_kind="unknown",
                    retryable=False,
                ) from exc
            try:
                imap.login(self._email, self._password)
            except (TimeoutError, OSError) as exc:
                raise YandexImapError(
                    "failed to connect to yandex imap",
                    failure_kind="transient",
                    retryable=True,
                ) from exc
            except imaplib.IMAP4.abort as exc:
                raise YandexImapError(
                    "failed to connect to yandex imap",
                    failure_kind="transient",
                    retryable=True,
                ) from exc
            except imaplib.IMAP4.error as exc:
                raise YandexImapError(
                    "yandex imap login rejected",
                    failure_kind="authentication",
                    retryable=False,
                ) from exc
            self._imap = imap
        return self._imap

    def close(self) -> None:
        if self._imap is not None:
            try:
                self._imap.logout()
            except imaplib.IMAP4.error:
                pass
            self._imap = None
            self._selected_folder = None
            self._uidvalidity = None

    def select_folder(self, folder: str) -> int:
        imap = self._connect()
        if self._selected_folder != folder:
            try:
                status, _ = imap.select(folder, readonly=True)
            except (TimeoutError, OSError) as exc:
                raise YandexImapError(
                    f"failed to select imap folder {folder}",
                    failure_kind="transient",
                    retryable=True,
                ) from exc
            except imaplib.IMAP4.abort as exc:
                raise YandexImapError(
                    f"failed to select imap folder {folder}",
                    failure_kind="transient",
                    retryable=True,
                ) from exc
            except imaplib.IMAP4.error as exc:
                raise YandexImapError(
                    f"failed to select imap folder {folder}",
                    failure_kind="unknown",
                    retryable=False,
                ) from exc
            if status != "OK":
                raise YandexImapError(f"failed to select imap folder {folder}")
            self._uidvalidity = read_uidvalidity_from_response(imap)
            self._selected_folder = folder
        if self._uidvalidity is None:
            raise YandexImapError("imap UIDVALIDITY unavailable")
        return self._uidvalidity

    def search_uids_initial(
        self,
        folder: str,
        since_date: datetime,
        max_results: int,
    ) -> list[int]:
        self.select_folder(folder)
        imap = self._connect()
        date_str = since_date.strftime("%d-%b-%Y")
        criteria = f"(SINCE {date_str})"
        try:
            status, data = imap.uid("search", None, criteria)
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK" or not data or not data[0]:
            return []
        uids = sorted(int(uid) for uid in data[0].split())
        if len(uids) > max_results:
            return uids[-max_results:]
        return uids

    def search_uids_incremental(
        self,
        folder: str,
        after_uid: int,
        max_results: int,
    ) -> list[int]:
        self.select_folder(folder)
        imap = self._connect()
        criteria = f"(UID {after_uid + 1}:*)"
        try:
            status, data = imap.uid("search", None, criteria)
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK" or not data or not data[0]:
            return []
        return incremental_uids_from_search_result(data[0], after_uid, max_results)

    def search_uids_history_page(
        self,
        folder: str,
        since_date: datetime,
        before_date: datetime,
        before_uid: int,
        max_results: int,
    ) -> YandexMailHistoryUidPage:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        if before_uid <= 1:
            return YandexMailHistoryUidPage(uids=[], next_before_uid=None, complete=True)

        self.select_folder(folder)
        imap = self._connect()
        since_str = since_date.strftime("%d-%b-%Y")
        before_str = before_date.strftime("%d-%b-%Y")
        uid_upper = before_uid - 1
        criteria = f"(SINCE {since_str}) (BEFORE {before_str}) (UID 1:{uid_upper})"
        try:
            status, data = imap.uid("search", None, criteria)
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK" or not data or not data[0]:
            return YandexMailHistoryUidPage(uids=[], next_before_uid=None, complete=True)
        return history_uids_page_from_search(data[0], before_uid, max_results)

    def list_mailboxes(self) -> list[ImapMailbox]:
        imap = self._connect()
        try:
            status, data = imap.list()
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                "failed to list imap mailboxes",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                "failed to list imap mailboxes",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                "failed to list imap mailboxes",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK" or data is None:
            raise YandexImapError("failed to list imap mailboxes")
        mailboxes: list[ImapMailbox] = []
        for item in data:
            parsed = parse_imap_list_line(item)
            if parsed is not None:
                mailboxes.append(parsed)
        return mailboxes

    def discover_sent_folder(self) -> str:
        return sent_folder_from_mailboxes(self.list_mailboxes())

    def search_uids_since_before(
        self,
        folder: str,
        since_date: datetime,
        before_date: datetime,
        max_results: int,
    ) -> tuple[list[int], bool]:
        self.select_folder(folder)
        imap = self._connect()
        since_str = since_date.strftime("%d-%b-%Y")
        before_str = before_date.strftime("%d-%b-%Y")
        criteria = f"(SINCE {since_str}) (BEFORE {before_str})"
        try:
            status, data = imap.uid("search", None, criteria)
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK" or not data or not data[0]:
            return [], False
        uids = sorted(int(uid) for uid in data[0].split())
        if len(uids) > max_results:
            return uids[:max_results], True
        return uids, False

    def fetch_message(self, folder: str, uid: int) -> bytes:
        self.select_folder(folder)
        imap = self._connect()
        try:
            status, data = imap.uid("fetch", str(uid), "(RFC822)")
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                f"failed to fetch imap message uid {uid}",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                f"failed to fetch imap message uid {uid}",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                f"failed to fetch imap message uid {uid}",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK" or not data or data[0] is None:
            raise YandexImapError(f"failed to fetch imap message uid {uid}")

        part = data[0]
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
            return part[1]
        raise YandexImapError(f"failed to fetch imap message uid {uid}")

    def fetch_internaldate(self, folder: str, uid: int) -> datetime:
        self.select_folder(folder)
        imap = self._connect()
        try:
            status, data = imap.uid("fetch", str(uid), "(INTERNALDATE)")
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                f"failed to fetch imap INTERNALDATE uid {uid}",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                f"failed to fetch imap INTERNALDATE uid {uid}",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                f"failed to fetch imap INTERNALDATE uid {uid}",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK" or not data or data[0] is None:
            raise YandexImapError(f"failed to fetch imap INTERNALDATE uid {uid}")
        try:
            return parse_imap_internaldate(data)
        except YandexImapError as exc:
            raise YandexImapError(f"failed to fetch imap INTERNALDATE uid {uid}") from exc

    def search_uids_header(
        self,
        folder: str,
        header_name: str,
        header_value: str,
        max_results: int,
    ) -> tuple[list[int], bool]:
        self.select_folder(folder)
        imap = self._connect()
        criteria = f'(HEADER "{header_name}" "{header_value}")'
        try:
            status, data = imap.uid("search", None, criteria)
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                "failed to search imap messages",
                failure_kind="transient",
                retryable=True,
            ) from exc
        if status != "OK":
            raise YandexImapError("failed to search imap messages", retryable=True)
        if not data or not data[0]:
            return [], False
        uids = sorted(int(uid) for uid in data[0].split())
        if len(uids) > max_results:
            return uids[:max_results], True
        return uids, False

    def ensure_mailbox(self, folder: str) -> None:
        existing = {mailbox.name for mailbox in self.list_mailboxes()}
        if folder in existing:
            return
        imap = self._connect()
        try:
            status, _ = imap.create(folder)
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                f"failed to create imap mailbox {folder}",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                f"failed to create imap mailbox {folder}",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            existing = {mailbox.name for mailbox in self.list_mailboxes()}
            if folder in existing:
                return
            raise YandexImapError(
                f"failed to create imap mailbox {folder}",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK":
            existing = {mailbox.name for mailbox in self.list_mailboxes()}
            if folder in existing:
                return
            raise YandexImapError(f"failed to create imap mailbox {folder}")
        self._selected_folder = None

    def append_message(
        self,
        folder: str,
        message_bytes: bytes,
        flags: list[str] | None = None,
    ) -> None:
        imap = self._connect()
        flag_tokens = flags or ["\\Seen"]
        flag_str = "(" + " ".join(flag_tokens) + ")"
        try:
            status, _ = imap.append(folder, flag_str, None, message_bytes)
        except (TimeoutError, OSError) as exc:
            raise YandexImapError(
                "failed to append imap message",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.abort as exc:
            raise YandexImapError(
                "failed to append imap message",
                failure_kind="transient",
                retryable=True,
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise YandexImapError(
                "failed to append imap message",
                failure_kind="unknown",
                retryable=False,
            ) from exc
        if status != "OK":
            raise YandexImapError("failed to append imap message")
        self._selected_folder = None


class FakeImapTransport:
    def __init__(
        self,
        uidvalidity: int = 1,
        messages: dict[int, bytes] | None = None,
        folder: str = DEFAULT_MAIL_FOLDER,
        tx_checker: object | None = None,
        history_matching_uids: list[int] | None = None,
        mailboxes: list[ImapMailbox] | None = None,
        folder_messages: dict[str, dict[int, bytes]] | None = None,
    ) -> None:
        self._uidvalidity = uidvalidity
        self._messages = messages or {}
        self._folder = folder
        self._folder_messages = folder_messages or {folder: dict(self._messages)}
        if folder not in self._folder_messages:
            self._folder_messages[folder] = dict(self._messages)
        self._mailboxes = mailboxes
        self.fetch_calls: list[int] = []
        self.history_search_calls: list[dict[str, object]] = []
        self.initial_search_calls: list[dict[str, object]] = []
        self.incremental_search_calls: list[dict[str, object]] = []
        self.list_calls = 0
        self.window_search_calls: list[dict[str, object]] = []
        self.internaldate_fetch_calls: list[int] = []
        self.append_calls: list[dict[str, object]] = []
        self.create_calls: list[str] = []
        self.header_search_calls: list[dict[str, object]] = []
        self.persist_on_append = True
        self.lose_append_response = False
        self.append_error: YandexImapError | None = None
        self.create_error: YandexImapError | None = None
        self._internaldates: dict[tuple[str, int], datetime] = {}
        now = datetime.now(UTC)
        for folder_name, store in self._folder_messages.items():
            for uid in store:
                self._internaldates[(folder_name, uid)] = now
        self._tx_checker = tx_checker
        self._history_matching_uids = history_matching_uids
        self._selected_folder = folder

    def _history_candidates(self, before_uid: int) -> list[int]:
        if self._history_matching_uids is not None:
            source = self._history_matching_uids
        else:
            source = sorted(self._messages.keys())
        return sorted(uid for uid in source if uid < before_uid)

    def _check_tx(self) -> None:
        if self._tx_checker is not None:
            assert not self._tx_checker()

    def select_folder(self, folder: str) -> int:
        self._check_tx()
        if folder not in self._folder_messages and folder != self._folder:
            raise YandexImapError(f"failed to select imap folder {folder}")
        self._selected_folder = folder
        return self._uidvalidity

    def list_mailboxes(self) -> list[ImapMailbox]:
        self._check_tx()
        self.list_calls += 1
        if self._mailboxes is not None:
            return list(self._mailboxes)
        return [ImapMailbox(flags=frozenset(), name=self._folder)]

    def discover_sent_folder(self) -> str:
        return sent_folder_from_mailboxes(self.list_mailboxes())

    def search_uids_since_before(
        self,
        folder: str,
        since_date: datetime,
        before_date: datetime,
        max_results: int,
    ) -> tuple[list[int], bool]:
        self._check_tx()
        self.select_folder(folder)
        self.window_search_calls.append(
            {
                "folder": folder,
                "since_date": since_date,
                "before_date": before_date,
                "max_results": max_results,
            }
        )
        uids = sorted(self._folder_messages.get(folder, {}).keys())
        if len(uids) > max_results:
            return uids[:max_results], True
        return uids, False

    def search_uids_initial(
        self,
        folder: str,
        since_date: datetime,
        max_results: int,
    ) -> list[int]:
        self._check_tx()
        self.initial_search_calls.append(
            {"folder": folder, "since_date": since_date, "max_results": max_results}
        )
        uids = sorted(self._messages.keys())
        if len(uids) > max_results:
            return uids[-max_results:]
        return uids

    def search_uids_incremental(
        self,
        folder: str,
        after_uid: int,
        max_results: int,
    ) -> list[int]:
        self._check_tx()
        self.incremental_search_calls.append(
            {"folder": folder, "after_uid": after_uid, "max_results": max_results}
        )
        uids = sorted(uid for uid in self._messages if uid > after_uid)
        if len(uids) > max_results:
            return uids[:max_results]
        return uids

    def search_uids_history_page(
        self,
        folder: str,
        since_date: datetime,
        before_date: datetime,
        before_uid: int,
        max_results: int,
    ) -> YandexMailHistoryUidPage:
        self._check_tx()
        if before_uid <= 1:
            return YandexMailHistoryUidPage(uids=[], next_before_uid=None, complete=True)
        self.history_search_calls.append(
            {
                "folder": folder,
                "since_date": since_date,
                "before_date": before_date,
                "before_uid": before_uid,
                "max_results": max_results,
            }
        )
        candidates = self._history_candidates(before_uid)
        payload = b" ".join(str(uid).encode() for uid in candidates)
        return history_uids_page_from_search(payload, before_uid, max_results)

    def fetch_message(self, folder: str, uid: int) -> bytes:
        self._check_tx()
        self.fetch_calls.append(uid)
        folder = self._selected_folder
        store = self._folder_messages.get(folder, self._messages)
        if uid not in store:
            raise YandexImapError(f"failed to fetch imap message uid {uid}")
        return store[uid]

    def fetch_internaldate(self, folder: str, uid: int) -> datetime:
        self._check_tx()
        self.select_folder(folder)
        self.internaldate_fetch_calls.append(uid)
        key = (self._selected_folder, uid)
        stored = self._internaldates.get(key)
        if stored is None:
            raise YandexImapError(f"failed to fetch imap INTERNALDATE uid {uid}")
        return stored.astimezone(UTC)

    def search_uids_header(
        self,
        folder: str,
        header_name: str,
        header_value: str,
        max_results: int,
    ) -> tuple[list[int], bool]:
        self._check_tx()
        self.select_folder(folder)
        self.header_search_calls.append(
            {
                "folder": folder,
                "header_name": header_name,
                "header_value": header_value,
                "max_results": max_results,
            }
        )
        matches: list[int] = []
        store = self._folder_messages.get(folder, {})
        for uid, raw in sorted(store.items()):
            parsed = BytesParser(policy=email_default_policy).parsebytes(raw)
            actual = str(parsed.get(header_name) or "").strip()
            if actual == header_value.strip():
                matches.append(uid)
        if len(matches) > max_results:
            return matches[:max_results], True
        return matches, False

    def ensure_mailbox(self, folder: str) -> None:
        self._check_tx()
        names = {mailbox.name for mailbox in self.list_mailboxes()}
        if folder in names:
            return
        if self.create_error is not None:
            raise self.create_error
        self.create_calls.append(folder)
        self._folder_messages.setdefault(folder, {})
        extra = ImapMailbox(flags=frozenset({"HASNOCHILDREN"}), name=folder)
        if self._mailboxes is None:
            self._mailboxes = [
                ImapMailbox(flags=frozenset(), name=self._folder),
                extra,
            ]
        else:
            self._mailboxes = list(self._mailboxes) + [extra]

    def append_message(
        self,
        folder: str,
        message_bytes: bytes,
        flags: list[str] | None = None,
    ) -> None:
        self._check_tx()
        self.append_calls.append(
            {"folder": folder, "message_bytes": message_bytes, "flags": list(flags or ["\\Seen"])}
        )
        if self.persist_on_append:
            existing = self._folder_messages.setdefault(folder, {})
            uid = (max(existing) + 1) if existing else 1
            self.add_message(folder, uid, message_bytes)
        if self.lose_append_response:
            self.lose_append_response = False
            raise YandexImapError("lost IMAP APPEND response", retryable=True)
        if self.append_error is not None:
            raise self.append_error

    def add_message(
        self,
        folder: str,
        uid: int,
        raw: bytes,
        *,
        internaldate: datetime | None = None,
    ) -> None:
        self._folder_messages.setdefault(folder, {})[uid] = raw
        stamp = internaldate or datetime.now(UTC)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        self._internaldates[(folder, uid)] = stamp.astimezone(UTC)
