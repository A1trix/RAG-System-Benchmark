#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure boundary report has pass=true")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.report).read_text(encoding="utf-8"))
    if not bool(data.get("pass")):
        print("boundary audit report pass=false")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
