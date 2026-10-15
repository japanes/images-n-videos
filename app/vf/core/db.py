"""SQLite access: one shared connection, a re-entrant lock, small helpers.

Conventions:
- Columns ending in ``_json`` hold JSON. Helpers encode dict/list values on
  write and decode them on read, keeping the column name as is.
- Times are ISO-8601 UTC strings (see ``now()``).
- Never ``await`` inside ``tx()``: the lock is held by the thread.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_local = threading.local()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _encode(key: str, value: Any) -> Any:
    if key.endswith("_json") and value is not None and not isinstance(value, str | bytes):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return int(value)
    return value


def _decode_row(cursor: sqlite3.Cursor, row: tuple) -> dict:
    out: dict[str, Any] = {}
    for (name, *_), value in zip(cursor.description, row, strict=True):
        if name.endswith("_json") and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        out[name] = value
    return out


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = _decode_row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")

    # ── raw access ──────────────────────────────────────────────────────────

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def execute(self, sql: str, params: Iterable | Mapping = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, _params(params))

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)

    def fetch_all(self, sql: str, params: Iterable | Mapping = ()) -> list[dict]:
        with self._lock:
            return self._conn.execute(sql, _params(params)).fetchall()

    def fetch_one(self, sql: str, params: Iterable | Mapping = ()) -> dict | None:
        with self._lock:
            return self._conn.execute(sql, _params(params)).fetchone()

    def fetch_value(self, sql: str, params: Iterable | Mapping = (), default: Any = None) -> Any:
        with self._lock:
            cur = self._conn.execute(sql, _params(params))
            cur.row_factory = None
            row = cur.fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]

    # ── helpers ─────────────────────────────────────────────────────────────

    def insert(self, table: str, values: Mapping[str, Any], *, or_replace: bool = False) -> int:
        cols = list(values)
        verb = "INSERT OR REPLACE" if or_replace else "INSERT"
        sql = (
            f"{verb} INTO {_ident(table)} ({', '.join(_ident(c) for c in cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})"
        )
        with self._lock:
            cur = self._conn.execute(sql, [_encode(c, values[c]) for c in cols])
            return int(cur.lastrowid or 0)

    def update(self, table: str, row_id: int, values: Mapping[str, Any]) -> int:
        if not values:
            return 0
        cols = list(values)
        sql = (
            f"UPDATE {_ident(table)} SET {', '.join(f'{_ident(c)} = ?' for c in cols)} WHERE id = ?"
        )
        with self._lock:
            cur = self._conn.execute(sql, [*(_encode(c, values[c]) for c in cols), row_id])
            return cur.rowcount

    def update_where(self, table: str, where: str, params: Iterable, values: Mapping[str, Any]) -> int:
        cols = list(values)
        sql = f"UPDATE {_ident(table)} SET {', '.join(f'{_ident(c)} = ?' for c in cols)} WHERE {where}"
        with self._lock:
            cur = self._conn.execute(sql, [*(_encode(c, values[c]) for c in cols), *params])
            return cur.rowcount

    def get(self, table: str, row_id: int) -> dict | None:
        return self.fetch_one(f"SELECT * FROM {_ident(table)} WHERE id = ?", (row_id,))

    def delete(self, table: str, row_id: int) -> int:
        with self._lock:
            return self._conn.execute(f"DELETE FROM {_ident(table)} WHERE id = ?", (row_id,)).rowcount

    @contextmanager
    def tx(self) -> Iterator[Database]:
        """A transaction. Nested calls join the outer one (savepoints)."""
        with self._lock:
            depth = getattr(_local, "depth", 0)
            name = f"sp{depth}"
            if depth == 0:
                self._conn.execute("BEGIN IMMEDIATE")
            else:
                self._conn.execute(f"SAVEPOINT {name}")
            _local.depth = depth + 1
            try:
                yield self
            except BaseException:
                if depth == 0:
                    self._conn.execute("ROLLBACK")
                else:
                    self._conn.execute(f"ROLLBACK TO {name}")
                    self._conn.execute(f"RELEASE {name}")
                raise
            else:
                if depth == 0:
                    self._conn.execute("COMMIT")
                else:
                    self._conn.execute(f"RELEASE {name}")
            finally:
                _local.depth = depth

    def backup_to(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(str(target))
        try:
            with self._lock:
                self._conn.backup(dest)
        finally:
            dest.close()


def _ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"bad identifier: {name!r}")
    return f'"{name}"'


def _params(params: Iterable | Mapping) -> Any:
    if isinstance(params, Mapping):
        return {k: _encode(k, v) for k, v in params.items()}
    return [_encode("", v) if isinstance(v, bool) else v for v in params]


# ── process-wide instance ───────────────────────────────────────────────────

_db: Database | None = None


def init(path: Path | str) -> Database:
    global _db
    if _db is not None:
        _db.close()
    _db = Database(path)
    return _db


def instance() -> Database:
    if _db is None:
        raise RuntimeError("database is not initialised")
    return _db


def close() -> None:
    global _db
    if _db is not None:
        _db.close()
        _db = None


def execute(sql: str, params: Iterable | Mapping = ()) -> sqlite3.Cursor:
    return instance().execute(sql, params)


def fetch_all(sql: str, params: Iterable | Mapping = ()) -> list[dict]:
    return instance().fetch_all(sql, params)


def fetch_one(sql: str, params: Iterable | Mapping = ()) -> dict | None:
    return instance().fetch_one(sql, params)


def fetch_value(sql: str, params: Iterable | Mapping = (), default: Any = None) -> Any:
    return instance().fetch_value(sql, params, default)


def insert(table: str, values: Mapping[str, Any], *, or_replace: bool = False) -> int:
    return instance().insert(table, values, or_replace=or_replace)


def update(table: str, row_id: int, values: Mapping[str, Any]) -> int:
    return instance().update(table, row_id, values)


def update_where(table: str, where: str, params: Iterable, values: Mapping[str, Any]) -> int:
    return instance().update_where(table, where, params, values)


def get(table: str, row_id: int) -> dict | None:
    return instance().get(table, row_id)


def delete(table: str, row_id: int) -> int:
    return instance().delete(table, row_id)


def tx():
    return instance().tx()
