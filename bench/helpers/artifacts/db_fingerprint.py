#!/usr/bin/env python3
"""Generate a stable fingerprint of the Postgres RAG dataset.

This is used as a hard gate for benchmark validity:
- The dataset must not change during a benchmark run.
- The fingerprint is stored as an artifact (reproducibility).

The script only inspects DB state; it does not mutate.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
from typing import Any

import psycopg2


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _connect():
    host = os.getenv("POSTGRES_HOST", "db")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    dbname = os.getenv("POSTGRES_DB", "postgres")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    return psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = %s
        );
        """,
        (table,),
    )
    return bool(cur.fetchone()[0])


def _fingerprint_documents(cur, table: str) -> dict[str, Any]:
    if not _table_exists(cur, table):
        return {"table": table, "exists": False}

    # Basic per-file stats. (text column name is "text" in both implementations.)
    cur.execute(
        f"""
        SELECT
          COALESCE(metadata->>'file_id', '') AS file_id,
          COUNT(*) AS chunk_count,
          SUM(LENGTH(text)) AS text_len_sum,
          MIN(LENGTH(text)) AS text_len_min,
          MAX(LENGTH(text)) AS text_len_max
        FROM {table}
        GROUP BY COALESCE(metadata->>'file_id', '')
        ORDER BY file_id ASC;
        """
    )
    per_file = []
    for file_id, chunk_count, text_len_sum, text_len_min, text_len_max in cur.fetchall():
        per_file.append(
            {
                "file_id": file_id,
                "chunk_count": int(chunk_count),
                "text_len_sum": int(text_len_sum or 0),
                "text_len_min": int(text_len_min or 0),
                "text_len_max": int(text_len_max or 0),
            }
        )

    # Stable signatures independent of row ordering.
    # We hash md5(text) and md5(embedding::text) values sorted lexicographically per file_id.
    cur.execute(
        f"""
        SELECT
          COALESCE(metadata->>'file_id', '') AS file_id,
          md5(COALESCE(string_agg(md5(text), '' ORDER BY md5(text)), '')) AS text_md5,
          md5(
            COALESCE(
              string_agg(
                md5(COALESCE(embedding::text, '')),
                ''
                ORDER BY md5(COALESCE(embedding::text, ''))
              ),
              ''
            )
          ) AS embedding_md5
        FROM {table}
        GROUP BY COALESCE(metadata->>'file_id', '')
        ORDER BY file_id ASC;
        """
    )
    per_file_md5 = []
    for file_id, text_md5, embedding_md5 in cur.fetchall():
        per_file_md5.append(
            {
                "file_id": file_id,
                "text_md5": text_md5 or "",
                "embedding_md5": embedding_md5 or "",
            }
        )

    # Global stats
    cur.execute(f"SELECT COUNT(*) FROM {table};")
    total_rows = int(cur.fetchone()[0])
    cur.execute(f"SELECT COUNT(DISTINCT COALESCE(metadata->>'file_id','')) FROM {table};")
    distinct_files = int(cur.fetchone()[0])

    return {
        "table": table,
        "exists": True,
        "total_rows": total_rows,
        "distinct_file_ids": distinct_files,
        "per_file": per_file,
        "per_file_signatures": per_file_md5,
    }


def _fingerprint_simple_count(cur, table: str, key_expr: str) -> dict[str, Any]:
    if not _table_exists(cur, table):
        return {"table": table, "exists": False}

    cur.execute(
        f"""
        SELECT
          COALESCE({key_expr}, '') AS key,
          COUNT(*) AS row_count
        FROM {table}
        GROUP BY COALESCE({key_expr}, '')
        ORDER BY key ASC;
        """
    )
    grouped = [{"key": k, "row_count": int(c)} for k, c in cur.fetchall()]
    cur.execute(f"SELECT COUNT(*) FROM {table};")
    total_rows = int(cur.fetchone()[0])
    return {
        "table": table,
        "exists": True,
        "total_rows": total_rows,
        "grouped": grouped,
    }


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def build_fingerprint() -> dict[str, Any]:
    table_docs = os.getenv("PGVECTOR_TABLE", "documents_pg")
    table_meta = os.getenv("DOCUMENT_METADATA_TABLE", "document_metadata")
    table_rows = os.getenv("DOCUMENT_ROWS_TABLE", "document_rows")

    conn = _connect()
    try:
        with conn.cursor() as cur:
            docs = _fingerprint_documents(cur, table_docs)
            # document_metadata schema uses primary key column "id" (file_id).
            meta = _fingerprint_simple_count(cur, table_meta, "id")
            rows = _fingerprint_simple_count(cur, table_rows, "dataset_id")
    finally:
        conn.close()

    fingerprint: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "db": {
            "host": os.getenv("POSTGRES_HOST", "db"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "dbname": os.getenv("POSTGRES_DB", "postgres"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
        },
        "tables": {
            "documents": docs,
            "document_metadata": meta,
            "document_rows": rows,
        },
    }

    # Stable hash over content-relevant parts.
    # Exclude generated_at to keep hash stable across runs.
    for_hash = dict(fingerprint)
    for_hash.pop("generated_at", None)
    digest = hashlib.sha256(_canonical_json_bytes(for_hash)).hexdigest()
    fingerprint["fingerprint_sha256"] = digest
    return fingerprint


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a stable DB fingerprint for RAG benchmark gating")
    parser.add_argument("--output", help="Write fingerprint JSON to file (otherwise stdout)")
    parser.add_argument("--compare", help="Compare against an existing fingerprint JSON file; exit non-zero on mismatch")
    args = parser.parse_args()

    fp = build_fingerprint()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(fp, handle, indent=2, sort_keys=True)
    else:
        print(json.dumps(fp, indent=2, sort_keys=True))

    if args.compare:
        with open(args.compare, "r", encoding="utf-8") as handle:
            other = json.load(handle)
        if other.get("fingerprint_sha256") != fp.get("fingerprint_sha256"):
            print(
                json.dumps(
                    {
                        "match": False,
                        "expected_fingerprint_sha256": other.get("fingerprint_sha256"),
                        "actual_fingerprint_sha256": fp.get("fingerprint_sha256"),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        print(json.dumps({"match": True, "fingerprint_sha256": fp.get("fingerprint_sha256")}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
