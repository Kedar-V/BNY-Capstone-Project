#!/usr/bin/env python3
"""Initialize Postgres schema and load corpus into the BNY event datastore.

Usage:
  docker compose up -d
  python scripts/init_db.py
  python scripts/init_db.py --no-reset   # upsert without truncating
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from db.connection import get_dsn  # noqa: E402
from db.load import load_all  # noqa: E402


def wait_for_db(timeout_sec: int = 60) -> None:
    import psycopg

    dsn = get_dsn()
    deadline = time.time() + timeout_sec
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5)
    raise RuntimeError(f"Postgres not reachable at {dsn}: {last_err}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-reset", action="store_true", help="Do not truncate before load")
    parser.add_argument("--dsn", default=None, help="Override DATABASE_URL")
    args = parser.parse_args()

    if args.dsn:
        import os

        os.environ["DATABASE_URL"] = args.dsn

    print("DSN:", get_dsn())
    wait_for_db()
    counts = load_all(reset=not args.no_reset, dsn=get_dsn())
    print(json.dumps(counts, indent=2))
    print("Done.")


if __name__ == "__main__":
    main()
