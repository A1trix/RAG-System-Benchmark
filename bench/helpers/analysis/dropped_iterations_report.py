#!/usr/bin/env python3
"""Build a dropped-iterations diagnosis report for one benchmark run folder.

Usage:
  python3 bench/helpers/analysis/dropped_iterations_report.py bench/results/run_<timestamp>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Optional


ARRIVAL_RUN_RE = re.compile(
    r"^arrival-(?P<endpoint>[^-]+)-(?P<prompt_set>[^-]+)-(?P<rpm>\d+)rpm-rep(?P<rep>\d+)-.+$"
)
FRONTIER_RUN_RE = ARRIVAL_RUN_RE


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def as_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def as_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def metric_values(metric: Any) -> dict[str, Any]:
    if isinstance(metric, dict):
        vals = metric.get("values")
        if isinstance(vals, dict):
            return vals
        return metric
    return {}


def counter_count_best_effort(metrics: dict[str, Any], base: str, required_substrings: list[str]) -> Optional[int]:
    for key, metric in metrics.items():
        if not isinstance(key, str):
            continue
        if not (key == base or key.startswith(base + "{")):
            continue
        if any(s not in key for s in required_substrings):
            continue
        c = as_int(metric_values(metric).get("count"))
        if c is not None:
            return c
    return None


def trend_quantile_ms(metrics: dict[str, Any], base: str, quantile_key: str) -> Optional[float]:
    keys: list[str] = [
        f"{base}{{scenario:measure}}",
        f"{base}{{expected_response:true,scenario:measure}}",
        f"{base}{{scenario:measure,expected_response:true}}",
        f"{base}{{expected_response:true}}",
        base,
    ]
    for key in keys:
        vals = metric_values(metrics.get(key))
        if vals:
            v = as_float(vals.get(quantile_key))
            if v is not None:
                return v
    for key, metric in metrics.items():
        if not isinstance(key, str) or not key.startswith(base):
            continue
        vals = metric_values(metric)
        v = as_float(vals.get(quantile_key))
        if v is not None:
            return v
    return None


def safe_div(a: Optional[float | int], b: Optional[float | int]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    try:
        return float(a) / float(b)
    except Exception:
        return None


def parse_duration_seconds(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().lower()
    if not s:
        return None
    try:
        if s.endswith("ms"):
            return float(s[:-2]) / 1000.0
        if s.endswith("s"):
            return float(s[:-1])
        if s.endswith("m"):
            return float(s[:-1]) * 60.0
        if s.endswith("h"):
            return float(s[:-1]) * 3600.0
        return float(s)
    except Exception:
        return None


def classify_reasons(row: dict[str, Any]) -> tuple[str, str]:
    dropped = as_int(row.get("dropped_iterations_count")) or 0
    if dropped <= 0:
        return "none", "No dropped iterations detected."

    reasons: list[str] = []
    recs: list[str] = []

    vus_max = as_int(row.get("vus_max"))
    vus_cap = as_int(row.get("vus_cap"))
    prealloc = as_int(row.get("preallocated_vus_cfg"))
    timeout_rate = as_float(row.get("timeout_rate"))
    error_rate_total = as_float(row.get("error_rate_total"))
    required_conc = as_float(row.get("required_concurrency_est"))
    delivery_ratio = as_float(row.get("delivery_ratio"))
    p95_s = as_float(row.get("latency_p95_s"))
    offered_rpm = as_int(row.get("offered_rpm"))

    if vus_max is not None and vus_cap is not None and vus_max >= vus_cap:
        reasons.append("vu_cap_hit")
        recs.append("Increase BENCH_ARRIVAL_MAX_VUS and re-run this RPM.")

    if required_conc is not None and prealloc is not None and required_conc > float(prealloc):
        reasons.append("preallocated_vus_too_low")
        recs.append("Increase BENCH_ARRIVAL_PREALLOCATED_VUS to reduce scheduler ramp-up misses.")

    if required_conc is not None and vus_cap is not None and required_conc > 0.8 * float(vus_cap):
        reasons.append("service_latency_pressure")
        recs.append("Reduce RPM or increase service capacity; long request duration needs higher concurrency.")

    if delivery_ratio is not None and delivery_ratio < 0.95:
        reasons.append("arrival_not_sustained")
        recs.append("Point did not sustain requested arrival rate in measure window; reduce RPM or increase capacity.")

    if p95_s is not None and offered_rpm is not None and offered_rpm > 0:
        interarrival_s = 60.0 / float(offered_rpm)
        if p95_s > interarrival_s:
            reasons.append("long_request_duration_vs_interarrival")
            recs.append("Request duration exceeds inter-arrival spacing; higher concurrency or lower RPM is required.")

    if timeout_rate is not None and timeout_rate > 0:
        reasons.append("timeout_pressure")
        recs.append("Investigate timeout sources (backend latency/upstream model/network) before scaling load.")

    if error_rate_total is not None and error_rate_total > 0:
        reasons.append("error_pressure")
        recs.append("Investigate application/transport errors at this load level.")

    if not reasons:
        reasons.append("unknown")
        recs.append("Inspect k6 host/container CPU and network; if healthy, increase VU headroom and rerun.")

    return ";".join(dict.fromkeys(reasons)), " ".join(dict.fromkeys(recs))


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose dropped iterations for a benchmark run folder")
    parser.add_argument("results_dir", help="Path to bench/results/run_<timestamp>")
    parser.add_argument("--run-tag", action="append", default=[], help="Filter by run_tag from runs.jsonl (repeatable)")
    parser.add_argument("--csv-out", default=None, help="Output CSV path (default: <results_dir>/analysis/dropped_iterations_report.csv)")
    parser.add_argument("--md-out", default=None, help="Output Markdown path (default: <results_dir>/analysis/dropped_iterations_report.md)")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists() or not results_dir.is_dir():
        print(f"results_dir not found or not a directory: {results_dir}")
        return 2

    analysis_dir = results_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    csv_out = Path(args.csv_out) if args.csv_out else (analysis_dir / "dropped_iterations_report.csv")
    md_out = Path(args.md_out) if args.md_out else (analysis_dir / "dropped_iterations_report.md")

    run_rows = load_jsonl(results_dir / "runs.jsonl")
    run_by_id: dict[str, dict[str, Any]] = {}
    for r in run_rows:
        rid = r.get("run_id")
        if isinstance(rid, str):
            run_by_id[rid] = r

    include_tags = {str(x).strip() for x in args.run_tag if str(x).strip()}

    rows: list[dict[str, Any]] = []
    for summary_path in sorted(results_dir.glob("arrival-*.json")):
        run_id = summary_path.stem
        m = FRONTIER_RUN_RE.match(run_id)
        if not m:
            continue

        rr = run_by_id.get(run_id, {})
        run_tag = str(rr.get("run_tag") or "")
        if include_tags and run_tag not in include_tags:
            continue

        data = load_json(summary_path)
        metrics_raw = data.get("metrics")
        metrics: dict[str, Any] = metrics_raw if isinstance(metrics_raw, dict) else {}
        options_raw = data.get("options")
        options: dict[str, Any] = options_raw if isinstance(options_raw, dict) else {}
        scenarios_raw = options.get("scenarios")
        scenarios: dict[str, Any] = scenarios_raw if isinstance(scenarios_raw, dict) else {}
        measure_raw = scenarios.get("measure")
        measure: dict[str, Any] = measure_raw if isinstance(measure_raw, dict) else {}
        measure_seconds = parse_duration_seconds(measure.get("duration"))
        if measure_seconds is None:
            measure_seconds = parse_duration_seconds(rr.get("measure_seconds"))

        attempts = counter_count_best_effort(metrics, "attempts_measure", ["scenario:measure"])
        if attempts is None:
            attempts = counter_count_best_effort(metrics, "attempts_measure", [])

        successes = counter_count_best_effort(metrics, "successes_measure", ["scenario:measure"])
        if successes is None:
            successes = counter_count_best_effort(metrics, "successes_measure", [])

        dropped = counter_count_best_effort(metrics, "dropped_iterations", ["scenario:measure"])
        dropped_source = "metric"
        if dropped is None:
            dropped = counter_count_best_effort(metrics, "dropped_iterations", [])
            if dropped is not None:
                dropped_source = "metric"
        if dropped is None:
            dropped = as_int(rr.get("dropped_iterations_count"))
            dropped_source = "runs_jsonl" if dropped is not None else "missing"
        dropped = dropped if dropped is not None else 0

        timeouts = counter_count_best_effort(metrics, "timeouts_measure", ["scenario:measure"])
        if timeouts is None:
            timeouts = counter_count_best_effort(metrics, "timeouts_measure", [])
        if timeouts is None and attempts is not None and attempts > 0:
            timeouts = 0

        err_total = counter_count_best_effort(metrics, "errors_total_measure", ["scenario:measure"])
        if err_total is None:
            err_total = counter_count_best_effort(metrics, "errors_total_measure", [])
        if err_total is None and attempts is not None and attempts > 0:
            err_total = 0

        p95_ms = trend_quantile_ms(metrics, "latency_measure_ms", "p(95)")
        if p95_ms is None:
            p95_ms = trend_quantile_ms(metrics, "http_req_duration", "p(95)")

        offered_rpm = int(m.group("rpm"))
        offered_rps = offered_rpm / 60.0
        achieved_attempt_rps = safe_div(attempts, measure_seconds)
        delivery_ratio = safe_div(achieved_attempt_rps, offered_rps)
        p95_s = (p95_ms / 1000.0) if p95_ms is not None else None
        required_concurrency_est = offered_rps * p95_s if p95_s is not None else None

        prealloc = as_int(measure.get("preAllocatedVUs"))
        max_vus_cfg = as_int(measure.get("maxVUs"))
        vus_max_vals = metric_values(metrics.get("vus_max"))
        vus_max = as_int(vus_max_vals.get("value"))
        if vus_max is None:
            vus_max = as_int(vus_max_vals.get("max"))

        vus_cap = as_int(rr.get("vus"))
        if vus_cap is None:
            vus_cap = max_vus_cfg

        row: dict[str, Any] = {
            "run_id": run_id,
            "run_tag": run_tag,
            "endpoint": m.group("endpoint"),
            "prompt_set": m.group("prompt_set"),
            "offered_rpm": offered_rpm,
            "rep": int(m.group("rep")),
            "measure_seconds": measure_seconds,
            "attempts_measure_count": attempts,
            "successes_measure_count": successes,
            "dropped_iterations_count": dropped,
            "dropped_iterations_source": dropped_source,
            "dropped_rate": safe_div(dropped, attempts),
            "timeouts_measure_count": timeouts,
            "errors_total_measure_count": err_total,
            "timeout_rate": safe_div(timeouts, attempts),
            "error_rate_total": safe_div(err_total, attempts),
            "latency_p95_s": p95_s,
            "offered_rps": offered_rps,
            "achieved_attempt_rps": achieved_attempt_rps,
            "delivery_ratio": delivery_ratio,
            "preallocated_vus_cfg": prealloc,
            "max_vus_cfg": max_vus_cfg,
            "vus_cap": vus_cap,
            "vus_max": vus_max,
            "cap_utilization": safe_div(vus_max, vus_cap),
            "required_concurrency_est": required_concurrency_est,
            "summary_file": str(summary_path),
        }
        classification, recommendation = classify_reasons(row)
        row["likely_reasons"] = classification
        row["recommendation"] = recommendation
        rows.append(row)

    fields = [
        "run_id",
        "run_tag",
        "endpoint",
        "prompt_set",
        "offered_rpm",
        "rep",
        "attempts_measure_count",
        "successes_measure_count",
        "measure_seconds",
        "offered_rps",
        "achieved_attempt_rps",
        "delivery_ratio",
        "dropped_iterations_count",
        "dropped_iterations_source",
        "dropped_rate",
        "timeouts_measure_count",
        "errors_total_measure_count",
        "timeout_rate",
        "error_rate_total",
        "latency_p95_s",
        "preallocated_vus_cfg",
        "max_vus_cfg",
        "vus_cap",
        "vus_max",
        "cap_utilization",
        "required_concurrency_est",
        "likely_reasons",
        "recommendation",
        "summary_file",
    ]

    with csv_out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    dropped_rows = [r for r in rows if (as_int(r.get("dropped_iterations_count")) or 0) > 0]

    lines: list[str] = [
        "# Dropped Iterations Report",
        "",
        f"Results dir: `{results_dir}`",
        f"Total runs scanned: {len(rows)}",
        f"Runs with dropped iterations: {len(dropped_rows)}",
        "",
    ]

    if not rows:
        lines.append("No arrival summary files found.")
    elif not dropped_rows:
        lines.append("No dropped iterations detected.")
    else:
        lines.append("## Affected Runs")
        lines.append("")
        lines.append("| run_id | endpoint | rpm | dropped | vus_max/vus_cap | p95(s) | reasons |")
        lines.append("|---|---|---:|---:|---|---:|---|")
        for r in dropped_rows:
            vm = as_int(r.get("vus_max"))
            vc = as_int(r.get("vus_cap"))
            lines.append(
                "| {run_id} | {endpoint} | {rpm} | {dropped} | {vm}/{vc} | {p95} | {reasons} |".format(
                    run_id=r.get("run_id") or "",
                    endpoint=r.get("endpoint") or "",
                    rpm=r.get("offered_rpm") or "",
                    dropped=r.get("dropped_iterations_count") or 0,
                    vm="" if vm is None else vm,
                    vc="" if vc is None else vc,
                    p95="" if r.get("latency_p95_s") is None else f"{float(r['latency_p95_s']):.2f}",
                    reasons=r.get("likely_reasons") or "",
                )
            )
        lines.append("")
        lines.append("## Recommended Actions")
        lines.append("")
        for r in dropped_rows:
            lines.append(f"- `{r.get('run_id')}`: {r.get('recommendation')}")

    md_out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    print(str(csv_out))
    print(str(md_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
