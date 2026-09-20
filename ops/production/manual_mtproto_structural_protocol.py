"""Closed stdout protocol for the human-only M4AN2 bridge (stdlib only)."""

import sys
from pathlib import Path

EXCEPTION_CLASSES = {
    "NONE",
    "OTHER",
    "RuntimeError",
    "ValueError",
    "TypeError",
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "OperationalError",
    "ProgrammingError",
    "DatabaseError",
    "InterfaceError",
    "InvalidToken",
    "KeyError",
    "IndexError",
    "UnicodeDecodeError",
    "InvalidRequestError",
    "StatementError",
    "TelegramMtprotoProviderReferenceInvalidError",
}
CHECKS = (
    ("IMPORTS_PASS", "IMPORTS"),
    ("DB_QUERY_PASS", "DB_QUERY"),
    ("HISTORY_STATE_READ_PASS", "HISTORY_STATE_READ"),
    ("CREDENTIAL_ENCRYPTION_CONSTRUCT_PASS", "ENCRYPTION_CONSTRUCT"),
    ("SESSION_DECRYPT_PASS", "SESSION_DECRYPT"),
    ("STRING_SESSION_PARSE_PASS", "STRING_SESSION_PARSE"),
    ("REFERENCE_DECRYPT_PASS", "REFERENCE_DECRYPT"),
    ("REFERENCE_PARSE_PASS", "REFERENCE_PARSE"),
    ("REFERENCE_PEER_MATCH_PASS", "REFERENCE_PEER_MATCH"),
)
TERMINAL = "MANUAL_M4AN2_REMOTE_TERMINAL"


class Incomplete(ValueError):
    pass


class Reader:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.pos = 0
        self.safe = []

    def take(self, key, values):
        return self.choose({f"{key}={value}\n": value for value in values})

    def choose(self, options):
        if self.pos == len(self.lines):
            raise Incomplete()
        line = self.lines[self.pos]
        if not line.endswith("\n"):
            raise Incomplete()
        if line not in options:
            raise ValueError()
        self.pos += 1
        self.safe.append(line)
        return options[line]

    def boolean(self, key):
        return self.take(key, ("true", "false")) == "true"

    def marker(self, marker):
        self.choose({f"{marker}\n": marker})

    def end(self):
        if self.pos != len(self.lines):
            raise ValueError()


def child(reader):
    failure = "NONE"
    for key, stage in CHECKS:
        if not reader.boolean(key):
            failure = stage
            break
        if stage == "DB_QUERY":
            account = reader.boolean("ACCOUNT_EXACTLY_ONE")
            selection = reader.boolean("MANUAL_SELECTED_EXACTLY_ONE")
            if not account or not selection:
                failure = (
                    "ACCOUNT_CARDINALITY"
                    if not account
                    else "MANUAL_SELECTION_CARDINALITY"
                )
                break
        if stage == "HISTORY_STATE_READ":
            for state in (
                "INITIAL_STATE",
                "HISTORY_COMPLETE_BEFORE",
                "BACKFILL_CURSOR_PRESENT_BEFORE",
            ):
                reader.boolean(state)
    reader.take("FAILURE_SUBSTAGE", (failure,))
    reader.take(
        "RAW_EXCEPTION_CLASS",
        ("NONE",) if failure == "NONE" else EXCEPTION_CLASSES - {"NONE"},
    )
    reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
    reader.take("M4AN2_CHILD_TERMINAL", ("complete",))
    return failure


def blocked(reader, cause):
    reader.take("M4AM_GENERIC_DB_STAGE_CAUSE", (cause,))
    reader.take(TERMINAL, ("blocked",))


def remote(reader):
    if reader.lines and reader.lines[0] == "REMOTE_REPO_PASS=false\n":
        reader.take("REMOTE_REPO_PASS", ("false",))
        return blocked(reader, "REMOTE_REPO")
    guards = [
        reader.boolean(key)
        for key in (
            "REMOTE_HEAD_PASS",
            "REMOTE_PRODUCTION_REF_PASS",
            "REMOTE_WORKTREE_CLEAN",
        )
    ]
    if not all(guards):
        return blocked(reader, "REMOTE_GUARD")
    for stage in (
        "COMPOSE_CONFIG",
        "DB_RUNNING",
        "API_RUNNING",
        "WORKER_RUNNING",
        "DB_HEALTH",
    ):
        if not reader.boolean(f"{stage}_PASS"):
            return blocked(reader, stage)
    reader.take("ALEMBIC_CHECK_STARTED", ("true",))
    if not reader.boolean("ALEMBIC_0046_PASS"):
        return blocked(reader, "ALEMBIC")
    reader.take("CHILD_STARTED", ("true",))
    rc_ok = reader.boolean("CHILD_RETURN_CODE_ZERO")
    stderr = reader.boolean("CHILD_STDERR_PRESENT")
    if (
        reader.pos < len(reader.lines)
        and reader.lines[reader.pos] == "CHILD_TERMINAL_RESULT=invalid\n"
    ):
        reader.take("CHILD_TERMINAL_RESULT", ("invalid",))
        return blocked(reader, "CHILD_PROTOCOL")
    failure = child(reader)
    reader.take("CHILD_TERMINAL_RESULT", ("valid",))
    if failure != "NONE":
        cause = failure
    elif stderr:
        cause = "CHILD_STDERR_COLLAPSE"
    elif rc_ok:
        cause = "NOT_REPRODUCED_PRE_PROVIDER"
    else:
        cause = "CHILD_EXECUTION"
    reader.take("M4AM_GENERIC_DB_STAGE_CAUSE", (cause,))
    # Keep the existing bare ready marker compatible with human transcripts.
    reader.marker("TELEGRAM_MTPROTO_M4AN2_STRUCTURAL_READY")
    reader.take(TERMINAL, ("structural",))


def main():
    reader = Reader("")
    try:
        text = Path(sys.argv[2]).read_bytes().decode("utf-8")
        reader = Reader(text)
        (child if sys.argv[1] == "child" else remote)(reader)
        reader.end()
    except Incomplete:
        code = 3
    except (ValueError, OSError):
        code = 2
    else:
        code = 0
    # Child output is atomic; partial remote output contains only validated lines.
    if code == 0 or sys.argv[1] == "remote":
        print("".join(reader.safe), end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
