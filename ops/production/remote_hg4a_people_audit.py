#!/usr/bin/env python3
"""Read-only HG4A People audit. Streamed only by hg4a_people_audit.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path("/opt/secretary")
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
PRODUCTION_SHA = "f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6"
EXPECTED_ALEMBIC = "0054"
AUDIT_WINDOW_HOURS = 48
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(REPO / ".env"),
    "-f",
    "infra/compose.yaml",
    "-f",
    "infra/compose.deploy.yaml",
]
BLOCKED_STAGES = {
    "arguments",
    "cwd",
    "origin",
    "worktree",
    "head",
    "production_ref",
    "db_running",
    "api_running",
    "worker_running",
    "db_health",
    "api_health",
    "alembic",
    "command",
    "read_only",
    "census_output",
    "user_count",
}

CLASSIFIER_SOURCE = r'''
from datetime import timedelta

FACT_ORDER = (
    "USER_COUNT",
    "AUDIT_WINDOW_HOURS",
    "ACTIVE_PERSON_TOTAL",
    "RECENT_PERSON_48H",
    "RECENT_PERSON_WITH_ACTIVE_IDENTITY",
    "RECENT_PERSON_WITHOUT_ACTIVE_IDENTITY",
    "RECENT_PERSON_WITH_ACTIVE_CONFIRMATION_EVIDENCE",
    "RECENT_MANUAL_LIKE",
    "RECENT_IDENTITY_BACKED",
    "PEOPLE_OVERVIEW_DEFAULT_LIMIT",
    "PEOPLE_OVERVIEW_RETURNED",
    "PEOPLE_OVERVIEW_TRUNCATED",
    "RECENT_PERSON_IN_OVERVIEW",
    "RECENT_PERSON_OUTSIDE_OVERVIEW",
    "RECENT_MANUAL_LIKE_IN_OVERVIEW",
    "RECENT_MANUAL_LIKE_OUTSIDE_OVERVIEW",
    "RECENT_IDENTITY_BACKED_IN_OVERVIEW",
    "RECENT_IDENTITY_BACKED_OUTSIDE_OVERVIEW",
    "CURRENT_SALIENCE_RANKED_COUNT",
    "CURRENT_POSITIVE_SALIENCE_COUNT",
    "RECENT_MANUAL_LIKE_POSITIVE_SALIENCE",
    "RECENT_TASK_ACTOR_UPDATED_48H",
    "RECENT_TASK_ACTOR_ACTIVE_48H",
    "RECENT_TASK_ACTOR_REJECTED_48H",
    "LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS",
)

TASK_ACTOR_ROLES = frozenset(
    {"requested_by", "delegated_to", "waiting_on", "involves"}
)
AUDIT_WINDOW_HOURS = 48


class PreflightError(RuntimeError):
    def __init__(self, stage):
        self.stage = stage
        super().__init__(stage)


def require_transaction_read_only(value):
    if value != "on":
        raise PreflightError("read_only")


def require_sole_user(user_count):
    if user_count != 1:
        raise PreflightError("user_count")


def _hidden(person):
    if person.get("deleted_at") is not None:
        return True
    return person.get("status") == "deleted"


def _active_person(person):
    if person.get("kind") != "person":
        return False
    if person.get("state") == "rejected":
        return False
    return not _hidden(person)


def classify_recent_people(people, identities, evidences, *, now, window_hours=AUDIT_WINDOW_HOURS):
    cutoff = now - timedelta(hours=window_hours)
    active_ids = {row["id"] for row in people if _active_person(row)}
    recent_ids = {
        row["id"]
        for row in people
        if row["id"] in active_ids and row.get("created_at") is not None and row["created_at"] >= cutoff
    }
    identity_people = {
        row["person_id"]
        for row in identities
        if row.get("state") != "rejected" and row.get("person_id") in recent_ids
    }
    evidence_people = {
        row["person_id"]
        for row in evidences
        if row.get("state") == "active" and row.get("person_id") in recent_ids
    }
    identity_backed = set(identity_people)
    manual_like = {
        person_id
        for person_id in recent_ids
        if person_id not in identity_people and person_id not in evidence_people
    }
    return {
        "active_ids": active_ids,
        "recent_ids": recent_ids,
        "identity_backed_ids": identity_backed,
        "manual_like_ids": manual_like,
        "with_identity_ids": identity_people,
        "with_evidence_ids": evidence_people,
    }


def overview_counts(groups, overview_ids, *, truncated, default_limit):
    overview = set(overview_ids)
    recent = groups["recent_ids"]
    manual = groups["manual_like_ids"]
    backed = groups["identity_backed_ids"]
    return {
        "PEOPLE_OVERVIEW_DEFAULT_LIMIT": default_limit,
        "PEOPLE_OVERVIEW_RETURNED": len(overview),
        "PEOPLE_OVERVIEW_TRUNCATED": 1 if truncated else 0,
        "RECENT_PERSON_IN_OVERVIEW": len(recent & overview),
        "RECENT_PERSON_OUTSIDE_OVERVIEW": len(recent - overview),
        "RECENT_MANUAL_LIKE_IN_OVERVIEW": len(manual & overview),
        "RECENT_MANUAL_LIKE_OUTSIDE_OVERVIEW": len(manual - overview),
        "RECENT_IDENTITY_BACKED_IN_OVERVIEW": len(backed & overview),
        "RECENT_IDENTITY_BACKED_OUTSIDE_OVERVIEW": len(backed - overview),
    }


def salience_counts(groups, scores):
    positive = {person_id for person_id, score in scores.items() if score > 0}
    return {
        "CURRENT_SALIENCE_RANKED_COUNT": len(scores),
        "CURRENT_POSITIVE_SALIENCE_COUNT": len(positive),
        "RECENT_MANUAL_LIKE_POSITIVE_SALIENCE": len(groups["manual_like_ids"] & positive),
    }


def actor_counts(edges, *, now, window_hours=AUDIT_WINDOW_HOURS):
    cutoff = now - timedelta(hours=window_hours)
    recent = [
        row
        for row in edges
        if row.get("type") in TASK_ACTOR_ROLES
        and row.get("updated_at") is not None
        and row["updated_at"] >= cutoff
    ]
    active = [row for row in recent if row.get("state") != "rejected"]
    rejected = [row for row in recent if row.get("state") == "rejected"]
    if not recent:
        age = -1
    else:
        latest = max(row["updated_at"] for row in recent)
        age = int((now - latest).total_seconds())
        if age < 0:
            age = 0
    return {
        "RECENT_TASK_ACTOR_UPDATED_48H": len(recent),
        "RECENT_TASK_ACTOR_ACTIVE_48H": len(active),
        "RECENT_TASK_ACTOR_REJECTED_48H": len(rejected),
        "LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS": age,
    }


def build_facts(
    *,
    user_count,
    people,
    identities,
    evidences,
    edges,
    overview_ids,
    overview_truncated,
    default_limit,
    scores,
    now,
):
    require_sole_user(user_count)
    groups = classify_recent_people(people, identities, evidences, now=now)
    facts = {
        "USER_COUNT": user_count,
        "AUDIT_WINDOW_HOURS": AUDIT_WINDOW_HOURS,
        "ACTIVE_PERSON_TOTAL": len(groups["active_ids"]),
        "RECENT_PERSON_48H": len(groups["recent_ids"]),
        "RECENT_PERSON_WITH_ACTIVE_IDENTITY": len(groups["with_identity_ids"]),
        "RECENT_PERSON_WITHOUT_ACTIVE_IDENTITY": len(
            groups["recent_ids"] - groups["with_identity_ids"]
        ),
        "RECENT_PERSON_WITH_ACTIVE_CONFIRMATION_EVIDENCE": len(groups["with_evidence_ids"]),
        "RECENT_MANUAL_LIKE": len(groups["manual_like_ids"]),
        "RECENT_IDENTITY_BACKED": len(groups["identity_backed_ids"]),
    }
    facts.update(
        overview_counts(
            groups,
            overview_ids,
            truncated=overview_truncated,
            default_limit=default_limit,
        )
    )
    facts.update(salience_counts(groups, scores))
    facts.update(actor_counts(edges, now=now))
    if tuple(facts) != FACT_ORDER:
        missing = [key for key in FACT_ORDER if key not in facts]
        raise PreflightError("census_output" if missing else "census_output")
    return {key: facts[key] for key in FACT_ORDER}
'''

ADAPTER_SOURCE = r'''
def _read_only_facts():
    from datetime import UTC, datetime

    from sqlalchemy import func, select, text

    from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence, User
    from app.db.session import SessionLocal
    from app.domain.task_relations import TASK_ACTOR_ROLES as LIVE_ROLES
    from app.services.graph_workspace_service import DEFAULT_SEED_LIMIT
    from app.services.person_graph_workspace_service import PersonGraphWorkspaceService
    from app.services.person_salience_service import PersonSalienceService

    if LIVE_ROLES != TASK_ACTOR_ROLES:
        raise PreflightError("census_output")

    session = SessionLocal()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        mode = session.scalar(text("SHOW transaction_read_only"))
        require_transaction_read_only(mode)
        now = session.scalar(text("SELECT NOW()"))
        if now is None:
            raise PreflightError("census_output")
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        user_count = session.scalar(select(func.count()).select_from(User))
        require_sole_user(int(user_count or 0))
        user_id = session.scalar(select(User.id).limit(1))
        people = [
            {
                "id": row.id,
                "kind": row.kind,
                "state": row.state,
                "status": row.status,
                "deleted_at": row.deleted_at,
                "created_at": row.created_at,
            }
            for row in session.scalars(
                select(Object).where(Object.user_id == user_id, Object.kind == "person")
            )
        ]
        identities = [
            {"person_id": row.person_object_id, "state": row.state}
            for row in session.scalars(
                select(PersonIdentity).where(PersonIdentity.user_id == user_id)
            )
        ]
        evidences = [
            {"person_id": row.person_object_id, "state": row.state}
            for row in session.scalars(
                select(PersonIdentityEvidence).where(
                    PersonIdentityEvidence.user_id == user_id
                )
            )
        ]
        edges = [
            {
                "type": row.type,
                "state": row.state,
                "updated_at": row.updated_at,
            }
            for row in session.scalars(select(Edge).where(Edge.user_id == user_id))
        ]
        workspace = PersonGraphWorkspaceService(session, user_id).get_workspace()
        overview_ids = [item["person_id"] for item in workspace.people]
        ranked = PersonSalienceService(session, user_id, now=now).rank()
        scores = {item.person_id: item.score for item in ranked}
        return build_facts(
            user_count=1,
            people=people,
            identities=identities,
            evidences=evidences,
            edges=edges,
            overview_ids=overview_ids,
            overview_truncated=workspace.truncated,
            default_limit=DEFAULT_SEED_LIMIT,
            scores=scores,
            now=now,
        )
    finally:
        session.close()


def container_main():
    try:
        facts = _read_only_facts()
    except PreflightError as exc:
        print(f"CHILD_BLOCKED={exc.stage}")
        print("CHILD_ERROR_CLASS=PreflightError")
        return 1
    except Exception as exc:
        print("CHILD_BLOCKED=census_output")
        name = type(exc).__name__
        if name.isascii() and name.isidentifier():
            print(f"CHILD_ERROR_CLASS={name}")
        else:
            print("CHILD_ERROR_CLASS=SanitizedError")
        return 1
    print("CHILD_READ_ONLY=on")
    for key in FACT_ORDER:
        print(f"{key}={facts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(container_main())
'''

_CLASSIFIER: dict = {}
exec(CLASSIFIER_SOURCE, _CLASSIFIER)  # noqa: S102
FACT_ORDER = _CLASSIFIER["FACT_ORDER"]
AUDIT_WINDOW_HOURS = _CLASSIFIER["AUDIT_WINDOW_HOURS"]
PreflightError = _CLASSIFIER["PreflightError"]
require_transaction_read_only = _CLASSIFIER["require_transaction_read_only"]
require_sole_user = _CLASSIFIER["require_sole_user"]
classify_recent_people = _CLASSIFIER["classify_recent_people"]
overview_counts = _CLASSIFIER["overview_counts"]
salience_counts = _CLASSIFIER["salience_counts"]
actor_counts = _CLASSIFIER["actor_counts"]
build_facts = _CLASSIFIER["build_facts"]
TASK_ACTOR_ROLES = _CLASSIFIER["TASK_ACTOR_ROLES"]
CHILD_SOURCE = CLASSIFIER_SOURCE + "\n" + ADAPTER_SOURCE


class RemotePreflightError(RuntimeError):
    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(stage)


def run(command: list[str], *, stdin: str | None = None) -> str:
    result = subprocess.run(
        command,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RemotePreflightError("command")
    return result.stdout.strip()


def git(*args: str) -> str:
    return run(["git", *args])


def compose(*args: str, stdin: str | None = None) -> str:
    return run([*COMPOSE, *args], stdin=stdin)


def require_repository(expected_sha: str) -> None:
    if Path.cwd().resolve() != REPO:
        raise RemotePreflightError("cwd")
    if git("remote", "get-url", "origin") != CANONICAL_ORIGIN:
        raise RemotePreflightError("origin")
    if git("status", "--porcelain"):
        raise RemotePreflightError("worktree")
    if git("rev-parse", "HEAD") != expected_sha:
        raise RemotePreflightError("head")
    if git("rev-parse", "origin/production") != expected_sha:
        raise RemotePreflightError("production_ref")


def require_alembic_output(text: str) -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines != [f"{EXPECTED_ALEMBIC} (head)"]:
        raise RemotePreflightError("alembic")


def require_runtime(health_url: str) -> None:
    for service in ("db", "api", "worker"):
        container = compose("ps", "-q", service).strip()
        if not container:
            raise RemotePreflightError(f"{service}_running")
        state = run(["docker", "inspect", "-f", "{{.State.Running}}", container])
        if state != "true":
            raise RemotePreflightError(f"{service}_running")
    db = compose("ps", "-q", "db").strip()
    if run(["docker", "inspect", "-f", "{{.State.Health.Status}}", db]) != "healthy":
        raise RemotePreflightError("db_health")
    body = run(["curl", "-fsS", health_url]).replace(" ", "")
    if '"status":"ok"' not in body:
        raise RemotePreflightError("api_health")
    require_alembic_output(compose("exec", "-T", "api", "alembic", "current"))


def parse_child_output(text: str) -> dict[str, int]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise RemotePreflightError("census_output")
    if lines[0].startswith("CHILD_BLOCKED="):
        stage = lines[0].split("=", 1)[1]
        if stage not in BLOCKED_STAGES or len(lines) != 2:
            raise RemotePreflightError("census_output")
        if not lines[1].startswith("CHILD_ERROR_CLASS="):
            raise RemotePreflightError("census_output")
        raise RemotePreflightError(stage)
    if lines[0] != "CHILD_READ_ONLY=on":
        raise RemotePreflightError("read_only")
    if len(lines) != 1 + len(FACT_ORDER):
        raise RemotePreflightError("census_output")
    facts: dict[str, int] = {}
    for line, key in zip(lines[1:], FACT_ORDER, strict=True):
        prefix = f"{key}="
        if not line.startswith(prefix):
            raise RemotePreflightError("census_output")
        value_text = line[len(prefix) :]
        if key == "LATEST_TASK_ACTOR_UPDATE_AGE_SECONDS":
            if value_text != "-1" and (
                not value_text.isdecimal()
                or (value_text != "0" and value_text.startswith("0"))
            ):
                raise RemotePreflightError("census_output")
            facts[key] = int(value_text)
            continue
        if not value_text.isdecimal() or (value_text != "0" and value_text.startswith("0")):
            raise RemotePreflightError("census_output")
        facts[key] = int(value_text)
    return facts


def run_child() -> dict[str, int]:
    output = compose("exec", "-T", "api", "python3", "-", stdin=CHILD_SOURCE)
    return parse_child_output(output)


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != PRODUCTION_SHA:
        print("AUDIT_BLOCKED=arguments", flush=True)
        print("AUDIT_ERROR_CLASS=RemotePreflightError", flush=True)
        print("PROVIDER_NETWORK_CALLS=0", flush=True)
        return 1
    try:
        require_repository(sys.argv[1])
        require_runtime(sys.argv[2])
    except RemotePreflightError as exc:
        print(f"AUDIT_BLOCKED={exc.stage}", flush=True)
        print("AUDIT_ERROR_CLASS=RemotePreflightError", flush=True)
        print("PROVIDER_NETWORK_CALLS=0", flush=True)
        return 1
    print("AUDIT_MARKER=started", flush=True)
    try:
        facts = run_child()
    except RemotePreflightError as exc:
        print(f"AUDIT_BLOCKED={exc.stage}", flush=True)
        print("AUDIT_ERROR_CLASS=RemotePreflightError", flush=True)
        print("PROVIDER_NETWORK_CALLS=0", flush=True)
        return 1
    print("AUDIT_PREFLIGHT=pass", flush=True)
    print("AUDIT_READ_ONLY=on", flush=True)
    print("PRODUCTION_SHA_OK=true", flush=True)
    print("ALEMBIC_0054_OK=true", flush=True)
    for key in FACT_ORDER:
        print(f"{key}={facts[key]}", flush=True)
    print("PROVIDER_NETWORK_CALLS=0", flush=True)
    print("AUDIT_TERMINAL=success", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
