"""Local fail-closed checks for the one-shot Person census."""

from __future__ import annotations

import importlib.util
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
    "alembic upgrade",
    "compose stop",
    "compose restart",
    "compose up",
)


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

    def test_sql_is_read_only_and_helper_has_no_mutation_path(self) -> None:
        source = (OPS / "remote_people_p1_person_census.py").read_text(encoding="utf-8")
        self.assertIn("BEGIN TRANSACTION READ ONLY", source)
        for token in FORBIDDEN:
            self.assertNotIn(token, source)
        self.assertNotIn("provider", source.lower())

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


if __name__ == "__main__":
    unittest.main()
