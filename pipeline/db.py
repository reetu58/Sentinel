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
    """Run `infra/sql/init.sql` against the target database.

    Idempotent (every CREATE is IF NOT EXISTS); safe to call from one-off
    setup scripts or `daily_drift.py --init`.
    """
    sql_path = config.REPO_ROOT / "infra" / "sql" / "init.sql"
    sql = sql_path.read_text()
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()
