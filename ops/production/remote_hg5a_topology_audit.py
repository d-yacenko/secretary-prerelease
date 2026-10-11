#!/usr/bin/env python3
"""Read-only HG5A topology audit. Streamed only by hg5a_topology_audit.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path("/opt/secretary")
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
PRODUCTION_SHA = "50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f"
EXPECTED_ALEMBIC = "0054"
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
    "duplicate_task_window",
    "duplicate_person_page",
    "people_union",
    "window_count",
}

CLASSIFIER_SOURCE = r'''
FACT_BEFORE_TASK_WINDOWS = (
    "USER_COUNT",
    "TASK_SEMANTIC_WINDOW_COUNT",
    "TASK_SEMANTIC_TASK_TOTAL",
)
FACT_AFTER_TASK_WINDOWS = (
    "TASK_IDS_DUPLICATED_ACROSS_WINDOWS",
    "TASK_WINDOW_UNION_UNIQUE_COUNT",
    "ACTIVE_PERSON_TOTAL",
    "PEOPLE_PAGES_ENUMERATED",
    "PEOPLE_ENUMERATED_UNIQUE",
    "PEOPLE_DUPLICATED_ACROSS_CURRENT_PAGES",
    "PEOPLE_UNANCHORED",
    "PEOPLE_SINGLE_WINDOW_ANCHORED",
    "PEOPLE_MULTI_WINDOW_ANCHORED",
    "PEOPLE_INCOMPLETE_ANCHORS",
    "PEOPLE_UNMAPPED_ANCHORS",
)
FACT_AFTER_RELEVANCE = (
    "PEOPLE_WINDOW_RELEVANCE_MEMBERSHIPS",
    "PEOPLE_MULTI_WINDOW_MAX_SPAN",
    "PEOPLE_WITH_ONE_TASK_ANCHOR",
    "PEOPLE_WITH_MULTIPLE_TASK_ANCHORS",
    "CURRENT_PEOPLE_PAGE_COUNT",
    "CURRENT_PEOPLE_PAGE_WINDOW_ALIGNED_COUNT",
    "CURRENT_PEOPLE_PAGE_WINDOW_MISMATCH_COUNT",
)


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


def fact_key_order(window_count):
    if not isinstance(window_count, int) or isinstance(window_count, bool) or window_count < 1:
        raise PreflightError("window_count")
    return (
        *FACT_BEFORE_TASK_WINDOWS,
        *(f"TASK_WINDOW_{index}_TASK_COUNT" for index in range(window_count)),
        *FACT_AFTER_TASK_WINDOWS,
        *(f"PEOPLE_RELEVANT_TO_WINDOW_{index}" for index in range(window_count)),
        *FACT_AFTER_RELEVANCE,
    )


def _mapped_windows(anchor_ids, task_to_window):
    windows = set()
    unmapped = False
    for task_id in anchor_ids:
        window = task_to_window.get(task_id)
        if window is None:
            unmapped = True
        else:
            windows.add(window)
    return windows, unmapped


def build_facts(
    *,
    user_count,
    task_windows,
    people_pages,
    active_person_total,
    task_window_count=None,
    people_page_count=None,
):
    require_sole_user(user_count)
    if task_window_count is None:
        task_window_count = len(task_windows)
    if people_page_count is None:
        people_page_count = len(people_pages)
    if (
        task_window_count != len(task_windows)
        or people_page_count != len(people_pages)
        or task_window_count < 1
        or people_page_count < 1
    ):
        raise PreflightError("window_count")

    task_to_window = {}
    window_task_counts = []
    for window_index, task_ids in enumerate(task_windows):
        seen_here = set()
        for task_id in task_ids:
            if task_id in seen_here or task_id in task_to_window:
                raise PreflightError("duplicate_task_window")
            seen_here.add(task_id)
            task_to_window[task_id] = window_index
        window_task_counts.append(len(seen_here))

    categories = {
        "unanchored": 0,
        "single": 0,
        "multi": 0,
        "incomplete": 0,
        "unmapped": 0,
    }
    relevance = [0 for _ in range(task_window_count)]
    max_span = 0
    one_anchor = 0
    multiple_anchors = 0
    aligned = 0
    mismatched = 0
    seen_people = set()
    for page_index, page in enumerate(people_pages):
        for person in page:
            person_id = person["person_id"]
            if person_id in seen_people:
                raise PreflightError("duplicate_person_page")
            seen_people.add(person_id)
            anchor_ids = list(person["landscape_task_ids"])
            if not person["landscape_task_ids_complete"]:
                categories["incomplete"] += 1
                continue
            windows, unmapped = _mapped_windows(anchor_ids, task_to_window)
            span = len(windows)
            if span > max_span:
                max_span = span
            if len(anchor_ids) == 1:
                one_anchor += 1
            elif len(anchor_ids) > 1:
                multiple_anchors += 1
            for window_index in windows:
                relevance[window_index] += 1
            if not anchor_ids:
                categories["unanchored"] += 1
                continue
            if unmapped:
                categories["unmapped"] += 1
                continue
            if span >= 2:
                categories["multi"] += 1
                continue
            categories["single"] += 1
            only_window = next(iter(windows))
            if page_index == only_window:
                aligned += 1
            else:
                mismatched += 1

    if len(seen_people) != active_person_total:
        raise PreflightError("people_union")
    exclusive = (
        categories["unanchored"]
        + categories["single"]
        + categories["multi"]
        + categories["incomplete"]
        + categories["unmapped"]
    )
    if exclusive != active_person_total:
        raise PreflightError("census_output")

    facts = {
        "USER_COUNT": user_count,
        "TASK_SEMANTIC_WINDOW_COUNT": task_window_count,
        "TASK_SEMANTIC_TASK_TOTAL": sum(window_task_counts),
        "TASK_IDS_DUPLICATED_ACROSS_WINDOWS": 0,
        "TASK_WINDOW_UNION_UNIQUE_COUNT": len(task_to_window),
        "ACTIVE_PERSON_TOTAL": active_person_total,
        "PEOPLE_PAGES_ENUMERATED": people_page_count,
        "PEOPLE_ENUMERATED_UNIQUE": len(seen_people),
        "PEOPLE_DUPLICATED_ACROSS_CURRENT_PAGES": 0,
        "PEOPLE_UNANCHORED": categories["unanchored"],
        "PEOPLE_SINGLE_WINDOW_ANCHORED": categories["single"],
        "PEOPLE_MULTI_WINDOW_ANCHORED": categories["multi"],
        "PEOPLE_INCOMPLETE_ANCHORS": categories["incomplete"],
        "PEOPLE_UNMAPPED_ANCHORS": categories["unmapped"],
        "PEOPLE_WINDOW_RELEVANCE_MEMBERSHIPS": sum(relevance),
        "PEOPLE_MULTI_WINDOW_MAX_SPAN": max_span,
        "PEOPLE_WITH_ONE_TASK_ANCHOR": one_anchor,
        "PEOPLE_WITH_MULTIPLE_TASK_ANCHORS": multiple_anchors,
        "CURRENT_PEOPLE_PAGE_COUNT": people_page_count,
        "CURRENT_PEOPLE_PAGE_WINDOW_ALIGNED_COUNT": aligned,
        "CURRENT_PEOPLE_PAGE_WINDOW_MISMATCH_COUNT": mismatched,
    }
    for index, count in enumerate(window_task_counts):
        facts[f"TASK_WINDOW_{index}_TASK_COUNT"] = count
    for index, count in enumerate(relevance):
        facts[f"PEOPLE_RELEVANT_TO_WINDOW_{index}"] = count
    order = fact_key_order(task_window_count)
    if tuple(facts) != order and set(facts) != set(order):
        raise PreflightError("census_output")
    return {key: facts[key] for key in order}
'''

ADAPTER_SOURCE = r'''
def _task_ids(workspace):
    return [node.id for node in workspace.nodes if node.kind == "task"]


def _people_rows(workspace):
    rows = []
    for person in workspace.people:
        rows.append(
            {
                "person_id": person["person_id"],
                "landscape_task_ids": list(person["landscape_task_ids"]),
                "landscape_task_ids_complete": bool(person["landscape_task_ids_complete"]),
            }
        )
    return rows


def _read_only_facts():
    from sqlalchemy import func, select, text

    from app.db.models import Object, User
    from app.db.session import SessionLocal
    from app.services.graph_workspace_service import GraphWorkspaceService
    from app.services.person_graph_workspace_service import PersonGraphWorkspaceService

    session = SessionLocal()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        mode = session.scalar(text("SHOW transaction_read_only"))
        require_transaction_read_only(mode)
        user_count = int(session.scalar(select(func.count()).select_from(User)) or 0)
        require_sole_user(user_count)
        user_id = session.scalar(select(User.id).limit(1))
        tasks = GraphWorkspaceService(session, user_id)
        people = PersonGraphWorkspaceService(session, user_id)
        first_tasks = tasks.get_workspace(window_index=0)
        task_window_count = int(first_tasks.window_count)
        if first_tasks.window_index != 0 or task_window_count < 1:
            raise PreflightError("window_count")
        task_windows = [_task_ids(first_tasks)]
        for index in range(1, task_window_count):
            workspace = tasks.get_workspace(window_index=index)
            if workspace.window_count != task_window_count or workspace.window_index != index:
                raise PreflightError("window_count")
            task_windows.append(_task_ids(workspace))
        first_people = people.get_workspace(window_index=0)
        people_page_count = int(first_people.window_count)
        if first_people.window_index != 0 or people_page_count < 1:
            raise PreflightError("window_count")
        people_pages = [_people_rows(first_people)]
        for index in range(1, people_page_count):
            workspace = people.get_workspace(window_index=index)
            if workspace.window_count != people_page_count or workspace.window_index != index:
                raise PreflightError("window_count")
            people_pages.append(_people_rows(workspace))
        active_person_total = int(
            session.scalar(
                select(func.count()).select_from(Object).where(*people._active_filters())
            )
            or 0
        )
        return build_facts(
            user_count=user_count,
            task_windows=task_windows,
            people_pages=people_pages,
            active_person_total=active_person_total,
            task_window_count=task_window_count,
            people_page_count=people_page_count,
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
    for key in fact_key_order(facts["TASK_SEMANTIC_WINDOW_COUNT"]):
        print(f"{key}={facts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(container_main())
'''

_CLASSIFIER: dict = {}
exec(CLASSIFIER_SOURCE, _CLASSIFIER)  # noqa: S102
FACT_BEFORE_TASK_WINDOWS = _CLASSIFIER["FACT_BEFORE_TASK_WINDOWS"]
FACT_AFTER_TASK_WINDOWS = _CLASSIFIER["FACT_AFTER_TASK_WINDOWS"]
FACT_AFTER_RELEVANCE = _CLASSIFIER["FACT_AFTER_RELEVANCE"]
PreflightError = _CLASSIFIER["PreflightError"]
require_transaction_read_only = _CLASSIFIER["require_transaction_read_only"]
require_sole_user = _CLASSIFIER["require_sole_user"]
fact_key_order = _CLASSIFIER["fact_key_order"]
build_facts = _CLASSIFIER["build_facts"]
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


def require_health_body(body: str) -> None:
    if '"status":"ok"' not in body.replace(" ", ""):
        raise RemotePreflightError("api_health")


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
    require_health_body(run(["curl", "-fsS", health_url]))
    require_alembic_output(compose("exec", "-T", "api", "alembic", "current"))


def _integer_text(value_text: str) -> int:
    if not value_text.isdecimal() or (value_text != "0" and value_text.startswith("0")):
        raise RemotePreflightError("census_output")
    return int(value_text)


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
    facts: dict[str, int] = {}
    for line in lines[1:]:
        if "=" not in line:
            raise RemotePreflightError("census_output")
        key, value_text = line.split("=", 1)
        if key in facts:
            raise RemotePreflightError("census_output")
        facts[key] = _integer_text(value_text)
    if "TASK_SEMANTIC_WINDOW_COUNT" not in facts:
        raise RemotePreflightError("census_output")
    order = fact_key_order(facts["TASK_SEMANTIC_WINDOW_COUNT"])
    if tuple(facts) != order:
        raise RemotePreflightError("census_output")
    return {key: facts[key] for key in order}


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
    for key in fact_key_order(facts["TASK_SEMANTIC_WINDOW_COUNT"]):
        print(f"{key}={facts[key]}", flush=True)
    print("PROVIDER_NETWORK_CALLS=0", flush=True)
    print("AUDIT_TERMINAL=success", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
