"""Static branding site and fail-closed public_web rollout checks."""

import importlib.util
import re
import unittest
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


if __name__ == "__main__":
    unittest.main()
