"""Fail-closed checks for the HG5A topology production audit harness."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

EMAIL = "alpha@example.com"
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRODUCTION_SHA = "50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, OPS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


local = _load("hg5a_topology_audit", "hg5a_topology_audit.py")
remote = _load("remote_hg5a_topology_audit", "remote_hg5a_topology_audit.py")
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


def _person(person_id: str, anchors: list[str], *, complete: bool = True) -> dict:
    return {
        "person_id": person_id,
        "landscape_task_ids": anchors,
        "landscape_task_ids_complete": complete,
    }


def _sample_inputs():
    task_windows = [["t0"], ["t1"], ["t2"]]
    people_pages = [
        [
            _person("unanchored", []),
            _person("single0", ["t0"]),
            _person("multi", ["t0", "t1"]),
        ],
        [
            _person("incomplete", ["t0", "t1", "t2"], complete=False),
            _person("unmapped", ["tx"]),
            _person("single1", ["t1"]),
            _person("mismatch", ["t0"]),
        ],
    ]
    return task_windows, people_pages


def _sample_facts() -> dict[str, int]:
    task_windows, people_pages = _sample_inputs()
    return remote.build_facts(
        user_count=1,
        task_windows=task_windows,
        people_pages=people_pages,
        active_person_total=7,
        task_window_count=3,
        people_page_count=2,
    )


def _success(facts: dict[str, int] | None = None) -> str:
    return local.format_facts(facts or _sample_facts())


class Hg5aTopologyAuditTests(unittest.TestCase):
    def test_wrong_release_sha_and_production_ref_fail_closed(self) -> None:
        with self.assertRaises(local.PreflightClientError) as release_error:
            local.require_release_sha("0" * 40)
        self.assertEqual(release_error.exception.code, "release_sha")
        with self.assertRaises(local.PreflightClientError) as ref_error:
            local.require_origin_production("0" * 40)
        self.assertEqual(ref_error.exception.code, "origin_production")
        self.assertEqual(local.PRODUCTION_SHA, remote.PRODUCTION_SHA)
        self.assertEqual(local.PRODUCTION_SHA, PRODUCTION_SHA)
        self.assertEqual(local.EXPECTED_ALEMBIC, "0054")
        self.assertEqual(remote.EXPECTED_ALEMBIC, "0054")

    def test_remote_wrong_cwd_origin_head_health_and_alembic_fail_closed(self) -> None:
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
        with self.assertRaises(remote.RemotePreflightError) as health_error:
            remote.require_health_body('{"status":"down"}')
        self.assertEqual(health_error.exception.stage, "api_health")
        remote.require_health_body('{"status":"ok"}')

    def test_read_only_transaction_is_required_before_queries(self) -> None:
        remote.require_transaction_read_only("on")
        with self.assertRaises(remote.PreflightError) as caught:
            remote.require_transaction_read_only("off")
        self.assertEqual(caught.exception.stage, "read_only")
        source = remote.CHILD_SOURCE
        read_only = source.index("SET TRANSACTION READ ONLY")
        shown = source.index("SHOW transaction_read_only")
        queried = source.index("select(")
        workspace = source.index("get_workspace(")
        self.assertLess(read_only, shown)
        self.assertLess(shown, queried)
        self.assertLess(shown, workspace)
        with self.assertRaises(remote.RemotePreflightError) as child_error:
            remote.parse_child_output("CHILD_READ_ONLY=off\n")
        self.assertEqual(child_error.exception.stage, "read_only")

    def test_user_count_other_than_one_blocks_person_audit(self) -> None:
        task_windows, people_pages = _sample_inputs()
        with self.assertRaises(remote.PreflightError) as zero:
            remote.require_sole_user(0)
        self.assertEqual(zero.exception.stage, "user_count")
        with self.assertRaises(remote.PreflightError) as many:
            remote.build_facts(
                user_count=2,
                task_windows=task_windows,
                people_pages=people_pages,
                active_person_total=7,
            )
        self.assertEqual(many.exception.stage, "user_count")

    def test_parser_accepts_contiguous_window_keys_only(self) -> None:
        facts = local.parse_remote_output(_success())
        self.assertEqual(tuple(facts), remote.fact_key_order(3))
        self.assertEqual(facts["TASK_WINDOW_0_TASK_COUNT"], 1)
        self.assertEqual(facts["TASK_WINDOW_2_TASK_COUNT"], 1)
        self.assertNotIn("TASK_WINDOW_3_TASK_COUNT", facts)
        gapped = _success().replace("TASK_WINDOW_1_TASK_COUNT=1\n", "")
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(gapped)
        extra = _success().replace(
            "TASK_WINDOW_2_TASK_COUNT=1\n",
            "TASK_WINDOW_2_TASK_COUNT=1\nTASK_WINDOW_3_TASK_COUNT=1\n",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(extra)

    def test_parser_rejects_identifiers_names_and_unapproved_keys(self) -> None:
        leaked = _success().replace(
            "ACTIVE_PERSON_TOTAL=7",
            f"ACTIVE_PERSON_TOTAL=7 {EMAIL}",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(leaked)
        uuid_leaked = _success().replace("ACTIVE_PERSON_TOTAL=7", f"ACTIVE_PERSON_TOTAL={TENANT}")
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(uuid_leaked)
        named = _success().replace(
            "PEOPLE_UNANCHORED=1\n",
            "PEOPLE_UNANCHORED=1\nPERSON_TITLE=Ada\n",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(named)
        raw = _success().replace(
            "PEOPLE_UNANCHORED=1\n",
            "PEOPLE_UNANCHORED=1\nROW=person\n",
        )
        with self.assertRaises(local.PreflightClientError):
            local.parse_remote_output(raw)

    def test_fixture_categories_are_exclusive_and_relevance_is_not(self) -> None:
        facts = _sample_facts()
        self.assertEqual(facts["ACTIVE_PERSON_TOTAL"], 7)
        self.assertEqual(facts["PEOPLE_UNANCHORED"], 1)
        self.assertEqual(facts["PEOPLE_SINGLE_WINDOW_ANCHORED"], 3)
        self.assertEqual(facts["PEOPLE_MULTI_WINDOW_ANCHORED"], 1)
        self.assertEqual(facts["PEOPLE_INCOMPLETE_ANCHORS"], 1)
        self.assertEqual(facts["PEOPLE_UNMAPPED_ANCHORS"], 1)
        self.assertEqual(
            facts["PEOPLE_UNANCHORED"]
            + facts["PEOPLE_SINGLE_WINDOW_ANCHORED"]
            + facts["PEOPLE_MULTI_WINDOW_ANCHORED"]
            + facts["PEOPLE_INCOMPLETE_ANCHORS"]
            + facts["PEOPLE_UNMAPPED_ANCHORS"],
            facts["ACTIVE_PERSON_TOTAL"],
        )
        self.assertEqual(facts["PEOPLE_RELEVANT_TO_WINDOW_0"], 3)
        self.assertEqual(facts["PEOPLE_RELEVANT_TO_WINDOW_1"], 2)
        self.assertEqual(facts["PEOPLE_RELEVANT_TO_WINDOW_2"], 0)
        self.assertEqual(facts["PEOPLE_WINDOW_RELEVANCE_MEMBERSHIPS"], 5)
        self.assertEqual(facts["PEOPLE_MULTI_WINDOW_MAX_SPAN"], 2)
        self.assertEqual(facts["PEOPLE_WITH_ONE_TASK_ANCHOR"], 4)
        self.assertEqual(facts["PEOPLE_WITH_MULTIPLE_TASK_ANCHORS"], 1)

    def test_duplicate_task_membership_fails(self) -> None:
        _, people_pages = _sample_inputs()
        with self.assertRaises(remote.PreflightError) as caught:
            remote.build_facts(
                user_count=1,
                task_windows=[["t0"], ["t0"]],
                people_pages=people_pages,
                active_person_total=7,
            )
        self.assertEqual(caught.exception.stage, "duplicate_task_window")

    def test_duplicate_person_across_pages_fails(self) -> None:
        with self.assertRaises(remote.PreflightError) as caught:
            remote.build_facts(
                user_count=1,
                task_windows=[["t0"]],
                people_pages=[[_person("ada", [])], [_person("ada", [])]],
                active_person_total=1,
            )
        self.assertEqual(caught.exception.stage, "duplicate_person_page")

    def test_people_union_must_match_active_total(self) -> None:
        with self.assertRaises(remote.PreflightError) as caught:
            remote.build_facts(
                user_count=1,
                task_windows=[["t0"]],
                people_pages=[[_person("ada", [])]],
                active_person_total=2,
            )
        self.assertEqual(caught.exception.stage, "people_union")

    def test_page_window_mismatch_counts_only_single_window_people(self) -> None:
        facts = _sample_facts()
        self.assertEqual(facts["CURRENT_PEOPLE_PAGE_WINDOW_ALIGNED_COUNT"], 2)
        self.assertEqual(facts["CURRENT_PEOPLE_PAGE_WINDOW_MISMATCH_COUNT"], 1)
        self.assertEqual(
            facts["CURRENT_PEOPLE_PAGE_WINDOW_ALIGNED_COUNT"]
            + facts["CURRENT_PEOPLE_PAGE_WINDOW_MISMATCH_COUNT"],
            facts["PEOPLE_SINGLE_WINDOW_ANCHORED"],
        )

    def test_window_count_disagreement_fails(self) -> None:
        task_windows, people_pages = _sample_inputs()
        with self.assertRaises(remote.PreflightError) as caught:
            remote.build_facts(
                user_count=1,
                task_windows=task_windows,
                people_pages=people_pages,
                active_person_total=7,
                task_window_count=2,
                people_page_count=2,
            )
        self.assertEqual(caught.exception.stage, "window_count")

    def test_no_provider_or_model_call_path(self) -> None:
        combined = "\n".join(
            [
                (OPS / "hg5a_topology_audit.py").read_text(encoding="utf-8"),
                (OPS / "remote_hg5a_topology_audit.py").read_text(encoding="utf-8"),
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
            "httpx.Client",
            "requests.",
        ):
            self.assertNotIn(token, combined)
        self.assertIn("PROVIDER_NETWORK_CALLS=0", combined)
        self.assertIn("GraphWorkspaceService", remote.CHILD_SOURCE)
        self.assertIn("PersonGraphWorkspaceService", remote.CHILD_SOURCE)

    def test_child_source_has_no_mutation_sql(self) -> None:
        source = (OPS / "remote_hg5a_topology_audit.py").read_text(encoding="utf-8")
        local_source = (OPS / "hg5a_topology_audit.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertIsNone(re.search(rf"\b{token}\b", source))
            self.assertIsNone(re.search(rf"\b{token}\b", local_source))

    def test_git_diff_check_and_ruff_clean(self) -> None:
        files = [
            OPS / "hg5a_topology_audit.py",
            OPS / "remote_hg5a_topology_audit.py",
            Path(__file__),
        ]
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
