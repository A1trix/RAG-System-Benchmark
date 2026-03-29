from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from .io_utils import save_markdown_table
from .metrics import as_int
from .types import PointKey

def fmt_float(x: Any, digits: int = 6) -> str:
    if x is None:
        return ""
    try:
        xf = float(x)
    except Exception:
        return ""
    if math.isnan(xf) or math.isinf(xf):
        return ""
    return f"{xf:.{digits}f}"

def fmt_int(x: Any) -> str:
    try:
        if x is None:
            return ""
        return str(int(x))
    except Exception:
        return ""

def write_prompt_mix_report(
    path: Path,
    results_dir: Path,
    expected_prompt_ids: list[str],
    expected_prompts_arg: int | None,
    rep_rows: list[dict[str, Any]],
    agg_rows: list[dict[str, Any]],
    by_point_all: dict[PointKey, list[dict[str, Any]]],
) -> None:
    prompt_lines: list[str] = []
    prompt_lines.append("# Prompt Mix Report")
    prompt_lines.append("")
    prompt_lines.append(f"Results dir: `{results_dir}`")
    prompt_lines.append(
        f"Expected prompts: {len(expected_prompt_ids)}"
        + (
            f" (from --expected-prompts={int(expected_prompts_arg)})"
            if expected_prompts_arg is not None
            else " (derived from tagged metrics or prompt_order artifacts)"
        )
    )
    prompt_lines.append("")
    prompt_lines.append("## Per Rep")
    prompt_lines.append("")
    prompt_lines.append("| run_id | endpoint | prompt_set | rpm | rep | attempts | tagged_attempts | prompt_ids | source | max-min | ok | reasons | distribution |")
    prompt_lines.append("|---|---|---:|---:|---:|---:|---:|---|---|---:|---|---|---|")
    for r in rep_rows:
        attempts_cnt = as_int(r.get("attempts_measure_count"))
        try:
            abp = json.loads(str(r.get("prompt_attempts_by_id") or "{}"))
        except Exception:
            abp = {}
        if not isinstance(abp, dict):
            abp = {}
        abp_i: dict[str, int] = {}
        for k, v in abp.items():
            iv = as_int(v)
            if iv is None:
                continue
            abp_i[str(k)] = int(iv)
        tagged_total = sum(abp_i.values())
        dist = " ".join(f"{pid}:{abp_i.get(pid, 0)}" for pid in expected_prompt_ids) if expected_prompt_ids else ""
        prompt_lines.append(
            "| {run_id} | {endpoint} | {prompt_set} | {rpm} | {rep} | {attempts} | {tagged} | {pids} | {source} | {diff} | {ok} | {reasons} | {dist} |".format(
                run_id=str(r.get("run_id") or ""),
                endpoint=str(r.get("endpoint") or ""),
                prompt_set=str(r.get("prompt_set") or ""),
                rpm=str(r.get("offered_rpm") or ""),
                rep=str(r.get("rep") or ""),
                attempts=str(attempts_cnt) if attempts_cnt is not None else "",
                tagged=str(tagged_total) if tagged_total else "0",
                pids=str(r.get("prompt_ids") or ""),
                source=str(r.get("prompt_mix_source") or ""),
                diff=str(r.get("prompt_mix_max_minus_min") or ""),
                ok="yes" if bool(r.get("prompt_mix_ok")) else "no" if bool(r.get("prompt_mix_checked")) else "",
                reasons=str(r.get("invalid_reasons") or ""),
                dist=dist,
            )
        )
    prompt_lines.append("")
    prompt_lines.append("## Per Point")
    prompt_lines.append("")
    prompt_lines.append("| endpoint | prompt_set | rpm | reps | prompt_mix_valid | invalid_reps |")
    prompt_lines.append("|---|---|---:|---:|---|---:|")
    for pr in sorted(
        agg_rows,
        key=lambda rr: (str(rr.get("endpoint") or ""), str(rr.get("prompt_set") or ""), int(rr.get("offered_rpm") or 0)),
    ):
        key = PointKey(str(pr.get("endpoint") or ""), str(pr.get("prompt_set") or ""), int(pr.get("offered_rpm") or 0))
        reps = by_point_all.get(key) or []
        invalid_reps = sum(1 for rr in reps if not bool(rr.get("prompt_mix_ok")))
        prompt_lines.append(
            "| {endpoint} | {prompt_set} | {rpm} | {reps} | {ok} | {bad} |".format(
                endpoint=str(pr.get("endpoint") or ""),
                prompt_set=str(pr.get("prompt_set") or ""),
                rpm=str(pr.get("offered_rpm") or ""),
                reps=str(pr.get("reps") or ""),
                ok="yes" if bool(pr.get("point_prompt_mix_valid")) else "no",
                bad=str(invalid_reps),
            )
        )
    prompt_lines.append("")
    path.write_text("\n".join(prompt_lines), encoding="utf-8")

def write_knee_reports(analysis_dir: Path, results_dir: Path, knee_report: dict[str, Any], args: argparse.Namespace) -> tuple[Path, Path]:
    knee_json = analysis_dir / "knee_report.json"
    knee_md = analysis_dir / "knee_report.md"
    knee_json.write_text(json.dumps(knee_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md_rows: list[list[str]] = []
    for _k, c in sorted((knee_report.get("cohorts") or {}).items()):
        knee = c.get("knee") or {}
        kc = c.get("knee_candidates") or {}
        p95 = kc.get("p95") or {}
        err = kc.get("error_rate_total") or {}
        reasons = knee.get("first_bad_reasons") or []
        if not isinstance(reasons, list):
            reasons = []
        reasons_s = ",".join(str(x) for x in reasons if x is not None)
        row = [
            c.get("endpoint") or "",
            c.get("prompt_set") or "",
            fmt_int(knee.get("last_good_rpm")),
            fmt_int(knee.get("first_bad_rpm")),
            reasons_s,
            fmt_float(knee.get("sustainable_throughput_success_rps"), 4),
            fmt_int(p95.get("rpm_break_right")),
            "yes" if p95.get("knee_trigger") else "no" if p95 else "",
            fmt_int(err.get("rpm_break_right")),
            "yes" if err.get("knee_trigger") else "no" if err else "",
        ]
        md_rows.append(row)

    header = [
        "endpoint",
        "prompt_set",
        "last_good_rpm",
        "first_bad_rpm",
        "first_bad_reasons",
        "sustainable_thr_rps",
        "p95_knee_rpm",
        "p95_knee",
        "err_knee_rpm",
        "err_knee",
    ]

    intro_lines = [
        f"Results dir: `{results_dir}`",
        f"Timeout compliance per rep: timeout_rate <= {float(args.timeout_rate_max):.4f}",
        "Scientifically invalid points excluded from sweep comparison, best-tradeoff summaries, and knee analysis: measure_seconds_ok AND dropped_iterations==0 AND vus_max < vus_cap AND prompt_mix_ok.",
        (
            f"Optional gate: error_rate_non_timeout <= {float(args.error_non_timeout_max):.4f} (knee analysis)."
            if args.error_non_timeout_max is not None
            else "Optional gate: error_rate_non_timeout_max disabled."
        ),
        f"Point compliance requires >= {int(args.expected_reps)} reps and all reps timeout-compliant.",
    ]

    save_markdown_table(
        knee_md,
        header=header,
        rows=md_rows,
        title="Sweep Knee Report",
        intro_lines=intro_lines,
    )
    return knee_json, knee_md

def emit_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    for w in warnings[:50]:
        print(f"Warning: {w}", file=sys.stderr)
    if len(warnings) > 50:
        print(f"Warning: ... ({len(warnings) - 50} more)", file=sys.stderr)

def print_written_outputs(
    *,
    rep_csv: Path,
    agg_csv: Path,
    invalid_csv: Path,
    prompt_md: Path,
    knee_json: Path,
    knee_md: Path,
    no_plots: bool,
    analysis_dir: Path,
) -> None:
    print(f"Wrote {rep_csv}")
    print(f"Wrote {agg_csv}")
    print(f"Wrote {invalid_csv}")
    print(f"Wrote {prompt_md}")
    print(f"Wrote {knee_json}")
    print(f"Wrote {knee_md}")
    if not no_plots:
        print(f"Wrote plots under {analysis_dir}")
