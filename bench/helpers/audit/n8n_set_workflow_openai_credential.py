#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


def _connect():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "db"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("N8N_DB_NAME", "n8n_data"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )


def _pick_column(columns: set[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _qident(name: str) -> str:
    return f'"{name}"'


def _find_workflow_table(conn) -> str:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('workflow_entity', 'workflows')
            """
        )
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError("No workflow table found (workflow_entity or workflows).")
    names = [r["table_name"] for r in rows]
    return "workflow_entity" if "workflow_entity" in names else names[0]


def _as_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [n for n in value if isinstance(n, dict)]
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [n for n in parsed if isinstance(n, dict)]
    raise RuntimeError("Workflow nodes are missing or invalid JSON.")


def _credential_exists(conn, credential_id: str) -> dict[str, Any]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, type FROM credentials_entity WHERE id = %s",
            (credential_id,),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Credential not found: {credential_id}")
    if row.get("type") != "openAiApi":
        raise RuntimeError(
            f"Credential {credential_id} is type={row.get('type')}, expected openAiApi"
        )
    return dict(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Set OpenAI credential on n8n workflow nodes")
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--credential-id", required=True)
    parser.add_argument("--credential-name", default=None)
    parser.add_argument("--source-credential-id", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    conn = _connect()
    try:
        cred = _credential_exists(conn, args.credential_id)
        target_name = args.credential_name or str(cred.get("name") or "")

        table = _find_workflow_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
            )
            columns = {row["column_name"] for row in cur.fetchall()}

        id_col = _pick_column(columns, "id")
        nodes_col = _pick_column(columns, "nodes")
        updated_col = _pick_column(columns, "updatedAt", "updatedat")
        if not id_col or not nodes_col:
            raise RuntimeError("Workflow table missing required columns.")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {_qident(id_col)} AS id, {_qident(nodes_col)} AS nodes FROM {_qident(table)} WHERE {_qident(id_col)} = %s",
                (args.workflow_id,),
            )
            row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Workflow not found: {args.workflow_id}")

        nodes = _as_nodes(row.get("nodes"))
        changed = 0
        touched = 0
        for node in nodes:
            creds = node.get("credentials")
            if not isinstance(creds, dict):
                continue
            openai = creds.get("openAiApi")
            if not isinstance(openai, dict):
                continue
            touched += 1
            if args.source_credential_id and str(openai.get("id") or "") != args.source_credential_id:
                continue
            prev_id = str(openai.get("id") or "")
            prev_name = str(openai.get("name") or "")
            if prev_id != args.credential_id or (target_name and prev_name != target_name):
                openai["id"] = args.credential_id
                if target_name:
                    openai["name"] = target_name
                changed += 1

        if touched == 0:
            raise RuntimeError("No openAiApi credentials found in workflow nodes.")
        if changed == 0:
            result = {
                "workflow_id": args.workflow_id,
                "changed_nodes": 0,
                "touched_nodes": touched,
                "credential_id": args.credential_id,
                "credential_name": target_name,
                "status": "no-op",
            }
        else:
            nodes_json = json.dumps(nodes, ensure_ascii=True)
            with conn.cursor() as cur:
                if updated_col:
                    cur.execute(
                        f"UPDATE {_qident(table)} SET {_qident(nodes_col)} = %s, {_qident(updated_col)} = %s WHERE {_qident(id_col)} = %s",
                        (nodes_json, dt.datetime.now(dt.timezone.utc), args.workflow_id),
                    )
                else:
                    cur.execute(
                        f"UPDATE {_qident(table)} SET {_qident(nodes_col)} = %s WHERE {_qident(id_col)} = %s",
                        (nodes_json, args.workflow_id),
                    )
            conn.commit()
            result = {
                "workflow_id": args.workflow_id,
                "changed_nodes": changed,
                "touched_nodes": touched,
                "credential_id": args.credential_id,
                "credential_name": target_name,
                "status": "updated",
            }

        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        else:
            print(json.dumps(result, ensure_ascii=True))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
