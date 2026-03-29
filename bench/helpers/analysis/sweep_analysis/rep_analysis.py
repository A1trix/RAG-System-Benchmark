from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from .discovery import (
    ARRIVAL_RUN_RE,
    FAILURE_MODE_COUNTER_BASES,
    LATENCY_TREND,
    MEASURE_COUNTERS,
    PROMPT_ATTEMPTS_COUNTER_BASE,
    PROMPT_SUCCESSES_COUNTER_BASE,
    find_summary_files,
)
from .io_utils import load_json
from .metrics import (
    _metric_base_name,
    _sorted_prompt_ids,
    as_float,
    as_int,
    counter_count,
    counter_count_best_effort,
    metric_values,
    parse_duration_seconds,
    safe_div,
    tagged_counter_series,
    trend_quantile_ms,
)
from .prompt_mix import build_prompt_counts_from_schedule, load_prompt_metrics, load_prompt_order_prompt_ids

def collect_rep_rows(
    results_dir: Path,
    run_by_id: dict[str, dict[str, Any]],
    include_run_tags: list[str] | None,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[str], set[str], set[str]]:
    rep_rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    discovered_measure_counter_bases: set[str] = set()
    discovered_prompt_ids: set[str] = set()
    prompt_fallback_warning_emitted = False

    for summary_path in find_summary_files(results_dir):
        m = ARRIVAL_RUN_RE.match(summary_path.stem)
        if not m:
            continue
        endpoint = m.group("endpoint")
        prompt_set = m.group("prompt_set")
        offered_rpm = int(m.group("rpm"))
        rep = int(m.group("rep"))
        run_id = summary_path.stem

        rr = run_by_id.get(run_id) or {}
        run_tag = rr.get("run_tag")
        run_tag_s = str(run_tag) if isinstance(run_tag, str) else ""
        if include_run_tags is not None:
            if not run_tag_s:
                warnings.append(f"missing run_tag in runs.jsonl; skipping due to --run-tag filter: run_id={run_id}")
                continue
            if run_tag_s not in include_run_tags:
                continue

        prompt_order_ids = load_prompt_order_prompt_ids(results_dir, run_id)
        for pid in prompt_order_ids:
            discovered_prompt_ids.add(str(pid))
        prompt_metrics = load_prompt_metrics(results_dir, run_id)
        prompt_metric_ids = prompt_metrics.get("prompt_ids") if isinstance(prompt_metrics, dict) else []
        if isinstance(prompt_metric_ids, list):
            for pid in prompt_metric_ids:
                discovered_prompt_ids.add(str(pid))

        data = load_json(summary_path)
        if not data:
            warnings.append(f"could not parse JSON: {summary_path.name}")
            continue
        metrics = data.get("metrics")
        if not isinstance(metrics, dict):
            warnings.append(f"missing metrics dict: {summary_path.name}")
            continue

        # Measure window seconds.
        measure_seconds = args.measure_seconds
        opts = data.get("options") or {}
        scenarios: dict[str, Any] = {}
        measure_scn: dict[str, Any] = {}
        if isinstance(opts, dict):
            sc = opts.get("scenarios") or {}
            if isinstance(sc, dict):
                scenarios = sc
                ms = scenarios.get("measure") or {}
                if isinstance(ms, dict):
                    measure_scn = ms
        if measure_seconds is None:
            # Prefer k6 scenario config when present (settle/measure split).
            if measure_scn:
                measure_seconds = parse_duration_seconds(measure_scn.get("duration"))

        preallocated_vus_cfg = as_int(measure_scn.get("preAllocatedVUs")) if measure_scn else None
        max_vus_cfg = as_int(measure_scn.get("maxVUs")) if measure_scn else None

        if measure_seconds is None:
            # Some runners may record measure_duration/measure_seconds explicitly.
            measure_seconds = parse_duration_seconds(rr.get("measure_duration"))
            if measure_seconds is None:
                measure_seconds = parse_duration_seconds(rr.get("measure_seconds"))
            # NOTE: rr["duration"] is typically the *total* test duration.
            # Do not treat it as measure_seconds unless you ran measure-only (settle=0).
            if measure_seconds is None:
                measure_seconds = parse_duration_seconds(rr.get("duration"))
        if measure_seconds is None:
            state = data.get("state") or {}
            if isinstance(state, dict):
                # Best-effort: k6 has used testRunDurationMs in some exports.
                ms = as_float(state.get("testRunDurationMs"))
                if ms is not None:
                    measure_seconds = ms / 1000.0
        if measure_seconds is None:
            warnings.append(f"measure_seconds missing; set --measure-seconds (run_id={run_id})")

        counts: dict[str, Optional[int]] = {}
        for name in MEASURE_COUNTERS:
            counts[name] = counter_count(metrics, name)

        # Load generation validity gates (measure window).
        dropped_iterations_count = counter_count_best_effort(metrics, "dropped_iterations", ["scenario:measure"])
        if dropped_iterations_count is None:
            dropped_iterations_count = counter_count_best_effort(metrics, "dropped_iterations", [])
        dropped_iterations_source = "metric"
        if dropped_iterations_count is None:
            rr_dropped = as_int(rr.get("dropped_iterations_count"))
            if rr_dropped is not None:
                dropped_iterations_count = int(rr_dropped)
                dropped_iterations_source = "runs_jsonl"
            else:
                dropped_iterations_source = "missing"
        iterations_count = counter_count_best_effort(metrics, "iterations", ["scenario:measure"])
        if iterations_count is None:
            iterations_count = counter_count_best_effort(metrics, "iterations", [])

        data_sent_metric = metrics.get("data_sent", {})
        data_received_metric = metrics.get("data_received", {})
        data_sent_count = as_int(data_sent_metric.get("count"))
        if data_sent_count is None:
            data_sent_count = as_int(metric_values(data_sent_metric).get("count"))
        data_received_count = as_int(data_received_metric.get("count"))
        if data_received_count is None:
            data_received_count = as_int(metric_values(data_received_metric).get("count"))

        vus_max_metric = metric_values(metrics.get("vus_max", {}))
        vus_max = as_int(vus_max_metric.get("value"))
        if vus_max is None:
            vus_max = as_int(vus_max_metric.get("max"))

        # Determine configured maxVUs cap (prefer runs.jsonl vus for arrival runs).
        vus_cap = as_int(rr.get("vus"))
        if vus_cap is None:
            vus_cap = max_vus_cfg

        # Queue saturation: requests sent but none received (system capacity exceeded).
        has_data_sent = data_sent_count is not None and int(data_sent_count) > 0
        has_data_received = data_received_count is not None and int(data_received_count) > 0
        has_http_reqs = iterations_count is not None and int(iterations_count) > 0
        queue_saturation = bool(has_data_sent and not has_data_received and not has_http_reqs)

        dropped_ok = bool(dropped_iterations_count is not None and int(dropped_iterations_count) == 0)
        vu_cap_ok = bool(vus_max is not None and vus_cap is not None and int(vus_max) < int(vus_cap))
        loadgen_valid = bool(dropped_ok and vu_cap_ok)
        loadgen_invalid_reasons: list[str] = []
        if dropped_iterations_source == "missing":
            loadgen_invalid_reasons.append("dropped_iterations_missing")
        elif dropped_iterations_count is not None and int(dropped_iterations_count) > 0:
            loadgen_invalid_reasons.append("dropped_iterations")
        if vus_cap is None:
            loadgen_invalid_reasons.append("vu_cap_missing")
        if vus_max is None:
            loadgen_invalid_reasons.append("vus_max_missing")
        if vus_max is not None and vus_cap is not None and int(vus_max) >= int(vus_cap):
            loadgen_invalid_reasons.append("vu_cap_hit")
        if queue_saturation:
            loadgen_invalid_reasons.append("queue_saturation")

        # Prompt-mix tagged counters (Option C tagging).
        attempts_by_prompt = tagged_counter_series(
            metrics,
            PROMPT_ATTEMPTS_COUNTER_BASE,
            tag_key="prompt_id",
            required_substrings=["scenario:measure"],
        )
        if not attempts_by_prompt:
            attempts_by_prompt = tagged_counter_series(metrics, PROMPT_ATTEMPTS_COUNTER_BASE, tag_key="prompt_id", required_substrings=[])
        if not attempts_by_prompt and isinstance(prompt_metrics, dict):
            attempts_sidecar = prompt_metrics.get("attempts_by_prompt")
            if isinstance(attempts_sidecar, dict):
                attempts_by_prompt = {str(k): int(v) for k, v in attempts_sidecar.items()}
        successes_by_prompt = tagged_counter_series(
            metrics,
            PROMPT_SUCCESSES_COUNTER_BASE,
            tag_key="prompt_id",
            required_substrings=["scenario:measure"],
        )
        if not successes_by_prompt:
            successes_by_prompt = tagged_counter_series(metrics, PROMPT_SUCCESSES_COUNTER_BASE, tag_key="prompt_id", required_substrings=[])
        if not successes_by_prompt and isinstance(prompt_metrics, dict):
            successes_sidecar = prompt_metrics.get("successes_by_prompt")
            if isinstance(successes_sidecar, dict):
                successes_by_prompt = {str(k): int(v) for k, v in successes_sidecar.items()}
        for pid in attempts_by_prompt.keys():
            discovered_prompt_ids.add(str(pid))

        # Failure-mode and taxonomy counters (best-effort).
        measure_counter_bases_here: set[str] = set(FAILURE_MODE_COUNTER_BASES)
        for mk, mv in metrics.items():
            if not isinstance(mk, str) or not isinstance(mv, dict):
                continue
            base = _metric_base_name(mk)
            if not base.endswith("_measure"):
                continue
            if base in MEASURE_COUNTERS:
                continue
            mtype = mv.get("type")
            if isinstance(mtype, str) and mtype.lower() != "counter":
                continue
            measure_counter_bases_here.add(base)
        discovered_measure_counter_bases |= measure_counter_bases_here

        attempts = counts.get("attempts_measure")
        successes = counts.get("successes_measure")
        timeouts = counts.get("timeouts_measure")
        err_total = counts.get("errors_total_measure")
        err_non_timeout = counts.get("errors_non_timeout_measure")

        timeouts_source = "metric" if timeouts is not None else "missing"
        err_total_source = "metric" if err_total is not None else "missing"
        err_non_timeout_source = "metric" if err_non_timeout is not None else "missing"
        if attempts is not None and int(attempts) > 0:
            if timeouts is None:
                timeouts = 0
                timeouts_source = "implicit_zero"
            if err_total is None:
                err_total = 0
                err_total_source = "implicit_zero"
            if err_non_timeout is None:
                err_non_timeout = 0
                err_non_timeout_source = "implicit_zero"

        p50_ms = trend_quantile_ms(metrics, LATENCY_TREND, "med")
        p95_ms = trend_quantile_ms(metrics, LATENCY_TREND, "p(95)")

        # Convert ms -> s.
        p50_s = (p50_ms / 1000.0) if p50_ms is not None else None
        p95_s = (p95_ms / 1000.0) if p95_ms is not None else None

        throughput_success_rps = safe_div(successes, measure_seconds)
        throughput_attempt_rps = safe_div(attempts, measure_seconds)
        timeout_rate = safe_div(timeouts, attempts)
        error_rate_total = safe_div(err_total, attempts)
        error_rate_non_timeout = safe_div(err_non_timeout, attempts)

        failure_counts: dict[str, Optional[int]] = {}
        failure_rates: dict[str, Optional[float]] = {}
        for base in sorted(measure_counter_bases_here):
            c = counter_count_best_effort(metrics, base, ["scenario:measure"])
            if c is None:
                c = counter_count_best_effort(metrics, base, [])
            if c is None and attempts is not None and int(attempts) > 0:
                c = 0
            failure_counts[base] = c
            failure_rates[base] = safe_div(c, attempts)

        prompt_mix_source = "tagged"
        if not attempts_by_prompt:
            prompt_mix_source = "unverifiable"
            if (not args.require_prompt_tags) and attempts is not None and int(attempts) > 0 and prompt_order_ids:
                attempts_by_prompt = build_prompt_counts_from_schedule(prompt_order_ids, int(attempts))
                prompt_mix_source = "scheduler_fallback"
                if successes_by_prompt:
                    pass
                elif successes is not None and int(successes) >= 0:
                    successes_by_prompt = build_prompt_counts_from_schedule(prompt_order_ids, int(successes))
                if not prompt_fallback_warning_emitted:
                    warnings.append("prompt-tagged counters missing; using scheduler-based prompt-mix fallback from prompt_order artifacts")
                    prompt_fallback_warning_emitted = True

        timeout_compliant = bool(timeout_rate is not None and timeout_rate <= float(args.timeout_rate_max))

        row: dict[str, Any] = {
                "run_id": run_id,
                "run_tag": run_tag_s,
                "endpoint": endpoint,
                "target_endpoint": rr.get("target_endpoint"),
                "prompt_set": prompt_set,
                "offered_rpm": offered_rpm,
                "rep": rep,
                "parent_compare_id": rr.get("parent_compare_id"),
                "child_batch_id": rr.get("child_batch_id"),
                "pair_rep": rr.get("pair_rep"),
                "pair_order": rr.get("pair_order"),
                "pair_prompt_seed": rr.get("pair_prompt_seed"),
                "measure_seconds": measure_seconds,
                "preallocated_vus_cfg": preallocated_vus_cfg,
                "max_vus_cfg": max_vus_cfg,
                "vus_max": vus_max,
                "vus_cap": vus_cap,
                "iterations_count": iterations_count,
                "dropped_iterations_count": dropped_iterations_count,
                "dropped_iterations_source": dropped_iterations_source,
                "dropped_ok": dropped_ok,
                "vu_cap_ok": vu_cap_ok,
                "loadgen_valid": loadgen_valid,
                "data_sent_count": data_sent_count,
                "data_received_count": data_received_count,
                "queue_saturation": queue_saturation,
                "attempts_measure_count": attempts,
                "successes_measure_count": successes,
                "timeouts_measure_count": timeouts,
                "timeouts_measure_source": timeouts_source,
                "errors_total_measure_count": err_total,
                "errors_total_measure_source": err_total_source,
                "errors_non_timeout_measure_count": err_non_timeout,
                "errors_non_timeout_measure_source": err_non_timeout_source,
                "throughput_success_rps": throughput_success_rps,
                "throughput_attempt_rps": throughput_attempt_rps,
                "timeout_rate": timeout_rate,
                "error_rate_total": error_rate_total,
                "error_rate_non_timeout": error_rate_non_timeout,
                "latency_p50_s": p50_s,
                "latency_p95_s": p95_s,
                "timeout_compliant": timeout_compliant,
                "prompt_attempts_by_id": json.dumps(attempts_by_prompt, sort_keys=True),
                "prompt_successes_by_id": json.dumps(successes_by_prompt, sort_keys=True),
                "prompt_ids": ",".join(_sorted_prompt_ids(attempts_by_prompt.keys())) if attempts_by_prompt else "",
                "prompt_mix_source": prompt_mix_source,
                "prompt_mix_checked": False,
                "prompt_mix_ok": True,
                "prompt_mix_max_minus_min": None,
                "rep_valid": loadgen_valid,
                "invalid_reasons": ",".join(sorted(set(loadgen_invalid_reasons))) if loadgen_invalid_reasons else "",
                "summary_file": str(summary_path),
            }

        for base in sorted(measure_counter_bases_here):
            row[f"{base}_count"] = failure_counts.get(base)
            row[f"{base}_rate"] = failure_rates.get(base)

        rep_rows.append(row)

    rep_rows.sort(key=lambda r: (r.get("endpoint") or "", r.get("prompt_set") or "", int(r.get("offered_rpm") or 0), int(r.get("rep") or 0)))
    return rep_rows, warnings, discovered_measure_counter_bases, discovered_prompt_ids
