"""Plain SQL migrations from ``app/migrations/NNNN_name.sql``.

Numbering is global and split into ranges so modules never collide:
core 0001–0099, module NN uses NN00–NN99 (e.g. chat = 1500–1599).
Every file not yet applied runs once, in order, inside a transaction.
"""

from __future__ import annotations

import logging
from pathlib import Path

from vf.core.db import Database, now

log = logging.getLogger("vf.migrations")

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def apply_all(database: Database, directory: Path = MIGRATIONS_DIR) -> list[str]:
    database.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {r["name"] for r in database.fetch_all("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in done:
            continue
        sql = path.read_text(encoding="utf-8")
        log.info("applying migration %s", path.name)
        conn = database.connection
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in _split(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)", (path.name, now())
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            log.exception("migration %s failed", path.name)
            raise
        applied.append(path.name)
    return applied


def _split(sql: str) -> list[str]:
    """Split a script into statements (sqlite3.complete_statement aware)."""
    import sqlite3

    out: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            if stmt and stmt != ";":
                out.append(stmt)
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out
