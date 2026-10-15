import unittest

from tests.fakes import PREFIX, digest, make_manifest
from vf_updater.manifest import ManifestError, can_upgrade_from, validate


class ManifestTests(unittest.TestCase):
    def test_valid(self):
        result = validate(make_manifest("1.2.0", min_from="1.0.0"), "v1.2.0", PREFIX)
        self.assertEqual(result["version"], "1.2.0")
        self.assertFalse(result["prerelease"])
        self.assertEqual(result["min_upgrade_from"], "1.0.0")
        self.assertEqual(result["images"]["app"], f"{PREFIX}/app@{digest('a')}")

    def test_prefix_with_trailing_slash(self):
        validate(make_manifest("1.2.0"), "1.2.0", PREFIX + "/")

    def bad(self, data, tag="1.2.0", prefix=PREFIX):
        with self.assertRaises(ManifestError):
            validate(data, tag, prefix)

    def test_rejects(self):
        self.bad([])
        self.bad(make_manifest("1.2.0"), tag="1.3.0")
        self.bad({**make_manifest("1.2.0"), "version": "latest"})
        self.bad({**make_manifest("1.2.0-beta.1", prerelease=False)}, tag="1.2.0-beta.1")
        self.bad({**make_manifest("1.2.0"), "prerelease": "no"})
        self.bad({**make_manifest("1.2.0"), "min_upgrade_from": "abc"})
        self.bad(make_manifest("1.2.0"), prefix="ghcr.io/someone/else")
        m = make_manifest("1.2.0")
        m["images"]["app"] = f"{PREFIX}/app:1.2.0"
        self.bad(m)
        m = make_manifest("1.2.0")
        m["images"]["app"] = f"{PREFIX}/app@sha256:xyz"
        self.bad(m)
        m = make_manifest("1.2.0")
        m["images"]["app"] = f"{PREFIX}/render@{digest('a')}"
        self.bad(m)
        m = make_manifest("1.2.0")
        del m["images"]["stt"]
        self.bad(m)
        m = make_manifest("1.2.0")
        m["images"]["Bad Key"] = f"{PREFIX}/Bad Key@{digest('e')}"
        self.bad(m)
        self.bad({**make_manifest("1.2.0"), "images": {}})

    def test_extra_service_allowed(self):
        m = make_manifest("1.2.0")
        m["images"]["worker"] = f"{PREFIX}/worker@{digest('e')}"
        self.assertIn("worker", validate(m, "1.2.0", PREFIX)["images"])

    def test_min_upgrade_from(self):
        m = validate(make_manifest("2.0.0", min_from="1.5.0"), "2.0.0", PREFIX)
        self.assertTrue(can_upgrade_from(m, "1.5.0"))
        self.assertTrue(can_upgrade_from(m, "1.9.0"))
        self.assertFalse(can_upgrade_from(m, "1.4.9"))
        self.assertTrue(can_upgrade_from(validate(make_manifest("2.0.0"), "2.0.0", PREFIX),
                                         "0.1.0"))


if __name__ == "__main__":
    unittest.main()
