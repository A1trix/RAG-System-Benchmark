#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def fail(msg: str) -> int:
    print(msg)
    return 2


def metric_value(metrics: dict, metric_name: str, key: str):
    metric = metrics.get(metric_name, {})
    if not isinstance(metric, dict):
        return None
    values = metric.get("values")
    if isinstance(values, dict) and key in values:
        return values.get(key)
    return metric.get(key)


def pick_metric_key(metrics: dict, base: str, required_substrings: list[str]) -> str:
    """Pick a metric key, preferring tagged measure-window series.

    k6 may emit tagged sub-metrics like:
      http_req_duration{expected_response:true,scenario:measure}
    """

    keys = [k for k in metrics.keys() if isinstance(k, str) and (k == base or k.startswith(base + "{"))]
    for k in keys:
        if all(s in k for s in required_substrings):
            return k
    return base


def as_float(value):
    try:
        return float(value)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build k6 summary report metrics")
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail(f"summary missing: {path}")
    except json.JSONDecodeError as exc:
        return fail(f"summary invalid JSON: {path} ({exc})")

    root_group = data.get("root_group", {})
    checks = root_group.get("checks", {})
    metrics = data.get("metrics", {})
    checks_key = pick_metric_key(metrics, "checks", ["scenario:measure"])
    mchecks = metrics.get(checks_key, {})

    try:
        check_fails = int(mchecks.get("fails", 0))
    except Exception:
        check_fails = 0
    try:
        check_passes = int(mchecks.get("passes", 0))
    except Exception:
        check_passes = 0

    if check_fails == 0 and check_passes == 0:
        for check in checks.values():
            try:
                fails = int(check.get("fails", 0))
                passes = int(check.get("passes", 0))
                check_fails += fails
                check_passes += passes
            except Exception:
                pass

    check_rate = mchecks.get("value")
    if check_rate is None:
        total = check_passes + check_fails
        check_rate = (check_passes / total) if total > 0 else None

    http_failed_key = pick_metric_key(metrics, "http_req_failed", ["scenario:measure"])
    http_failed = metrics.get(http_failed_key, {})
    http_failed_rate = None
    http_failed_count = None
    try:
        http_failed_rate = float(http_failed.get("value", 0))
    except Exception:
        pass
    try:
        http_failed_count = int(http_failed.get("passes", http_failed.get("fails", http_failed.get("count", 0))))
    except Exception:
        pass

    http_duration_key = pick_metric_key(
        metrics,
        "http_req_duration",
        ["expected_response:true", "scenario:measure"],
    )
    if http_duration_key == "http_req_duration" and "http_req_duration{expected_response:true}" in metrics:
        http_duration_key = "http_req_duration{expected_response:true}"
    latency_avg_ms = as_float(metric_value(metrics, http_duration_key, "avg"))
    latency_p50_ms = as_float(metric_value(metrics, http_duration_key, "med"))
    latency_p95_ms = as_float(metric_value(metrics, http_duration_key, "p(95)"))
    latency_min_ms = as_float(metric_value(metrics, http_duration_key, "min"))
    latency_max_ms = as_float(metric_value(metrics, http_duration_key, "max"))

    http_reqs = metrics.get(pick_metric_key(metrics, "http_reqs", ["scenario:measure"]), {})
    iterations = metrics.get(pick_metric_key(metrics, "iterations", ["scenario:measure"]), {})
    dropped_iterations = metrics.get(pick_metric_key(metrics, "dropped_iterations", ["scenario:measure"]), {})
    req_count = http_reqs.get("count", 0)
    iter_count = iterations.get("count", 0)
    dropped_iter_count = dropped_iterations.get("count", 0)
    
    data_sent = metrics.get("data_sent", {})
    data_received = metrics.get("data_received", {})
    data_sent_count = data_sent.get("count", 0)
    data_received_count = data_received.get("count", 0)
    
    no_requests_or_iterations = False
    try:
        if int(req_count) <= 0 and int(iter_count) <= 0:
            no_requests_or_iterations = True
    except Exception:
        # Best-effort: if parsing fails, do not treat as empty.
        no_requests_or_iterations = False

    summary = {
        "check_fails": check_fails,
        "check_passes": check_passes,
        "check_rate": check_rate,
        "http_req_failed_rate": http_failed_rate,
        "http_req_failed_count": http_failed_count,
        "latency_avg_ms": latency_avg_ms,
        "latency_p50_ms": latency_p50_ms,
        "latency_p95_ms": latency_p95_ms,
        "latency_min_ms": latency_min_ms,
        "latency_max_ms": latency_max_ms,
        "http_reqs": int(req_count) if str(req_count).isdigit() else req_count,
        "iterations": int(iter_count) if str(iter_count).isdigit() else iter_count,
        "dropped_iterations_count": int(dropped_iter_count)
        if str(dropped_iter_count).isdigit()
        else dropped_iter_count,
        "no_requests_or_iterations": bool(no_requests_or_iterations),
        "data_sent_count": int(data_sent_count) if str(data_sent_count).isdigit() else data_sent_count,
        "data_received_count": int(data_received_count)
        if str(data_received_count).isdigit()
        else data_received_count,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
