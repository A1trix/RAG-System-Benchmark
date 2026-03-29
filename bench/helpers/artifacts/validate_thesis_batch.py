#!/usr/bin/env python3
"""Validate a benchmark batch against thesis hard-gate artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        data = None
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def is_running_entry(entry: dict[str, Any]) -> bool:
    state = str(entry.get("State") or "").strip().lower()
    if state:
        return state == "running"
    status = str(entry.get("Status") or "").strip().lower()
    if status:
        return status.startswith("up") or status == "running"
    return True


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def is_configured(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate thesis benchmark batch artifacts")
    parser.add_argument("run_dir", help="Path to bench/results/run_<timestamp>")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    failures: list[str] = []
    notes: list[str] = []

    required_groups = [
        ["runs.jsonl"],
        ["manifest.json"],
        ["docker_images.json"],
        ["source_fingerprint.json"],
        ["n8n_workflow_runtime_snapshot.json"],
        ["n8n_constraints_validation.json"],
        ["db_fingerprint_pre.json"],
        ["db_fingerprint_post.json"],
        ["boundary_audit_report.json"],
        ["analysis/sweep_points.csv"],
        ["analysis/sweep_points_agg.csv"],
        ["analysis/knee_report.json"],
        ["analysis/invalid_points.csv"],
        ["analysis/prompt_mix_report.md"],
    ]
    for candidates in required_groups:
        existing = [run_dir / rel for rel in candidates if (run_dir / rel).exists() and (run_dir / rel).stat().st_size > 0]
        if existing:
            continue
        failures.append(f"missing_or_empty: {' | '.join(candidates)}")

    pre = load_json(run_dir / "db_fingerprint_pre.json") or {}
    post = load_json(run_dir / "db_fingerprint_post.json") or {}
    if pre.get("fingerprint_sha256") != post.get("fingerprint_sha256"):
        failures.append("db fingerprint mismatch (pre vs post)")

    boundary = load_json(run_dir / "boundary_audit_report.json") or {}
    if not boundary.get("pass"):
        failures.append("boundary_audit_report.pass != true")

    n8n_constraints = load_json(run_dir / "n8n_constraints_validation.json") or {}
    if not n8n_constraints.get("pass"):
        failures.append("n8n_constraints_validation.pass != true")

    manifest = load_json(run_dir / "manifest.json") or {}
    bench_env = manifest.get("bench_env") if isinstance(manifest, dict) else {}
    batch_kind = str(manifest.get("batch_kind") or "").strip()
    target_endpoint = str(manifest.get("target_endpoint") or (bench_env.get("BENCH_TARGET_ENDPOINT") if isinstance(bench_env, dict) else "") or "").strip()
    smoke_configured = is_configured(bench_env.get("BENCH_SWEEP_SMOKE_RPM_LIST")) if isinstance(bench_env, dict) else False

    if batch_kind == "isolated_parent_compare":
        failures.append("validate_thesis_batch.py does not validate parent compare dirs; use validate_thesis_pair.py")

    if isinstance(bench_env, dict):
        if str(bench_env.get("BENCH_REQUIRE_BOUNDARY_AUDIT")) != "1":
            notes.append("BENCH_REQUIRE_BOUNDARY_AUDIT not set to 1 in manifest")

        forbidden_manifest_keys = {
            "N8N_AUDIT_OPENAI_CREDENTIAL_NAME",
            "N8N_AUDIT_OPENAI_CREDENTIAL_ID",
            "BOUNDARY_AUDIT_PROMPT_COUNT",
            "BOUNDARY_AUDIT_HTTP_TIMEOUT",
            "BOUNDARY_AUDIT_SLEEP_MS",
            "BOUNDARY_AUDIT_STRICT",
            "BOUNDARY_AUDIT_REQUIRE_ALL_USER_REQUESTS_OK",
            "BOUNDARY_AUDIT_MAX_CHAT_CALL_DELTA_PER_REQUEST",
            "BOUNDARY_AUDIT_MAX_EMBEDDING_CALL_DELTA_PER_REQUEST",
            "BOUNDARY_AUDIT_TOKEN_RATIO_LOWER",
            "BOUNDARY_AUDIT_TOKEN_RATIO_UPPER",
            "BOUNDARY_AUDIT_MIN_PROXY_OK_RATE",
            "UPSTREAM_OPENAI_BASE_URL",
            "PROXY_TIMEOUT_SECONDS",
        }
        leaked_keys = sorted(key for key in forbidden_manifest_keys if key in bench_env)
        for key in leaked_keys:
            failures.append(f"manifest bench_env includes audit-only key: {key}")

        # Optional prereg decision enforcement (only if enabled in manifest).
        if batch_kind != "isolated_child" and str(bench_env.get("BENCH_PREREG_ENFORCE")) == "1":
            prereg_path = run_dir / "analysis" / "prereg_decision.json"
            prereg = load_json(prereg_path) or {}
            if not prereg_path.exists() or prereg_path.stat().st_size == 0:
                failures.append("missing_or_empty: analysis/prereg_decision.json")
            elif not isinstance(prereg, dict):
                failures.append("prereg_decision.json is not a valid object")
            elif not prereg.get("decision_contract_version"):
                failures.append("prereg_decision.decision_contract_version missing")
            elif prereg.get("prereg_schema_version") is None:
                failures.append("prereg_decision.prereg_schema_version missing")
            elif prereg.get("shared_valid_offered_rpms") is None:
                failures.append("prereg_decision.shared_valid_offered_rpms missing")
            elif not prereg.get("conclusion_label"):
                failures.append("prereg_decision.conclusion_label missing")

    runs = load_jsonl(run_dir / "runs.jsonl")
    if not runs:
        failures.append("runs.jsonl has no rows")

    if batch_kind == "isolated_child" and target_endpoint not in {"rag", "n8n"}:
        failures.append("isolated child batch manifest missing valid target_endpoint")

    blank_run_tag_count = sum(
        1
        for row in runs
        if isinstance(row, dict) and not str(row.get("run_tag") or "").strip()
    )
    if batch_kind == "isolated_child" and blank_run_tag_count:
        failures.append(f"runs.jsonl contains {blank_run_tag_count} rows with missing or blank run_tag")

    run_tags = {
        str(row.get("run_tag") or "").strip()
        for row in runs
        if isinstance(row, dict) and str(row.get("run_tag") or "").strip()
    }
    if batch_kind == "isolated_child" and smoke_configured and "sweep_smoke" not in run_tags:
        failures.append("runs.jsonl missing sweep_smoke runs even though BENCH_SWEEP_SMOKE_RPM_LIST is configured")
    if "sweep_primary" not in run_tags:
        failures.append("runs.jsonl does not contain sweep_primary runs")
    if run_tags and run_tags.issubset({"sweep_smoke"}):
        failures.append("batch contains only sweep_smoke runs and is not thesis-valid")
    if batch_kind == "isolated_child":
        allowed_run_tags = {"sweep_smoke", "sweep_primary"}
        unexpected_run_tags = sorted(tag for tag in run_tags if tag not in allowed_run_tags)
        if unexpected_run_tags:
            failures.append(f"isolated child batch contains unexpected run_tag values: {unexpected_run_tags}")

    endpoints = {
        str(row.get("endpoint")).strip()
        for row in runs
        if isinstance(row, dict) and row.get("endpoint") is not None
    }
    if batch_kind == "isolated_child":
        if len(endpoints) != 1:
            failures.append(f"isolated child batch must contain exactly one endpoint, found: {sorted(endpoints)}")
        elif target_endpoint and target_endpoint not in endpoints:
            failures.append(
                f"isolated child batch target_endpoint={target_endpoint} does not match recorded endpoint {sorted(endpoints)}"
            )

    source_fp = load_json(run_dir / "source_fingerprint.json") or {}
    manifest_source_fp_sha = str(
        ((manifest.get("artifacts") or {}).get("source_fingerprint") or {}).get("fingerprint_sha256") or ""
    ).strip()
    batch_source_fp_sha = str(source_fp.get("fingerprint_sha256") or "").strip() if isinstance(source_fp, dict) else ""
    if not manifest_source_fp_sha:
        failures.append("manifest missing artifacts.source_fingerprint.fingerprint_sha256")
    if not batch_source_fp_sha:
        failures.append("source_fingerprint.json missing fingerprint_sha256")
    if manifest_source_fp_sha and batch_source_fp_sha and manifest_source_fp_sha != batch_source_fp_sha:
        failures.append(
            "manifest source_fingerprint fingerprint_sha256 does not match source_fingerprint.json"
        )

    roots = source_fp.get("roots") if isinstance(source_fp, dict) else None
    if isinstance(roots, list):
        forbidden_roots = {"docker-compose.audit.yml", "docker-compose.override.yml"}
        root_labels = {
            str(root.get("label"))
            for root in roots
            if isinstance(root, dict) and root.get("label") is not None
        }
        for label in sorted(forbidden_roots & root_labels):
            failures.append(f"source_fingerprint includes unexpected root: {label}")

    compose_ps = load_json_rows(run_dir / "compose_ps.json")
    images_rows = load_json_rows(run_dir / "docker_images.json")
    if compose_ps and images_rows:
        active_services = {
            str(row.get("Service"))
            for row in compose_ps
            if isinstance(row, dict) and row.get("Service") and is_running_entry(row)
        }
        leaked_services = {
            str(row.get("Service"))
            for row in images_rows
            if isinstance(row, dict) and row.get("Service") and str(row.get("Service")) not in active_services
        }
        for service in sorted(leaked_services):
            failures.append(f"docker_images includes non-active service: {service}")

    out = {
        "run_dir": str(run_dir),
        "pass": len(failures) == 0,
        "failures": failures,
        "notes": notes,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
