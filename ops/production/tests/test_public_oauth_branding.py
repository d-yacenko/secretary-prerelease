"""Static branding pages and nginx-root publisher checks."""

import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OPS = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "infra" / "public"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


remote = _load("remote_public_web", OPS / "remote_public_web.py")
local = _load("public_web_rollout", OPS / "public_web_rollout.py")

RELEASE = "a" * 40
ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"


def _pages():
    return {
        "index.html": b"home-v2",
        "privacy/index.html": b"privacy-v1",
        "terms/index.html": b"terms-v1",
    }


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

    def test_repository_pages_map_to_nginx_targets(self):
        pages, manifest = remote.load_pages(ROOT)
        self.assertEqual(set(pages), set(remote.OWNED_PATHS))
        self.assertEqual(
            pages["privacy/index.html"], (PUBLIC / "privacy.html").read_bytes()
        )
        self.assertEqual(
            manifest["terms/index.html"], remote.sha256_bytes(pages["terms/index.html"])
        )


class ComposeRetirementTest(unittest.TestCase):
    def test_compose_does_not_publish_public_web(self):
        text = (ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("public_web:", text)
        self.assertNotIn("caddy", text.lower())
        self.assertNotIn('"80:80"', text)
        self.assertNotIn('"443:443"', text)
        self.assertFalse((ROOT / "infra" / "Caddyfile").exists())


class PublisherPolicyTest(unittest.TestCase):
    def test_local_checkout_and_release_gates(self):
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
        remote.require_remote_release(
            repository_path="/opt/secretary",
            origin_url=ORIGIN,
            expected_origin=ORIGIN,
            head=RELEASE,
            origin_production=RELEASE,
            release_sha=RELEASE,
        )
        with self.assertRaises(remote.PublicWebError):
            remote.require_remote_release(
                repository_path="/tmp/other",
                origin_url=ORIGIN,
                expected_origin=ORIGIN,
                head=RELEASE,
                origin_production=RELEASE,
                release_sha=RELEASE,
            )

    def _publish(
        self, root: Path, pages, *, verify=None, identity_after=None, manifest=None
    ):
        pages = dict(pages)
        manifest = remote.page_manifest(pages) if manifest is None else manifest
        remote.publish_branding_files(
            root,
            pages,
            manifest,
            verify=verify or (lambda: None),
            identity_after=identity_after or (lambda: None),
        )

    def test_initial_rollout_creates_privacy_and_terms(self):
        root = Path(self._tmp())
        (root / "index.html").write_bytes(b"old-home")
        self._publish(root, _pages())
        self.assertEqual((root / "index.html").read_bytes(), b"home-v2")
        self.assertEqual((root / "privacy" / "index.html").read_bytes(), b"privacy-v1")
        self.assertEqual((root / "terms" / "index.html").read_bytes(), b"terms-v1")
        self.assertEqual(
            (root / "privacy" / "index.html").stat().st_mode & 0o777, 0o644
        )

    def test_replaces_existing_index(self):
        root = Path(self._tmp())
        (root / "index.html").write_bytes(b"previous")
        self._publish(root, _pages())
        self.assertEqual((root / "index.html").read_bytes(), b"home-v2")

    def test_failure_restores_preexisting_files_and_removes_created_dirs(self):
        root = Path(self._tmp())
        index = root / "index.html"
        index.write_bytes(b"keep-home")
        mode = index.stat().st_mode & 0o777

        def fail():
            raise remote.PublicWebError("public page verification failed")

        with self.assertRaises(remote.PublicWebError):
            self._publish(root, _pages(), verify=fail)
        self.assertEqual(index.read_bytes(), b"keep-home")
        self.assertEqual(index.stat().st_mode & 0o777, mode)
        self.assertFalse((root / "privacy").exists())
        self.assertFalse((root / "terms").exists())

    def test_cleanup_does_not_remove_preexisting_directory(self):
        root = Path(self._tmp())
        (root / "index.html").write_bytes(b"keep-home")
        privacy = root / "privacy"
        privacy.mkdir()
        (privacy / "keep.txt").write_bytes(b"leave-me")

        def fail():
            raise remote.PublicWebError("public page verification failed")

        with self.assertRaises(remote.PublicWebError):
            self._publish(root, _pages(), verify=fail)
        self.assertEqual((privacy / "keep.txt").read_bytes(), b"leave-me")
        self.assertFalse((privacy / "index.html").exists())
        self.assertTrue(privacy.is_dir())

    def test_refuses_to_touch_unrelated_files(self):
        root = Path(self._tmp())
        (root / "index.html").write_bytes(b"old-home")
        (root / "robots.txt").write_bytes(b"unrelated")
        self._publish(root, _pages())
        self.assertEqual((root / "robots.txt").read_bytes(), b"unrelated")

    def test_identity_drift_rolls_back(self):
        root = Path(self._tmp())
        (root / "index.html").write_bytes(b"keep-home")

        def drift():
            raise remote.PublicWebError("db, api, worker, or env identity changed")

        with self.assertRaises(remote.PublicWebError):
            self._publish(root, _pages(), identity_after=drift)
        self.assertEqual((root / "index.html").read_bytes(), b"keep-home")
        self.assertFalse((root / "privacy").exists())

    def test_http_verification_failure_rolls_back(self):
        root = Path(self._tmp())
        (root / "index.html").write_bytes(b"keep-home")
        with self.assertRaises(remote.PublicWebError):
            self._publish(
                root,
                _pages(),
                verify=lambda: remote.verify_branding_responses({}, _pages()),
            )
        self.assertEqual((root / "index.html").read_bytes(), b"keep-home")

    def test_manifest_mismatch_writes_nothing(self):
        root = Path(self._tmp())
        (root / "index.html").write_bytes(b"keep-home")
        pages = _pages()
        manifest = remote.page_manifest(pages)
        manifest["index.html"] = "0" * 64
        with self.assertRaises(remote.PublicWebError):
            self._publish(root, pages, manifest=manifest)
        self.assertEqual((root / "index.html").read_bytes(), b"keep-home")
        self.assertFalse((root / "privacy").exists())

    def test_slash_and_plain_privacy_terms_share_page_hash(self):
        pages = _pages()
        observed = {}
        for url, status, rel in remote.VERIFY_URLS:
            body = b"" if rel is None else pages[rel]
            observed[url] = (status, body)
        remote.verify_branding_responses(observed, pages)
        observed[f"https://{remote.BRANDING_HOST}/privacy/"] = (200, b"other")
        with self.assertRaises(remote.PublicWebError):
            remote.verify_branding_responses(observed, pages)

    def test_publisher_does_not_mutate_nginx_or_compose(self):
        source = (OPS / "remote_public_web.py").read_text(encoding="utf-8")
        self.assertNotIn("nginx", source)
        self.assertNotIn("systemctl", source)
        self.assertNotIn("--insecure", source)
        self.assertNotRegex(source, r"(^|\s)-k(\s|$)")
        with self.assertRaises(remote.PublicWebError):
            remote.compose("up", "-d", "public_web")
        with self.assertRaises(remote.PublicWebError):
            remote.compose("restart", "api")

    def _tmp(self) -> str:
        import tempfile

        path = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(path))
        os.chmod(path, 0o755)
        return path


if __name__ == "__main__":
    unittest.main()
