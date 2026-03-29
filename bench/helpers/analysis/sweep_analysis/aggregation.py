from __future__ import annotations

from typing import Any

from .metrics import as_float, as_int
from .stats import bootstrap_mean_ci, mean_sd
from .types import PointKey

def build_rep_fields(discovered_measure_counter_bases: set[str]) -> list[str]:
    rep_fields = [
        "run_id",
        "run_tag",
        "endpoint",
        "target_endpoint",
        "prompt_set",
        "offered_rpm",
        "rep",
        "parent_compare_id",
        "child_batch_id",
        "pair_rep",
        "pair_order",
        "pair_prompt_seed",
        "measure_seconds",
        "measure_ok",
        "preallocated_vus_cfg",
        "max_vus_cfg",
        "vus_cap",
        "vus_max",
        "iterations_count",
        "dropped_iterations_count",
        "dropped_iterations_source",
        "dropped_ok",
        "vu_cap_ok",
        "loadgen_valid",
        "data_sent_count",
        "data_received_count",
        "queue_saturation",
        "attempts_measure_count",
        "successes_measure_count",
        "timeouts_measure_count",
        "timeouts_measure_source",
        "errors_total_measure_count",
        "errors_total_measure_source",
        "errors_non_timeout_measure_count",
        "errors_non_timeout_measure_source",
        "throughput_success_rps",
        "throughput_attempt_rps",
        "timeout_rate",
        "error_rate_total",
        "error_rate_non_timeout",
        "latency_p50_s",
        "latency_p95_s",
        "timeout_compliant",
        "prompt_ids",
        "prompt_attempts_by_id",
        "prompt_successes_by_id",
        "prompt_mix_source",
        "prompt_mix_checked",
        "prompt_mix_ok",
        "prompt_mix_max_minus_min",
        "rep_valid",
        "invalid_reasons",
    ]
    for base in sorted(discovered_measure_counter_bases):
        rep_fields.append(f"{base}_count")
        rep_fields.append(f"{base}_rate")
    rep_fields.append("summary_file")
    return rep_fields

def aggregate_points(
    rep_rows_subset: list[dict[str, Any]],
    *,
    discovered_measure_counter_bases: set[str],
    expected_reps: int,
    bootstrap_iters: int,
    bootstrap_seed: int,
    error_non_timeout_max: float | None,
    seed_bump: int,
) -> tuple[list[dict[str, Any]], dict[PointKey, list[dict[str, Any]]]]:
    by_point: dict[PointKey, list[dict[str, Any]]] = {}
    for r in rep_rows_subset:
        key = PointKey(str(r.get("endpoint") or ""), str(r.get("prompt_set") or ""), int(r.get("offered_rpm") or 0))
        by_point.setdefault(key, []).append(r)

    agg_rows: list[dict[str, Any]] = []
    for key, reps in sorted(by_point.items(), key=lambda kv: (kv[0].endpoint, kv[0].prompt_set, kv[0].offered_rpm)):
        rep_timeout_ok = [bool(rr.get("timeout_compliant")) for rr in reps]
        expected_reps_n = max(int(expected_reps), 1)
        point_timeout_compliant = len(reps) >= expected_reps_n and all(rep_timeout_ok)
        point_measure_ok = bool(reps) and all(bool(rr.get("measure_ok")) for rr in reps)
        point_loadgen_valid = bool(reps) and all(bool(rr.get("loadgen_valid")) for rr in reps)
        point_prompt_mix_valid = bool(reps) and all(bool(rr.get("prompt_mix_ok")) for rr in reps)
        point_valid = len(reps) >= expected_reps_n and point_measure_ok and point_loadgen_valid and point_prompt_mix_valid
        run_tags = sorted({str(rr.get("run_tag") or "") for rr in reps if str(rr.get("run_tag") or "").strip()})

        def vals(field: str) -> list[float]:
            out: list[float] = []
            for rr in reps:
                v = rr.get(field)
                if v is None:
                    continue
                try:
                    out.append(float(v))
                except Exception:
                    pass
            return out

        def agg_metric(name: str, field: str, seed_offset: int = 0) -> dict[str, Any]:
            xs = vals(field)
            mean, sd = mean_sd(xs)
            lo, hi = bootstrap_mean_ci(xs, int(bootstrap_iters), int(bootstrap_seed) + seed_bump + seed_offset)
            return {
                f"{name}_n": len(xs),
                f"{name}_mean": mean,
                f"{name}_sd": sd,
                f"{name}_ci95_lo": lo,
                f"{name}_ci95_hi": hi,
            }

        row: dict[str, Any] = {
            "endpoint": key.endpoint,
            "prompt_set": key.prompt_set,
            "offered_rpm": key.offered_rpm,
            "reps": len(reps),
            "run_tags": ",".join(run_tags) if run_tags else "",
            "point_measure_ok": point_measure_ok,
            "point_loadgen_valid": point_loadgen_valid,
            "point_prompt_mix_valid": point_prompt_mix_valid,
            "point_valid": point_valid,
            "point_timeout_compliant": point_timeout_compliant,
        }
        row.update(agg_metric("vus_max", "vus_max", seed_offset=0))
        row.update(agg_metric("vus_cap", "vus_cap", seed_offset=0))
        row.update(agg_metric("iterations_count", "iterations_count", seed_offset=0))
        row.update(agg_metric("dropped_iterations_count", "dropped_iterations_count", seed_offset=0))
        row.update(agg_metric("throughput_success_rps", "throughput_success_rps", seed_offset=1))
        row.update(agg_metric("throughput_attempt_rps", "throughput_attempt_rps", seed_offset=2))
        row.update(agg_metric("timeout_rate", "timeout_rate", seed_offset=3))
        row.update(agg_metric("error_rate_total", "error_rate_total", seed_offset=4))
        row.update(agg_metric("error_rate_non_timeout", "error_rate_non_timeout", seed_offset=5))
        row.update(agg_metric("latency_p50_s", "latency_p50_s", seed_offset=6))
        row.update(agg_metric("latency_p95_s", "latency_p95_s", seed_offset=7))

        # Failure mode / taxonomy counters: aggregate both count and rate (best-effort).
        seed = 100
        for idx, base in enumerate(sorted(discovered_measure_counter_bases)):
            row.update(agg_metric(f"{base}_count", f"{base}_count", seed_offset=seed + idx * 2))
            row.update(agg_metric(f"{base}_rate", f"{base}_rate", seed_offset=seed + idx * 2 + 1))

        # Optional non-timeout error compliance gate (tier/knee only).
        if error_non_timeout_max is None:
            row["point_error_non_timeout_compliant"] = True
        else:
            ern = row.get("error_rate_non_timeout_mean")
            if ern is None:
                row["point_error_non_timeout_compliant"] = False
            else:
                try:
                    row["point_error_non_timeout_compliant"] = float(ern) <= float(error_non_timeout_max)
                except Exception:
                    row["point_error_non_timeout_compliant"] = False
        agg_rows.append(row)

    return agg_rows, by_point

def _pareto_mark(rows: list[dict[str, Any]], *, x_field: str, y_field: str, out_field: str) -> None:
    # Maximize x, minimize y.
    pts: list[tuple[float, float, dict[str, Any]]] = []
    for rr in rows:
        if not bool(rr.get("point_valid")):
            continue
        x = as_float(rr.get(x_field))
        y = as_float(rr.get(y_field))
        if x is None or y is None:
            continue
        pts.append((float(x), float(y), rr))
    for i, (xi, yi, ri) in enumerate(pts):
        dominated = False
        for j, (xj, yj, _rj) in enumerate(pts):
            if i == j:
                continue
            if (xj >= xi and yj <= yi) and (xj > xi or yj < yi):
                dominated = True
                break
        ri[out_field] = not dominated

def mark_pareto_best_tradeoffs(agg_rows: list[dict[str, Any]]) -> None:
    # Pareto-best tradeoff membership (valid points only).
    for r in agg_rows:
        r["on_best_tradeoff_p95"] = False

    cohorts_for_tradeoff: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in agg_rows:
        cohorts_for_tradeoff.setdefault((str(r.get("endpoint") or ""), str(r.get("prompt_set") or "")), []).append(r)

    for (_endpoint, _prompt_set), rows in cohorts_for_tradeoff.items():
        _pareto_mark(rows, x_field="throughput_success_rps_mean", y_field="latency_p95_s_mean", out_field="on_best_tradeoff_p95")

def build_agg_fields(discovered_measure_counter_bases: set[str]) -> list[str]:
    agg_fields = [
        "endpoint",
        "prompt_set",
        "offered_rpm",
        "reps",
        "run_tags",
        "point_measure_ok",
        "point_loadgen_valid",
        "point_prompt_mix_valid",
        "point_valid",
        "point_error_non_timeout_compliant",
        "point_timeout_compliant",
        "on_best_tradeoff_p95",
    ]
    for base in [
        "vus_max",
        "vus_cap",
        "iterations_count",
        "dropped_iterations_count",
        "throughput_success_rps",
        "throughput_attempt_rps",
        "timeout_rate",
        "error_rate_total",
        "error_rate_non_timeout",
        "latency_p50_s",
        "latency_p95_s",
    ]:
        agg_fields.extend(
            [
                f"{base}_n",
                f"{base}_mean",
                f"{base}_sd",
                f"{base}_ci95_lo",
                f"{base}_ci95_hi",
            ]
        )
    for base in sorted(discovered_measure_counter_bases):
        for suffix in ("count", "rate"):
            m = f"{base}_{suffix}"
            agg_fields.extend([f"{m}_n", f"{m}_mean", f"{m}_sd", f"{m}_ci95_lo", f"{m}_ci95_hi"])
    return agg_fields

def build_invalid_rows(
    rep_rows: list[dict[str, Any]],
    agg_rows: list[dict[str, Any]],
    by_point_all: dict[PointKey, list[dict[str, Any]]],
    expected_reps: int,
) -> list[dict[str, Any]]:
    invalid_rows: list[dict[str, Any]] = []
    expected_reps_n = max(int(expected_reps), 1)

    for r in rep_rows:
        if bool(r.get("rep_valid")):
            continue
        invalid_rows.append(
            {
                "row_type": "rep",
                "run_id": r.get("run_id"),
                "run_tag": r.get("run_tag"),
                "endpoint": r.get("endpoint"),
                "prompt_set": r.get("prompt_set"),
                "offered_rpm": r.get("offered_rpm"),
                "rep": r.get("rep"),
                "reason_codes": r.get("invalid_reasons") or "",
            }
        )

    for pr in agg_rows:
        reps_n = as_int(pr.get("reps")) or 0
        point_valid = bool(pr.get("point_valid"))
        if reps_n >= expected_reps_n and point_valid:
            continue
        point_reasons: set[str] = set()
        if reps_n < expected_reps_n:
            point_reasons.add("insufficient_reps")
        if not bool(pr.get("point_measure_ok")):
            point_reasons.add("measure_seconds_missing")
        if not bool(pr.get("point_loadgen_valid")):
            point_reasons.add("loadgen_invalid")
        if not bool(pr.get("point_prompt_mix_valid")):
            point_reasons.add("prompt_mix_mismatch")

        key = PointKey(str(pr.get("endpoint") or ""), str(pr.get("prompt_set") or ""), int(pr.get("offered_rpm") or 0))
        for rr in (by_point_all.get(key) or []):
            rs = str(rr.get("invalid_reasons") or "").strip()
            if not rs:
                continue
            for code in rs.split(","):
                code = code.strip()
                if code:
                    point_reasons.add(code)

        invalid_rows.append(
            {
                "row_type": "point",
                "run_id": "",
                "run_tag": pr.get("run_tags") or "",
                "endpoint": pr.get("endpoint"),
                "prompt_set": pr.get("prompt_set"),
                "offered_rpm": pr.get("offered_rpm"),
                "rep": "",
                "reason_codes": ",".join(sorted(point_reasons)),
            }
        )
    return invalid_rows
