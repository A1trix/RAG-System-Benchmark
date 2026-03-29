#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check if JSONL contains run_id")
    parser.add_argument("--file", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("run_id") == args.run_id:
                    return 0
    except FileNotFoundError:
        pass

    print(f"run_id not found in {path}: {args.run_id}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
