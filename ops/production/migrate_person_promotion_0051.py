#!/usr/bin/env python3
"""Fail-closed entrypoint for the exact PP1 0050 -> 0051 rollout.

Only release 07bd8bafdb2f53a6a8475fc2d792687fa373a149, rollback
9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa, and revision pair 0050 -> 0051
are accepted. This script does not generalize deploy.py.
"""

from __future__ import annotations

import argparse
import re
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
REMOTE_HELPER = (
    Path(__file__).resolve().with_name("remote_migrate_person_promotion_0051.py")
)
AUTHORIZED_RELEASE = "07bd8bafdb2f53a6a8475fc2d792687fa373a149"
AUTHORIZED_ROLLBACK = "9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa"
FROM_ALEMBIC = "0050"
TO_ALEMBIC = "0051"
AUTHORIZED_MIGRATION = "backend/alembic/versions/0051_person_promotion_feedback.py"
REVISION_CHAIN = ((AUTHORIZED_MIGRATION, "0051", "0050"),)
ALEMBIC_INFRA = (
    "backend/alembic/env.py",
    "backend/alembic.ini",
    "backend/alembic/script.py.mako",
)
_REVISION_RE = re.compile(r'^revision: str = "([0-9]+)"$', re.MULTILINE)
_DOWN_RE = re.compile(r'^down_revision: str \| None = "([0-9]+)"$', re.MULTILINE)


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
        if not row:
            continue
        fields = row.split("\t")
        if len(fields) < 2:
            raise DeployError("unable to inspect migration delta")
        if fields[0] != "A" or len(fields) != 2:
            raise DeployError("migration delta is not the authorized additive file")
        changed.add(fields[1])
    if changed != {AUTHORIZED_MIGRATION}:
        raise DeployError(
            "migration delta is not exactly 0051_person_promotion_feedback"
        )
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


def _require_revision_chain(release: str) -> None:
    for path, revision, down in REVISION_CHAIN:
        text = _git("show", f"{release}:{path}")
        found = _REVISION_RE.search(text)
        parent = _DOWN_RE.search(text)
        if (
            found is None
            or parent is None
            or found.group(1) != revision
            or parent.group(1) != down
        ):
            raise DeployError("revision chain is not exactly 0050 to 0051")


def _require_authorized_transition(
    release: str,
    rollback: str,
    from_alembic: str,
    to_alembic: str,
) -> None:
    if release != AUTHORIZED_RELEASE:
        raise DeployError("release SHA is not the authorized PP1 release")
    if rollback != AUTHORIZED_ROLLBACK:
        raise DeployError("rollback SHA is not the authorized production base")
    if from_alembic != FROM_ALEMBIC or to_alembic != TO_ALEMBIC:
        raise DeployError("only the authorized 0050 to 0051 transition is supported")
    if release == rollback:
        raise DeployError("release SHA must differ from the rollback SHA")


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
        _require_authorized_transition(
            release, rollback, args.from_alembic, args.to_alembic
        )
        _require_ancestry(rollback, release)
        _require_exact_migration_delta(rollback, release)
        _require_revision_chain(release)
        for sha in (rollback, release):
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
            command = f"cd {shlex.quote(target['repository_path'])} && " + " ".join(
                shlex.quote(value) for value in values
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
        print(
            "PERSON_PROMOTION_MIGRATION_DEPLOYMENT_BLOCKED=preflight", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
