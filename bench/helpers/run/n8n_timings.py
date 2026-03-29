import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import RealDictCursor


def parse_time(value: str) -> datetime:
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def load_execution_rows(conn, since: datetime, until: datetime):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('execution_entity', 'executions')
            """
        )
        tables = [row["table_name"] for row in cur.fetchall()]
    if not tables:
        raise RuntimeError("No n8n execution table found (execution_entity or executions).")

    table = "execution_entity" if "execution_entity" in tables else "executions"

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

    def pick(*candidates):
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None

    def col_expr(column_name: str, alias: str):
        return f'"{column_name}" AS {alias}'

    started_col = pick("startedAt", "startedat")
    stopped_col = pick("stoppedAt", "stoppedat")
    workflow_col = pick("workflowId", "workflowid")
    status_col = pick("status")
    exec_time_col = pick("executionTime", "executiontime")
    exec_data_col = pick("executionData", "executiondata")

    select_parts = [col_expr("id", "id")]
    select_parts.append(col_expr(workflow_col, "workflow_id") if workflow_col else "NULL AS workflow_id")
    select_parts.append(col_expr(status_col, "status") if status_col else "NULL AS status")
    select_parts.append(col_expr(started_col, "started_at") if started_col else "NULL AS started_at")
    select_parts.append(col_expr(stopped_col, "stopped_at") if stopped_col else "NULL AS stopped_at")
    select_parts.append(
        col_expr(exec_time_col, "execution_time_ms") if exec_time_col else "NULL AS execution_time_ms"
    )
    select_parts.append(
        col_expr(exec_data_col, "execution_data") if exec_data_col else "NULL AS execution_data"
    )

    where_clause = ""
    params = []
    if started_col:
        where_clause = f'WHERE "{started_col}" >= %s AND "{started_col}" <= %s'
        params = [since, until]
    elif stopped_col:
        where_clause = f'WHERE "{stopped_col}" >= %s AND "{stopped_col}" <= %s'
        params = [since, until]

    query = f"""
        SELECT {", ".join(select_parts)}
        FROM \"{table}\"
        {where_clause}
        ORDER BY id
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def extract_node_timings(execution_data):
    if not execution_data:
        return []
    if isinstance(execution_data, str):
        try:
            execution_data = json.loads(execution_data)
        except json.JSONDecodeError:
            return []

    result_data = execution_data.get("resultData", {})
    run_data = result_data.get("runData", {})
    timings = []
    for node_name, runs in run_data.items():
        if not isinstance(runs, list):
            continue
        for idx, run in enumerate(runs):
            if not isinstance(run, dict):
                continue
            timings.append(
                {
                    "node": node_name,
                    "run_index": idx,
                    "execution_time_ms": run.get("executionTime"),
                    "start_time": run.get("startTime"),
                }
            )
    return timings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="ISO timestamp (UTC)")
    parser.add_argument("--until", help="ISO timestamp (UTC)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    until = parse_time(args.until) if args.until else datetime.now(timezone.utc)
    since = parse_time(args.since) if args.since else until - timedelta(hours=1)

    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "db"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("N8N_DB_NAME", "n8n_data"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )
    rows = load_execution_rows(conn, since, until)
    conn.close()

    mode = "a" if args.append else "w"
    with open(args.output, mode, encoding="utf-8") as handle:
        for row in rows:
            started_at = row.get("started_at")
            stopped_at = row.get("stopped_at")
            duration_ms = None
            if started_at and stopped_at:
                duration_ms = int((stopped_at - started_at).total_seconds() * 1000)

            payload = {
                "run_id": args.run_id,
                "execution_id": row.get("id"),
                "workflow_id": row.get("workflow_id"),
                "status": row.get("status"),
                "started_at": started_at.isoformat() if started_at else None,
                "stopped_at": stopped_at.isoformat() if stopped_at else None,
                "duration_ms": duration_ms,
                "execution_time_ms": row.get("execution_time_ms"),
                "node_timings": extract_node_timings(row.get("execution_data")),
            }
            handle.write(json.dumps(payload) + "\n")


if __name__ == "__main__":
    main()
