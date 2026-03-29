from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

from .metrics import as_float
from .stats import linear_fit

def piecewise_knee(
    xs: list[float],
    ys: list[float],
    min_points_per_segment: int,
    slope_factor: float,
    slope_abs_threshold: float,
) -> dict[str, Any] | None:
    """Find best breakpoint by SSE and decide if it is a knee."""
    if len(xs) != len(ys):
        return None
    n = len(xs)
    if n < (min_points_per_segment * 2):
        return None

    best: dict[str, Any] | None = None
    for k in range(min_points_per_segment - 1, n - min_points_per_segment):
        xl = xs[: k + 1]
        yl = ys[: k + 1]
        xr = xs[k + 1 :]
        yr = ys[k + 1 :]
        _, bl, ssel = linear_fit(xl, yl)
        _, br, sser = linear_fit(xr, yr)
        sse = ssel + sser
        if best is None or sse < float(best.get("sse") or 0.0):
            best = {
                "break_index": k,
                "x_break": xs[k],
                "sse": sse,
                "slope_left": bl,
                "slope_right": br,
            }

    if best is None:
        return None

    sl = float(best["slope_left"])
    sr = float(best["slope_right"])
    delta = sr - sl
    factor_ok = sr > (sl * slope_factor)
    abs_ok = delta > slope_abs_threshold
    best["knee_trigger"] = bool(factor_ok and abs_ok)
    best["knee_reason"] = {
        "slope_factor": slope_factor,
        "slope_abs_threshold": slope_abs_threshold,
        "factor_ok": factor_ok,
        "abs_ok": abs_ok,
        "delta": delta,
    }
    return best

def series_xy(rows: list[dict[str, Any]], y_field: str) -> tuple[list[float], list[float], list[int]]:
    xs: list[float] = []
    ys: list[float] = []
    rpms: list[int] = []
    for r in rows:
        x = as_float(r.get("offered_rpm"))
        y = as_float(r.get(y_field))
        if x is None or y is None:
            continue
        xs.append(float(x))
        ys.append(float(y))
        rpms.append(int(r.get("offered_rpm") or 0))
    return xs, ys, rpms

def knee_candidate(
    rows: list[dict[str, Any]],
    y_field: str,
    *,
    min_points_per_seg: int,
    slope_factor: float,
    slope_abs: float,
) -> dict[str, Any] | None:
    xs, ys, rpms = series_xy(rows, y_field)
    knee = piecewise_knee(xs, ys, int(min_points_per_seg), slope_factor, slope_abs)
    if not knee:
        return None
    bi = int(knee.get("break_index") or 0)
    knee["rpm_break_left"] = rpms[bi] if 0 <= bi < len(rpms) else None
    knee["rpm_break_right"] = rpms[bi + 1] if 0 <= (bi + 1) < len(rpms) else knee.get("rpm_break_left")
    return knee

def build_sorted_cohorts(agg_rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    cohorts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in agg_rows:
        cohorts.setdefault((str(r.get("endpoint") or ""), str(r.get("prompt_set") or "")), []).append(r)
    for crows in cohorts.values():
        crows.sort(key=lambda row: int(row.get("offered_rpm") or 0))
    return cohorts

def compute_knee_report(
    *,
    results_dir: Path,
    args: argparse.Namespace,
    include_run_tags: list[str] | None,
    knee_run_tags: list[str] | None,
    warnings: list[str],
    cohorts_all: dict[tuple[str, str], list[dict[str, Any]]],
    cohorts_knee: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    knee_report: dict[str, Any] = {
        "results_dir": str(results_dir),
        "params": {
            "timeout_rate_max": float(args.timeout_rate_max),
            "error_non_timeout_max": float(args.error_non_timeout_max) if args.error_non_timeout_max is not None else None,
            "expected_prompts": int(args.expected_prompts) if args.expected_prompts is not None else None,
            "require_prompt_tags": bool(args.require_prompt_tags),
            "enforce_validity": bool(args.enforce_validity),
            "expected_reps": int(args.expected_reps),
            "include_run_tags": include_run_tags,
            "knee_run_tags": knee_run_tags,
            "bootstrap_iters": int(args.bootstrap_iters),
            "bootstrap_seed": int(args.bootstrap_seed),
            "knee_min_points_per_seg": int(args.knee_min_points_per_seg),
            "knee_p95_slope_factor": float(args.knee_p95_slope_factor),
            "knee_p95_slope_abs_threshold": float(args.knee_p95_slope_abs_threshold),
            "knee_error_slope_factor": float(args.knee_error_slope_factor),
            "knee_error_slope_abs_threshold": float(args.knee_error_slope_abs_threshold),
        },
        "cohorts": {},
        "warnings": warnings,
    }

    cohort_keys = sorted(set(cohorts_all.keys()) | set(cohorts_knee.keys()), key=lambda k: (k[0], k[1]))
    for (endpoint, prompt_set) in cohort_keys:
        rows_knee = cohorts_knee.get((endpoint, prompt_set), [])

        rows_knee_valid = [r for r in rows_knee if bool(r.get("point_valid"))]

        last_good_rpm: Optional[int] = None
        first_timeout_bad_rpm: Optional[int] = None
        for r in rows_knee_valid:
            rpm = int(r.get("offered_rpm") or 0)
            ok = bool(r.get("point_timeout_compliant"))
            if ok:
                last_good_rpm = rpm
            elif first_timeout_bad_rpm is None:
                first_timeout_bad_rpm = rpm
                break

        first_error_non_timeout_bad_rpm: Optional[int] = None
        if args.error_non_timeout_max is not None:
            for r in rows_knee_valid:
                rpm = int(r.get("offered_rpm") or 0)
                ok = bool(r.get("point_error_non_timeout_compliant"))
                if not ok:
                    first_error_non_timeout_bad_rpm = rpm
                    break

        knee_p95 = knee_candidate(
            rows_knee_valid,
            "latency_p95_s_mean",
            min_points_per_seg=int(args.knee_min_points_per_seg),
            slope_factor=float(args.knee_p95_slope_factor),
            slope_abs=float(args.knee_p95_slope_abs_threshold),
        )
        knee_err = knee_candidate(
            rows_knee_valid,
            "error_rate_total_mean",
            min_points_per_seg=int(args.knee_min_points_per_seg),
            slope_factor=float(args.knee_error_slope_factor),
            slope_abs=float(args.knee_error_slope_abs_threshold),
        )

        candidates: list[tuple[str, int]] = []
        if first_timeout_bad_rpm is not None:
            candidates.append(("timeout_noncompliance", int(first_timeout_bad_rpm)))
        if first_error_non_timeout_bad_rpm is not None:
            candidates.append(("error_non_timeout_noncompliance", int(first_error_non_timeout_bad_rpm)))
        if knee_err and bool(knee_err.get("knee_trigger")) and knee_err.get("rpm_break_right"):
            candidates.append(("error_rate_slope_break", int(knee_err["rpm_break_right"])))
        if knee_p95 and bool(knee_p95.get("knee_trigger")) and knee_p95.get("rpm_break_right"):
            candidates.append(("p95_slope_break", int(knee_p95["rpm_break_right"])))

        first_bad_rpm: Optional[int] = None
        first_bad_reasons: list[str] = []
        if candidates:
            first_bad_rpm = min(rpm for _, rpm in candidates)
            first_bad_reasons = sorted({reason for reason, rpm in candidates if rpm == first_bad_rpm})

        if first_bad_rpm is not None:
            last_good_rpm = None
            for r in rows_knee_valid:
                rpm = int(r.get("offered_rpm") or 0)
                if rpm >= first_bad_rpm:
                    break
                ok = bool(r.get("point_timeout_compliant"))
                if args.error_non_timeout_max is not None:
                    ok = ok and bool(r.get("point_error_non_timeout_compliant"))
                if ok:
                    last_good_rpm = rpm
        else:
            last_good_rpm = None
            for r in rows_knee_valid:
                rpm = int(r.get("offered_rpm") or 0)
                ok = bool(r.get("point_timeout_compliant"))
                if args.error_non_timeout_max is not None:
                    ok = ok and bool(r.get("point_error_non_timeout_compliant"))
                if ok:
                    last_good_rpm = rpm

        sustainable_thr: Optional[float] = None
        if last_good_rpm is not None:
            for r in rows_knee_valid:
                if int(r.get("offered_rpm") or 0) == int(last_good_rpm):
                    v = r.get("throughput_success_rps_mean")
                    try:
                        sustainable_thr = float(v) if v is not None else None
                    except Exception:
                        sustainable_thr = None
                    break

        knee_report["cohorts"][f"{endpoint}:{prompt_set}"] = {
            "endpoint": endpoint,
            "prompt_set": prompt_set,
            "knee": {
                "last_good_rpm": last_good_rpm,
                "first_bad_rpm": first_bad_rpm,
                "first_bad_reasons": first_bad_reasons,
                "sustainable_throughput_success_rps": sustainable_thr,
            },
            "knee_candidates": {
                "timeout_first_bad_rpm": first_timeout_bad_rpm,
                "p95": knee_p95,
                "error_rate_total": knee_err,
            },
        }

    return knee_report
