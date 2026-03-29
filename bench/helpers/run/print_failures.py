#!/usr/bin/env python3
"""
Print validation failures from thesis batch validation JSON file.
Replaces inline Python heredoc from run_all.sh lines 819-838.
"""
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: print_failures.py <validation_file>", file=sys.stderr)
        sys.exit(1)
    
    path = Path(sys.argv[1])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"thesis batch validation emitted non-JSON output: {path}", file=sys.stderr)
        raise

    failures = payload.get("failures") if isinstance(payload, dict) else None
    if isinstance(failures, list) and failures:
        print("thesis batch validation failures:")
        for item in failures:
            print(f"- {item}")
    else:
        print(f"thesis batch validation failed; see {path}")


if __name__ == "__main__":
    main()
