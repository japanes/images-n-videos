import os
import shutil
import sqlite3
import stat
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from vf_updater import backup
from vf_updater.store import DEFAULT_SETTINGS, Store, validate_settings


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vf-store-", dir=os.environ.get("VF_TEST_TMP") or None)
        self.store = Store(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_token_created_once_with_0600(self):
        token = self.store.ensure_token()
        self.assertGreaterEqual(len(token), 32)
        mode = stat.S_IMODE(os.stat(self.store.token_path).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(self.store.ensure_token(), token)
        self.assertTrue(self.store.check_token(token))
        self.assertTrue(self.store.check_token(token + "\n"))
        self.assertFalse(self.store.check_token("wrong"))
        self.assertFalse(self.store.check_token(""))
        self.assertFalse(self.store.check_token(None))

    def test_no_token_file_rejects_everything(self):
        self.assertFalse(self.store.check_token(""))
        self.assertFalse(self.store.check_token("x"))

    def test_settings(self):
        self.assertEqual(self.store.read_settings(), DEFAULT_SETTINGS)
        updated = self.store.update_settings({"auto": False, "time": "04:30",
                                              "tz": "Europe/Kyiv", "channel": "beta"})
        self.assertEqual(updated, {"auto": False, "time": "04:30", "tz": "Europe/Kyiv",
                                   "channel": "beta"})
        self.assertEqual(self.store.read_settings(), updated)
        for bad in ({"auto": "yes"}, {"time": "25:00"}, {"time": "3:00"}, {"tz": "Mars/Base"},
                    {"channel": "nightly"}, {"color": "red"}, []):
            with self.assertRaises(ValueError):
                validate_settings(bad, DEFAULT_SETTINGS)

    def test_corrupt_files_fall_back(self):
        self.store.ensure_dirs()
        with open(self.store.settings_path, "w") as fh:
            fh.write("{not json")
        with open(self.store.state_path, "w") as fh:
            fh.write("[]")
        self.assertEqual(self.store.read_settings(), DEFAULT_SETTINGS)
        self.assertEqual(self.store.read_state(), {})

    def test_state_and_op_atomic(self):
        self.store.write_state(installed_version="1.0.0")
        self.store.write_state(previous_version="0.9.0")
        self.assertEqual(self.store.read_state()["installed_version"], "1.0.0")
        self.store.write_op({"id": "x", "state": "preparing", "unknown_future_field": 1})
        op = self.store.op_log("hello", state="pulling")
        self.assertEqual(op["state"], "pulling")
        self.assertEqual(op["step_log"][-1]["message"], "hello")
        self.assertEqual(op["step_log"][-1]["state"], "pulling")
        self.assertEqual(self.store.read_op()["unknown_future_field"], 1)
        leftovers = [n for n in os.listdir(self.store.root) if ".tmp" in n]
        self.assertEqual(leftovers, [])

    def test_history_newest_first(self):
        for i in range(5):
            self.store.append_history({"version_to": f"0.{i}.0"})
        with open(self.store.history_path, "a") as fh:
            fh.write("garbage\n")
        items = self.store.read_history(limit=3)
        self.assertEqual([i["version_to"] for i in items], ["0.4.0", "0.3.0", "0.2.0"])


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vf-backup-", dir=os.environ.get("VF_TEST_TMP") or None)
        self.db = os.path.join(self.tmp, "app.db")
        self.dir = os.path.join(self.tmp, "backups")
        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('before')")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY rowid")]
        finally:
            conn.close()

    def test_missing_db(self):
        self.assertIsNone(backup.create(os.path.join(self.tmp, "none.db"), self.dir, "1.0.0"))

    def test_create_and_restore(self):
        path = backup.create(self.db, self.dir, "1.0.0")
        self.assertTrue(os.path.basename(path).startswith("app-1.0.0-"))
        self.assertTrue(path.endswith("Z.db"))
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO t VALUES ('after')")
        conn.execute("CREATE TABLE new_schema (x)")
        conn.commit()
        conn.close()
        self.assertEqual(self.rows(), ["before", "after"])
        backup.restore(path, self.db)
        self.assertEqual(self.rows(), ["before"])
        conn = sqlite3.connect(self.db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        conn.close()
        self.assertNotIn("new_schema", tables)

    def test_restore_missing_backup(self):
        with self.assertRaises(FileNotFoundError):
            backup.restore(os.path.join(self.tmp, "nope.db"), self.db)

    def test_rotation_keeps_five(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        made = []
        for i in range(7):
            path = backup.create(self.db, self.dir, "1.0.0", now=start + timedelta(hours=i))
            mtime = time.time() - 1000 + i
            os.utime(path, (mtime, mtime))
            made.append(path)
        other = os.path.join(self.dir, "user-file.db")
        open(other, "w").close()
        removed = backup.rotate(self.dir, keep=5)
        self.assertEqual(sorted(removed), sorted(made[:2]))
        self.assertEqual(backup.list_backups(self.dir), list(reversed(made[2:])))
        self.assertTrue(os.path.exists(other))

    def test_rotation_protects_current(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        made = []
        for i in range(6):
            path = backup.create(self.db, self.dir, "1.0.0", now=start + timedelta(hours=i))
            mtime = time.time() - 1000 + (100 - i if i == 0 else i)
            os.utime(path, (mtime, mtime))
            made.append(path)
        removed = backup.rotate(self.dir, keep=1, protect=[made[1]])
        self.assertNotIn(made[1], removed)
        self.assertTrue(os.path.exists(made[1]))


if __name__ == "__main__":
    unittest.main()
