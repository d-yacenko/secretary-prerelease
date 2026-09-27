from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
ROLLBACK = "296b4735f9473ea60ef22f1827ed94260603128e"
RELEASE = "a" * 40
MIGRATIONS = (
    "backend/alembic/versions/0048_person_identities.py",
    "backend/alembic/versions/0049_person_identity_evidence.py",
    "backend/alembic/versions/0050_task_completion_mode.py",
)


def load_script(name: str):
    path = ROOT / "ops" / "production" / name
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.modules["deploy"] = load_script("deploy.py")
local = load_script("migrate_people_tasks_0050.py")
remote = load_script("remote_migrate_people_tasks_0050.py")


def _db_env() -> dict[str, str]:
    return {
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "secretary",
        "POSTGRES_USER": "secretary",
        "POSTGRES_PASSWORD": "db-password",
        "SECRETARY_CREDENTIAL_KEY": "credential-key",
    }


def _recovery_kwargs() -> dict:
    return {
        "rollback": ROLLBACK,
        "from_alembic": "0047",
        "health_url": "http://127.0.0.1:18080/health",
        "db": "db",
        "db_values": _db_env(),
        "release_db_values": _db_env(),
        "db_volume": ("volume", "name", "source"),
        "before_env": "env",
        "api": "old-api",
        "worker": "old-worker",
    }


def _args(**overrides):
    args = type("Args", (), {})()
    args.release_sha = RELEASE
    args.rollback_sha = ROLLBACK
    args.from_alembic = "0047"
    args.to_alembic = "0050"
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_current_main_accepts_exact_0047_to_0050_delta():
    release = local._git("rev-parse", "HEAD")
    local._require_authorized_transition(release, ROLLBACK, "0047", "0050")
    local._require_ancestry(ROLLBACK, release)
    local._require_exact_migration_delta(ROLLBACK, release)
    local._require_revision_chain(release)


def test_exact_migration_delta_rejects_extra_file(monkeypatch):
    rows = [f"A\t{path}" for path in MIGRATIONS]
    rows.append("A\tbackend/alembic/versions/0051_extra.py")
    monkeypatch.setattr(local, "_git", lambda *args: "\n".join(rows))
    with pytest.raises(local.DeployError, match="exactly 0048, 0049, and 0050"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_modified_preexisting_migration_is_rejected(monkeypatch):
    monkeypatch.setattr(
        local,
        "_git",
        lambda *args: "\n".join(
            (
                "M\tbackend/alembic/versions/0047_assistant_conversations.py",
                *[f"A\t{path}" for path in MIGRATIONS],
            )
        ),
    )
    with pytest.raises(local.DeployError, match="authorized additive"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_changed_alembic_infrastructure_is_rejected(monkeypatch):
    monkeypatch.setattr(local, "_git", lambda *args: "\n".join(f"A\t{path}" for path in MIGRATIONS))

    class Result:
        returncode = 1

    monkeypatch.setattr(local.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(local.DeployError, match="Alembic infrastructure changed"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_wrong_rollback_sha_is_rejected():
    with pytest.raises(local.DeployError, match="authorized production base"):
        local._require_authorized_transition(RELEASE, "b" * 40, "0047", "0050")


@pytest.mark.parametrize(
    ("source", "target"),
    [("0046", "0050"), ("0047", "0049"), ("0048", "0050")],
)
def test_wrong_revisions_are_rejected(source, target):
    with pytest.raises(local.DeployError, match="0047 to 0050"):
        local._require_authorized_transition(RELEASE, ROLLBACK, source, target)


def test_remote_requires_origin_production_equals_release():
    remote.require_production_ref(RELEASE, RELEASE)
    with pytest.raises(remote.DeployError, match="not the authorized release"):
        remote.require_production_ref(ROLLBACK, RELEASE)


def test_pinned_host_key_contract_is_preserved():
    source = (ROOT / "ops/production/migrate_people_tasks_0050.py").read_text()
    assert "_verified_known_hosts" in source
    assert "StrictHostKeyChecking=yes" in source
    assert "GlobalKnownHostsFile=/dev/null" in source
    assert "UserKnownHostsFile=" in source
    assert 'target["host_key_sha256"]' in source
    assert "BatchMode=yes" in source


def test_remote_builds_before_downtime_and_checks_structure_before_start():
    source = (ROOT / "ops/production/remote_migrate_people_tasks_0050.py").read_text()
    main = source[source.index("def main()") :]
    positions = [
        main.index("rollout_action("),
        main.index('compose("build", "api", "worker")'),
        main.index("stop_applications(api, worker)"),
        main.index('"alembic", "upgrade", args.to_alembic'),
        main.index("require_post_migration_structure(db, release_api_env)"),
        main.index('compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")'),
    ]
    assert positions == sorted(positions)
    assert 'compose("up", "-d", "--no-deps", "--force-recreate", "db")' not in source
    assert "DELETE FROM" not in source
    assert '"docker", "rm"' not in source


def test_migration_requires_stopped_api_and_worker(monkeypatch):
    monkeypatch.setattr(remote, "running", lambda container: True)
    with pytest.raises(remote.DeployError, match="did not stop"):
        remote.require_stopped("api", "worker")


def test_pre_cutover_failure_downgrades_to_0047(monkeypatch):
    calls = []
    monkeypatch.setattr(
        remote,
        "prove_post_cutover_release_data_absent",
        lambda *args, **kwargs: pytest.fail("safety query must not run"),
    )
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(
        remote,
        "require_db_revision",
        lambda db, values, expected: calls.append(("revision", expected)),
    )
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: True)
    code = remote.recover_failed_rollout(live=False, migration_started=True, **_recovery_kwargs())
    assert code == 0
    assert ("run", "--rm", "--no-deps", "api", "alembic", "downgrade", "0047") in calls
    assert ("revision", "0047") in calls


def _post_cutover(monkeypatch, row: str):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda container: False)
    monkeypatch.setattr(remote, "require_db_revision", lambda *args: None)
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: True)

    def query(cmd, **kwargs):
        assert cmd[-1] == remote.SAFETY_SQL
        return row

    monkeypatch.setattr(remote, "run", query)
    return calls


def test_post_cutover_empty_state_can_downgrade(monkeypatch):
    calls = _post_cutover(monkeypatch, "0|0|0")
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 0
    assert ("run", "--rm", "--no-deps", "api", "alembic", "downgrade", "0047") in calls


@pytest.mark.parametrize(
    "row",
    ["1|0|0", "0|1|0", "0|0|1"],
)
def test_post_cutover_release_data_blocks_downgrade(monkeypatch, row, capsys):
    calls = _post_cutover(monkeypatch, row)
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 2
    assert not any("downgrade" in arg for call in calls for arg in call)
    error = capsys.readouterr().err
    assert "BREAK_GLASS_REQUIRED=true" in error
    assert "db-password" not in error
    assert "DELETE" not in error


def test_post_cutover_safety_query_failure_blocks_downgrade(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda container: False)
    monkeypatch.setattr(remote, "require_db_revision", lambda *args: None)

    def query(cmd, **kwargs):
        raise remote.DeployError("sensitive preflight failed")

    monkeypatch.setattr(remote, "run", query)
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 2
    assert not any("downgrade" in arg for call in calls for arg in call)
    error = capsys.readouterr().err
    assert "BREAK_GLASS_REQUIRED=true" in error
    assert "sensitive preflight failed" not in error


def test_idempotent_release_does_not_migrate():
    assert remote.rollout_action(RELEASE, RELEASE, "0050") == "idempotent"


def test_inconsistent_release_revision_fails_closed():
    with pytest.raises(remote.DeployError, match="inconsistent"):
        remote.rollout_action(RELEASE, RELEASE, "0047")
    with pytest.raises(remote.DeployError, match="inconsistent"):
        remote.rollout_action(ROLLBACK, RELEASE, "0050")


def test_sensitive_command_failure_does_not_print_secrets(monkeypatch):
    class Proc:
        returncode = 1
        stdout = "POSTGRES_PASSWORD=db-password"
        stderr = "POSTGRES_PASSWORD=db-password"

    monkeypatch.setattr(remote.subprocess, "run", lambda *args, **kwargs: Proc())
    with pytest.raises(remote.DeployError, match="sensitive preflight failed") as exc:
        remote.run(["psql"], sensitive=True)
    assert "db-password" not in str(exc.value)


def test_structure_check_accepts_only_counts(monkeypatch, capsys):
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: "1|1|1|0|0|0")
    remote.require_post_migration_structure("db", _db_env())
    out = capsys.readouterr().out
    assert "TASK_NULL_COMPLETION_MODE=0" in out
    assert "NON_TASK_COMPLETION_MODE=0" in out
    assert "title" not in out.lower()


def test_structure_check_rejects_null_task_mode(monkeypatch):
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: "1|1|1|1|0|0")
    with pytest.raises(remote.DeployError, match="structure check failed"):
        remote.require_post_migration_structure("db", _db_env())


def test_remote_contract_rejects_wrong_rollback():
    with pytest.raises(remote.DeployError, match="preflight rejected"):
        remote.require_remote_contract(_args(rollback_sha="b" * 40))


def test_schema_neutral_deploy_guard_remains():
    source = (ROOT / "ops/production/deploy.py").read_text()
    assert "MIGRATION_PATHS" in source
    assert "0048_person_identities.py" not in source
