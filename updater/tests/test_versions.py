import unittest

from vf_updater import versions
from vf_updater.releases import filter_available


class VersionTests(unittest.TestCase):
    def test_parse_and_normalize(self):
        self.assertEqual(versions.normalize("v1.2.3"), "1.2.3")
        self.assertEqual(versions.normalize("1.2.3-beta.2"), "1.2.3-beta.2")
        self.assertEqual(versions.normalize("1.2.3+build.5"), "1.2.3")
        for bad in ("1.2", "01.2.3", "1.2.3.4", "latest", "", None, "v", "1.2.3-"):
            self.assertFalse(versions.is_valid(bad), bad)

    def test_order(self):
        ordered = ["0.0.0-dev", "0.9.9", "1.0.0-beta.1", "1.0.0-beta.2", "1.0.0-beta.10",
                   "1.0.0-rc.1", "1.0.0", "1.0.1", "1.10.0", "2.0.0"]
        parsed = [versions.parse(v) for v in ordered]
        self.assertEqual(sorted(parsed), parsed)
        self.assertEqual(versions.compare("1.0.0", "v1.0.0"), 0)
        self.assertEqual(versions.compare("1.0.0", "1.0.0-rc.1"), 1)
        self.assertEqual(versions.compare("1.0.0-beta.2", "1.0.0-beta.10"), -1)

    def test_prerelease_and_channel(self):
        self.assertTrue(versions.is_prerelease("1.0.0-beta.1"))
        self.assertFalse(versions.is_prerelease("1.0.0"))
        self.assertTrue(versions.channel_allows("stable", "1.0.0"))
        self.assertFalse(versions.channel_allows("stable", "1.0.0-rc.1"))
        self.assertFalse(versions.channel_allows("stable", "1.0.0", prerelease_flag=True))
        self.assertTrue(versions.channel_allows("beta", "1.0.0-rc.1"))
        self.assertTrue(versions.channel_allows("beta", "1.0.0"))


class FilterTests(unittest.TestCase):
    releases = [
        {"version": "0.1.0", "prerelease": False},
        {"version": "0.2.0", "prerelease": False},
        {"version": "0.3.0-beta.1", "prerelease": True},
        {"version": "0.2.1", "prerelease": True},  # flagged prerelease on GitHub
        {"version": "bogus"},
    ]

    def test_stable_channel(self):
        result = filter_available(self.releases, "0.1.0", "stable")
        self.assertEqual([r["version"] for r in result], ["0.2.0"])

    def test_beta_channel_newest_first(self):
        result = filter_available(self.releases, "0.1.0", "beta")
        self.assertEqual([r["version"] for r in result], ["0.3.0-beta.1", "0.2.1", "0.2.0"])

    def test_nothing_newer(self):
        self.assertEqual(filter_available(self.releases, "0.3.0", "beta"), [])

    def test_dev_current_version(self):
        result = filter_available(self.releases, "0.0.0-dev", "stable")
        self.assertEqual([r["version"] for r in result], ["0.2.0", "0.1.0"])


if __name__ == "__main__":
    unittest.main()
