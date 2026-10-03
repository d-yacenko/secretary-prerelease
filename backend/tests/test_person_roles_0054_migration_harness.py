from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
ROLLBACK = "2314bf72101fbd83d50a7b264154d73740e28db1"
RELEASE = "6f802d6959aca40758376a83d5bdfcbbd77fc537"
MIGRATIONS = (
    "backend/alembic/versions/0053_person_role_vocabulary.py",
    "backend/alembic/versions/0054_person_role_key_width.py",
)


def load_script(name: str):
    path = ROOT / "ops" / "production" / name
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.modules["deploy"] = load_script("deploy.py")
local = load_script("migrate_person_roles_0054.py")
remote = load_script("remote_migrate_person_roles_0054.py")


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
        "from_alembic": "0052",
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
    args.from_alembic = "0052"
    args.to_alembic = "0054"
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _added(*paths: str) -> str:
    return "\n".join(f"A\t{path}" for path in paths)


def test_authorized_constants_are_exact():
    assert local.AUTHORIZED_RELEASE == RELEASE
    assert remote.AUTHORIZED_RELEASE == RELEASE
    assert local.AUTHORIZED_ROLLBACK == ROLLBACK
    assert remote.AUTHORIZED_ROLLBACK == ROLLBACK
    assert local.FROM_ALEMBIC == "0052"
    assert local.TO_ALEMBIC == "0054"
    assert remote.FROM_ALEMBIC == "0052"
    assert remote.TO_ALEMBIC == "0054"
    assert local.AUTHORIZED_MIGRATIONS == MIGRATIONS
    assert local.REVISION_CHAIN == (
        (MIGRATIONS[0], "0053", "0052"),
        (MIGRATIONS[1], "0054", "0053"),
    )


def test_authorized_pair_accepts_exact_0052_to_0054_delta():
    local._require_authorized_transition(RELEASE, ROLLBACK, "0052", "0054")
    local._require_ancestry(ROLLBACK, RELEASE)
    local._require_exact_migration_delta(ROLLBACK, RELEASE)
    local._require_revision_chain(RELEASE)


def test_wrong_release_sha_is_rejected():
    with pytest.raises(local.DeployError, match="authorized REL1 release"):
        local._require_authorized_transition("a" * 40, ROLLBACK, "0052", "0054")


def test_wrong_rollback_sha_is_rejected():
    with pytest.raises(local.DeployError, match="authorized production base"):
        local._require_authorized_transition(RELEASE, "b" * 40, "0052", "0054")


@pytest.mark.parametrize(
    ("source", "target"),
    [("0051", "0054"), ("0052", "0053"), ("0053", "0054")],
)
def test_wrong_revisions_are_rejected(source, target):
    with pytest.raises(local.DeployError, match="0052 to 0054"):
        local._require_authorized_transition(RELEASE, ROLLBACK, source, target)


def test_rollback_must_be_ancestor(monkeypatch):
    class Result:
        returncode = 1

    monkeypatch.setattr(local.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(local.DeployError, match="not an ancestor"):
        local._require_ancestry(ROLLBACK, RELEASE)


def test_exact_migration_delta_rejects_extra_file(monkeypatch):
    monkeypatch.setattr(
        local,
        "_git",
        lambda *args: _added(*MIGRATIONS, "backend/alembic/versions/0055_extra.py"),
    )
    with pytest.raises(local.DeployError, match="exactly"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_modified_preexisting_migration_is_rejected(monkeypatch):
    monkeypatch.setattr(
        local,
        "_git",
        lambda *args: (
            "M\tbackend/alembic/versions/0052_task_layout_positions.py\n" + _added(*MIGRATIONS)
        ),
    )
    with pytest.raises(local.DeployError, match="authorized additive"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_changed_alembic_infrastructure_is_rejected(monkeypatch):
    monkeypatch.setattr(local, "_git", lambda *args: _added(*MIGRATIONS))

    class Result:
        returncode = 1

    monkeypatch.setattr(local.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(local.DeployError, match="Alembic infrastructure changed"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_wrong_revision_chain_is_rejected(monkeypatch):
    monkeypatch.setattr(
        local,
        "_git",
        lambda *args: 'revision: str = "0054"\ndown_revision: str | None = "0052"\n',
    )
    with pytest.raises(local.DeployError, match="0052 to 0054"):
        local._require_revision_chain(RELEASE)


def test_remote_requires_origin_production_equals_release():
    remote.require_production_ref(RELEASE, RELEASE)
    with pytest.raises(remote.DeployError, match="not the authorized release"):
        remote.require_production_ref(ROLLBACK, RELEASE)


def test_pinned_host_key_contract_is_preserved():
    source = (ROOT / "ops/production/migrate_person_roles_0054.py").read_text()
    assert "_require_canonical_local_checkout" in source
    assert "_load_target" in source
    assert "_verified_known_hosts" in source
    assert "StrictHostKeyChecking=yes" in source
    assert "GlobalKnownHostsFile=/dev/null" in source
    assert "UserKnownHostsFile=" in source
    assert 'target["host_key_sha256"]' in source
    assert "BatchMode=yes" in source
    assert "web-itx" not in source


def test_remote_builds_before_downtime_and_checks_structure_before_start():
    source = (ROOT / "ops/production/remote_migrate_person_roles_0054.py").read_text()
    main = source[source.index("def main()") :]
    positions = [
        main.index("rollout_action("),
        main.index('compose("build", "api", "worker")'),
        main.index("stop_applications(api, worker)"),
        main.index('"alembic", "upgrade", args.to_alembic'),
        main.index("require_post_migration_structure(db, release_api_env, require_empty=True)"),
        main.index('compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")'),
    ]
    assert positions == sorted(positions)
    assert 'compose("up", "-d", "--no-deps", "--force-recreate", "db")' not in source
    assert "DELETE FROM" not in source
    assert "TRUNCATE" not in source
    assert '"docker", "rm"' not in source
    assert "/graph/people" not in source
    idempotent = main[main.index('if action == "idempotent"') : main.index("stopped = False")]
    assert "require_db_identity" in idempotent
    assert "require_post_migration_structure" in idempotent
    assert "require_empty=False" in idempotent
    assert "upgrade" not in idempotent
    assert "force-recreate" not in idempotent


def test_migration_requires_stopped_api_and_worker(monkeypatch):
    monkeypatch.setattr(remote, "running", lambda container: True)
    with pytest.raises(remote.DeployError, match="did not stop"):
        remote.require_stopped("api", "worker")


def test_pre_cutover_empty_tables_can_downgrade(monkeypatch):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(
        remote,
        "require_db_revision",
        lambda db, values, expected: calls.append(("revision", expected)),
    )
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: True)

    def query(cmd, **kwargs):
        assert cmd[-1] == remote.EMPTY_SQL
        return "0|0"

    monkeypatch.setattr(remote, "run", query)
    code = remote.recover_failed_rollout(live=False, migration_started=True, **_recovery_kwargs())
    assert code == 0
    assert ("run", "--rm", "--no-deps", "api", "alembic", "downgrade", "0052") in calls
    assert ("revision", "0052") in calls


@pytest.mark.parametrize("row", ["1|0", "0|1", "2|3"])
def test_pre_cutover_nonempty_tables_do_not_downgrade(monkeypatch, capsys, row):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: pytest.fail("restore"))
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: row)
    code = remote.recover_failed_rollout(live=False, migration_started=True, **_recovery_kwargs())
    assert code == 2
    assert not any("downgrade" in arg for call in calls for arg in call)
    error = capsys.readouterr().err
    assert "tables_not_proven_empty" in error
    assert "BREAK_GLASS_REQUIRED=true" in error
    assert "db-password" not in error


def test_pre_cutover_unreadable_tables_do_not_downgrade(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")

    def fail(cmd, **kwargs):
        raise remote.DeployError("sensitive preflight failed")

    monkeypatch.setattr(remote, "run", fail)
    code = remote.recover_failed_rollout(live=False, migration_started=True, **_recovery_kwargs())
    assert code == 2
    assert not any("downgrade" in arg for call in calls for arg in call)
    error = capsys.readouterr().err
    assert "tables_not_proven_empty" in error
    assert "BREAK_GLASS_REQUIRED=true" in error
    assert "sensitive preflight failed" not in error


def _post_cutover(monkeypatch, row: str):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda container: False)
    monkeypatch.setattr(remote, "require_db_revision", lambda *args: None)
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: True)

    def query(cmd, **kwargs):
        assert cmd[-1] == remote.EMPTY_SQL
        return row

    monkeypatch.setattr(remote, "run", query)
    return calls


def test_post_cutover_empty_state_can_downgrade(monkeypatch):
    calls = _post_cutover(monkeypatch, "0|0")
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 0
    assert ("stop", "api", "worker") in calls
    assert ("run", "--rm", "--no-deps", "api", "alembic", "downgrade", "0052") in calls


@pytest.mark.parametrize("row", ["1|0", "0|1"])
def test_post_cutover_rows_block_downgrade(monkeypatch, capsys, row):
    calls = _post_cutover(monkeypatch, row)
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 2
    assert not any("downgrade" in arg for call in calls for arg in call)
    error = capsys.readouterr().err
    assert "BREAK_GLASS_REQUIRED=true" in error
    assert "post_cutover_role_rows" in error
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


def test_rollout_state_machine_accepts_only_two_states():
    assert remote.rollout_action(ROLLBACK, RELEASE, "0052") == "migrate"
    assert remote.rollout_action(RELEASE, RELEASE, "0054") == "idempotent"


@pytest.mark.parametrize(
    ("head", "revision"),
    [(RELEASE, "0052"), (ROLLBACK, "0054"), ("c" * 40, "0052")],
)
def test_inconsistent_release_revision_fails_closed(head, revision):
    with pytest.raises(remote.DeployError, match="inconsistent"):
        remote.rollout_action(head, RELEASE, revision)


def test_sensitive_command_failure_does_not_print_secrets(monkeypatch):
    class Proc:
        returncode = 1
        stdout = "POSTGRES_PASSWORD=db-password"
        stderr = "POSTGRES_PASSWORD=db-password"

    monkeypatch.setattr(remote.subprocess, "run", lambda *args, **kwargs: Proc())
    with pytest.raises(remote.DeployError, match="sensitive preflight failed") as exc:
        remote.run(["psql"], sensitive=True)
    assert "db-password" not in str(exc.value)


def test_structure_check_accepts_empty_new_tables(monkeypatch, capsys):
    answers = iter(("|".join(remote.EXPECTED_STRUCTURE), "0|0"))
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: next(answers))
    remote.require_post_migration_structure("db", _db_env(), require_empty=True)
    out = capsys.readouterr().out
    assert "PERSON_ROLE_TERMS_TABLE=true" in out
    assert "PERSON_ROLE_ASSIGNMENTS_TABLE=true" in out
    assert "TERMS_REQUIRED_COLUMNS=6" in out
    assert "ASSIGNMENTS_REQUIRED_COLUMNS=14" in out
    assert "DISPLAY_TEXT_VARCHAR_120=true" in out
    assert "NORMALIZED_KEY_VARCHAR_360=true" in out
    assert "CONTEXT_TEXT_VARCHAR_200=true" in out
    assert "CONTEXT_KEY_VARCHAR_600=true" in out
    assert "TERMS_NAMED_CHECKS=2" in out
    assert "ASSIGNMENTS_NAMED_CHECKS=7" in out
    assert "USER_KEY_UNIQUE=true" in out
    assert "ACTIVE_ASSIGNMENT_INDEX=true" in out
    assert "RESTRICT_FOREIGN_KEYS=5" in out
    assert "PERSON_ROLE_TERMS_ROWS=0" in out
    assert "PERSON_ROLE_ASSIGNMENTS_ROWS=0" in out


def test_structure_check_rejects_missing_shape(monkeypatch):
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: "1|1|6|14|1|1|1|1|2|7|0|1|1|1|5")
    with pytest.raises(remote.DeployError, match="structure check failed"):
        remote.require_post_migration_structure("db", _db_env(), require_empty=True)


def test_structure_check_rejects_rows_before_runtime(monkeypatch):
    answers = iter(("|".join(remote.EXPECTED_STRUCTURE), "0|1"))
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: next(answers))
    with pytest.raises(remote.DeployError, match="structure check failed"):
        remote.require_post_migration_structure("db", _db_env(), require_empty=True)


def test_idempotent_structure_allows_later_rows(monkeypatch, capsys):
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: "|".join(remote.EXPECTED_STRUCTURE))
    remote.require_post_migration_structure("db", _db_env(), require_empty=False)
    out = capsys.readouterr().out
    assert "PERSON_ROLE_TERMS_ROWS" not in out
    assert "PERSON_ROLE_ASSIGNMENTS_ROWS" not in out


def test_remote_contract_rejects_wrong_identities():
    with pytest.raises(remote.DeployError, match="preflight rejected"):
        remote.require_remote_contract(_args(rollback_sha="b" * 40))
    with pytest.raises(remote.DeployError, match="preflight rejected"):
        remote.require_remote_contract(_args(release_sha="a" * 40))
    with pytest.raises(remote.DeployError, match="preflight rejected"):
        remote.require_remote_contract(_args(from_alembic="0052", to_alembic="0053"))


def test_schema_neutral_deploy_guard_remains():
    source = (ROOT / "ops/production/deploy.py").read_text()
    assert "MIGRATION_PATHS" in source
    assert "0053_person_role_vocabulary.py" not in source
    assert "0054_person_role_key_width.py" not in source
    assert "separate migration deployment plan required" in source


def test_stopped_before_migration_restores_without_downgrade(monkeypatch):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: True)
    code = remote.recover_failed_rollout(live=False, migration_started=False, **_recovery_kwargs())
    assert code == 0
    assert not any("downgrade" in arg for call in calls for arg in call)
