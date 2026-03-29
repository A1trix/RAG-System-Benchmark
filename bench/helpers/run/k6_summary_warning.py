#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit warning message for non-strict k6 summary errors")
    parser.add_argument("--summary-metrics", required=True)
    args = parser.parse_args()

    data = json.loads(args.summary_metrics)
    check_fails = int(data.get("check_fails") or 0)
    http_failed_rate = data.get("http_req_failed_rate") or 0
    if check_fails > 0 or http_failed_rate > 0:
        print(f"k6 run had errors: check_fails={check_fails}, http_req_failed_rate={http_failed_rate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
