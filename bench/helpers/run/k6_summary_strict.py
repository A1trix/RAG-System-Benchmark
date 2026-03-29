#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def fail(msg: str) -> int:
    print(msg)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict validation for k6 summary")
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail(f"summary missing: {path}")
    except json.JSONDecodeError as exc:
        return fail(f"summary invalid JSON: {path} ({exc})")

    root_group = data.get("root_group", {})
    checks = root_group.get("checks", {})
    check_fails = 0
    failed_checks: list[dict] = []
    for check in checks.values():
        try:
            fails = int(check.get("fails", 0))
            check_fails += fails
            if fails > 0:
                failed_checks.append(check)
        except Exception:
            pass

    metrics = data.get("metrics", {})
    mchecks = metrics.get("checks", {})
    try:
        global_fails = int(mchecks.get("fails", 0))
        check_fails += global_fails
    except Exception:
        pass

    if check_fails > 0:
        if failed_checks:
            print("failed checks:")
            for check in failed_checks:
                name = check.get("name", "(unnamed)")
                fails = check.get("fails", 0)
                passes = check.get("passes", 0)
                rate = check.get("rate")
                if rate is None:
                    print(f"- check: {name}, fails: {fails}, passes: {passes}")
                else:
                    print(f"- check: {name}, fails: {fails}, passes: {passes}, rate: {rate}")
        return fail(f"checks failed: {check_fails}")

    http_failed = metrics.get("http_req_failed", {})
    try:
        value = float(http_failed.get("value", 0))
        if value > 0:
            return fail(f"http_req_failed.value > 0 ({value})")
    except Exception:
        pass

    http_reqs = metrics.get("http_reqs", {})
    iterations = metrics.get("iterations", {})
    req_count = http_reqs.get("count", 0)
    iter_count = iterations.get("count", 0)
    try:
        if int(req_count) <= 0 and int(iter_count) <= 0:
            return fail("no requests or iterations recorded")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
