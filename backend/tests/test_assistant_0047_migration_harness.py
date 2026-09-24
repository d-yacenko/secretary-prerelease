from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
RELEASE = "296b4735f9473ea60ef22f1827ed94260603128e"
ROLLBACK = "42db393be50a4c3f20ce86dadc280d77bada3959"
MIGRATION = "backend/alembic/versions/0047_assistant_conversations.py"


def load_script(name: str):
    path = ROOT / "ops" / "production" / name
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.modules["deploy"] = load_script("deploy.py")
local = load_script("migrate_assistant_0047.py")
remote = load_script("remote_migrate_assistant_0047.py")


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
        "from_alembic": "0046",
        "health_url": "http://127.0.0.1:18080/health",
        "db": "db",
        "db_values": _db_env(),
        "release_db_values": _db_env(),
        "db_volume": ("volume", "name", "source"),
        "before_env": "env",
        "api": "old-api",
        "worker": "old-worker",
    }


def test_authorized_transition_is_exact():
    assert local.AUTHORIZED_RELEASE == RELEASE
    assert local.AUTHORIZED_ROLLBACK == ROLLBACK
    assert local.FROM_ALEMBIC == "0046"
    assert local.TO_ALEMBIC == "0047"
    assert local.AUTHORIZED_MIGRATION == MIGRATION
    local._require_authorized_transition(RELEASE, ROLLBACK, "0046", "0047")


@pytest.mark.parametrize(
    ("release", "rollback", "source", "target", "match"),
    [
        ("a" * 40, ROLLBACK, "0046", "0047", "authorized Assistant"),
        (RELEASE, "b" * 40, "0046", "0047", "authorized production base"),
        (RELEASE, ROLLBACK, "0041", "0047", "0046 to 0047"),
        (RELEASE, ROLLBACK, "0046", "0048", "0046 to 0047"),
    ],
)
def test_other_shas_or_revisions_are_rejected(release, rollback, source, target, match):
    with pytest.raises(local.DeployError, match=match):
        local._require_authorized_transition(release, rollback, source, target)


def test_remote_contract_rejects_other_transition():
    args = type("Args", (), {})()
    args.release_sha = "a" * 40
    args.rollback_sha = ROLLBACK
    args.from_alembic = "0046"
    args.to_alembic = "0047"
    with pytest.raises(remote.DeployError, match="preflight rejected"):
        remote.require_remote_contract(args)


def test_exact_migration_delta_accepts_only_0047(monkeypatch):
    monkeypatch.setattr(
        local,
        "_git",
        lambda *args: f"A\t{MIGRATION}" if args[:2] == ("diff", "--name-status") else "",
    )

    class Result:
        returncode = 0

    monkeypatch.setattr(local.subprocess, "run", lambda *args, **kwargs: Result())
    local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_exact_migration_delta_rejects_extra_file(monkeypatch):
    monkeypatch.setattr(
        local,
        "_git",
        lambda *args: "\n".join(
            (f"A\t{MIGRATION}", "A\tbackend/alembic/versions/0048_extra.py")
        ),
    )
    with pytest.raises(local.DeployError, match="exactly 0047"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_modified_or_renamed_alembic_file_is_rejected(monkeypatch):
    monkeypatch.setattr(
        local,
        "_git",
        lambda *args: f"M\t{MIGRATION}",
    )
    with pytest.raises(local.DeployError, match="authorized additive"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_modified_alembic_infrastructure_is_rejected(monkeypatch):
    monkeypatch.setattr(local, "_git", lambda *args: f"A\t{MIGRATION}")

    class Result:
        returncode = 1

    monkeypatch.setattr(local.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(local.DeployError, match="Alembic infrastructure changed"):
        local._require_exact_migration_delta(ROLLBACK, RELEASE)


def test_historical_telegram_harness_contract_is_unchanged():
    historical = (ROOT / "ops/production/migrate_deploy.py").read_text()
    remote_historical = (ROOT / "ops/production/remote_migrate_deploy.py").read_text()
    assert 'FROM_ALEMBIC = "0041"' in historical
    assert 'TO_ALEMBIC = "0046"' in historical
    assert "0047_assistant_conversations.py" not in historical
    assert "telegram_mtproto_accounts" in remote_historical
    assert "require_telegram=True" in remote_historical


def test_remote_rollout_preserves_db_and_has_no_new_provider_requirement():
    source = (ROOT / "ops/production/remote_migrate_assistant_0047.py").read_text()
    assert '"--env-file"' in source
    assert "str(ENV)" in source
    assert 'compose("run", "--rm", "--no-deps", "api", "alembic", "upgrade", args.to_alembic)' in source
    assert 'compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")' in source
    assert 'compose("up", "-d", "--no-deps", "--force-recreate", "db")' not in source
    assert '"docker", "rm"' not in source
    assert "DELETE FROM" not in source
    assert "TELEGRAM_API_HASH" not in source
    assert "require_db_identity(db, before_volume, before_env)" in source
    assert 'require_db_revision(db, db_values, "0047")' in source
    assert 'compose("run", "--rm", "--no-deps", "api", "alembic", "downgrade", from_alembic)' in source
    main_position = source.index("def main()")
    positions = [
        source.index('compose("build", "api", "worker")', main_position),
        source.index("stop_applications(api, worker)", main_position),
        source.index(
            'compose("run", "--rm", "--no-deps", "api", "alembic", "upgrade", args.to_alembic)'
        ),
        source.index('require_db_revision(db, release_api_env, args.to_alembic)', main_position),
        source.rindex('compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")'),
    ]
    assert positions == sorted(positions)


def test_db_identity_change_is_rejected(monkeypatch):
    monkeypatch.setattr(remote, "service_id", lambda name: "db")
    monkeypatch.setattr(remote, "volume", lambda container: ("volume", "other", "source"))
    monkeypatch.setattr(remote, "env_hash", lambda: "env")
    with pytest.raises(remote.DeployError, match="identity changed"):
        remote.require_db_identity("db", ("volume", "name", "source"), "env")


def test_restore_rejects_changed_db_identity(monkeypatch):
    monkeypatch.setattr(remote, "git", lambda *args: "")
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: "")
    monkeypatch.setattr(remote, "service_id", lambda name: "db" if name == "db" else "new")
    monkeypatch.setattr(remote, "volume", lambda container: ("volume", "changed", "source"))
    monkeypatch.setattr(remote, "env_hash", lambda: "env")
    assert (
        remote.restore_old(
            ROLLBACK,
            "0046",
            "http://health",
            "db",
            _db_env(),
            ("volume", "name", "source"),
            "env",
            "old-api",
            "old-worker",
        )
        is False
    )


def test_release_environment_does_not_require_telegram_credentials():
    values = _db_env()
    remote.require_release_environment(values, values, values, values)


def test_release_environment_db_change_is_rejected():
    rollback = _db_env()
    release = {**rollback, "POSTGRES_PASSWORD": "other-password"}
    with pytest.raises(remote.DeployError, match="DB or credential"):
        remote.require_release_environment(rollback, rollback, release, release)


def test_pre_cutover_downgrade_does_not_query_assistant_tables(monkeypatch):
    calls = []
    monkeypatch.setattr(
        remote,
        "assistant_tables_empty",
        lambda *args, **kwargs: pytest.fail("empty query must not run"),
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
    assert ("run", "--rm", "--no-deps", "api", "alembic", "downgrade", "0046") in calls
    assert ("revision", "0046") in calls


def test_post_cutover_downgrade_runs_only_when_both_tables_are_empty(monkeypatch):
    calls = []

    def prove(db, values):
        calls.append("prove")
        assert remote.assistant_tables_empty(db, values) is True

    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda container: False)
    monkeypatch.setattr(
        remote,
        "require_db_revision",
        lambda db, values, expected: calls.append(("revision", expected)),
    )

    def query(cmd, **kwargs):
        assert "SELECT count(*) FROM assistant_messages" in cmd or (
            "SELECT count(*) FROM assistant_conversations" in cmd
        )
        return "0"

    monkeypatch.setattr(remote, "run", query)
    monkeypatch.setattr(remote, "prove_post_cutover_rollback_safe", prove)
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: True)
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 0
    assert calls[0] == ("stop", "api", "worker")
    assert "prove" in calls
    assert ("run", "--rm", "--no-deps", "api", "alembic", "downgrade", "0046") in calls


def test_assistant_empty_requires_both_tables(monkeypatch):
    seen = []

    def query(cmd, **kwargs):
        seen.append(cmd[-1])
        if "assistant_messages" in cmd[-1]:
            return "0"
        return "0"

    monkeypatch.setattr(remote, "run", query)
    assert remote.assistant_tables_empty("db", _db_env()) is True
    assert seen == [
        "SELECT count(*) FROM assistant_messages",
        "SELECT count(*) FROM assistant_conversations",
    ]


@pytest.mark.parametrize("bad", ["1", ""])
def test_nonempty_assistant_table_blocks_downgrade(monkeypatch, bad, capsys):
    calls = []

    def query(cmd, **kwargs):
        if "assistant_messages" in cmd[-1]:
            return bad
        return "0"

    monkeypatch.setattr(remote, "run", query)
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda container: False)
    monkeypatch.setattr(remote, "require_db_revision", lambda *args: None)
    monkeypatch.setattr(remote, "restore_old", lambda *args, **kwargs: pytest.fail("restore"))
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 2
    assert not any("downgrade" in arg for call in calls for arg in call)
    error = capsys.readouterr().err
    assert "BREAK_GLASS_REQUIRED=true" in error
    assert "db-password" not in error
    assert "credential-key" not in error


def test_unknown_assistant_table_state_blocks_downgrade(monkeypatch, capsys):
    calls = []

    def query(cmd, **kwargs):
        raise remote.DeployError("sensitive preflight failed")

    monkeypatch.setattr(remote, "run", query)
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda container: False)
    monkeypatch.setattr(remote, "require_db_revision", lambda *args: None)
    code = remote.recover_failed_rollout(live=True, migration_started=True, **_recovery_kwargs())
    assert code == 2
    assert not any("downgrade" in arg for call in calls for arg in call)
    error = capsys.readouterr().err
    assert "BREAK_GLASS_REQUIRED=true" in error
    assert "sensitive preflight failed" not in error


def test_running_writer_blocks_before_empty_query(monkeypatch):
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda container: container == "api-current")
    monkeypatch.setattr(
        remote,
        "assistant_tables_empty",
        lambda *args: pytest.fail("empty query must not run"),
    )
    with pytest.raises(remote.DeployError, match="did not stop"):
        remote.prove_post_cutover_rollback_safe("db", _db_env())
