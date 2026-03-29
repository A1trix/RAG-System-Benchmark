#!/usr/bin/env python3
"""Analyze constant-arrival-rate sweep runs."""

from __future__ import annotations

from sweep_analysis.config import build_parser
from sweep_analysis.pipeline import run_analysis


def main() -> int:
    return run_analysis(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
