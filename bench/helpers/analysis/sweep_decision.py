#!/usr/bin/env python3
"""Evaluate a benchmark batch against the preregistered comparison rules.

This evaluator is intentionally lightweight:
- It relies on `analyze_sweep.py` outputs for aggregated sweep metrics,
  best-tradeoff summaries, and knee reports.
- It does not run benchmarks.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from statistics import median
from typing import Any


PRIMARY_METRICS: dict[str, dict[str, Any]] = {
    "throughput_success_rps": {
        "column": "throughput_success_rps_mean",
        "higher_better": True,
    },
    "latency_p95_s": {
        "column": "latency_p95_s_mean",
        "higher_better": False,
    },
    "timeout_rate": {
        "column": "timeout_rate_mean",
        "higher_better": False,
    },
    "error_rate_total": {
        "column": "error_rate_total_mean",
        "higher_better": False,
    },
}


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _as_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _as_int(x: Any) -> int | None:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _as_bool(x: Any) -> bool:
    s = str(x).strip().lower()
    return s in {"1", "true", "yes", "y"}


def _parse_tag_list(raw: Any) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        vals = raw
    else:
        vals = str(raw).split(",")
    return {str(v).strip() for v in vals if str(v).strip()}


def _scope_list(scope: dict[str, Any], key: str) -> list[Any]:
    value = scope.get(key)
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _design_track(prereg: dict[str, Any]) -> dict[str, Any]:
    design = prereg.get("design") or {}
    return (design.get("sweep_track") or {}) if isinstance(design, dict) else {}


def _analysis_paths(results_dir: Path) -> dict[str, Path]:
    analysis_dir = results_dir / "analysis"
    return {
        "knee": analysis_dir / "knee_report.json",
        "rep_csv": analysis_dir / "sweep_points.csv",
        "agg_csv": analysis_dir / "sweep_points_agg.csv",
    }


def _analysis_script(results_dir: Path) -> Path:
    return results_dir.parents[1] / "helpers" / "analysis" / "analyze_sweep.py"


def ensure_sweep_analysis(results_dir: Path, prereg: dict[str, Any]) -> None:
    """Run analyze_sweep.py if required outputs are missing."""
    analysis_paths = _analysis_paths(results_dir)
    required = [analysis_paths["knee"], analysis_paths["rep_csv"], analysis_paths["agg_csv"]]
    if all(path.exists() for path in required):
        return

    scope = prereg.get("scope") or {}
    include_tags = [str(tag) for tag in _scope_list(scope, "sweep_run_tags") if str(tag).strip()]
    knee_tags = [str(tag) for tag in _scope_list(scope, "knee_stage1_run_tags") if str(tag).strip()] or include_tags

    windows = prereg.get("windows") or {}
    measure_s = windows.get("measure_s")
    expected_reps = (_design_track(prereg).get("stage1_primary") or {}).get("repetitions")
    gates = prereg.get("gates") or {}
    timeout_rate_max = (gates.get("timeout_compliance") or {}).get("timeout_rate_max")

    cmd = [
        sys.executable,
        str(_analysis_script(results_dir)),
        str(results_dir),
        "--no-plots",
    ]
    for tag in include_tags:
        cmd += ["--run-tag", str(tag)]
    for tag in knee_tags:
        cmd += ["--knee-run-tag", str(tag)]
    if measure_s is not None:
        cmd += ["--measure-seconds", str(measure_s)]
    if expected_reps is not None:
        cmd += ["--expected-reps", str(expected_reps)]
    if timeout_rate_max is not None:
        cmd += ["--timeout-rate-max", str(timeout_rate_max)]

    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _filtered_agg_rows(results_dir: Path, prereg: dict[str, Any]) -> list[dict[str, str]]:
    rows = load_csv(_analysis_paths(results_dir)["agg_csv"])
    scope = prereg.get("scope") or {}
    prompt_set = str(scope.get("prompt_set") or "in_scope")
    include_tags = {str(tag) for tag in _scope_list(scope, "sweep_run_tags") if str(tag).strip()}
    filtered: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("prompt_set") or "") != prompt_set:
            continue
        row_tags = _parse_tag_list(row.get("run_tags"))
        if include_tags and row_tags and row_tags.isdisjoint(include_tags):
            continue
        filtered.append(row)
    return filtered


def _group_rows_by_endpoint(rows: list[dict[str, str]]) -> dict[str, dict[int, dict[str, str]]]:
    grouped: dict[str, dict[int, dict[str, str]]] = {}
    for row in rows:
        endpoint = str(row.get("endpoint") or "").strip()
        rpm = _as_int(row.get("offered_rpm"))
        if not endpoint or rpm is None:
            continue
        grouped.setdefault(endpoint, {})[rpm] = row
    return grouped


def _metric_counts(rows_by_endpoint: dict[str, dict[int, dict[str, str]]], shared_rpms: list[int], metric_name: str) -> dict[str, Any]:
    spec = PRIMARY_METRICS[metric_name]
    column = str(spec["column"])
    higher_better = bool(spec["higher_better"])
    endpoints = sorted(rows_by_endpoint.keys())
    if len(endpoints) != 2:
        return {
            "column": column,
            "higher_better": higher_better,
            "comparisons": 0,
            "wins": {},
            "median_difference": {},
            "winner": None,
        }

    left, right = endpoints
    wins = {left: 0, right: 0, "tie": 0}
    diffs_left_minus_right: list[float] = []
    compared = 0

    for rpm in shared_rpms:
        lv = _as_float(rows_by_endpoint.get(left, {}).get(rpm, {}).get(column))
        rv = _as_float(rows_by_endpoint.get(right, {}).get(rpm, {}).get(column))
        if lv is None or rv is None:
            continue
        compared += 1
        diffs_left_minus_right.append(lv - rv)
        if abs(lv - rv) <= 1e-12:
            wins["tie"] += 1
        elif higher_better:
            wins[left if lv > rv else right] += 1
        else:
            wins[left if lv < rv else right] += 1

    winner = None
    if wins.get(left, 0) > wins.get(right, 0):
        winner = left
    elif wins.get(right, 0) > wins.get(left, 0):
        winner = right
    elif compared > 0:
        winner = "tie"

    med = median(diffs_left_minus_right) if diffs_left_minus_right else None
    return {
        "column": column,
        "higher_better": higher_better,
        "comparisons": compared,
        "wins": wins,
        "median_difference": {
            f"{left}_minus_{right}": med,
            f"{right}_minus_{left}": (-med if med is not None else None),
        },
        "winner": winner,
    }


def _load_knee_by_endpoint(results_dir: Path) -> dict[str, dict[str, Any]]:
    knee = load_json(results_dir / "analysis" / "knee_report.json") or {}
    knee_cohorts = knee.get("cohorts") or {}
    knee_by_ep: dict[str, dict[str, Any]] = {}
    for cohort in knee_cohorts.values():
        endpoint = str(cohort.get("endpoint") or "")
        prompt_set = str(cohort.get("prompt_set") or "")
        knee_data = (cohort.get("knee") or {}) if isinstance(cohort, dict) else {}
        if not endpoint:
            continue
        knee_by_ep.setdefault(endpoint, {})[prompt_set] = knee_data
    return knee_by_ep


def _validity_coverage(rows_by_endpoint: dict[str, dict[int, dict[str, str]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for endpoint, rpm_rows in rows_by_endpoint.items():
        offered = sorted(rpm_rows.keys())
        valid = sorted(rpm for rpm, row in rpm_rows.items() if _as_bool(row.get("point_valid")))
        timeout_ok = sorted(rpm for rpm, row in rpm_rows.items() if _as_bool(row.get("point_timeout_compliant")))
        out[endpoint] = {
            "offered_rpms": offered,
            "point_count": len(offered),
            "valid_rpms": valid,
            "valid_point_count": len(valid),
            "timeout_compliant_rpms": timeout_ok,
            "timeout_compliant_point_count": len(timeout_ok),
        }
    return out


def _compare_scalar(a: float | None, b: float | None, *, higher_better: bool) -> str | None:
    if a is None and b is None:
        return None
    if a is None:
        return "b"
    if b is None:
        return "a"
    if abs(a - b) <= 1e-12:
        return "tie"
    if higher_better:
        return "a" if a > b else "b"
    return "a" if a < b else "b"


def _not_worse(candidate: float | None, other: float | None, *, higher_better: bool) -> bool:
    if candidate is None and other is None:
        return True
    if candidate is None:
        return False
    if other is None:
        return True
    if higher_better:
        return candidate >= other
    return candidate <= other


def _system_qualifies(
    candidate: str,
    other: str,
    *,
    validity: dict[str, Any],
    metric_results: dict[str, Any],
    sustainable: dict[str, float | None],
) -> bool:
    if validity.get(candidate, {}).get("valid_point_count", 0) < validity.get(other, {}).get("valid_point_count", 0):
        return False

    if metric_results.get("timeout_rate", {}).get("winner") != candidate:
        return False
    if metric_results.get("error_rate_total", {}).get("winner") != candidate:
        return False

    if candidate not in {
        metric_results.get("throughput_success_rps", {}).get("winner"),
        metric_results.get("latency_p95_s", {}).get("winner"),
    }:
        return False

    if not _not_worse(sustainable.get(candidate), sustainable.get(other), higher_better=True):
        return False

    return True


def evaluate(results_dir: Path, prereg: dict[str, Any]) -> dict[str, Any]:
    manifest = load_json(results_dir / "manifest.json") or {}
    batch_kind = str(manifest.get("batch_kind") or "").strip()
    if batch_kind != "isolated_parent_compare":
        raise ValueError(
            f"unsupported benchmark batch kind for thesis decision: {batch_kind or '<missing>'}; expected isolated_parent_compare"
        )

    analysis_paths = _analysis_paths(results_dir)
    required = [analysis_paths["knee"], analysis_paths["rep_csv"], analysis_paths["agg_csv"]]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("missing parent comparison analysis artifacts: " + ", ".join(missing))

    pair_validation = load_json(results_dir / "analysis" / "pair_validation.json") or {}
    if not pair_validation.get("pass"):
        raise ValueError("pair validation missing or failed")

    rows = _filtered_agg_rows(results_dir, prereg)
    rows_by_endpoint = _group_rows_by_endpoint(rows)
    endpoints = sorted(rows_by_endpoint.keys())
    prompt_set = str((prereg.get("scope") or {}).get("prompt_set") or "in_scope")

    validity = _validity_coverage(rows_by_endpoint)

    valid_sets = [set(data.get("valid_rpms") or []) for data in validity.values()]
    shared_valid_rpms = sorted(set.intersection(*valid_sets)) if valid_sets else []

    metric_results = {
        name: _metric_counts(rows_by_endpoint, shared_valid_rpms, name)
        for name in PRIMARY_METRICS
    }

    knee_by_ep = _load_knee_by_endpoint(results_dir)

    sustainable: dict[str, float | None] = {}
    for endpoint in endpoints:
        sustainable[endpoint] = _as_float(((knee_by_ep.get(endpoint) or {}).get(prompt_set) or {}).get("sustainable_throughput_success_rps"))

    criterion_winners = {
        "validity_coverage": None,
        "throughput_success_rps": metric_results.get("throughput_success_rps", {}).get("winner"),
        "latency_p95_s": metric_results.get("latency_p95_s", {}).get("winner"),
        "timeout_rate": metric_results.get("timeout_rate", {}).get("winner"),
        "error_rate_total": metric_results.get("error_rate_total", {}).get("winner"),
        "sustainable_throughput": None,
    }

    if len(endpoints) == 2:
        left, right = endpoints
        left_valid = validity.get(left, {}).get("valid_point_count", 0)
        right_valid = validity.get(right, {}).get("valid_point_count", 0)
        if left_valid > right_valid:
            criterion_winners["validity_coverage"] = left
        elif right_valid > left_valid:
            criterion_winners["validity_coverage"] = right
        elif left_valid or right_valid:
            criterion_winners["validity_coverage"] = "tie"

        sustain_cmp = _compare_scalar(sustainable.get(left), sustainable.get(right), higher_better=True)
        if sustain_cmp == "a":
            criterion_winners["sustainable_throughput"] = left
        elif sustain_cmp == "b":
            criterion_winners["sustainable_throughput"] = right
        elif sustain_cmp == "tie":
            criterion_winners["sustainable_throughput"] = "tie"

    overall_winner = None
    conclusion_label = "trade_off_not_single_winner"
    if len(endpoints) == 2 and shared_valid_rpms:
        left, right = endpoints
        left_ok = _system_qualifies(
            left,
            right,
            validity=validity,
            metric_results=metric_results,
            sustainable=sustainable,
        )
        right_ok = _system_qualifies(
            right,
            left,
            validity=validity,
            metric_results=metric_results,
            sustainable=sustainable,
        )
        if left_ok and not right_ok:
            overall_winner = left
            conclusion_label = "better_overall"
        elif right_ok and not left_ok:
            overall_winner = right
            conclusion_label = "better_overall"
        else:
            timeout_winner = metric_results.get("timeout_rate", {}).get("winner")
            error_winner = metric_results.get("error_rate_total", {}).get("winner")
            sustain_winner = criterion_winners.get("sustainable_throughput")
            if timeout_winner == error_winner and timeout_winner in endpoints:
                conclusion_label = "more_reliable_across_tested_range"
            elif sustain_winner in endpoints and sustain_winner != timeout_winner:
                conclusion_label = "more_scalable_before_knee"
            else:
                conclusion_label = "trade_off_not_single_winner"

    return {
        "results_dir": str(results_dir),
        "batch_kind": batch_kind,
        "decision_contract_version": "thesis-batch-decision/v1",
        "prereg_id": prereg.get("id"),
        "prereg_schema_version": prereg.get("schema_version"),
        "prereg_boundary_audit_required": (((prereg.get("preconditions") or {}).get("boundary_audit") or {}).get("required")),
        "pair_validation_pass": bool(pair_validation.get("pass")) if pair_validation else None,
        "prompt_set": prompt_set,
        "shared_valid_offered_rpms": shared_valid_rpms,
        "has_shared_valid_points": bool(shared_valid_rpms),
        "validity_coverage": validity,
        "primary_metrics": metric_results,
        "criterion_winners": criterion_winners,
        "knee": knee_by_ep,
        "sustainable_throughput_winner": criterion_winners.get("sustainable_throughput"),
        "overall_winner": overall_winner,
        "conclusion_label": conclusion_label,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate preregistered benchmark comparison rules")
    parser.add_argument("results_dir", help="Path to bench/results/compare_<timestamp>")
    parser.add_argument(
        "--prereg",
        default=None,
        help="Path to preregistration JSON (default: <repo>/bench/preregistration.json)",
    )
    parser.add_argument("--output", default=None, help="Write JSON decision output")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit non-zero if the comparison is thesis-invalid (missing required artifacts, failed pair validation, or no shared valid points)",
    )
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    prereg_path = Path(args.prereg) if args.prereg else (results_dir.parents[1] / "preregistration.json")
    prereg = load_json(prereg_path) or {}

    try:
        out = evaluate(results_dir, prereg)
    except Exception as exc:
        print(f"comparison decision failed: {exc}", file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("=" * 80)
    print("PREREG COMPARISON DECISION")
    print("=" * 80)
    print(f"schema_version: {out.get('prereg_schema_version')}")
    print(f"prompt_set: {out.get('prompt_set')}")
    print(f"shared_valid_offered_rpms: {out.get('shared_valid_offered_rpms')}")
    print(f"overall_winner: {out.get('overall_winner')}")
    print(f"conclusion_label: {out.get('conclusion_label')}")
    print(f"sustainable_throughput_winner: {out.get('sustainable_throughput_winner')}")
    print("=" * 80)

    if args.enforce:
        analysis_paths = _analysis_paths(results_dir)
        required = [analysis_paths["knee"], analysis_paths["rep_csv"], analysis_paths["agg_csv"]]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            print("missing analysis artifacts: " + ", ".join(missing), file=sys.stderr)
            return 2
        pair_validation = load_json(results_dir / "analysis" / "pair_validation.json") or {}
        if not pair_validation.get("pass"):
            print("pair validation missing or failed", file=sys.stderr)
            return 2
        if not out.get("has_shared_valid_points"):
            print("comparison decision thesis-invalid: no shared valid offered RPMs", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
