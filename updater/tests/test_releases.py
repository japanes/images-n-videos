import unittest

from tests.fakes import Env, gh_release, make_manifest
from vf_updater.http_util import HttpError
from vf_updater.releases import MAX_NOTES, ReleaseClient, ReleaseError

API = "https://api.github.com/repos/japanes/images-n-videos/releases"


class ReleaseClientTests(unittest.TestCase):
    def setUp(self):
        self.env = Env("0.1.0")
        self.client = ReleaseClient(self.env.cfg, self.env.store, http=self.env.http,
                                    clock=self.env.clock)

    def tearDown(self):
        self.env.cleanup()

    def api_calls(self):
        return [c for c in self.env.http.calls if c[1].startswith(API)]

    def test_fetch_normalizes_and_skips_bad_entries(self):
        self.env.add_release("0.2.0")
        self.env.releases_list.append({"tag_name": "nightly", "draft": False})
        self.env.releases_list.append(gh_release("0.9.0", draft=True))
        self.env.releases_list.append({**gh_release("0.3.0"), "body": "x" * (MAX_NOTES + 10)})
        self.env.releases_list.append(gh_release("0.4.0-beta.1"))  # not flagged on GitHub
        releases = self.client.fetch()
        by_version = {r["version"]: r for r in releases}
        self.assertEqual(set(by_version), {"0.2.0", "0.3.0", "0.4.0-beta.1"})
        self.assertEqual(len(by_version["0.3.0"]["notes_md"]), MAX_NOTES)
        self.assertTrue(by_version["0.4.0-beta.1"]["prerelease"])
        self.assertEqual(by_version["0.2.0"]["manifest_url"],
                         "https://dl.test/0.2.0/manifest.json")
        check = self.env.store.read_check()
        self.assertEqual(check["etag"], '"e1"')
        self.assertIsNone(check["last_check_error"])
        self.assertTrue(check["last_check_at"])

    def test_manual_check_is_throttled_and_etag_is_sent(self):
        self.env.add_release("0.2.0")
        self.client.fetch(manual=True)
        self.client.fetch(manual=True)
        self.assertEqual(len(self.api_calls()), 1)
        self.env.clock.sleep(61)
        seen = {}

        def not_modified(method, url, headers, body):
            seen.update(headers)
            return 304, b"", {}

        self.env.http.route("GET", API, not_modified)
        releases = self.client.fetch(manual=True)
        self.assertEqual(seen.get("If-None-Match"), '"e1"')
        self.assertEqual([r["version"] for r in releases], ["0.2.0"])
        self.assertEqual(len(self.api_calls()), 2)

    def test_rate_limit_blocks_until_reset(self):
        reset = self.env.clock() + 600

        def limited(method, url, headers, body):
            return 403, {"message": "API rate limit exceeded"}, {
                "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(reset))}

        self.env.http.route("GET", API, limited)
        with self.assertRaises(ReleaseError):
            self.client.fetch()
        check = self.env.store.read_check()
        self.assertIn("rate limit", check["last_check_error"])
        self.assertGreaterEqual(check["rate_limited_until"], reset - 1)
        calls = len(self.api_calls())
        with self.assertRaises(ReleaseError) as ctx:
            self.client.fetch(manual=True)
        self.assertIn("min", str(ctx.exception))
        self.assertEqual(len(self.api_calls()), calls)
        self.env.clock.sleep(601)
        self.env.http.routes.pop(0)
        self.env.add_release("0.2.0")
        self.assertEqual(len(self.client.fetch()), 1)
        self.assertIsNone(self.env.store.read_check()["last_check_error"])

    def test_network_and_http_errors_are_recorded(self):
        def down(method, url, headers, body):
            raise HttpError("connection refused")

        self.env.http.route("GET", API, down)
        with self.assertRaises(ReleaseError):
            self.client.fetch()
        self.assertIn("cannot reach GitHub", self.env.store.read_check()["last_check_error"])
        self.env.http.route("GET", API, lambda *a: (500, {"message": "boom"}, {}))
        self.env.clock.sleep(61)
        with self.assertRaises(ReleaseError):
            self.client.fetch(manual=True)
        self.assertIn("HTTP 500", self.env.store.read_check()["last_check_error"])

    def test_manifest_download_validation_and_cache(self):
        self.env.add_release("0.2.0", min_from="0.1.0")
        rel = self.client.fetch()[0]
        man = self.client.get_manifest(rel)
        self.assertEqual(man["min_upgrade_from"], "0.1.0")
        downloads = [c for c in self.env.http.calls if c[1].startswith("https://dl.test/")]
        self.client.get_manifest(rel)
        self.assertEqual(len([c for c in self.env.http.calls
                              if c[1].startswith("https://dl.test/")]), len(downloads))

    def test_bad_or_missing_manifest(self):
        self.env.add_release("0.2.0")
        self.env.add_release("0.3.0", with_manifest=False)
        self.env.manifests["0.2.0"] = make_manifest("0.2.1")  # wrong version inside
        releases = {r["version"]: r for r in self.client.fetch()}
        with self.assertRaises(ReleaseError):
            self.client.get_manifest(releases["0.2.0"])
        with self.assertRaises(ReleaseError):
            self.client.get_manifest(releases["0.3.0"])

    def test_fetch_tag(self):
        self.env.add_release("0.1.0")
        rel = self.client.fetch_tag("0.1.0")
        self.assertEqual(rel["version"], "0.1.0")
        with self.assertRaises(ReleaseError):
            self.client.fetch_tag("9.9.9")


if __name__ == "__main__":
    unittest.main()
