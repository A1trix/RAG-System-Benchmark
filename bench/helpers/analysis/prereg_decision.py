#!/usr/bin/env python3
"""Evaluate a run batch against preregistered benchmark decision rules.

The optional --enforce mode fails only when the benchmark state is thesis-invalid,
not when a valid comparison ends in a scientific trade-off without a single winner.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate preregistered benchmark decision rules")
    parser.add_argument("run_dir", help="Path to bench/results/compare_<timestamp>")
    parser.add_argument("--prereg", default=None, help="Path to preregistration JSON (default: <repo>/bench/preregistration.json)")
    parser.add_argument("--output", default=None, help="Write JSON decision output")
    parser.add_argument("--enforce", action="store_true", help="Exit non-zero if prereg decision fails validity")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    prereg_path = Path(args.prereg) if args.prereg else (run_dir.parents[1] / "preregistration.json")
    prereg = load_json(prereg_path) or {}
    schema_version = str(prereg.get("schema_version") or "")
    supported_prefixes = ("sweep-first/", "thesis-batch/")

    if not any(schema_version.startswith(prefix) for prefix in supported_prefixes):
        print(
            f"unsupported prereg schema for this benchmark evaluator: {schema_version or '<missing>'}",
            file=sys.stderr,
        )
        return 2

    try:
        from sweep_decision import main as decision_main
    except Exception as exc:
        print(f"failed to import sweep_decision.py: {exc}", file=sys.stderr)
        return 2

    f_argv = [str(run_dir), "--prereg", str(prereg_path)]
    if args.output:
        f_argv += ["--output", str(args.output)]
    if args.enforce:
        f_argv += ["--enforce"]
    return int(decision_main(f_argv) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
