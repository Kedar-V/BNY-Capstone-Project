"""Postgres connection helpers for the BNY capstone event datastore."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

DEFAULT_DSN = "postgresql://bny:bny@localhost:5433/bny_capstone"


def get_dsn() -> str:
    return os.environ.get("DATABASE_URL") or os.environ.get("BNY_DATABASE_URL") or DEFAULT_DSN


@contextmanager
def connect(dsn: str | None = None) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(dsn or get_dsn(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
