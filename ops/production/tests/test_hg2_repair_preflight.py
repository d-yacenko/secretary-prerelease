"""Fail-closed checks for the HG2 repair preflight census harness."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MS_USER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
EMAIL = "alpha@example.com"
YANDEX_EMAIL = "inbox@example.com"
SECRET_NAME = "Visible Name"
TG_ACCOUNT = "tg-account-1"
TG_ACCOUNT_2 = "tg-account-2"
MM_ACCOUNT = "mm-account-1"
MM_ACCOUNT_2 = "mm-account-2"
TEAMS_ACCOUNT = "teams-account-1"
GMAIL_ACCOUNT = "gmail-account-1"
YANDEX_ACCOUNT = "yandex-account-1"
YANDEX_ACCOUNT_2 = "yandex-account-2"
USER = "user-1"
USER_2 = "user-2"
SERVER = "https://chat.example"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, OPS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


local = _load("hg2_repair_preflight", "hg2_repair_preflight.py")
remote = _load("remote_hg2_repair_preflight", "remote_hg2_repair_preflight.py")
FORBIDDEN = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
)


def _row(**overrides):
    row = {
        "user_id": USER,
        "provider": "telegram",
        "kind": "chat_message",
        "external_id": "ext",
        "deleted_at": None,
        "status": None,
        "metadata": {},
    }
    row.update(overrides)
    return row


def _sample_facts() -> dict[str, int]:
    return remote.census([], [], [], [], [], [], [])


def _success(facts: dict[str, int] | None = None) -> str:
    return local.format_facts(facts or _sample_facts())


class Hg2RepairPreflightTests(unittest.TestCase):
    def test_wrong_release_sha_and_production_ref_fail_closed(self) -> None:
        with self.assertRaises(local.PreflightClientError) as release_error:
            local.require_release_sha("0" * 40)
        self.assertEqual(release_error.exception.code, "release_sha")
        with self.assertRaises(local.PreflightClientError) as ref_error:
            local.require_origin_production("0" * 40)
        self.assertEqual(ref_error.exception.code, "origin_production")
        self.assertEqual(local.PRODUCTION_SHA, remote.PRODUCTION_SHA)
        self.assertEqual(local.EXPECTED_ALEMBIC, "0054")
        self.assertEqual(remote.EXPECTED_ALEMBIC, "0054")

    def test_remote_wrong_cwd_origin_head_and_alembic_fail_closed(self) -> None:
        with self.assertRaises(remote.RemotePreflightError) as cwd_error:
            remote.require_repository(remote.PRODUCTION_SHA)
        self.assertEqual(cwd_error.exception.stage, "cwd")

        def wrong_origin(*_args: str) -> str:
            return "https://example.invalid/other.git"

        original = remote.git
        remote.git = wrong_origin
        try:
            remote.REPO = Path.cwd().resolve()
            with self.assertRaises(remote.RemotePreflightError) as origin_error:
                remote.require_repository(remote.PRODUCTION_SHA)
            self.assertEqual(origin_error.exception.stage, "origin")
            remote.git = lambda *args: (
                remote.CANONICAL_ORIGIN if args[:2] == ("remote", "get-url") else "dirty"
            )
            with self.assertRaises(remote.RemotePreflightError) as worktree_error:
                remote.require_repository(remote.PRODUCTION_SHA)
            self.assertEqual(worktree_error.exception.stage, "worktree")
            remote.git = lambda *args: {
                ("remote", "get-url", "origin"): remote.CANONICAL_ORIGIN,
                ("status", "--porcelain"): "",
                ("rev-parse", "HEAD"): "0" * 40,
                ("rev-parse", "origin/production"): remote.PRODUCTION_SHA,
            }[args]
            with self.assertRaises(remote.RemotePreflightError) as head_error:
                remote.require_repository(remote.PRODUCTION_SHA)
            self.assertEqual(head_error.exception.stage, "head")
            remote.git = lambda *args: {
                ("remote", "get-url", "origin"): remote.CANONICAL_ORIGIN,
                ("status", "--porcelain"): "",
                ("rev-parse", "HEAD"): remote.PRODUCTION_SHA,
                ("rev-parse", "origin/production"): "0" * 40,
            }[args]
            with self.assertRaises(remote.RemotePreflightError) as ref_error:
                remote.require_repository(remote.PRODUCTION_SHA)
            self.assertEqual(ref_error.exception.stage, "production_ref")
        finally:
            remote.git = original
            remote.REPO = Path("/opt/secretary")

        with self.assertRaises(remote.RemotePreflightError) as alembic_error:
            remote.require_alembic_output("0053 (head)\n")
        self.assertEqual(alembic_error.exception.stage, "alembic")
        with self.assertRaises(remote.RemotePreflightError):
            remote.require_alembic_output("0054\n")

    def test_parser_accepts_one_exact_success_protocol(self) -> None:
        facts = local.parse_remote_output(_success())
        self.assertEqual(tuple(facts), remote.FACT_ORDER)
        self.assertTrue(_success().splitlines()[-3:] == [
            "YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false",
            "PROVIDER_NETWORK_CALLS=0",
            "HG2_PREFLIGHT_TERMINAL=success",
        ])

    def test_parser_rejects_missing_extra_duplicate_reordered_and_malformed(self) -> None:
        lines = _success().splitlines()
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(lines[:-1]) + "\n")
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(_success() + "EXTRA=1\n")
        swapped = lines[:]
        swapped[3], swapped[4] = swapped[4], swapped[3]
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(swapped) + "\n")
        duplicated = lines[:]
        duplicated.insert(3, duplicated[3])
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(duplicated) + "\n")
        negative = lines[:]
        negative[3] = "TELEGRAM_ACCOUNTS=-1"
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(negative) + "\n")
        with self.assertRaises(local.PreflightClientError):
            local.format_facts({**_sample_facts(), "TELEGRAM_ACCOUNTS": -1})

    def test_parser_rejects_identity_leakage_and_nonzero_provider_calls(self) -> None:
        leaked = _success().replace("TELEGRAM_ACCOUNTS=0", f"TELEGRAM_ACCOUNTS=0 {EMAIL}")
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(leaked)
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(_success().replace("=0", f"={TENANT}", 1))
        provider = _success().replace(
            "PROVIDER_NETWORK_CALLS=0",
            "PROVIDER_NETWORK_CALLS=1",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(provider)
        claimed = _success().replace(
            "YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false",
            "YANDEX_PROVIDER_UIDVALIDITY_KNOWN=true",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(claimed)

    def test_read_only_transaction_is_required_before_queries(self) -> None:
        remote.require_transaction_read_only("on")
        with self.assertRaises(remote.PreflightError) as caught:
            remote.require_transaction_read_only("off")
        self.assertEqual(caught.exception.stage, "read_only")
        source = remote.CHILD_SOURCE
        read_only = source.index("SET TRANSACTION READ ONLY")
        shown = source.index("SHOW transaction_read_only")
        queried = source.index("select(")
        self.assertLess(read_only, shown)
        self.assertLess(shown, queried)
        with self.assertRaises(remote.RemotePreflightError) as child_error:
            remote.parse_child_output("CHILD_READ_ONLY=off\n")
        self.assertEqual(child_error.exception.stage, "read_only")

    def test_every_terminal_reports_zero_provider_calls(self) -> None:
        self.assertIn("PROVIDER_NETWORK_CALLS=0", _success())
        blocked = (
            "HG2_PREFLIGHT_BLOCKED=alembic\n"
            "HG2_PREFLIGHT_ERROR_CLASS=RemotePreflightError\n"
            "PROVIDER_NETWORK_CALLS=0"
        )
        with self.assertRaises(local.PreflightClientError) as caught:
            local.parse_remote_output(blocked + "\n")
        self.assertEqual(caught.exception.code, "alembic")
        started = "HG2_PREFLIGHT_MARKER=started\n" + blocked + "\n"
        with self.assertRaises(local.PreflightClientError) as started_error:
            local.parse_remote_output(started)
        self.assertEqual(started_error.exception.code, "alembic")
        self.assertNotIn(".stderr", (OPS / "hg2_repair_preflight.py").read_text(encoding="utf-8"))
        self.assertNotIn(".stderr", (OPS / "remote_hg2_repair_preflight.py").read_text(encoding="utf-8"))

    def test_child_source_has_no_mutation_or_provider_io_path(self) -> None:
        source = (OPS / "remote_hg2_repair_preflight.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertIsNone(re.search(rf"\b{token}\b", source))
        for token in (
            "select_folder",
            "fetch_message",
            "Telethon",
            "decrypt",
            "repair_named_recipients",
            "repair_sender_kind",
            "repair_author_display",
            "repair_inbound_sender_metadata",
            "alembic upgrade",
            "alembic downgrade",
            "enqueue",
            "commit(",
            "session_encrypted",
            "access_token_encrypted",
            "refresh_token_encrypted",
            "app_password_encrypted",
            "provider_peer_reference_encrypted",
            "httpx",
            "urllib",
        ):
            self.assertNotIn(token, source)
        self.assertNotIn("restart", source)
        self.assertNotRegex(source, r"compose[^\n]*\bup\b")
        self.assertNotRegex(source, r"\bstop\b")

    def test_classification_separates_repairable_hidden_and_invalid(self) -> None:
        tenant_external = f"{TENANT}|{MS_USER}|chat-1|msg-1"
        facts = remote.census(
            [
                _row(
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "peer_id": 10,
                        "message_id": 5,
                    }
                ),
                _row(
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "peer_id": 10,
                        "message_id": 6,
                    }
                ),
                _row(
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT_2,
                        "peer_id": 20,
                        "message_id": 7,
                    }
                ),
                _row(
                    status="deleted",
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "peer_id": 10,
                        "message_id": 8,
                    },
                ),
                _row(
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "peer_id": 10,
                        "message_id": True,
                    }
                ),
                _row(
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "peer_id": 11,
                        "message_id": 9,
                    }
                ),
                _row(
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "message_id": 9,
                    }
                ),
                _row(
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "sender_kind": "user",
                    }
                ),
                _row(
                    deleted_at="tombstone",
                    metadata={
                        "transport": "mtproto",
                        "direction": "inbound",
                        "account_id": TG_ACCOUNT,
                        "peer_id": 10,
                        "message_id": 1,
                    },
                ),
                _row(
                    provider="mattermost",
                    metadata={
                        "account_id": MM_ACCOUNT,
                        "server_url": SERVER,
                        "author_user_id": "author-1",
                    },
                ),
                _row(
                    provider="mattermost",
                    metadata={
                        "account_id": MM_ACCOUNT_2,
                        "server_url": SERVER,
                        "author_user_id": "author-2",
                    },
                ),
                _row(
                    provider="mattermost",
                    metadata={
                        "account_id": MM_ACCOUNT_2,
                        "server_url": SERVER,
                        "author_user_id": "author-3",
                    },
                ),
                _row(
                    provider="mattermost",
                    metadata={
                        "account_id": MM_ACCOUNT,
                        "server_url": SERVER,
                        "author_user_id": "   ",
                    },
                ),
                _row(
                    provider="mattermost",
                    status="deleted",
                    metadata={
                        "account_id": MM_ACCOUNT,
                        "server_url": SERVER,
                        "author_user_id": "author-9",
                    },
                ),
                _row(
                    provider="mattermost",
                    metadata={
                        "account_id": MM_ACCOUNT,
                        "server_url": SERVER,
                        "author_display_name": SECRET_NAME,
                        "author_user_id": "author-4",
                    },
                ),
                _row(
                    provider="teams",
                    external_id=tenant_external,
                    metadata={
                        "direction": "inbound",
                        "account_id": TEAMS_ACCOUNT,
                        "tenant_id": TENANT,
                        "teams_user_id": MS_USER,
                        "chat_id": "chat-1",
                        "message_id": "msg-1",
                        "sender_id": "sender-1",
                        "sender_display_name": SECRET_NAME,
                    },
                ),
                _row(
                    provider="teams",
                    external_id=tenant_external,
                    metadata={
                        "direction": "inbound",
                        "account_id": TEAMS_ACCOUNT,
                        "tenant_id": TENANT,
                        "teams_user_id": MS_USER,
                        "message_id": "msg-1",
                        "sender_id": "sender-1",
                        "sender_display_name": SECRET_NAME,
                    },
                ),
                _row(
                    provider="teams",
                    external_id="not-the-external-id",
                    metadata={
                        "direction": "inbound",
                        "account_id": TEAMS_ACCOUNT,
                        "tenant_id": TENANT,
                        "teams_user_id": MS_USER,
                        "chat_id": "chat-1",
                        "message_id": "msg-1",
                        "sender_id": "sender-1",
                        "sender_display_name": SECRET_NAME,
                    },
                ),
                _row(
                    provider="teams",
                    external_id=tenant_external,
                    metadata={
                        "direction": "inbound",
                        "account_id": TEAMS_ACCOUNT,
                        "tenant_id": TENANT,
                        "teams_user_id": MS_USER,
                        "chat_id": "chat-1",
                        "message_id": "msg-1",
                        "sender_id": "sender-1",
                        "sender_display_name": "  ",
                    },
                ),
                _row(
                    provider="teams",
                    status="deleted",
                    external_id=tenant_external,
                    metadata={
                        "direction": "inbound",
                        "account_id": TEAMS_ACCOUNT,
                        "tenant_id": TENANT,
                        "teams_user_id": MS_USER,
                        "chat_id": "chat-1",
                        "message_id": "msg-1",
                        "sender_id": "sender-1",
                        "sender_display_name": SECRET_NAME,
                    },
                ),
                _row(
                    provider="teams",
                    metadata={
                        "direction": "inbound",
                        "account_id": TEAMS_ACCOUNT,
                        "tenant_id": TENANT,
                        "teams_user_id": MS_USER,
                        "sender_kind": "application",
                    },
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    external_id="msg-a",
                    metadata={
                        "source_account_email": EMAIL,
                        "message_id": "msg-a",
                    },
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    status="deleted",
                    external_id="msg-b",
                    metadata={
                        "source_account_email": EMAIL,
                        "message_id": "msg-b",
                    },
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    external_id="other",
                    metadata={
                        "source_account_email": EMAIL,
                        "message_id": "msg-c",
                    },
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    external_id="msg-d",
                    metadata={
                        "source_account_email": EMAIL,
                        "message_id": "msg-d",
                        "to_participants": [],
                        "cc_participants": [],
                    },
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    status="deleted",
                    external_id="msg-e",
                    metadata={
                        "source_account_email": EMAIL,
                        "message_id": "msg-e",
                        "to_participants": [],
                        "cc_participants": None,
                    },
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    metadata={"message_id": "msg-f"},
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    metadata={"source_account_email": "   ", "message_id": "msg-g"},
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    metadata={"source_account_email": "other@example.com", "message_id": "msg-h"},
                ),
                _row(
                    provider="gmail",
                    kind="email",
                    user_id=USER_2,
                    metadata={"source_account_email": EMAIL, "message_id": "msg-i"},
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    external_id="inbox:50:4",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "INBOX",
                        "imap_uid": 4,
                        "imap_uidvalidity": 50,
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    external_id="inbox:49:5",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "INBOX",
                        "imap_uid": 5,
                        "imap_uidvalidity": 49,
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    user_id=USER_2,
                    external_id="inbox:7:6",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "INBOX",
                        "imap_uid": 6,
                        "imap_uidvalidity": 7,
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    external_id="inbox:50:1",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "INBOX",
                        "imap_uid": True,
                        "imap_uidvalidity": 50,
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    external_id="inbox:1:8",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "INBOX",
                        "imap_uid": 8,
                        "imap_uidvalidity": 50,
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    status="deleted",
                    external_id="inbox:50:9",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "INBOX",
                        "imap_uid": 9,
                        "imap_uidvalidity": 50,
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    external_id="inbox:50:10",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "INBOX",
                        "imap_uid": 10,
                        "imap_uidvalidity": 50,
                        "to_participants": [],
                        "cc_participants": [],
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    external_id="sent:1:1",
                    metadata={
                        "source_account_email": YANDEX_EMAIL,
                        "folder": "Sent",
                        "imap_uid": 1,
                        "imap_uidvalidity": 50,
                    },
                ),
                _row(
                    provider="yandex_mail",
                    kind="email",
                    metadata={"folder": "INBOX", "imap_uid": 1, "imap_uidvalidity": 50},
                ),
            ],
            [
                {"id": TG_ACCOUNT, "user_id": USER},
                {"id": TG_ACCOUNT_2, "user_id": USER},
            ],
            [
                {"account_id": TG_ACCOUNT, "peer_id": 10, "scope_active": True},
                {"account_id": TG_ACCOUNT, "peer_id": 11, "scope_active": False},
                {"account_id": TG_ACCOUNT_2, "peer_id": 20, "scope_active": True},
            ],
            [
                {"id": MM_ACCOUNT, "user_id": USER, "server_url": SERVER},
                {"id": MM_ACCOUNT_2, "user_id": USER, "server_url": SERVER},
            ],
            [
                {
                    "id": TEAMS_ACCOUNT,
                    "user_id": USER,
                    "tenant_id": TENANT,
                    "microsoft_user_id": MS_USER,
                }
            ],
            [{"id": GMAIL_ACCOUNT, "user_id": USER, "email": EMAIL}],
            [
                {
                    "id": YANDEX_ACCOUNT,
                    "user_id": USER,
                    "email": YANDEX_EMAIL,
                    "sync_state": {"inbox_uidvalidity": 50},
                },
                {
                    "id": YANDEX_ACCOUNT_2,
                    "user_id": USER_2,
                    "email": YANDEX_EMAIL,
                    "sync_state": {},
                },
            ],
        )
        self.assertEqual(facts["TELEGRAM_ACCOUNTS"], 2)
        self.assertEqual(facts["TELEGRAM_LOCAL_REPAIRABLE"], 3)
        self.assertEqual(facts["TELEGRAM_HIDDEN"], 1)
        self.assertEqual(facts["TELEGRAM_INVALID_PROVENANCE"], 3)
        self.assertEqual(facts["TELEGRAM_ALREADY_ENRICHED"], 1)
        self.assertEqual(facts["TELEGRAM_COARSE_CANDIDATES"], 7)
        self.assertEqual(facts["TELEGRAM_ACCOUNTS_WITH_LOCAL_REPAIRABLE"], 2)
        self.assertEqual(facts["TELEGRAM_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT"], 2)
        self.assertEqual(facts["MATTERMOST_LOCAL_REPAIRABLE"], 3)
        self.assertEqual(facts["MATTERMOST_HIDDEN"], 1)
        self.assertEqual(facts["MATTERMOST_INVALID_PROVENANCE"], 1)
        self.assertEqual(facts["MATTERMOST_ALREADY_ENRICHED"], 1)
        self.assertEqual(facts["MATTERMOST_COARSE_CANDIDATES"], 5)
        self.assertEqual(facts["MATTERMOST_ACCOUNTS_WITH_LOCAL_REPAIRABLE"], 2)
        self.assertEqual(facts["MATTERMOST_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT"], 2)
        self.assertEqual(facts["TEAMS_LOCAL_REPAIRABLE"], 1)
        self.assertEqual(facts["TEAMS_HIDDEN"], 1)
        self.assertEqual(facts["TEAMS_INVALID_PROVENANCE"], 3)
        self.assertEqual(facts["TEAMS_ALREADY_ENRICHED"], 1)
        self.assertEqual(facts["TEAMS_COARSE_CANDIDATES"], 5)
        self.assertEqual(facts["GMAIL_ATTRIBUTABLE"], 5)
        self.assertEqual(facts["GMAIL_LOCAL_REPAIRABLE"], 1)
        self.assertEqual(facts["GMAIL_HIDDEN"], 1)
        self.assertEqual(facts["GMAIL_INVALID_PROVENANCE"], 1)
        self.assertEqual(facts["GMAIL_ALREADY_ENRICHED"], 2)
        self.assertEqual(facts["GMAIL_COARSE_CANDIDATES"], 3)
        self.assertEqual(facts["GMAIL_UNATTRIBUTABLE"], 2)
        self.assertEqual(facts["GMAIL_UNMATCHED_SOURCE_ACCOUNT"], 2)
        self.assertEqual(facts["YANDEX_LOCAL_REPAIRABLE"], 3)
        self.assertEqual(facts["YANDEX_HIDDEN"], 1)
        self.assertEqual(facts["YANDEX_INVALID_PROVENANCE"], 2)
        self.assertEqual(facts["YANDEX_ALREADY_ENRICHED"], 1)
        self.assertEqual(facts["YANDEX_COARSE_CANDIDATES"], 6)
        self.assertEqual(facts["YANDEX_STORED_UIDVALIDITY_MATCH"], 1)
        self.assertEqual(facts["YANDEX_STORED_UIDVALIDITY_DIFFER"], 1)
        self.assertEqual(facts["YANDEX_STORED_UIDVALIDITY_UNVERIFIED"], 1)
        self.assertEqual(facts["YANDEX_UNATTRIBUTABLE"], 1)
        self.assertEqual(facts["YANDEX_NON_INBOX_OUTSIDE_REPAIR"], 1)
        self.assertEqual(facts["YANDEX_ACCOUNTS_WITH_LOCAL_REPAIRABLE"], 2)
        self.assertEqual(facts["YANDEX_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT"], 2)
        rendered = local.format_facts(facts)
        for secret in (EMAIL, YANDEX_EMAIL, SECRET_NAME, TENANT, MS_USER, TG_ACCOUNT, "other@example.com"):
            self.assertNotIn(secret, rendered)
        self.assertIn("YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false", rendered)

    def test_missing_sender_kind_is_not_treated_as_user(self) -> None:
        facts = remote.census(
            [
                _row(
                    provider="teams",
                    external_id=f"{TENANT}|{MS_USER}|chat|message",
                    metadata={
                        "direction": "inbound",
                        "account_id": TEAMS_ACCOUNT,
                        "tenant_id": TENANT,
                        "teams_user_id": MS_USER,
                        "chat_id": "chat",
                        "message_id": "message",
                        "sender_id": "sender",
                        "sender_display_name": "Ada",
                    },
                )
            ],
            [],
            [],
            [],
            [
                {
                    "id": TEAMS_ACCOUNT,
                    "user_id": USER,
                    "tenant_id": TENANT,
                    "microsoft_user_id": MS_USER,
                }
            ],
            [],
            [],
        )
        self.assertEqual(facts["TEAMS_LOCAL_REPAIRABLE"], 1)
        self.assertEqual(facts["TEAMS_ALREADY_ENRICHED"], 0)
        self.assertNotIn('"user"', remote.CLASSIFIER_SOURCE.split("def _classify_teams", 1)[1].split("def _teams_target", 1)[0])


if __name__ == "__main__":
    unittest.main()
