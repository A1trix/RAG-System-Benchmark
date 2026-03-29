from __future__ import annotations

import argparse
import os


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze sweep (arrival-rate) results from measure-window metrics")
    parser.add_argument("results_dir", help="Benchmark results directory (contains k6 summaries + runs.jsonl)")
    parser.add_argument(
        "--run-tag",
        action="append",
        default=None,
        help="Include only runs with this runs.jsonl run_tag (repeatable). If unset: include all arrival summaries.",
    )
    parser.add_argument(
        "--knee-run-tag",
        action="append",
        default=None,
        help="Run tags to use for knee detection (repeatable). Defaults to --run-tag set (or all included points).",
    )
    parser.add_argument(
        "--measure-seconds",
        type=float,
        default=None,
        help="Override measure window seconds (default: derive from runs.jsonl duration/state)",
    )
    parser.add_argument(
        "--timeout-rate-max",
        type=float,
        default=float(os.getenv("BENCH_SWEEP_TIMEOUT_RATE_MAX", os.getenv("SWEEP_TIMEOUT_RATE_MAX", "0.01"))),
        help="Timeout compliance threshold per rep (default: 0.01)",
    )
    parser.add_argument(
        "--error-non-timeout-max",
        type=float,
        default=None,
        help="Optional gate: require error_rate_non_timeout <= this threshold for knee classification.",
    )
    parser.add_argument(
        "--expected-prompts",
        type=int,
        default=None,
        help="Expected number of prompts for prompt-mix verification (option C tagging). If unset: derive prompt list from tagged metrics.",
    )
    parser.add_argument(
        "--enforce-validity",
        action="store_true",
        help="Exit non-zero if any invalid rep/point is detected in included runs.",
    )
    parser.add_argument(
        "--require-prompt-tags",
        action="store_true",
        default=(os.getenv("BENCH_SWEEP_REQUIRE_PROMPT_TAGS", "0") == "1"),
        help="Require prompt-tagged measure counters for prompt-mix validation (default: env BENCH_SWEEP_REQUIRE_PROMPT_TAGS=0).",
    )
    parser.add_argument(
        "--expected-reps",
        type=int,
        default=int(os.getenv("BENCH_SWEEP_PRIMARY_REPS", os.getenv("SWEEP_EXPECTED_REPS", "3"))),
        help="Expected repetitions per point (default: 3)",
    )
    parser.add_argument(
        "--bootstrap-iters",
        type=int,
        default=int(os.getenv("SWEEP_BOOTSTRAP_ITERS", "5000")),
        help="Bootstrap iterations for mean CI over reps (default: 5000)",
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=int,
        default=int(os.getenv("SWEEP_BOOTSTRAP_SEED", "0")),
        help="Bootstrap RNG seed (default: 0)",
    )
    parser.add_argument(
        "--knee-min-points-per-seg",
        type=int,
        default=int(os.getenv("SWEEP_KNEE_MIN_POINTS", "2")),
        help="Minimum points per segment for piecewise regression (default: 2)",
    )
    parser.add_argument(
        "--knee-p95-slope-factor",
        type=float,
        default=float(os.getenv("SWEEP_KNEE_P95_SLOPE_FACTOR", "2.5")),
    )
    parser.add_argument(
        "--knee-p95-slope-abs-threshold",
        type=float,
        default=float(os.getenv("SWEEP_KNEE_P95_SLOPE_ABS", "0.005")),
        help="Absolute slope increase threshold for p95 knee (seconds per RPM)",
    )
    parser.add_argument(
        "--knee-error-slope-factor",
        type=float,
        default=float(os.getenv("SWEEP_KNEE_ERR_SLOPE_FACTOR", "3.0")),
    )
    parser.add_argument(
        "--knee-error-slope-abs-threshold",
        type=float,
        default=float(os.getenv("SWEEP_KNEE_ERR_SLOPE_ABS", "0.001")),
        help="Absolute slope increase threshold for error_rate_total knee (per RPM)",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip plot generation (still writes CSV/JSON/MD)",
    )
    return parser
