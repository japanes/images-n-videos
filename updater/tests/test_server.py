import json
import threading
import unittest
import urllib.error
import urllib.request

from tests.fakes import Env
from vf_updater.server import make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.env = Env("0.1.0")
        self.env.install_state("0.1.0")
        self.env.add_release("0.1.0")
        self.env.add_release("0.2.0")
        self.token = self.env.store.read_token()
        self.server = make_server(self.env.engine, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        worker = self.env.engine._worker
        if worker:
            worker.join(10)
        self.env.cleanup()

    def call(self, method, path, body=None, token=True, raw=None):
        headers = {}
        if token:
            headers["X-VF-Token"] = self.token if token is True else token
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None
                                             else None)
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def test_health_is_open(self):
        status, data = self.call("GET", "/health", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(data, {"ok": True, "version": "0.1.0", "state": "idle"})

    def test_token_required(self):
        for method, path in (("GET", "/status"), ("POST", "/check"), ("POST", "/install"),
                             ("POST", "/settings"), ("POST", "/stop"), ("GET", "/history")):
            status, data = self.call(method, path, token=False)
            self.assertEqual((status, data["error"]), (401, "unauthorized"), path)
            status, _ = self.call(method, path, token="wrong")
            self.assertEqual(status, 401, path)

    def test_status_and_check(self):
        status, data = self.call("GET", "/status")
        self.assertEqual(status, 200)
        self.assertEqual(data["installed_version"], "0.1.0")
        self.assertEqual(data["available"], [])
        status, data = self.call("POST", "/check")
        self.assertEqual(status, 200)
        self.assertEqual([a["version"] for a in data["available"]], ["0.2.0"])
        self.assertTrue(data["last_check_at"])
        self.assertNotIn(self.token, json.dumps(data))

    def test_settings(self):
        status, data = self.call("POST", "/settings", {"auto": False, "tz": "Europe/Kyiv"})
        self.assertEqual(status, 200)
        self.assertEqual((data["auto"], data["tz"]), (False, "Europe/Kyiv"))
        status, data = self.call("POST", "/settings", {"channel": "nightly"})
        self.assertEqual((status, data["error"]), (400, "bad_request"))

    def test_install(self):
        status, data = self.call("POST", "/install", {"version": "0.2.0"})
        self.assertEqual(status, 202)
        self.assertEqual(data["operation"]["to"], "0.2.0")
        self.env.engine._worker.join(10)
        status, data = self.call("POST", "/install", {"version": "0.2.0"})
        self.assertEqual((status, data["error"]), (409, "conflict"))
        status, data = self.call("POST", "/stop")
        self.assertEqual(status, 409)

    def test_install_errors(self):
        self.assertEqual(self.call("POST", "/install", {"version": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/install", {"version": "0.1.0"})[0], 409)
        self.assertEqual(self.call("POST", "/install", {"version": "5.0.0"})[0], 404)
        self.assertEqual(self.call("POST", "/install", raw=b"{oops")[0], 400)
        self.assertEqual(self.call("POST", "/install", raw=b"[1]")[0], 400)

    def test_routing_errors(self):
        status, data = self.call("GET", "/nope")
        self.assertEqual((status, data["error"]), (404, "not_found"))
        status, data = self.call("GET", "/install")
        self.assertEqual((status, data["error"]), (405, "method_not_allowed"))
        self.assertEqual(self.call("DELETE", "/status")[0], 405)

    def test_stop_and_history(self):
        status, data = self.call("POST", "/stop")
        self.assertEqual((status, data), (202, {"ok": True}))
        self.assertEqual(self.env.docker.helpers[-1][1], ["stop"])
        status, data = self.call("GET", "/history")
        self.assertEqual((status, data), (200, {"items": []}))


if __name__ == "__main__":
    unittest.main()
