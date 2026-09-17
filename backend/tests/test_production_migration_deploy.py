from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def load_script(name: str):
    path = ROOT / "ops" / "production" / name
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.modules["deploy"] = load_script("deploy.py")
migrate = load_script("migrate_deploy.py")
remote = load_script("remote_migrate_deploy.py")


def test_migration_arguments_are_exact():
    assert migrate.FROM_ALEMBIC == "0041"
    assert migrate.TO_ALEMBIC == "0046"
    assert len(migrate.AUTHORIZED_MIGRATIONS) == 5


def test_malformed_sha_is_rejected():
    with pytest.raises(migrate.DeployError, match="exact 40-character"):
        migrate._validate_sha("release-sha", "not-a-sha")


def test_normal_deploy_guard_rejects_migration_bearing_release(monkeypatch):
    class Result:
        returncode = 1

    normal = load_script("deploy.py")
    monkeypatch.setattr(normal, "_run_local", lambda *args: "")
    monkeypatch.setattr(normal.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(normal.DeployError, match="migration infrastructure"):
        normal._require_schema_neutral_release("a" * 40, "b" * 40)


def test_non_ancestor_rollback_is_rejected(monkeypatch):
    class Result:
        returncode = 1

    monkeypatch.setattr(migrate.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(migrate.DeployError, match="not an ancestor"):
        migrate._require_ancestry("a" * 40, "b" * 40)


def test_exact_migration_delta_rejects_extra_file(monkeypatch):
    expected = sorted(migrate.AUTHORIZED_MIGRATIONS)
    monkeypatch.setattr(
        migrate,
        "_git",
        lambda *args: "\n".join(f"A\t{path}" for path in expected + ["backend/alembic/versions/0047_bad.py"])
        if args[:2] == ("diff", "--name-status")
        else "",
    )
    with pytest.raises(migrate.DeployError, match="exactly 0042"):
        migrate._require_exact_migration_delta("a" * 40, "b" * 40)


def test_normal_harness_still_has_schema_neutral_guard():
    source = (ROOT / "ops/production/deploy.py").read_text()
    assert "_require_schema_neutral_release" in source
    assert "release changes migration infrastructure" in source


def test_remote_uses_explicit_compose_and_only_application_rollout():
    source = (ROOT / "ops/production/remote_migrate_deploy.py").read_text()
    assert '"--env-file", str(ENV)' in source
    assert '"-f", "infra/compose.yaml"' in source
    assert '"-f", "infra/compose.deploy.yaml"' in source
    assert 'compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")' in source
    assert 'compose("up", "-d", "--no-deps", "--force-recreate", "db")' not in source
    assert '"docker", "rm"' not in source


def test_build_stop_migrate_verify_start_order():
    source = (ROOT / "ops/production/remote_migrate_deploy.py").read_text()
    positions = [
        source.index('compose("build", "api", "worker")'),
        source.index('compose("stop", "api", "worker")'),
        source.index('compose("run", "--rm", "--no-deps", "api", "alembic", "upgrade", args.to_alembic)'),
        source.index('revision(args.to_alembic)', source.index('compose("run"')),
        source.rindex('compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")'),
    ]
    assert positions == sorted(positions)


def test_db_auth_is_tcp_and_password_is_environment_only():
    source = (ROOT / "ops/production/remote_migrate_deploy.py").read_text()
    assert '"-e", "PGPASSWORD"' in source
    assert '"-h", "127.0.0.1"' in source
    assert 'f"PGPASSWORD=' not in source
    assert "PGPASSWORD={" not in source


def test_mtproto_uncertainty_refuses_downgrade(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        raise remote.DeployError("query failed")

    monkeypatch.setattr(remote, "run", fake_run)
    with pytest.raises(remote.DeployError, match="prove MTProto"):
        remote.mtproto_empty("db", {"POSTGRES_PASSWORD": "secret"})
    assert not any("downgrade" in item for call in calls for item in call)


def test_mtproto_nonempty_blocks_downgrade(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return "1" if "count(*)" in cmd else ""

    monkeypatch.setattr(remote, "run", fake_run)
    assert remote.mtproto_empty("db", {"POSTGRES_PASSWORD": "secret"}) is False
    assert not any("downgrade" in item for call in calls for item in call)


def test_rollback_scope_is_application_only_and_no_ref_move():
    source = (ROOT / "ops/production/remote_migrate_deploy.py").read_text()
    assert 'compose("build", "api", "worker")' in source
    assert 'compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")' in source
    assert 'git("push"' not in source
    assert 'git("fetch"' in source
