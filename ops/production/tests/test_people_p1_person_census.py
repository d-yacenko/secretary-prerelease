"""Local fail-closed checks for the one-shot Person census."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, OPS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _load("people_p1_person_census", "people_p1_person_census.py")
remote = _load("remote_people_p1_person_census", "remote_people_p1_person_census.py")
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
OLD_PSQL_TAGS = "BEGIN\non|3|2|1|4|1|2\nCOMMIT\n"


def _success(**overrides: int) -> str:
    facts = {
        "PERSON_TOTAL": 3,
        "PERSON_VISIBLE": 2,
        "PERSON_WITH_EDGES": 1,
        "PERSON_INCIDENT_EDGES": 4,
        "PERSON_TASK_EDGES": 1,
        "PERSON_FLOW_EDGES": 2,
    }
    facts.update(overrides)
    lines = [
        "CENSUS_MARKER=started",
        "CENSUS_PREFLIGHT=pass",
        "CENSUS_READ_ONLY=on",
        *[f"{key}={facts[key]}" for key in census.FACTS],
    ]
    return "\n".join(lines) + "\n"


class PersonCensusTests(unittest.TestCase):
    def test_wrong_release_sha_fails_closed(self) -> None:
        with self.assertRaises(census.CensusClientError) as caught:
            census.require_release_sha("0" * 40)
        self.assertEqual(caught.exception.code, "release_sha")

    def test_wrong_origin_production_fails_closed(self) -> None:
        with self.assertRaises(census.CensusClientError) as caught:
            census.require_origin_production("0" * 40)
        self.assertEqual(caught.exception.code, "origin_production")

    def test_remote_wrong_cwd_origin_head_and_alembic_fail_closed(self) -> None:
        with self.assertRaises(remote.CensusError) as cwd_error:
            remote.require_repository(remote.PRODUCTION_SHA)
        self.assertEqual(cwd_error.exception.stage, "cwd")

        def wrong_origin(*_args: str) -> str:
            return "https://example.invalid/other.git"

        original = remote.git
        remote.git = wrong_origin
        try:
            remote.REPO = Path.cwd().resolve()
            with self.assertRaises(remote.CensusError) as origin_error:
                remote.require_repository(remote.PRODUCTION_SHA)
            self.assertEqual(origin_error.exception.stage, "origin")
        finally:
            remote.git = original
            remote.REPO = Path("/opt/secretary")

        with self.assertRaises(remote.CensusError) as head_error:
            remote.require_alembic_output("0046 (head)\n")
        self.assertEqual(head_error.exception.stage, "alembic")
        with self.assertRaises(remote.CensusError):
            remote.require_alembic_output("0047\n")

    def test_parser_accepts_only_the_six_integer_facts(self) -> None:
        facts = census.parse_remote_output(_success())
        self.assertEqual(list(facts), list(census.FACTS))
        self.assertEqual(census.format_facts(facts), "".join(
            f"{key}={facts[key]}\n" for key in census.FACTS
        ))

    def test_parser_rejects_raw_identity_fields(self) -> None:
        leaked = _success() + "TITLE=Ada\n"
        with self.assertRaises(census.CensusClientError):
            census.parse_remote_output(leaked)
        with self.assertRaises(census.CensusClientError):
            census.format_facts({**census.parse_remote_output(_success()), "id": "secret"})

    def test_old_single_line_assumption_rejects_psql_command_tags(self) -> None:
        lines = [line for line in OLD_PSQL_TAGS.splitlines() if line.strip()]
        with self.assertRaises(remote.CensusError) as caught:
            if len(lines) != 1:
                raise remote.CensusError("census_output")
            remote.parse_census_row(lines[0])
        self.assertEqual(caught.exception.stage, "census_output")
        values = remote.parse_census_row(remote.extract_census_row(OLD_PSQL_TAGS))
        self.assertEqual(values, [3, 2, 1, 4, 1, 2])
        self.assertEqual(
            remote.parse_census_row(remote.extract_census_row("on|3|2|1|4|1|2\n")),
            [3, 2, 1, 4, 1, 2],
        )
        with self.assertRaises(remote.CensusError):
            remote.extract_census_row("BEGIN\non|1|1|1|1|1|1\nNOTICE: extra\nCOMMIT\n")

    def test_post_marker_blocked_stage_is_not_malformed(self) -> None:
        with self.assertRaises(census.CensusClientError) as caught:
            census.parse_remote_output(
                "CENSUS_MARKER=started\nCENSUS_BLOCKED=census_output\n"
            )
        self.assertEqual(caught.exception.code, "census_output")
        self.assertTrue(caught.exception.consumed)

    def test_sql_is_read_only_and_helper_has_no_mutation_path(self) -> None:
        source = (OPS / "remote_people_p1_person_census.py").read_text(encoding="utf-8")
        self.assertIn("BEGIN TRANSACTION READ ONLY", source)
        self.assertIn("psql -X -q", source)
        for token in FORBIDDEN:
            self.assertIsNone(re.search(rf"\b{token}\b", source))
        for token in ("alembic upgrade", "compose stop", "compose restart", "compose up"):
            self.assertNotIn(token, source)
        local = (OPS / "people_p1_person_census.py").read_text(encoding="utf-8")
        self.assertNotIn("result.stderr", local)
        self.assertNotIn("probe.stderr", local)

    def test_malformed_db_output_fails_closed(self) -> None:
        with self.assertRaises(remote.CensusError):
            remote.parse_census_row("off|1|1|1|1|1|1")
        with self.assertRaises(remote.CensusError):
            remote.parse_census_row("on|1|1|1|1|1")
        with self.assertRaises(census.CensusClientError) as caught:
            census.parse_remote_output("CENSUS_MARKER=started\nPERSON_TOTAL=nope\n")
        self.assertTrue(caught.exception.consumed)
        with self.assertRaises(census.CensusClientError) as blocked:
            census.parse_remote_output("CENSUS_BLOCKED=alembic\n")
        self.assertFalse(blocked.exception.consumed)

    def test_classification_boundary(self) -> None:
        empty = census.parse_remote_output(_success(
            PERSON_TOTAL=0,
            PERSON_VISIBLE=0,
            PERSON_WITH_EDGES=0,
            PERSON_INCIDENT_EDGES=0,
            PERSON_TASK_EDGES=0,
            PERSON_FLOW_EDGES=0,
        ))
        self.assertEqual(census.classify(empty), "P1_REAL_DATA_NOT_USEFUL_YET")
        people_without_context = census.parse_remote_output(_success(
            PERSON_VISIBLE=2,
            PERSON_TASK_EDGES=0,
            PERSON_FLOW_EDGES=0,
        ))
        self.assertEqual(
            census.classify(people_without_context),
            "P1_REAL_DATA_NOT_USEFUL_YET",
        )
        useful = census.parse_remote_output(_success())
        self.assertEqual(census.classify(useful), "P1_REAL_DATA_CANDIDATE_EXISTS")

    def test_disposable_psql_rehearsal(self) -> None:
        if os.environ.get("P1R2R_REHEARSAL") != "1":
            self.skipTest("disposable rehearsal is opt-in")
        env = {**os.environ, "PGPASSWORD": "secretary"}
        setup = """
        DROP TABLE IF EXISTS edges;
        DROP TABLE IF EXISTS objects;
        CREATE TABLE objects (
            id int PRIMARY KEY,
            kind text NOT NULL,
            deleted_at timestamptz,
            status text
        );
        CREATE TABLE edges (
            id int PRIMARY KEY,
            source_id int NOT NULL,
            target_id int NOT NULL
        );
        INSERT INTO objects (id, kind, status) VALUES
            (1, 'person', NULL),
            (2, 'person', NULL),
            (10, 'task', 'open'),
            (11, 'email', NULL);
        INSERT INTO objects (id, kind, status, deleted_at) VALUES
            (3, 'person', 'deleted', now());
        INSERT INTO edges (id, source_id, target_id) VALUES
            (100, 1, 10),
            (101, 1, 11),
            (102, 3, 10);
        """
        base = [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            "55433",
            "-U",
            "secretary",
            "-d",
            "census_rehearsal",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
        ]
        setup_run = subprocess.run(
            [*base, "-c", setup],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(setup_run.returncode, 0, setup_run.stderr)
        census_run = subprocess.run(
            base,
            input=remote.CENSUS_SQL,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(census_run.returncode, 0, census_run.stderr)
        values = remote.parse_census_row(remote.extract_census_row(census_run.stdout))
        self.assertEqual(values, [3, 2, 1, 2, 1, 1])
        protocol = (
            "CENSUS_MARKER=started\n"
            "CENSUS_PREFLIGHT=pass\n"
            "CENSUS_READ_ONLY=on\n"
            + "".join(f"{key}={value}\n" for key, value in zip(census.FACTS, values))
        )
        facts = census.parse_remote_output(protocol)
        rendered = census.format_facts(facts)
        self.assertEqual(rendered.count("\n"), 6)
        self.assertNotIn("Ada", rendered)
        self.assertNotIn("@", rendered)


if __name__ == "__main__":
    unittest.main()
