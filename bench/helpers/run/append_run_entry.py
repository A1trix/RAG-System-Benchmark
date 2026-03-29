#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Append run entry JSONL record")
    parser.add_argument("--runs-file", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--vus", required=True, type=int)
    parser.add_argument("--duration", required=True)
    parser.add_argument("--settle-seconds", required=False, type=int, default=None)
    parser.add_argument("--measure-seconds", required=False, type=int, default=None)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--summary-file", required=True)
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--prompt-set", required=True)
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--run-order", required=True, type=int)
    parser.add_argument("--offered-rpm", required=False, type=int, default=None)
    parser.add_argument("--repetition-index", required=False, type=int, default=None)
    parser.add_argument("--target-endpoint", required=False, default=None)
    parser.add_argument("--parent-compare-id", required=False, default=None)
    parser.add_argument("--child-batch-id", required=False, default=None)
    parser.add_argument("--pair-rep", required=False, type=int, default=None)
    parser.add_argument("--pair-order", required=False, default=None)
    parser.add_argument("--pair-prompt-seed", required=False, type=int, default=None)
    parser.add_argument("--strict", required=True, type=int)
    parser.add_argument("--summary-metrics", required=True)
    args = parser.parse_args()

    metrics = json.loads(args.summary_metrics)
    entry = {
        "run_id": args.run_id,
        "run_tag": args.run_tag,
        "endpoint": args.endpoint,
        "prompt_set": args.prompt_set,
        "prompts_path": args.prompts_path,
        "run_order": args.run_order,
        "offered_rpm": args.offered_rpm,
        "repetition_index": args.repetition_index,
        "target_endpoint": args.target_endpoint,
        "parent_compare_id": args.parent_compare_id,
        "child_batch_id": args.child_batch_id,
        "pair_rep": args.pair_rep,
        "pair_order": args.pair_order,
        "pair_prompt_seed": args.pair_prompt_seed,
        "vus": args.vus,
        "duration": args.duration,
        "settle_seconds": args.settle_seconds,
        "measure_seconds": args.measure_seconds,
        "strict": bool(args.strict),
        "start": args.start,
        "end": args.end,
        "summary_file": args.summary_file,
    }
    if entry.get("settle_seconds") is None:
        entry.pop("settle_seconds", None)
    if entry.get("measure_seconds") is None:
        entry.pop("measure_seconds", None)
    for optional_key in (
        "offered_rpm",
        "repetition_index",
        "target_endpoint",
        "parent_compare_id",
        "child_batch_id",
        "pair_rep",
        "pair_order",
        "pair_prompt_seed",
    ):
        if entry.get(optional_key) is None:
            entry.pop(optional_key, None)
    entry.update(metrics)

    path = Path(args.runs_file)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
