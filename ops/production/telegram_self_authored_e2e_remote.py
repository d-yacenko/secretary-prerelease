#!/usr/bin/env python3
"""One-shot launcher for the self-authored MTProto acceptance harness.

The process starts with the production Telegram AI flag unchanged. The harness
sets process-local true only after its own privacy checks. This module does
not deploy, recreate, or restart long-running services.
"""

from __future__ import annotations

ONESHOT_HELPER_DEST = "/app/telegram_self_authored_e2e.py"
HOST_HELPER_PATH = "/tmp/telegram_self_authored_e2e.py"


def oneshot_compose_command(helper_path: str = HOST_HELPER_PATH) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        "/opt/secretary/.env",
        "-f",
        "infra/compose.yaml",
        "-f",
        "infra/compose.deploy.yaml",
        "run",
        "--rm",
        "--no-deps",
        "--no-build",
        "-e",
        "REHEARSAL_LONG_RUNNING_API_AI=false",
        "-e",
        "REHEARSAL_LONG_RUNNING_WORKER_AI=false",
        "-v",
        f"{helper_path}:{ONESHOT_HELPER_DEST}:ro",
        "api",
        "python3",
        ONESHOT_HELPER_DEST,
        "--live",
    ]
