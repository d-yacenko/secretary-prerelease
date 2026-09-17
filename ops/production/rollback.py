#!/usr/bin/env python3
"""Run the explicit, fail-closed production application rollback."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.production import deploy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--rollback-sha", required=True)
    parser.add_argument("--expected-alembic", required=True)
    args = parser.parse_args()
    try:
        deploy._require_canonical_local_checkout()
        target = deploy._load_target()
        release = deploy._validate_sha("release-sha", args.release_sha)
        rollback = deploy._validate_sha("rollback-sha", args.rollback_sha)
        deploy._require_schema_neutral_release(rollback, release)
        if not args.expected_alembic.isdigit() or len(args.expected_alembic) != 4:
            raise deploy.DeployError("expected-alembic must be a four-digit revision")
        production = deploy._run_local(["git", "-C", str(deploy.REPOSITORY_ROOT), "rev-parse", "origin/production"])
        if production != release:
            raise deploy.DeployError("origin/production is not the expected release")
        helper = deploy.HERE.joinpath("remote_rollback.py").read_text(encoding="utf-8")
        known_hosts = deploy._verified_known_hosts(target["ssh_target"], target["ssh_port"], target["host_key_sha256"])
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as hosts_file:
            hosts_file.write(known_hosts); hosts_file.flush()
            remote_args = ["python3", "-", "--release-sha", release, "--rollback-sha", rollback,
                           "--expected-alembic", args.expected_alembic, "--origin-url", target["origin_url"],
                           "--health-url", target["health_url"]]
            command = f"cd {shlex.quote(target['repository_path'])} && " + " ".join(shlex.quote(x) for x in remote_args)
            result = subprocess.run(["ssh", "-p", str(target["ssh_port"]), "-o", "BatchMode=yes",
                                     "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={hosts_file.name}",
                                     "-o", "GlobalKnownHostsFile=/dev/null", target["ssh_target"], command],
                                    input=helper, text=True, check=False)
        return result.returncode
    except (deploy.DeployError, OSError, ValueError):
        print("ROLLBACK_BLOCKED=preflight failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
