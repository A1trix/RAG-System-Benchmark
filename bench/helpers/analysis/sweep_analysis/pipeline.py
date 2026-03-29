from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .aggregation import (
    aggregate_points,
    build_agg_fields,
    build_invalid_rows,
    build_rep_fields,
    mark_pareto_best_tradeoffs,
)
from .discovery import load_run_index, resolve_run_tag_filters
from .io_utils import write_csv
from .knee import build_sorted_cohorts, compute_knee_report
from .plots import generate_plots
from .prompt_mix import resolve_expected_prompt_ids, validate_prompt_mix
from .rep_analysis import collect_rep_rows
from .reports import (
    emit_warnings,
    print_written_outputs,
    write_knee_reports,
    write_prompt_mix_report,
)

def enforce_validity_or_exit(enforce_validity: bool, invalid_rows: list[dict[str, Any]]) -> int | None:
    if not enforce_validity or not invalid_rows:
        return None
    for r in invalid_rows[:50]:
        print(
            "VALIDITY_FAIL: {row_type} endpoint={endpoint} prompt_set={prompt_set} offered_rpm={rpm} rep={rep} run_id={run_id} reasons={reasons}".format(
                row_type=str(r.get("row_type") or ""),
                endpoint=str(r.get("endpoint") or ""),
                prompt_set=str(r.get("prompt_set") or ""),
                rpm=str(r.get("offered_rpm") or ""),
                rep=str(r.get("rep") or ""),
                run_id=str(r.get("run_id") or ""),
                reasons=str(r.get("reason_codes") or ""),
            ),
            file=sys.stderr,
        )
    if len(invalid_rows) > 50:
        print(f"VALIDITY_FAIL: ... ({len(invalid_rows) - 50} more)", file=sys.stderr)
    return 3

def run_analysis(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"results_dir not found: {results_dir}", file=sys.stderr)
        return 2

    analysis_dir = results_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    for stale_name in ("tier_table.csv", "tier_table.md"):
        stale_path = analysis_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    run_by_id = load_run_index(results_dir)
    include_run_tags, knee_run_tags = resolve_run_tag_filters(args)
    rep_rows, warnings, discovered_measure_counter_bases, discovered_prompt_ids = collect_rep_rows(
        results_dir,
        run_by_id,
        include_run_tags,
        args,
    )
    expected_prompt_ids = resolve_expected_prompt_ids(args, discovered_prompt_ids, warnings)
    validate_prompt_mix(rep_rows, expected_prompt_ids, args, warnings)

    rep_csv = analysis_dir / "sweep_points.csv"
    write_csv(rep_csv, build_rep_fields(discovered_measure_counter_bases), rep_rows)

    agg_rows, by_point_all = aggregate_points(
        rep_rows,
        discovered_measure_counter_bases=discovered_measure_counter_bases,
        expected_reps=int(args.expected_reps),
        bootstrap_iters=int(args.bootstrap_iters),
        bootstrap_seed=int(args.bootstrap_seed),
        error_non_timeout_max=args.error_non_timeout_max,
        seed_bump=0,
    )
    rep_rows_knee = rep_rows
    if knee_run_tags is not None:
        knee_tag_set = set(knee_run_tags)
        rep_rows_knee = [r for r in rep_rows if str(r.get("run_tag") or "") in knee_tag_set]
    agg_rows_knee, _by_point_knee = aggregate_points(
        rep_rows_knee,
        discovered_measure_counter_bases=discovered_measure_counter_bases,
        expected_reps=int(args.expected_reps),
        bootstrap_iters=int(args.bootstrap_iters),
        bootstrap_seed=int(args.bootstrap_seed),
        error_non_timeout_max=args.error_non_timeout_max,
        seed_bump=1000,
    )

    mark_pareto_best_tradeoffs(agg_rows)
    agg_csv = analysis_dir / "sweep_points_agg.csv"
    write_csv(agg_csv, build_agg_fields(discovered_measure_counter_bases), agg_rows)

    invalid_csv = analysis_dir / "invalid_points.csv"
    invalid_rows = build_invalid_rows(rep_rows, agg_rows, by_point_all, int(args.expected_reps))
    invalid_fields = ["row_type", "run_id", "run_tag", "endpoint", "prompt_set", "offered_rpm", "rep", "reason_codes"]
    write_csv(invalid_csv, invalid_fields, invalid_rows)

    prompt_md = analysis_dir / "prompt_mix_report.md"
    write_prompt_mix_report(
        prompt_md, results_dir, expected_prompt_ids, args.expected_prompts, rep_rows, agg_rows, by_point_all
    )

    cohorts_all = build_sorted_cohorts(agg_rows)
    cohorts_knee = build_sorted_cohorts(agg_rows_knee)
    knee_report = compute_knee_report(
        results_dir=results_dir,
        args=args,
        include_run_tags=include_run_tags,
        knee_run_tags=knee_run_tags,
        warnings=warnings,
        cohorts_all=cohorts_all,
        cohorts_knee=cohorts_knee,
    )
    knee_json, knee_md = write_knee_reports(analysis_dir, results_dir, knee_report, args)
    if not args.no_plots:
        generate_plots(analysis_dir, cohorts_all)

    validity_rc = enforce_validity_or_exit(args.enforce_validity, invalid_rows)
    if validity_rc is not None:
        return validity_rc
    emit_warnings(warnings)
    print_written_outputs(
        rep_csv=rep_csv,
        agg_csv=agg_csv,
        invalid_csv=invalid_csv,
        prompt_md=prompt_md,
        knee_json=knee_json,
        knee_md=knee_md,
        no_plots=bool(args.no_plots),
        analysis_dir=analysis_dir,
    )
    return 0
