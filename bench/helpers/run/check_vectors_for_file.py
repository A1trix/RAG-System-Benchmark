#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

import psycopg2


def main() -> int:
    parser = argparse.ArgumentParser(description="Check vectors exist for file_id")
    parser.add_argument("--table", required=True)
    parser.add_argument("--file-id", required=True)
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "db"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "postgres"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )

    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {args.table} WHERE metadata->>'file_id' = %s;", (args.file_id,))
            count = cur.fetchone()[0]
    except Exception as exc:
        print(f"vector check failed for table {args.table}: {exc}")
        return 2
    finally:
        conn.close()

    if count <= 0:
        print(f"no vectors found for file_id={args.file_id} in {args.table}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
