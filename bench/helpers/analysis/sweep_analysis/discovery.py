from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from .io_utils import load_jsonl

ARRIVAL_RUN_RE = re.compile(
    r"^arrival-(?P<endpoint>[A-Za-z0-9_]+)-(?P<prompt_set>[A-Za-z0-9_]+)-(?P<rpm>[0-9]+)rpm-rep(?P<rep>[0-9]+)-(?P<rest>.+)$"
)

MEASURE_COUNTERS = (
    "attempts_measure",
    "successes_measure",
    "timeouts_measure",
    "errors_total_measure",
    "errors_non_timeout_measure",
)

PROMPT_ATTEMPTS_COUNTER_BASE = "attempts_measure_prompt"
PROMPT_SUCCESSES_COUNTER_BASE = "successes_measure_prompt"

FAILURE_MODE_COUNTER_BASES = (
    "http_429_measure",
    "http_5xx_measure",
    "http_non_200_measure",
)

LATENCY_TREND = "latency_measure_ms"

def find_summary_files(results_dir: Path) -> list[Path]:
    paths = []
    for p in sorted(results_dir.glob("*.json")):
        if p.name in (
            "manifest.json",
            "docker_images.json",
            "thesis_batch_validation.json",
        ):
            continue
        if ARRIVAL_RUN_RE.match(p.stem):
            paths.append(p)
    return paths

def load_run_index(results_dir: Path) -> dict[str, dict[str, Any]]:
    run_rows = load_jsonl(results_dir / "runs.jsonl")
    run_by_id: dict[str, dict[str, Any]] = {}
    for r in run_rows:
        rid = r.get("run_id")
        if isinstance(rid, str):
            run_by_id[rid] = r
    return run_by_id

def _normalize_tag_filter(values: list[Any] | None) -> list[str] | None:
    if not values:
        return None
    out = [str(x) for x in values if x is not None and str(x).strip()]
    return out if out else None

def resolve_run_tag_filters(args: argparse.Namespace) -> tuple[list[str] | None, list[str] | None]:
    include_run_tags = _normalize_tag_filter(args.run_tag)
    knee_run_tags = _normalize_tag_filter(args.knee_run_tag)
    if knee_run_tags is None:
        knee_run_tags = include_run_tags
    return include_run_tags, knee_run_tags
