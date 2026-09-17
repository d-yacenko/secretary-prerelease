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
    main_position = source.index("def main()")
    positions = [
        source.index('compose("build", "api", "worker")', main_position),
        source.index("stop_applications(api, worker)", main_position),
        source.index('compose("run", "--rm", "--no-deps", "api", "alembic", "upgrade", args.to_alembic)'),
        source.index('require_db_revision(db, release_api_env, args.to_alembic)', main_position),
        source.rindex('compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")'),
    ]
    assert positions == sorted(positions)


def test_db_auth_is_tcp_and_password_is_environment_only():
    source = (ROOT / "ops/production/remote_migrate_deploy.py").read_text()
    assert '"-e", "PGPASSWORD"' in source
    assert '"-h", "127.0.0.1"' in source
    assert 'f"PGPASSWORD=' not in source
    assert "PGPASSWORD={" not in source


def test_stopped_verification_uses_captured_ids_not_compose_ps(monkeypatch):
    states = {"api-before": False, "worker-before": False}
    calls = []
    monkeypatch.setattr(remote, "running", lambda container: states[container])
    monkeypatch.setattr(remote, "service_id", lambda _: pytest.fail("compose ps must not be used"))
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args))
    remote.stop_applications("api-before", "worker-before")
    assert calls == [("stop", "api", "worker")]


def test_post_cutover_uses_stopped_aware_current_ids_and_orders_guards(monkeypatch):
    calls = []
    states = {"api-current": False, "worker-current": False}

    def fake_compose(*args, **kwargs):
        calls.append(("compose", args))
        if args[:3] == ("ps", "--all", "-q"):
            return {"api": "api-current", "worker": "worker-current"}[args[3]]
        return ""

    monkeypatch.setattr(remote, "compose", fake_compose)
    monkeypatch.setattr(remote, "running", lambda container: states[container])
    monkeypatch.setattr(
        remote,
        "require_db_revision",
        lambda db, values, expected: calls.append(("revision", expected)),
    )
    monkeypatch.setattr(
        remote,
        "mtproto_empty",
        lambda db, values: calls.append(("empty", None)) or True,
    )
    remote.prove_post_cutover_rollback_safe("db", {"POSTGRES_PASSWORD": "secret"})
    assert [kind for kind, _ in calls] == ["compose", "compose", "revision", "empty"]
    assert calls[2] == ("revision", "0046")


@pytest.mark.parametrize("running_container", ["api-current", "worker-current"])
def test_post_cutover_running_writer_blocks_before_empty_query(monkeypatch, running_container):
    states = {"api-current": running_container == "api-current", "worker-current": running_container == "worker-current"}
    empty_called = []
    monkeypatch.setattr(
        remote,
        "compose",
        lambda *args, **kwargs: {"api": "api-current", "worker": "worker-current"}[args[3]]
        if args[:3] == ("ps", "--all", "-q")
        else "",
    )
    monkeypatch.setattr(remote, "running", lambda container: states[container])
    monkeypatch.setattr(remote, "mtproto_empty", lambda *args: empty_called.append(True) or True)
    with pytest.raises(remote.DeployError, match="did not stop"):
        remote.prove_post_cutover_rollback_safe("db", {"POSTGRES_PASSWORD": "secret"})
    assert empty_called == []


def test_post_cutover_lookup_uncertainty_blocks_before_revision_or_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote, "require_db_revision", lambda *args: pytest.fail("revision must not run"))
    monkeypatch.setattr(remote, "mtproto_empty", lambda *args: pytest.fail("empty must not run"))
    with pytest.raises(remote.DeployError, match="current container"):
        remote.prove_post_cutover_rollback_safe("db", {"POSTGRES_PASSWORD": "secret"})


def test_post_cutover_revision_uncertainty_blocks_before_empty(monkeypatch):
    monkeypatch.setattr(remote, "current_service_id", lambda name: f"{name}-current")
    monkeypatch.setattr(remote, "running", lambda _: False)
    monkeypatch.setattr(remote, "require_db_revision", lambda *args: (_ for _ in ()).throw(remote.DeployError("revision query failed")))
    monkeypatch.setattr(remote, "mtproto_empty", lambda *args: pytest.fail("empty must not run"))
    with pytest.raises(remote.DeployError, match="revision query"):
        remote.prove_post_cutover_rollback_safe("db", {"POSTGRES_PASSWORD": "secret"})


def test_post_cutover_stop_failure_blocks_before_empty_or_downgrade(monkeypatch):
    empty_called = []

    def stop_failure(*args, **kwargs):
        raise remote.DeployError("stop failed")

    monkeypatch.setattr(remote, "compose", stop_failure)
    monkeypatch.setattr(remote, "mtproto_empty", lambda *args: empty_called.append(True) or True)
    with pytest.raises(remote.DeployError, match="stop failed"):
        remote.stop_and_prove_post_cutover_rollback_safe("db", {"POSTGRES_PASSWORD": "secret"})
    assert empty_called == []


def test_release_telegram_environment_is_checked_after_switch():
    rollback = {
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "secretary",
        "POSTGRES_USER": "secretary",
        "POSTGRES_PASSWORD": "db-password",
        "SECRETARY_CREDENTIAL_KEY": "credential-key",
    }
    release = {**rollback, "TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "hash"}
    remote.require_release_environment(rollback, rollback, release, release)


def test_release_environment_change_is_rejected_before_stop():
    rollback = {"POSTGRES_PASSWORD": "old", "SECRETARY_CREDENTIAL_KEY": "key"}
    release = {
        "POSTGRES_PASSWORD": "new",
        "SECRETARY_CREDENTIAL_KEY": "key",
        "TELEGRAM_API_ID": "123",
        "TELEGRAM_API_HASH": "hash",
    }
    with pytest.raises(remote.DeployError, match="DB or credential"):
        remote.require_release_environment(rollback, rollback, release, release)


def test_release_environment_without_telegram_credentials_is_rejected():
    values = {"POSTGRES_PASSWORD": "db-password", "SECRETARY_CREDENTIAL_KEY": "credential-key"}
    with pytest.raises(remote.DeployError, match="Telegram credentials"):
        remote.require_release_environment(values, values, values, values)


def test_direct_db_revision_accepts_0041_with_release_scripts(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return " 0041\n"

    monkeypatch.setattr(remote, "run", fake_run)
    remote.require_db_revision("db", {"POSTGRES_PASSWORD": "secret"}, "0041")
    assert "SELECT version_num FROM alembic_version" in captured["cmd"]
    assert "PGPASSWORD=secret" not in captured["cmd"]


@pytest.mark.parametrize("output", ["0045\n", "0041\n0046\n", ""])
def test_direct_db_revision_rejects_wrong_multiple_or_missing(output, monkeypatch):
    monkeypatch.setattr(remote, "run", lambda *args, **kwargs: output)
    with pytest.raises(remote.DeployError, match="database Alembic"):
        remote.require_db_revision("db", {"POSTGRES_PASSWORD": "secret"}, "0041")


def test_direct_db_revision_query_failure_is_fail_closed(monkeypatch):
    def fail(*args, **kwargs):
        raise remote.DeployError("sensitive preflight failed")

    monkeypatch.setattr(remote, "run", fail)
    with pytest.raises(remote.DeployError):
        remote.require_db_revision("db", {"POSTGRES_PASSWORD": "secret"}, "0041")


def test_rollback_restore_continues_after_direct_0041_check(monkeypatch):
    calls = []
    monkeypatch.setattr(remote, "git", lambda *args: calls.append(("git", args)) or "")
    monkeypatch.setattr(remote, "compose", lambda *args, **kwargs: calls.append(("compose", args)) or "")
    monkeypatch.setattr(remote, "service_id", lambda name: {"db": "db", "api": "new-api", "worker": "new-worker"}[name])
    monkeypatch.setattr(remote, "volume", lambda _: ("volume", "name", "source"))
    monkeypatch.setattr(remote, "env_hash", lambda: "env")
    monkeypatch.setattr(remote, "require_db", lambda _: None)
    monkeypatch.setattr(remote, "health", lambda _, **kwargs: None)
    monkeypatch.setattr(remote, "require_db_revision", lambda db, values, expected: calls.append(("revision", expected)))
    assert remote.restore_old(
        "r" * 40,
        "0041",
        "http://health",
        "db",
        {"POSTGRES_PASSWORD": "secret"},
        ("volume", "name", "source"),
        "env",
        "old-api",
        "old-worker",
    ) is True
    assert ("revision", "0041") in calls


def test_health_succeeds_immediately_with_one_probe(monkeypatch):
    calls = []
    monkeypatch.setattr(remote, "run", lambda cmd, **kwargs: calls.append(cmd) or "ok")
    remote.health("http://health")
    assert len(calls) == 1


def test_health_retries_then_succeeds(monkeypatch):
    calls = []
    sleeps = []

    def probe(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) < 3:
            raise remote.DeployError("suppressed curl failure")
        return "ok"

    monkeypatch.setattr(remote, "run", probe)
    monkeypatch.setattr(remote.time, "sleep", sleeps.append)
    remote.health("http://health", attempts=5)
    assert len(calls) == 3
    assert sleeps == [2, 2]


def test_health_fails_after_exact_bounded_attempts_without_raw_error(monkeypatch):
    calls = []
    sleeps = []

    def probe(cmd, **kwargs):
        calls.append(cmd)
        raise remote.DeployError("secret curl/provider detail")

    monkeypatch.setattr(remote, "run", probe)
    monkeypatch.setattr(remote.time, "sleep", sleeps.append)
    with pytest.raises(remote.DeployError, match="production health check failed") as failure:
        remote.health("http://health", attempts=4)
    assert len(calls) == 4
    assert sleeps == [2, 2, 2]
    assert "secret curl/provider detail" not in str(failure.value)


def test_release_and_rollback_health_use_bounded_startup_wait():
    source = (ROOT / "ops/production/remote_migrate_deploy.py").read_text()
    assert 'health(args.health_url, attempts=30)' in source
    assert 'health(url, attempts=30)' in source


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
