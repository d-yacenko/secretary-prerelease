"""Fail-closed checks for the HG4A People production audit harness."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

EMAIL = "alpha@example.com"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, OPS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


local = _load("hg4a_people_audit", "hg4a_people_audit.py")
remote = _load("remote_hg4a_people_audit", "remote_hg4a_people_audit.py")
FORBIDDEN = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _person(person_id: str, *, created_offset_hours: int = 1, **overrides):
    row = {
        "id": person_id,
        "kind": "person",
        "state": "confirmed",
        "status": None,
        "deleted_at": None,
        "created_at": NOW - timedelta(hours=created_offset_hours),
    }
    row.update(overrides)
    return row


def _sample_facts() -> dict[str, int]:
    people = [
        _person("p-manual"),
        _person("p-backed"),
        _person("p-old", created_offset_hours=100),
        _person("p-rejected", state="rejected"),
    ]
    identities = [{"person_id": "p-backed", "state": "confirmed"}]
    evidences = [{"person_id": "p-backed", "state": "active"}]
    edges = [
        {
            "type": "involves",
            "state": "confirmed",
            "updated_at": NOW - timedelta(hours=2),
        },
        {
            "type": "requested_by",
            "state": "rejected",
            "updated_at": NOW - timedelta(hours=3),
        },
        {
            "type": "depends_on",
            "state": "confirmed",
            "updated_at": NOW - timedelta(hours=1),
        },
    ]
    return remote.build_facts(
        user_count=1,
        people=people,
        identities=identities,
        evidences=evidences,
        edges=edges,
        overview_ids=["p-backed", "p-old"],
        overview_truncated=True,
        default_limit=12,
        scores={"p-backed": 5, "p-old": 0, "p-manual": 0},
        now=NOW,
    )


def _success(facts: dict[str, int] | None = None) -> str:
    return local.format_facts(facts or _sample_facts())


class Hg4aPeopleAuditTests(unittest.TestCase):
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
        self.assertEqual(local.PRODUCTION_SHA, "f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6")

    def test_remote_wrong_cwd_origin_head_and_alembic_fail_closed(self) -> None:
        with self.assertRaises(remote.RemotePreflightError) as cwd_error:
            remote.require_repository(remote.PRODUCTION_SHA)
        self.assertEqual(cwd_error.exception.stage, "cwd")

        original = remote.git
        try:
            remote.REPO = Path.cwd().resolve()
            remote.git = lambda *args: "https://example.invalid/other.git"
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

    def test_alembic_accepts_exact_single_head_line(self) -> None:
        remote.require_alembic_output("0054 (head)\n")
        remote.require_alembic_output("  0054 (head)  \n")
        rejected = (
            "0054",
            "0053 (head)",
            "0054 (head)\n0055 (head)",
            "0055 (head)\n0054 (head)",
            "0054 (head) extra",
            "",
        )
        for sample in rejected:
            with self.assertRaises(remote.RemotePreflightError) as caught:
                remote.require_alembic_output(sample)
            self.assertEqual(caught.exception.stage, "alembic")

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

    def test_user_count_other_than_one_blocks_person_audit(self) -> None:
        with self.assertRaises(remote.PreflightError) as zero:
            remote.require_sole_user(0)
        self.assertEqual(zero.exception.stage, "user_count")
        with self.assertRaises(remote.PreflightError) as many:
            remote.require_sole_user(2)
        self.assertEqual(many.exception.stage, "user_count")
        with self.assertRaises(remote.PreflightError) as build:
            remote.build_facts(
                user_count=2,
                people=[],
                identities=[],
                evidences=[],
                edges=[],
                overview_ids=[],
                overview_truncated=False,
                default_limit=12,
                scores={},
                now=NOW,
            )
        self.assertEqual(build.exception.stage, "user_count")
        remote.require_sole_user(1)

    def test_parser_accepts_one_exact_success_protocol(self) -> None:
        facts = local.parse_remote_output(_success())
        self.assertEqual(tuple(facts), remote.FACT_ORDER)
        self.assertEqual(
            _success().splitlines()[-2:],
            ["PROVIDER_NETWORK_CALLS=0", "AUDIT_TERMINAL=success"],
        )
        self.assertEqual(facts["AUDIT_WINDOW_HOURS"], 48)
        self.assertEqual(facts["USER_COUNT"], 1)
        self.assertEqual(facts["PEOPLE_OVERVIEW_DEFAULT_LIMIT"], 12)

    def test_parser_rejects_missing_extra_duplicate_reordered_and_malformed(self) -> None:
        lines = _success().splitlines()
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(lines[:-1]) + "\n")
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(_success() + "EXTRA=1\n")
        swapped = lines[:]
        swapped[5], swapped[6] = swapped[6], swapped[5]
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(swapped) + "\n")
        duplicated = lines[:]
        duplicated.insert(5, duplicated[5])
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(duplicated) + "\n")
        negative = lines[:]
        negative[7] = "ACTIVE_PERSON_TOTAL=-1"
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output("\n".join(negative) + "\n")
        with self.assertRaises(local.PreflightClientError):
            local.format_facts({**_sample_facts(), "ACTIVE_PERSON_TOTAL": -1})

    def test_parser_rejects_identity_leakage_and_nonzero_provider_calls(self) -> None:
        facts = _sample_facts()
        leaked = _success(facts).replace(
            f"ACTIVE_PERSON_TOTAL={facts['ACTIVE_PERSON_TOTAL']}",
            f"ACTIVE_PERSON_TOTAL={facts['ACTIVE_PERSON_TOTAL']} {EMAIL}",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(leaked)
        uuid_leaked = _success(facts).replace(
            f"ACTIVE_PERSON_TOTAL={facts['ACTIVE_PERSON_TOTAL']}",
            f"ACTIVE_PERSON_TOTAL={TENANT}",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(uuid_leaked)
        provider = _success(facts).replace(
            "PROVIDER_NETWORK_CALLS=0",
            "PROVIDER_NETWORK_CALLS=1",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(provider)

    def test_blocked_protocol_is_parsed_and_rejects_stderr_paths(self) -> None:
        blocked = (
            "AUDIT_BLOCKED=alembic\n"
            "AUDIT_ERROR_CLASS=RemotePreflightError\n"
            "PROVIDER_NETWORK_CALLS=0"
        )
        with self.assertRaises(local.PreflightClientError) as caught:
            local.parse_remote_output(blocked + "\n")
        self.assertEqual(caught.exception.code, "alembic")
        started = "AUDIT_MARKER=started\n" + blocked + "\n"
        with self.assertRaises(local.PreflightClientError) as started_error:
            local.parse_remote_output(started)
        self.assertEqual(started_error.exception.code, "alembic")
        self.assertNotIn(".stderr", (OPS / "hg4a_people_audit.py").read_text(encoding="utf-8"))
        self.assertNotIn(
            ".stderr", (OPS / "remote_hg4a_people_audit.py").read_text(encoding="utf-8")
        )

    def test_child_source_has_no_mutation_or_provider_io_path(self) -> None:
        source = (OPS / "remote_hg4a_people_audit.py").read_text(encoding="utf-8")
        local_source = (OPS / "hg4a_people_audit.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertIsNone(re.search(rf"\b{token}\b", source))
            self.assertIsNone(re.search(rf"\b{token}\b", local_source))
        for token in (
            "commit(",
            "alembic upgrade",
            "alembic downgrade",
            "enqueue",
            "httpx",
            "urllib",
            "openai",
            "Anthropic",
            "Telethon",
            "decrypt",
            "session_encrypted",
            "access_token_encrypted",
            "refresh_token_encrypted",
            "app_password_encrypted",
            "provider_peer_reference_encrypted",
            "create_person",
            "attach(",
            "approve",
            "suppress",
            "retract",
            "merge",
        ):
            self.assertNotIn(token, source)
        self.assertNotIn("restart", source)
        self.assertNotRegex(source, r"compose[^\n]*\bup\b")
        self.assertNotRegex(source, r"\bstop\b")
        self.assertIn("SET TRANSACTION READ ONLY", source)
        self.assertIn("PersonGraphWorkspaceService", source)
        self.assertIn("PersonSalienceService", source)
        self.assertIn("get_workspace()", source)

    def test_manual_like_vs_identity_backed_classification(self) -> None:
        people = [
            _person("manual"),
            _person("backed"),
            _person("evidence-only"),
            _person("old", created_offset_hours=100),
            _person("hidden", status="deleted"),
            _person("rejected", state="rejected"),
        ]
        identities = [
            {"person_id": "backed", "state": "confirmed"},
            {"person_id": "manual", "state": "rejected"},
        ]
        evidences = [
            {"person_id": "backed", "state": "active"},
            {"person_id": "evidence-only", "state": "active"},
            {"person_id": "manual", "state": "retracted"},
        ]
        groups = remote.classify_recent_people(
            people, identities, evidences, now=NOW, window_hours=48
        )
        self.assertEqual(groups["recent_ids"], {"manual", "backed", "evidence-only"})
        self.assertEqual(groups["manual_like_ids"], {"manual"})
        self.assertEqual(groups["identity_backed_ids"], {"backed"})
        self.assertEqual(groups["with_identity_ids"], {"backed"})
        self.assertEqual(groups["with_evidence_ids"], {"backed", "evidence-only"})
        facts = remote.build_facts(
            user_count=1,
            people=people,
            identities=identities,
            evidences=evidences,
            edges=[],
            overview_ids=["backed"],
            overview_truncated=False,
            default_limit=12,
            scores={"backed": 3, "manual": 0},
            now=NOW,
        )
        self.assertEqual(facts["RECENT_MANUAL_LIKE"], 1)
        self.assertEqual(facts["RECENT_IDENTITY_BACKED"], 1)
        self.assertEqual(facts["RECENT_PERSON_WITH_ACTIVE_IDENTITY"], 1)
        self.assertEqual(facts["RECENT_PERSON_WITHOUT_ACTIVE_IDENTITY"], 2)
        self.assertEqual(facts["RECENT_PERSON_WITH_ACTIVE_CONFIRMATION_EVIDENCE"], 2)
        self.assertEqual(facts["RECENT_MANUAL_LIKE_IN_OVERVIEW"], 0)
        self.assertEqual(facts["RECENT_MANUAL_LIKE_OUTSIDE_OVERVIEW"], 1)
        self.assertEqual(facts["RECENT_IDENTITY_BACKED_IN_OVERVIEW"], 1)
        self.assertEqual(facts["RECENT_MANUAL_LIKE_POSITIVE_SALIENCE"], 0)
        self.assertEqual(facts["CURRENT_POSITIVE_SALIENCE_COUNT"], 1)

    def test_overview_membership_counts_without_emitting_ids(self) -> None:
        groups = {
            "recent_ids": {"a", "b", "c"},
            "manual_like_ids": {"a", "c"},
            "identity_backed_ids": {"b"},
        }
        counts = remote.overview_counts(
            groups, ["a", "b"], truncated=True, default_limit=12
        )
        self.assertEqual(counts["PEOPLE_OVERVIEW_DEFAULT_LIMIT"], 12)
        self.assertEqual(counts["PEOPLE_OVERVIEW_RETURNED"], 2)
        self.assertEqual(counts["PEOPLE_OVERVIEW_TRUNCATED"], 1)
        self.assertEqual(counts["RECENT_PERSON_IN_OVERVIEW"], 2)
        self.assertEqual(counts["RECENT_PERSON_OUTSIDE_OVERVIEW"], 1)
        self.assertEqual(counts["RECENT_MANUAL_LIKE_IN_OVERVIEW"], 1)
        self.assertEqual(counts["RECENT_MANUAL_LIKE_OUTSIDE_OVERVIEW"], 1)
        self.assertEqual(counts["RECENT_IDENTITY_BACKED_IN_OVERVIEW"], 1)
        self.assertEqual(counts["RECENT_IDENTITY_BACKED_OUTSIDE_OVERVIEW"], 0)
        rendered = local.format_facts(_sample_facts())
        self.assertNotIn("p-manual", rendered)
        self.assertNotIn("p-backed", rendered)
        self.assertNotIn("@", rendered)

    def test_task_actor_counts_and_age_sentinel(self) -> None:
        empty = remote.actor_counts([], now=NOW)
        self.assertEqual(empty["RECENT_TASK_ACTOR_UPDATED_48H"], 0)
        self.assertEqual(empty["LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS"], -1)
        edges = [
            {
                "type": "involves",
                "state": "confirmed",
                "updated_at": NOW - timedelta(seconds=90),
            },
            {
                "type": "waiting_on",
                "state": "rejected",
                "updated_at": NOW - timedelta(hours=1),
            },
            {
                "type": "depends_on",
                "state": "confirmed",
                "updated_at": NOW - timedelta(seconds=10),
            },
            {
                "type": "delegated_to",
                "state": "confirmed",
                "updated_at": NOW - timedelta(hours=100),
            },
        ]
        counts = remote.actor_counts(edges, now=NOW)
        self.assertEqual(counts["RECENT_TASK_ACTOR_UPDATED_48H"], 2)
        self.assertEqual(counts["RECENT_TASK_ACTOR_ACTIVE_48H"], 1)
        self.assertEqual(counts["RECENT_TASK_ACTOR_REJECTED_48H"], 1)
        self.assertEqual(counts["LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS"], 90)
        child = remote.parse_child_output(
            "CHILD_READ_ONLY=on\n"
            + "\n".join(f"{key}={_sample_facts()[key]}" for key in remote.FACT_ORDER)
            + "\n"
        )
        self.assertEqual(child["LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS"], 7200)
        sentinel_facts = dict(_sample_facts())
        sentinel_facts["LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS"] = -1
        parsed = local.parse_remote_output(local.format_facts(sentinel_facts))
        self.assertEqual(parsed["LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS"], -1)

    def test_no_provider_or_model_call_path(self) -> None:
        combined = "\n".join(
            [
                (OPS / "hg4a_people_audit.py").read_text(encoding="utf-8"),
                (OPS / "remote_hg4a_people_audit.py").read_text(encoding="utf-8"),
            ]
        )
        for token in (
            "Telethon",
            "imaplib",
            "openai",
            "Anthropic",
            "chat.completions",
            "generate_content",
            "fetch_history",
            "select_folder",
            "fetch_message",
            "httpx.Client",
            "requests.",
        ):
            self.assertNotIn(token, combined)
        self.assertIn("PROVIDER_NETWORK_CALLS=0", combined)
        self.assertEqual(remote.AUDIT_WINDOW_HOURS, 48)
        self.assertEqual(
            remote.TASK_ACTOR_ROLES,
            frozenset({"requested_by", "delegated_to", "waiting_on", "involves"}),
        )

    def test_git_diff_check_and_ruff_clean(self) -> None:
        files = [
            OPS / "hg4a_people_audit.py",
            OPS / "remote_hg4a_people_audit.py",
            Path(__file__),
        ]
        for path in files:
            self.assertTrue(path.is_file(), path)
        diff = subprocess.run(
            ["git", "diff", "--check", "--", *[str(path) for path in files]],
            cwd=OPS.parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(diff.returncode, 0, diff.stdout + diff.stderr)
        ruff = subprocess.run(
            ["ruff", "check", *[str(path) for path in files]],
            cwd=OPS.parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(ruff.returncode, 0, ruff.stdout + ruff.stderr)


if __name__ == "__main__":
    unittest.main()
