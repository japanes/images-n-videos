import os
import sqlite3
import unittest
from datetime import datetime, timezone

from tests.fakes import PREFIX, Clock, Env, digest
from vf_updater.engine import (OP_FILE, BadRequest, Conflict, NotFound, auto_window)
from vf_updater.store import utc_now


def at(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()


class Base(unittest.TestCase):
    version = "0.1.0"
    extra_env = None

    def setUp(self):
        self.env = Env(self.version, env=self.extra_env)
        self.engine = self.env.engine

    def tearDown(self):
        self.env.cleanup()

    def make_db(self, *rows):
        conn = sqlite3.connect(self.env.store.db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        for row in rows:
            conn.execute("INSERT INTO t VALUES (?)", (row,))
        conn.commit()
        conn.close()

    def db_rows(self):
        conn = sqlite3.connect(self.env.store.db_path)
        try:
            return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY rowid")]
        finally:
            conn.close()

    def start(self, version, **kwargs):
        op = self.engine.start_install(version, **kwargs)
        self.engine._worker.join(10)
        self.assertFalse(self.engine._worker.is_alive())
        return op

    def helper(self, version):
        return self.env.make_engine(version)


class InstallTests(Base):
    def setUp(self):
        super().setUp()
        self.env.install_state("0.1.0")
        self.env.add_release("0.1.0")
        self.env.add_release("0.2.0")
        self.make_db("v1")

    def test_happy_path(self):
        status = self.engine.check()
        self.assertEqual([a["version"] for a in status["available"]], ["0.2.0"])
        self.assertTrue(status["available"][0]["installable"])
        op = self.start("0.2.0")
        self.assertEqual(op["state"], "preparing")
        cur = self.env.store.read_op()
        self.assertEqual(cur["state"], "applying")
        self.assertEqual(cur["runner"], "helper")
        self.assertTrue(cur["active"])
        self.assertTrue(os.path.exists(cur["backup_file"]))
        self.assertEqual(self.env.docker.pulls, [f"{PREFIX}/{s}@{digest(c)}" for s, c in
                                                 (("app", "a"), ("render", "b"), ("stt", "c"),
                                                  ("updater", "d"))])
        self.assertIn((f"{PREFIX}/app@{digest('a')}", f"{PREFIX}/app:0.2.0"),
                      self.env.docker.tags)
        image, args, helper_env = self.env.docker.helpers[-1]
        self.assertEqual(image, f"{PREFIX}/updater:0.2.0")
        self.assertEqual(args, ["install", "--op", OP_FILE])
        self.assertEqual(helper_env["VF_PROJECT"], "vertexai-factory")
        prepare = [c for c in self.env.http.calls if c[1].endswith("/updates/prepare")]
        self.assertEqual(prepare[0][3]["target_version"], "0.2.0")
        self.assertEqual(prepare[0][2]["X-VF-Token"], self.env.store.read_token())

        self.assertEqual(self.helper("0.2.0").helper_install(), 0)
        state = self.env.store.read_state()
        self.assertEqual(state["installed_version"], "0.2.0")
        self.assertEqual(state["previous_version"], "0.1.0")
        op = self.env.store.read_op()
        self.assertEqual((op["state"], op["result"], op["active"]), ("done", "success", False))
        self.assertTrue(os.path.exists(self.env.store.stack_file("0.2.0")))
        self.assertEqual(self.env.docker.compose_calls[-1][2]["VF_VERSION"], "0.2.0")
        history = self.env.store.read_history()
        self.assertEqual(history[0]["result"], "success")
        self.assertEqual(history[0]["version_to"], "0.2.0")
        status = self.helper("0.2.0").status()
        self.assertEqual(status["state"], "done")
        self.assertEqual(status["available"], [])

    def test_busy_app_postpones_update(self):
        self.env.http.app_prepare = [{"ok": False, "busy": [{"kind": "video", "title": "Clip"}]}]
        self.start("0.2.0")
        op = self.env.store.read_op()
        self.assertEqual(op["state"], "failed")
        self.assertIn("still busy", op["error"])
        self.assertEqual(op["busy"], [{"kind": "video", "title": "Clip"}])
        self.assertEqual(self.env.http.resume_calls, 1)
        self.assertEqual(self.env.docker.pulls, [])
        self.assertEqual(self.env.store.read_history()[0]["result"], "failed")
        self.assertEqual(self.engine.status()["error"], op["error"])

    def test_force_installs_while_busy(self):
        self.env.http.app_prepare = [{"ok": False, "busy": [{"kind": "video", "title": "Clip"}]}]
        self.start("0.2.0", force=True)
        self.assertEqual(self.env.store.read_op()["state"], "applying")

    def test_force_for_waiting_operation(self):
        self.env.store.write_op({"id": "x", "kind": "install", "to": "0.2.0", "active": True,
                                 "state": "preparing", "runner": "updater",
                                 "heartbeat_at": utc_now()})
        with self.assertRaises(Conflict):
            self.engine.start_install("0.2.0")
        op = self.engine.start_install("0.2.0", force=True)
        self.assertTrue(op["force"])
        self.assertTrue(self.engine._force.is_set())

    def test_app_down_does_not_block(self):
        self.env.http.app_reachable = False
        self.start("0.2.0")
        self.assertEqual(self.env.store.read_op()["state"], "applying")

    def test_rejected_token_does_not_block(self):
        self.env.http.app_prepare_status = 403
        self.env.http.app_prepare = [{"ok": False, "error": "forbidden"}]
        self.start("0.2.0")
        op = self.env.store.read_op()
        self.assertEqual(op["state"], "applying")
        self.assertTrue(any("update token" in s["message"] for s in op["step_log"]))

    def test_pull_failure(self):
        self.env.docker.fail_pull.add(f"{PREFIX}/render@{digest('b')}")
        self.start("0.2.0")
        op = self.env.store.read_op()
        self.assertEqual(op["state"], "failed")
        self.assertIn("pull access denied", op["error"])
        self.assertEqual(self.env.docker.helpers, [])
        self.assertEqual(self.env.http.resume_calls, 1)

    def test_broken_version_rolls_back(self):
        self.env.add_release("0.3.0")
        self.env.docker.broken_versions.add("0.3.0")
        self.env.docker.files_in_images[f"{PREFIX}/updater:0.1.0"] = "services: {}\n"
        self.start("0.3.0")
        self.make_db("migrated-by-0.3.0")  # the new app changed the database
        self.assertEqual(self.helper("0.3.0").helper_install(), 1)
        op = self.env.store.read_op()
        self.assertEqual((op["state"], op["result"]), ("failed", "rolled_back"))
        self.assertIn("did not start", op["error"])
        self.assertIn("0.1.0 was restored", op["error"])
        self.assertEqual(self.db_rows(), ["v1"])
        self.assertEqual([c[2]["VF_VERSION"] for c in self.env.docker.compose_calls[-2:]],
                         ["0.3.0", "0.1.0"])
        state = self.env.store.read_state()
        self.assertEqual(state["installed_version"], "0.1.0")
        self.assertEqual(state["failed_versions"], ["0.3.0"])
        self.assertEqual(self.env.http.resume_calls, 1)
        self.assertEqual(self.env.store.read_history()[0]["result"], "rolled_back")
        self.engine.check()
        failed = {a["version"]: a["failed_before"] for a in self.engine.status()["available"]}
        self.assertEqual(failed, {"0.3.0": True, "0.2.0": False})

    def test_rollback_failure_is_reported(self):
        self.env.add_release("0.3.0")
        self.env.docker.broken_versions.add("0.3.0")
        self.env.docker.failing_compose_versions.add("0.1.0")
        self.env.docker.files_in_images[f"{PREFIX}/updater:0.1.0"] = "services: {}\n"
        self.start("0.3.0")
        self.assertEqual(self.helper("0.3.0").helper_install(), 1)
        op = self.env.store.read_op()
        self.assertEqual((op["state"], op["result"]), ("failed", "failed"))
        self.assertIn("also failed", op["error"])

    def test_helper_with_wrong_version_rolls_back(self):
        self.start("0.2.0")
        self.env.docker.files_in_images[f"{PREFIX}/updater:0.1.0"] = "services: {}\n"
        self.assertEqual(self.helper("0.1.5").helper_install(), 1)
        self.assertEqual(self.env.store.read_op()["result"], "rolled_back")

    def test_validation(self):
        with self.assertRaises(BadRequest):
            self.engine.start_install("latest")
        with self.assertRaises(BadRequest):
            self.engine.start_install("0.2.0", force="yes")
        with self.assertRaises(Conflict):
            self.engine.start_install("0.1.0")
        with self.assertRaises(NotFound):
            self.engine.start_install("0.9.0")
        self.env.add_release("0.4.0-beta.1", prerelease=True)
        self.env.clock.sleep(61)  # on-demand checks are throttled to one a minute
        with self.assertRaises(Conflict):
            self.engine.start_install("0.4.0-beta.1")
        self.env.docker.helper_state = "running"
        with self.assertRaises(Conflict):
            self.engine.start_install("0.2.0")

    def test_beta_channel(self):
        self.env.add_release("0.4.0-beta.1", prerelease=True)
        self.engine.update_settings({"channel": "beta"})
        self.start("0.4.0-beta.1")
        self.assertEqual(self.env.store.read_op()["state"], "applying")

    def test_min_upgrade_from(self):
        self.env.add_release("0.3.0", min_from="0.2.0")
        status = self.engine.check()
        by_version = {a["version"]: a for a in status["available"]}
        self.assertFalse(by_version["0.3.0"]["installable"])
        self.assertEqual(by_version["0.3.0"]["min_upgrade_from"], "0.2.0")
        self.start("0.3.0")
        op = self.env.store.read_op()
        self.assertEqual(op["state"], "failed")
        self.assertIn("only from 0.2.0", op["error"])

    def test_bad_settings(self):
        with self.assertRaises(BadRequest):
            self.engine.update_settings({"time": "9am"})


class DevModeTests(Base):
    extra_env = {"VF_UPDATER_DEV": "1"}

    def test_dev_mode_refuses(self):
        self.env.add_release("0.2.0")
        with self.assertRaises(Conflict):
            self.engine.start_install("0.2.0")
        with self.assertRaises(Conflict):
            self.engine.request_stop()
        self.engine.reconcile()
        self.assertEqual(self.env.docker.helpers, [])
        self.assertTrue(self.engine.status()["dev"])


class ReconcileTests(Base):
    def launcher_container(self):
        self.env.docker.containers = [{"id": "upd", "name": "vertexai-factory-updater-1",
                                       "service": "updater", "state": "running",
                                       "image": f"{PREFIX}/updater:stable"}]

    def test_fresh_install(self):
        self.env.add_release("0.1.0")
        self.launcher_container()
        self.engine.reconcile()
        op = self.env.store.read_op()
        self.assertEqual((op["kind"], op["purpose"], op["to"]), ("apply", "fresh", "0.1.0"))
        self.assertEqual(op["images"]["app"], f"{PREFIX}/app@{digest('a')}")
        self.assertIn(("sha256:own", f"{PREFIX}/updater:0.1.0"), self.env.docker.tags)
        image, args, _ = self.env.docker.helpers[-1]
        self.assertEqual((image, args), (f"{PREFIX}/updater:0.1.0", ["apply", "--op", OP_FILE]))
        self.assertEqual(self.helper("0.1.0").helper_apply(), 0)
        self.assertEqual(self.env.store.read_state()["installed_version"], "0.1.0")
        self.assertIn(f"{PREFIX}/stt@{digest('c')}", self.env.docker.pulls)
        self.assertEqual(self.env.store.read_history()[0]["kind"], "apply")
        self.assertEqual(self.engine.status()["state"], "idle")

    def test_fresh_install_failure_is_retried(self):
        self.env.add_release("0.1.0")
        self.launcher_container()
        started = self.env.clock()
        self.engine.reconcile()
        self.assertEqual(self.engine.reconcile_due, started + 300)
        self.env.docker.broken_versions.add("0.1.0")
        self.assertEqual(self.helper("0.1.0").helper_apply(), 1)
        self.assertNotIn("installed_version", self.env.store.read_state())
        self.env.clock.now = started + 301
        self.engine.tick()
        self.assertEqual(self.env.store.read_op()["purpose"], "fresh")
        self.assertTrue(self.env.store.read_op()["active"])

    def test_handover_to_installed_version(self):
        self.env.install_state("0.2.0")
        self.env.docker.containers[-1]["image"] = f"{PREFIX}/updater:stable"
        self.engine.reconcile()
        op = self.env.store.read_op()
        self.assertEqual((op["purpose"], op["to"]), ("handover", "0.2.0"))
        self.assertEqual(self.env.docker.helpers[-1][0], f"{PREFIX}/updater:0.2.0")
        self.assertEqual(self.helper("0.2.0").helper_apply(), 0)
        self.assertEqual(self.env.store.read_state()["installed_version"], "0.2.0")
        self.assertEqual(self.env.store.read_history(), [])

    def test_running_stack_left_alone(self):
        self.env.install_state("0.1.0")
        self.engine.reconcile()
        self.assertIsNone(self.env.store.read_op())

    def test_stopped_service_is_started(self):
        self.env.install_state("0.1.0")
        self.env.docker.containers[1]["state"] = "exited"
        self.engine.reconcile()
        self.assertEqual(self.env.store.read_op()["purpose"], "ensure")

    def test_new_updater_rechecks_after_running_operation(self):
        self.env.install_state("0.1.0")
        self.env.store.write_op({"id": "op1", "kind": "apply", "purpose": "fresh", "to": "0.1.0",
                                 "active": True, "state": "verifying", "runner": "helper",
                                 "step_log": [], "heartbeat_at": utc_now()})
        self.engine.clock.now = datetime.now(timezone.utc).timestamp()
        self.engine.reconcile_due = None
        self.engine.reconcile()
        self.assertEqual(self.engine.reconcile_due, self.engine.clock() + 60)
        self.env.store.update_op(active=False, state="failed")
        self.env.docker.containers[1]["state"] = "exited"
        self.engine.clock.now += 61
        self.engine.tick()
        self.assertEqual(self.env.store.read_op()["purpose"], "ensure")

    def test_apply_guard(self):
        self.env.install_state("0.1.0")
        self.env.docker.containers[1]["state"] = "exited"
        self.engine.reconcile()
        self.env.store.update_op(active=False, state="failed")
        self.engine.reconcile()
        self.assertEqual(len(self.env.docker.helpers), 1)


class RecoveryTests(Base):
    def setUp(self):
        super().setUp()
        self.env.install_state("0.1.0")

    def write_op(self, **fields):
        op = {"id": "op1", "kind": "install", "from": "0.1.0", "to": "0.2.0", "active": True,
              "state": "applying", "runner": "helper", "step_log": [],
              "heartbeat_at": "2020-01-01T00:00:00Z"}
        op.update(fields)
        self.env.store.write_op(op)

    def test_interrupted_preparation(self):
        self.write_op(runner="updater", state="pulling")
        self.engine.tick()
        op = self.env.store.read_op()
        self.assertEqual((op["state"], op["result"]), ("failed", "failed"))
        self.assertEqual(self.env.http.resume_calls, 1)

    def test_helper_finished_switch_but_died(self):
        self.env.docker.compose_up("vertexai-factory", "x", {"VF_VERSION": "0.2.0"})
        engine = self.helper("0.2.0")
        self.write_op()
        engine.tick()
        self.assertEqual(self.env.store.read_op()["result"], "success")
        self.assertEqual(self.env.store.read_state()["installed_version"], "0.2.0")

    def test_helper_died_midway_starts_rollback(self):
        self.write_op()
        self.engine.tick()
        image, args, _ = self.env.docker.helpers[-1]
        self.assertEqual((image, args), (f"{PREFIX}/updater:0.1.0", ["rollback", "--op", OP_FILE]))
        self.env.docker.files_in_images[f"{PREFIX}/updater:0.1.0"] = "services: {}\n"
        self.assertEqual(self.engine.helper_rollback(), 1)
        self.assertEqual(self.env.store.read_op()["result"], "rolled_back")

    def test_fresh_heartbeat_or_running_helper_waits(self):
        self.write_op(heartbeat_at=utc_now())
        self.engine.clock.now = datetime.now(timezone.utc).timestamp()
        self.engine.tick()
        self.assertTrue(self.env.store.read_op()["active"])
        self.write_op()
        self.env.docker.helper_state = "running"
        self.engine.tick()
        self.assertTrue(self.env.store.read_op()["active"])

    def test_dead_apply_helper(self):
        self.write_op(kind="apply", purpose="ensure", to="0.1.0")
        self.engine.tick()
        self.assertEqual(self.env.store.read_op()["state"], "failed")
        self.assertIsNotNone(self.engine.reconcile_due)


class StopTests(Base):
    def test_stop(self):
        self.env.install_state("0.1.0")
        self.engine.request_stop()
        self.assertEqual(self.env.docker.helpers[-1][1], ["stop"])
        self.assertEqual(self.helper("0.1.0").helper_stop(), 0)
        self.assertEqual(self.env.docker.stopped[-1], "updater-0.1.0")
        self.assertEqual(len(self.env.docker.stopped), 4)

    def test_stop_refused_during_update(self):
        self.env.store.write_op({"id": "x", "active": True, "state": "pulling"})
        with self.assertRaises(Conflict):
            self.engine.request_stop()


class ScheduleTests(unittest.TestCase):
    def test_auto_window(self):
        self.assertEqual(auto_window(at("2026-10-15 04:00"), "03:00", "UTC"), "2026-10-15")
        self.assertEqual(auto_window(at("2026-10-15 03:00"), "03:00", "UTC"), "2026-10-15")
        self.assertIsNone(auto_window(at("2026-10-15 02:59"), "03:00", "UTC"))
        self.assertIsNone(auto_window(at("2026-10-15 09:00"), "03:00", "UTC"))
        self.assertEqual(auto_window(at("2026-10-16 01:00"), "23:00", "UTC"), "2026-10-15")
        # 01:00 UTC is 04:00 in Kyiv (summer time ends 2026-10-25).
        self.assertEqual(auto_window(at("2026-10-15 01:00"), "03:00", "Europe/Kyiv"),
                         "2026-10-15")
        self.assertEqual(auto_window(at("2026-10-15 04:00"), "03:00", "Bad/Zone"), "2026-10-15")

    def make(self, when):
        env = Env("0.1.0", clock=Clock(at(when)))
        self.addCleanup(env.cleanup)
        env.install_state("0.1.0")
        env.add_release("0.1.0")
        return env

    def test_auto_update_in_window(self):
        env = self.make("2026-10-15 03:30")
        env.add_release("0.2.0")
        op = env.engine.maybe_auto_update()
        env.engine._worker.join(10)
        self.assertEqual((op["to"], op["source"]), ("0.2.0", "auto"))
        self.assertEqual(env.store.read_op()["state"], "applying")
        env.store.update_op(active=False, state="failed")
        self.assertIsNone(env.engine.maybe_auto_update())  # retried only after 30 min

    def test_auto_update_skips(self):
        env = self.make("2026-10-15 12:00")
        env.add_release("0.2.0")
        self.assertIsNone(env.engine.maybe_auto_update())  # outside the window
        env.clock.now = at("2026-10-15 03:10")
        env.store.update_settings({"auto": False})
        self.assertIsNone(env.engine.maybe_auto_update())
        env.store.update_settings({"auto": True})
        env.store.write_state(failed_versions=["0.2.0"])
        self.assertIsNone(env.engine.maybe_auto_update())
        self.assertEqual(env.store.read_state()["auto_done_window"], "2026-10-15")
        self.assertIsNone(env.store.read_op())

    def test_tick_checks_on_schedule(self):
        env = self.make("2026-10-15 12:00")
        env.engine.reconcile_due = None
        env.engine.tick()
        api = [c for c in env.http.calls if "api.github.com" in c[1]]
        self.assertEqual(len(api), 1)
        env.clock.sleep(600)
        env.engine.tick()
        self.assertEqual(len([c for c in env.http.calls if "api.github.com" in c[1]]), 1)
        env.clock.sleep(6 * 3600)
        env.engine.tick()
        self.assertEqual(len([c for c in env.http.calls if "api.github.com" in c[1]]), 2)


if __name__ == "__main__":
    unittest.main()
