"""Thin Postgres connection helper.

Wraps psycopg so the rest of the pipeline doesn't need to know about it.
Imports are lazy because psycopg is a Phase 2 dependency and not all callers
(e.g. pure-function unit tests) should have to install it.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from . import config


@contextmanager
def connect(dsn: str | None = None) -> Iterator:
    """Yield a psycopg connection with autocommit OFF (use explicit commit)."""
    import psycopg  # lazy

    conn = psycopg.connect(dsn or config.POSTGRES_DSN)
    try:
        yield conn
    finally:
        conn.close()


def apply_schema(dsn: str | None = None) -> None:
    """Run every `infra/sql/*.sql` file against the target database, in order.

    Idempotent (every CREATE is IF NOT EXISTS); safe to call from one-off
    setup scripts or `daily_drift.py --init`. Files are applied in sorted
    filename order, so `init.sql` (00/base tables) precedes `agents.sql`.
    """
    sql_dir = config.REPO_ROOT / "infra" / "sql"
    sql_files = sorted(sql_dir.glob("*.sql"))
    with connect(dsn) as conn, conn.cursor() as cur:
        for path in sql_files:
            cur.execute(path.read_text())
        conn.commit()
