#!/usr/bin/env python3
"""Export the active n8n workflow JSON from the n8n Postgres database.

Purpose: make the benchmark configuration machine-verifiable.

The on-disk workflow export (e.g. n8n_workflows/...) is not sufficient to prove
what the running n8n instance actually executed. This script captures the
workflow as stored in the n8n DB at run time.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _connect():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "db"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("N8N_DB_NAME", "n8n_data"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )


def _webhook_path_from_url(url: str) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    parts = [seg for seg in (p.path or "").split("/") if seg]
    if not parts:
        return None
    # Expected: /webhook/<path>
    if "webhook" in parts:
        idx = parts.index("webhook")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1]


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _parse_json_field(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return value
        try:
            return json.loads(s)
        except Exception:
            return value
    return value


def _extract_openai_credential_summary(nodes: Any) -> dict[str, Any]:
    if not isinstance(nodes, list):
        return {
            "openai_nodes": [],
            "openai_credential_ids": [],
            "openai_credential_names": [],
        }

    node_entries: list[dict[str, Any]] = []
    ids = set()
    names = set()

    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        creds = node.get("credentials")
        if not isinstance(creds, dict):
            continue
        openai = creds.get("openAiApi")
        if not isinstance(openai, dict):
            continue
        cid = openai.get("id")
        cname = openai.get("name")
        node_entries.append(
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "type": ntype,
                "credential_id": cid,
                "credential_name": cname,
            }
        )
        if cid:
            ids.add(str(cid))
        if cname:
            names.add(str(cname))

    node_entries.sort(key=lambda x: (str(x.get("type") or ""), str(x.get("name") or "")))
    return {
        "openai_nodes": node_entries,
        "openai_credential_ids": sorted(ids),
        "openai_credential_names": sorted(names),
    }


def _pick_column(columns: set[str], *candidates: str) -> str | None:
    for c in candidates:
        if c in columns:
            return c
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
    # Prefer the common n8n TypeORM table
    names = [r["table_name"] for r in rows]
    return "workflow_entity" if "workflow_entity" in names else names[0]


def snapshot_workflow(
    conn,
    *,
    workflow_id: str | None,
    webhook_path: str | None,
    limit_candidates: int = 10,
    require_unique: bool = False,
    expected_openai_credential_id: str | None = None,
    expected_openai_credential_name: str | None = None,
) -> dict[str, Any]:
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
    name_col = _pick_column(columns, "name")
    active_col = _pick_column(columns, "active")
    nodes_col = _pick_column(columns, "nodes")
    connections_col = _pick_column(columns, "connections")
    settings_col = _pick_column(columns, "settings")
    static_data_col = _pick_column(columns, "staticData", "staticdata")
    meta_col = _pick_column(columns, "meta")
    created_col = _pick_column(columns, "createdAt", "createdat")
    updated_col = _pick_column(columns, "updatedAt", "updatedat")

    def sel(column: str | None, alias: str) -> str:
        if not column:
            return f"NULL AS {alias}"
        return f"{_qident(column)} AS {alias}"

    select_parts = [
        sel(id_col, "id"),
        sel(name_col, "name"),
        sel(active_col, "active"),
        sel(nodes_col, "nodes"),
        sel(connections_col, "connections"),
        sel(settings_col, "settings"),
        sel(static_data_col, "static_data"),
        sel(meta_col, "meta"),
        sel(created_col, "created_at"),
        sel(updated_col, "updated_at"),
    ]

    where = ""
    params: list[Any] = []
    selection: dict[str, Any] = {"mode": None}

    if workflow_id:
        if not id_col:
            raise RuntimeError("Workflow table has no id column")
        where = f"WHERE {_qident(id_col)} = %s"
        params = [workflow_id]
        selection = {"mode": "workflow_id", "workflow_id": workflow_id}
    else:
        if not webhook_path:
            raise RuntimeError("Either workflow_id or webhook_path must be provided")
        if not nodes_col:
            raise RuntimeError("Workflow table has no nodes column; cannot search by webhook path")
        where = f"WHERE {_qident(nodes_col)}::text ILIKE %s"
        params = [f"%{webhook_path}%"]
        selection = {"mode": "webhook_path", "webhook_path": webhook_path}

    order_by = ""
    if updated_col:
        order_by = f"ORDER BY {_qident(updated_col)} DESC"
    elif id_col:
        order_by = f"ORDER BY {_qident(id_col)} DESC"

    query = f"""
        SELECT {", ".join(select_parts)}
        FROM {_qident(table)}
        {where}
        {order_by}
        LIMIT {int(limit_candidates)}
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        raise RuntimeError(f"No workflow matched selection: {selection}")

    if require_unique and selection.get("mode") != "workflow_id" and len(rows) > 1:
        # Ambiguous selection; force explicit workflow id for thesis-grade reproducibility.
        candidates = [{"id": r.get("id"), "name": r.get("name"), "active": r.get("active")} for r in rows]
        raise RuntimeError(
            "Multiple workflows matched selection; set N8N_WORKFLOW_ID or pass --workflow-id to disambiguate. "
            + json.dumps({"selection": selection, "candidates": candidates}, ensure_ascii=True)
        )

    # Pick the best candidate (first row due to ORDER BY).
    chosen = rows[0]
    candidates = []
    for r in rows:
        candidates.append(
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "active": r.get("active"),
                "updated_at": str(r.get("updated_at")) if r.get("updated_at") is not None else None,
                "created_at": str(r.get("created_at")) if r.get("created_at") is not None else None,
            }
        )

    workflow = {
        "id": chosen.get("id"),
        "name": chosen.get("name"),
        "active": chosen.get("active"),
        "nodes": _parse_json_field(chosen.get("nodes")),
        "connections": _parse_json_field(chosen.get("connections")),
        "settings": _parse_json_field(chosen.get("settings")),
        "staticData": _parse_json_field(chosen.get("static_data")),
        "meta": _parse_json_field(chosen.get("meta")),
        "createdAt": str(chosen.get("created_at")) if chosen.get("created_at") is not None else None,
        "updatedAt": str(chosen.get("updated_at")) if chosen.get("updated_at") is not None else None,
    }

    openai_summary = _extract_openai_credential_summary(workflow.get("nodes"))
    workflow.update(openai_summary)

    if expected_openai_credential_id:
        ids = set(openai_summary.get("openai_credential_ids") or [])
        if expected_openai_credential_id not in ids:
            raise RuntimeError(
                "Expected n8n OpenAI credential id not present in workflow nodes: "
                + json.dumps(
                    {
                        "expected_openai_credential_id": expected_openai_credential_id,
                        "observed_openai_credential_ids": sorted(ids),
                    },
                    ensure_ascii=True,
                )
            )

    if expected_openai_credential_name:
        names = set(openai_summary.get("openai_credential_names") or [])
        if expected_openai_credential_name not in names:
            raise RuntimeError(
                "Expected n8n OpenAI credential name not present in workflow nodes: "
                + json.dumps(
                    {
                        "expected_openai_credential_name": expected_openai_credential_name,
                        "observed_openai_credential_names": sorted(names),
                    },
                    ensure_ascii=True,
                )
            )

    # Stable hash over content-relevant workflow fields.
    content_obj = {
        "nodes": workflow.get("nodes"),
        "connections": workflow.get("connections"),
        "settings": workflow.get("settings"),
        "staticData": workflow.get("staticData"),
        "meta": workflow.get("meta"),
    }
    import hashlib

    content_sha = hashlib.sha256(_canonical_json_bytes(content_obj)).hexdigest()

    return {
        "generated_at": _utc_now_iso(),
        "db": {
            "host": os.getenv("POSTGRES_HOST", "db"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "dbname": os.getenv("N8N_DB_NAME", "n8n_data"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "table": table,
        },
        "selection": selection,
        "candidates": candidates,
        "workflow": workflow,
        "workflow_content_sha256": content_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export active n8n workflow JSON from DB")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--workflow-id", default=os.getenv("N8N_WORKFLOW_ID"), help="Workflow id (preferred)")
    parser.add_argument(
        "--webhook-url",
        default=os.getenv("N8N_WEBHOOK_URL"),
        help="Webhook URL to infer webhook path (fallback selection)",
    )
    parser.add_argument(
        "--webhook-path",
        default=os.getenv("N8N_WEBHOOK_PATH"),
        help="Webhook path to search in workflow nodes JSON (fallback selection)",
    )
    parser.add_argument("--limit", type=int, default=10, help="Max candidate workflows to return")
    parser.add_argument(
        "--expected-openai-credential-id",
        default=os.getenv("N8N_OPENAI_CREDENTIAL_ID") or None,
        help="Fail if this OpenAI credential id is not used in workflow nodes.",
    )
    parser.add_argument(
        "--expected-openai-credential-name",
        default=os.getenv("N8N_OPENAI_CREDENTIAL_NAME") or None,
        help="Fail if this OpenAI credential name is not used in workflow nodes.",
    )
    parser.add_argument(
        "--require-unique",
        action="store_true",
        help="Fail if multiple workflows match webhook-path selection (recommended).",
    )
    args = parser.parse_args()

    webhook_path = args.webhook_path
    if not args.workflow_id and not webhook_path:
        webhook_path = _webhook_path_from_url(args.webhook_url or "")

    conn = _connect()
    try:
        snap = snapshot_workflow(
            conn,
            workflow_id=args.workflow_id,
            webhook_path=webhook_path,
            limit_candidates=int(args.limit),
            require_unique=bool(args.require_unique),
            expected_openai_credential_id=args.expected_openai_credential_id,
            expected_openai_credential_name=args.expected_openai_credential_name,
        )
    finally:
        conn.close()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
