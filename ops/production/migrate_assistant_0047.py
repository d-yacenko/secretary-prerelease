#!/usr/bin/env python3
"""Fail-closed entrypoint for the Assistant conversations 0046 -> 0047 rollout."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from deploy import (
    CANONICAL_ORIGIN,
    DeployError,
    _load_target,
    _require_canonical_local_checkout,
    _validate_sha,
    _verified_known_hosts,
)

ROOT = Path(__file__).resolve().parents[2]
REMOTE_HELPER = Path(__file__).resolve().with_name("remote_migrate_assistant_0047.py")
AUTHORIZED_RELEASE = "296b4735f9473ea60ef22f1827ed94260603128e"
AUTHORIZED_ROLLBACK = "42db393be50a4c3f20ce86dadc280d77bada3959"
FROM_ALEMBIC = "0046"
TO_ALEMBIC = "0047"
AUTHORIZED_MIGRATION = "backend/alembic/versions/0047_assistant_conversations.py"
ALEMBIC_INFRA = (
    "backend/alembic/env.py",
    "backend/alembic.ini",
    "backend/alembic/script.py.mako",
)


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise DeployError("required local Git check failed")
    return proc.stdout.strip()


def _require_ancestry(rollback: str, release: str) -> None:
    if subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", rollback, release],
        check=False,
    ).returncode:
        raise DeployError("rollback SHA is not an ancestor of release SHA")


def _require_exact_migration_delta(rollback: str, release: str) -> None:
    rows = _git(
        "diff",
        "--name-status",
        "--find-renames",
        rollback,
        release,
        "--",
        "backend/alembic",
    )
    changed: set[str] = set()
    for row in rows.splitlines():
        fields = row.split("\t")
        if len(fields) < 2:
            raise DeployError("unable to inspect migration delta")
        if fields[0] != "A" or len(fields) != 2:
            raise DeployError("migration delta is not the authorized additive revision")
        changed.add(fields[1])
    if changed != {AUTHORIZED_MIGRATION}:
        raise DeployError("migration delta is not exactly 0047")
    for path in ALEMBIC_INFRA:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--quiet", rollback, release, "--", path],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 1:
            raise DeployError("Alembic infrastructure changed")
        if proc.returncode != 0:
            raise DeployError("unable to inspect Alembic infrastructure")


def _require_authorized_transition(release: str, rollback: str, from_alembic: str, to_alembic: str) -> None:
    if release != AUTHORIZED_RELEASE:
        raise DeployError("release SHA is not the authorized Assistant conversations release")
    if rollback != AUTHORIZED_ROLLBACK:
        raise DeployError("rollback SHA is not the authorized production base")
    if from_alembic != FROM_ALEMBIC or to_alembic != TO_ALEMBIC:
        raise DeployError("only the authorized 0046 to 0047 transition is supported")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--rollback-sha", required=True)
    parser.add_argument("--from-alembic", required=True)
    parser.add_argument("--to-alembic", required=True)
    args = parser.parse_args()
    try:
        _require_canonical_local_checkout()
        target = _load_target()
        release = _validate_sha("release-sha", args.release_sha)
        rollback = _validate_sha("rollback-sha", args.rollback_sha)
        _require_authorized_transition(release, rollback, args.from_alembic, args.to_alembic)
        _require_ancestry(rollback, release)
        _require_exact_migration_delta(rollback, release)
        for name, sha in (("rollback", rollback), ("release", release)):
            _git("cat-file", "-e", f"{sha}^{{commit}}")
        helper = REMOTE_HELPER.read_text(encoding="utf-8")
        known_hosts = _verified_known_hosts(
            target["ssh_target"],
            target["ssh_port"],
            target["host_key_sha256"],
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as hosts:
            hosts.write(known_hosts)
            hosts.flush()
            values = [
                "python3",
                "-",
                "--release-sha",
                release,
                "--rollback-sha",
                rollback,
                "--from-alembic",
                FROM_ALEMBIC,
                "--to-alembic",
                TO_ALEMBIC,
                "--origin-url",
                CANONICAL_ORIGIN,
                "--health-url",
                target["health_url"],
            ]
            command = (
                f"cd {shlex.quote(target['repository_path'])} && "
                + " ".join(shlex.quote(value) for value in values)
            )
            proc = subprocess.run(
                [
                    "ssh",
                    "-p",
                    str(target["ssh_port"]),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"UserKnownHostsFile={hosts.name}",
                    "-o",
                    "GlobalKnownHostsFile=/dev/null",
                    target["ssh_target"],
                    command,
                ],
                input=helper,
                text=True,
                check=False,
            )
        return proc.returncode
    except (DeployError, OSError):
        print("ASSISTANT_MIGRATION_DEPLOYMENT_BLOCKED=preflight", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
