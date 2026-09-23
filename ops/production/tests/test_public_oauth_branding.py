"""Static branding site and fail-closed public_web rollout checks."""

import importlib.util
import re
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OPS = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "infra" / "public"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


remote = _load("remote_public_web", OPS / "remote_public_web.py")
local = _load("public_web_rollout", OPS / "public_web_rollout.py")

RELEASE = "a" * 40
ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"


class BrandingPagesTest(unittest.TestCase):
    def test_homepage_describes_product_and_links_policy(self):
        page = (PUBLIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("Personal Secretary", page)
        self.assertIn("self-hosted", page)
        self.assertIn("unified inbox", page)
        self.assertIn('href="/privacy"', page)
        self.assertIn('href="/terms"', page)
        self.assertIn("Gmail", page)
        self.assertIn("Google Calendar", page)
        self.assertIn("Google Drive", page)

    def test_privacy_discloses_google_data_and_ai_provider(self):
        page = (PUBLIC / "privacy.html").read_text(encoding="utf-8")
        self.assertIn("Gmail", page)
        self.assertIn("Google Calendar", page)
        self.assertIn("Google Drive", page)
        self.assertIn("configured AI provider", page)
        self.assertIn("encrypted at rest", page)
        self.assertIn("not sold", page)

    def test_pages_have_no_third_party_resources(self):
        for path in PUBLIC.glob("*.html"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("<script", text.lower())
            self.assertIsNone(re.search(r"https?://", text))
            self.assertNotIn("analytics", text.lower())
            self.assertNotIn("fonts.googleapis", text)


class CaddyAndComposeTest(unittest.TestCase):
    def test_caddy_serves_only_branding_pages(self):
        text = (ROOT / "infra" / "Caddyfile").read_text(encoding="utf-8")
        self.assertNotIn("reverse_proxy", text)
        self.assertNotIn(":8000", text)
        self.assertNotIn(":18080", text)
        handles = re.findall(r"handle\s+(/\S*)\s+\{", text)
        self.assertEqual(handles, ["/", "/privacy", "/privacy/", "/terms", "/terms/"])
        self.assertIn('respond "Not found" 404', text)

    def test_compose_public_web_is_isolated(self):
        text = (ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8")
        match = re.search(r"\n  public_web:\n(?:    .*\n)+", text)
        self.assertIsNotNone(match)
        block = match.group(0)
        self.assertIn("image: caddy:2.10.2", block)
        self.assertNotIn("latest", block)
        self.assertIn('"80:80"', block)
        self.assertIn('"443:443"', block)
        self.assertNotIn("8000", block)
        self.assertNotIn("environment:", block)
        self.assertNotIn("SECRETARY_", block)
        self.assertNotIn("POSTGRES_", block)
        self.assertNotIn("depends_on:", block)
        self.assertIn("/etc/caddy/Caddyfile:ro", block)
        self.assertIn("/srv/public:ro", block)


class RolloutPolicyTest(unittest.TestCase):
    def test_rejects_wrong_origin_path_and_release(self):
        good = {
            "repository_path": "/opt/secretary",
            "origin_url": ORIGIN,
            "expected_origin": ORIGIN,
            "head": RELEASE,
            "origin_production": RELEASE,
            "release_sha": RELEASE,
        }
        remote.require_remote_release(**good)
        for field, value in (
            ("repository_path", "/tmp/other"),
            ("origin_url", "https://example.invalid/other.git"),
            ("expected_origin", "https://example.invalid/other.git"),
            ("head", "b" * 40),
            ("origin_production", "c" * 40),
        ):
            broken = dict(good)
            broken[field] = value
            with self.assertRaises(remote.PublicWebError):
                remote.require_remote_release(**broken)

    def test_local_checkout_rejects_wrong_origin_and_stale_main(self):
        local.assess_local_checkout(
            origin=ORIGIN,
            porcelain="",
            branch="main",
            head=RELEASE,
            origin_main=RELEASE,
        )
        with self.assertRaises(local.PublicWebError):
            local.assess_local_checkout(
                origin="https://example.invalid/other.git",
                porcelain="",
                branch="main",
                head=RELEASE,
                origin_main=RELEASE,
            )
        with self.assertRaises(local.PublicWebError):
            local.assess_local_checkout(
                origin=ORIGIN,
                porcelain=" M CURRENT_TASK.md",
                branch="main",
                head=RELEASE,
                origin_main=RELEASE,
            )
        with self.assertRaises(local.PublicWebError):
            local.assess_local_checkout(
                origin=ORIGIN,
                porcelain="",
                branch="main",
                head=RELEASE,
                origin_main="d" * 40,
            )

    def test_first_rollout_rejects_occupied_ports(self):
        listeners = remote.occupied_public_ports(
            "LISTEN 0 128 0.0.0.0:80 0.0.0.0:*\nLISTEN 0 128 [::]:443 [::]:*\n"
        )
        self.assertEqual(listeners, {80, 443})
        with self.assertRaises(remote.PublicWebError):
            remote.require_ports_free_for_first_rollout(
                service_exists=False, listeners={80}
            )
        remote.require_ports_free_for_first_rollout(
            service_exists=True, listeners={443}
        )
        remote.require_ports_free_for_first_rollout(
            service_exists=False, listeners=set()
        )

    def test_identities_and_cleanup_leave_existing_runtime_untouched(self):
        before = {
            "db_container": "db1",
            "db_volume": "volume1",
            "env_checksum": "abc",
            "api_container": "api1",
            "worker_container": "worker1",
        }
        remote.require_identities_unchanged(before, dict(before))
        changed = dict(before)
        changed["env_checksum"] = "def"
        with self.assertRaises(remote.PublicWebError):
            remote.require_identities_unchanged(before, changed)
        self.assertTrue(
            remote.must_remove_new_public_web(existed_before=False, verified=False)
        )
        self.assertFalse(
            remote.must_remove_new_public_web(existed_before=True, verified=False)
        )
        self.assertEqual(remote.PUBLIC_WEB_UP[-1], "public_web")
        self.assertNotIn("db", remote.PUBLIC_WEB_UP)
        self.assertNotIn("api", remote.PUBLIC_WEB_UP)
        self.assertNotIn("worker", remote.PUBLIC_WEB_UP)
        source = (OPS / "remote_public_web.py").read_text(encoding="utf-8")
        self.assertNotIn("git push", source)
        self.assertNotIn("update-ref", source)
        self.assertNotIn("compose down", source)
        self.assertNotRegex(source, r"open\(\s*ENV_FILE")


class ReadinessAndCleanupTest(unittest.TestCase):
    def _clock(self):
        state = {"now": 0.0, "sleeps": []}

        def monotonic():
            return state["now"]

        def sleep(seconds):
            self.assertGreater(seconds, 0)
            state["sleeps"].append(seconds)
            state["now"] += seconds

        return state, monotonic, sleep

    def test_transient_tls_failure_waits_then_succeeds(self):
        state, monotonic, sleep = self._clock()
        probes = {"count": 0}

        def probe():
            probes["count"] += 1
            if probes["count"] == 1:
                raise remote.PublicWebError("curl: (35) TLS connect error")
            return dict(remote.PUBLIC_URLS)

        statuses = remote.collect_statuses(
            probe=probe, sleep=sleep, monotonic=monotonic
        )
        self.assertEqual(statuses, dict(remote.PUBLIC_URLS))
        self.assertEqual(probes["count"], 2)
        self.assertEqual(state["sleeps"], [remote.READINESS_INTERVAL_SECONDS])
        self.assertLess(state["now"], remote.READINESS_TIMEOUT_SECONDS)

    def test_persistent_probe_failure_reaches_bounded_deadline(self):
        state, monotonic, sleep = self._clock()

        def probe():
            raise remote.PublicWebError("curl: (7) connection refused")

        with self.assertRaises(remote.PublicWebError):
            remote.collect_statuses(probe=probe, sleep=sleep, monotonic=monotonic)
        self.assertGreaterEqual(state["now"], remote.READINESS_TIMEOUT_SECONDS)
        self.assertGreater(len(state["sleeps"]), 1)
        self.assertAlmostEqual(
            sum(state["sleeps"]), remote.READINESS_TIMEOUT_SECONDS, places=6
        )

    def _before(self):
        return {
            "db_container": "db1",
            "db_volume": "volume1",
            "env_checksum": "abc",
            "api_container": "api1",
            "worker_container": "worker1",
        }

    def _run_rollout(
        self,
        *,
        existed_before,
        snapshot=None,
        service_id=None,
        require_running=None,
        collect=None,
    ):
        calls = []
        before = self._before()
        caught = []

        def compose(*args):
            calls.append(args)
            if any(name in args for name in ("db", "api", "worker")) and args[:1] != (
                "ps",
            ):
                raise AssertionError(args)
            return ""

        def default_service_id(name, *, required):
            if name == "public_web" and required:
                return "public1"
            return f"{name}1"

        try:
            with (
                unittest.mock.patch.object(remote, "compose", compose),
                unittest.mock.patch.object(
                    remote, "snapshot", snapshot or (lambda *args: dict(before))
                ),
                unittest.mock.patch.object(
                    remote, "service_id", service_id or default_service_id
                ),
                unittest.mock.patch.object(
                    remote, "require_running", require_running or (lambda *args: None)
                ),
                unittest.mock.patch.object(
                    remote,
                    "collect_statuses",
                    collect or (lambda **kwargs: dict(remote.PUBLIC_URLS)),
                ),
            ):
                remote.rollout_public_web(existed_before=existed_before, before=before)
        except remote.PublicWebError as exc:
            caught.append(exc)
        return calls, caught

    def test_first_rollout_persistent_verification_failure_removes_public_web(self):
        def collect(**kwargs):
            raise remote.PublicWebError("public page verification failed")

        calls, caught = self._run_rollout(existed_before=False, collect=collect)
        self.assertEqual(len(caught), 1)
        self.assertIn(remote.PUBLIC_WEB_UP, calls)
        self.assertIn(remote.PUBLIC_WEB_STOP, calls)
        self.assertIn(remote.PUBLIC_WEB_RM, calls)
        self.assertNotIn("-v", remote.PUBLIC_WEB_RM)

    def test_first_rollout_identity_failure_removes_public_web(self):
        before = self._before()
        changed = dict(before)
        changed["api_container"] = "api-recreated"

        calls, caught = self._run_rollout(
            existed_before=False, snapshot=lambda *args: changed
        )
        self.assertEqual(len(caught), 1)
        self.assertIn(remote.PUBLIC_WEB_STOP, calls)
        self.assertIn(remote.PUBLIC_WEB_RM, calls)
        self.assertNotIn(("stop", "api"), calls)
        self.assertNotIn(("stop", "db"), calls)
        self.assertNotIn(("stop", "worker"), calls)

    def test_first_rollout_missing_public_web_removes_public_web(self):
        def service_id(name, *, required):
            if name == "public_web":
                raise remote.PublicWebError("production service missing: public_web")
            return f"{name}1"

        calls, caught = self._run_rollout(existed_before=False, service_id=service_id)
        self.assertEqual(len(caught), 1)
        self.assertIn(remote.PUBLIC_WEB_STOP, calls)
        self.assertIn(remote.PUBLIC_WEB_RM, calls)

    def test_first_rollout_not_running_removes_public_web(self):
        def require_running(container_id, service_name):
            raise remote.PublicWebError(
                "production public_web container is not running"
            )

        calls, caught = self._run_rollout(
            existed_before=False, require_running=require_running
        )
        self.assertEqual(len(caught), 1)
        self.assertIn(remote.PUBLIC_WEB_STOP, calls)
        self.assertIn(remote.PUBLIC_WEB_RM, calls)

    def test_preexisting_public_web_failed_verification_is_not_removed(self):
        def collect(**kwargs):
            raise remote.PublicWebError("public page verification failed")

        calls, caught = self._run_rollout(existed_before=True, collect=collect)
        self.assertEqual(len(caught), 1)
        self.assertIn(remote.PUBLIC_WEB_UP, calls)
        self.assertNotIn(remote.PUBLIC_WEB_STOP, calls)
        self.assertNotIn(remote.PUBLIC_WEB_RM, calls)

    def test_first_rollout_unexpected_exception_removes_public_web(self):
        def collect(**kwargs):
            raise RuntimeError("verification probe crashed")

        calls = []
        before = self._before()

        def compose(*args):
            calls.append(args)
            return ""

        with (
            self.assertRaises(RuntimeError),
            unittest.mock.patch.object(remote, "compose", compose),
            unittest.mock.patch.object(remote, "snapshot", lambda *args: dict(before)),
            unittest.mock.patch.object(
                remote, "service_id", lambda name, *, required: name
            ),
            unittest.mock.patch.object(remote, "require_running", lambda *args: None),
            unittest.mock.patch.object(remote, "collect_statuses", collect),
        ):
            remote.rollout_public_web(existed_before=False, before=before)
        self.assertIn(remote.PUBLIC_WEB_STOP, calls)
        self.assertIn(remote.PUBLIC_WEB_RM, calls)

    def test_cleanup_cannot_target_db_api_or_worker(self):
        for args in (
            ("stop", "db"),
            ("rm", "-sf", "api"),
            ("up", "-d", "--force-recreate", "worker"),
            ("down",),
        ):
            with self.assertRaises(remote.PublicWebError):
                remote.compose(*args)
        self.assertEqual(remote.PUBLIC_WEB_STOP, ("stop", "public_web"))
        self.assertEqual(remote.PUBLIC_WEB_RM, ("rm", "-sf", "public_web"))

    def _ps_compose(self, outputs):
        calls = []

        def compose(*args):
            calls.append(args)
            return outputs.get(args, "")

        return calls, compose

    def test_running_preexisting_public_web_exists(self):
        calls, compose = self._ps_compose(
            {("ps", "--all", "-q", "public_web"): "running-id\n"}
        )
        with unittest.mock.patch.object(remote, "compose", compose):
            self.assertTrue(remote.public_web_existed_before())
        self.assertEqual(calls, [("ps", "--all", "-q", "public_web")])

    def test_stopped_preexisting_public_web_exists(self):
        calls, compose = self._ps_compose(
            {
                ("ps", "-q", "public_web"): "",
                ("ps", "--all", "-q", "public_web"): "exited-id\n",
            }
        )
        with unittest.mock.patch.object(remote, "compose", compose):
            self.assertTrue(remote.public_web_existed_before())
        self.assertEqual(calls, [("ps", "--all", "-q", "public_web")])

    def test_absent_public_web_does_not_exist(self):
        _calls, compose = self._ps_compose({})
        with unittest.mock.patch.object(remote, "compose", compose):
            self.assertFalse(remote.public_web_existed_before())

    def test_stopped_preexisting_failed_verification_is_not_removed(self):
        calls, compose = self._ps_compose(
            {("ps", "--all", "-q", "public_web"): "exited-id\n"}
        )
        before = self._before()

        def collect(**kwargs):
            raise remote.PublicWebError("public page verification failed")

        with (
            unittest.mock.patch.object(remote, "compose", compose),
            unittest.mock.patch.object(remote, "snapshot", lambda *args: dict(before)),
            unittest.mock.patch.object(
                remote, "service_id", lambda name, *, required: f"{name}1"
            ),
            unittest.mock.patch.object(remote, "require_running", lambda *args: None),
            unittest.mock.patch.object(remote, "collect_statuses", collect),
        ):
            existed_before = remote.public_web_existed_before()
            self.assertTrue(existed_before)
            with self.assertRaises(remote.PublicWebError):
                remote.rollout_public_web(existed_before=existed_before, before=before)
        self.assertNotIn(remote.PUBLIC_WEB_STOP, calls)
        self.assertNotIn(remote.PUBLIC_WEB_RM, calls)

    def test_post_start_still_requires_a_running_container(self):
        calls, compose = self._ps_compose(
            {("ps", "--all", "-q", "public_web"): "exited-id\n"}
        )
        with unittest.mock.patch.object(remote, "compose", compose):
            self.assertTrue(remote.public_web_existed_before())
            with self.assertRaises(remote.PublicWebError):
                remote.service_id("public_web", required=True)
        self.assertIn(("ps", "-q", "public_web"), calls)
        self.assertNotIn("--all", calls[-1])

    def test_https_probe_does_not_bypass_tls(self):
        source = (OPS / "remote_public_web.py").read_text(encoding="utf-8")
        self.assertNotIn("--insecure", source)
        self.assertNotRegex(source, r"(^|\s)-k(\s|$)")
        self.assertNotIn("curl -k", source)


if __name__ == "__main__":
    unittest.main()
