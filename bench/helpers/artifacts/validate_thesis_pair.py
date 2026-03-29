#!/usr/bin/env python3
"""Validate an isolated paired thesis benchmark cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _get(mapping: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _is_configured(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _single_value(values: set[str]) -> str | None:
    if len(values) != 1:
        return None
    return next(iter(values))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate isolated paired thesis benchmark artifacts")
    parser.add_argument("parent_dir", help="Path to bench/results/compare_<timestamp>")
    parser.add_argument("--pair-plan", default=None, help="Path to pair_plan.json (default: <parent>/pair_plan.json)")
    parser.add_argument("--prereg", default=None, help="Path to preregistration JSON (default: <repo>/bench/preregistration.json)")
    parser.add_argument("--output", default=None, help="Write JSON output (default: <parent>/analysis/pair_validation.json)")
    args = parser.parse_args()

    parent_dir = Path(args.parent_dir)
    analysis_dir = parent_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    pair_plan_path = Path(args.pair_plan) if args.pair_plan else (parent_dir / "pair_plan.json")
    prereg_path = Path(args.prereg) if args.prereg else (parent_dir.parents[1] / "preregistration.json")
    out_path = Path(args.output) if args.output else (analysis_dir / "pair_validation.json")

    failures: list[str] = []
    notes: list[str] = []

    pair_plan = load_json(pair_plan_path) or {}
    prereg = load_json(prereg_path) or {}
    children = pair_plan.get("children") if isinstance(pair_plan, dict) else None
    pair_reps_expected = int(pair_plan.get("pair_repetitions") or 0) if isinstance(pair_plan, dict) else 0
    pair_order_mode = str(pair_plan.get("pair_order_mode") or "") if isinstance(pair_plan, dict) else ""
    expected_parent_compare_id = str(pair_plan.get("parent_compare_id") or "") if isinstance(pair_plan, dict) else ""

    execution_model = _as_dict(prereg.get("execution_model"))
    scope = _as_dict(prereg.get("scope"))
    windows = _as_dict(prereg.get("windows"))
    design = _as_dict(prereg.get("design"))
    sweep_track = _as_dict(design.get("sweep_track"))
    stage1_primary = _as_dict(sweep_track.get("stage1_primary"))
    primary_rpm = _as_dict(stage1_primary.get("offered_rpm"))
    preconditions = _as_dict(prereg.get("preconditions"))
    boundary_audit_cfg = _as_dict(preconditions.get("boundary_audit"))

    expected_prereg_id = str(prereg.get("id") or "").strip()
    expected_prereg_sha = sha256_file(prereg_path)
    expected_prompts_path = str(scope.get("prompts_path") or "").strip()
    expected_primary_start = str(primary_rpm.get("start") or "").strip()
    expected_primary_end = str(primary_rpm.get("stop") or "").strip()
    expected_primary_step = str(primary_rpm.get("step") or "").strip()
    expected_primary_measure = str(windows.get("measure_s") or "").strip()
    expected_primary_settle = str(windows.get("settle_s") or "").strip()
    expected_pair_repetitions = int(execution_model.get("pair_repetitions") or 0) if isinstance(execution_model, dict) else 0
    expected_pair_order_mode = str(execution_model.get("pair_order_mode") or "").strip()
    expected_child_batch_reps = str(execution_model.get("child_batch_repetitions") or "").strip()
    expected_boundary_audit_required = boundary_audit_cfg.get("required") if isinstance(boundary_audit_cfg, dict) else None

    if not pair_plan_path.exists():
        failures.append(f"missing pair plan: {pair_plan_path}")
    if not prereg_path.exists():
        failures.append(f"missing preregistration: {prereg_path}")
    if not isinstance(children, list) or not children:
        failures.append("pair plan has no child entries")
        children = []
    if pair_reps_expected <= 0:
        failures.append("pair plan missing valid pair_repetitions")

    groups: dict[int, list[dict[str, Any]]] = {}
    child_summaries: list[dict[str, Any]] = []
    common_values: dict[str, set[str]] = {
        "prereg_sha": set(),
        "prereg_id": set(),
        "prompts_path": set(),
        "smoke_rpms": set(),
        "smoke_reps": set(),
        "smoke_measure": set(),
        "smoke_settle": set(),
        "primary_start": set(),
        "primary_end": set(),
        "primary_step": set(),
        "primary_reps": set(),
        "primary_measure": set(),
        "primary_settle": set(),
        "stop_after_smoke": set(),
        "timeout_rate_max": set(),
        "require_boundary_audit": set(),
        "boundary_audit_sha": set(),
        "source_fingerprint_sha256": set(),
        "db_fingerprint_pre": set(),
    }

    rag_first_count = 0
    n8n_first_count = 0
    smoke_configured = False

    for entry in children:
        if not isinstance(entry, dict):
            failures.append("pair plan child entry is not an object")
            continue
        pair_rep = int(entry.get("pair_rep") or 0)
        endpoint = str(entry.get("endpoint") or "").strip()
        order_index = int(entry.get("order_index") or 0)
        pair_order = str(entry.get("pair_order") or "").strip()
        pair_seed = entry.get("pair_prompt_seed")
        child_dir = Path(str(entry.get("results_dir") or "")).expanduser()

        if pair_rep <= 0:
            failures.append(f"child entry missing valid pair_rep: {entry}")
            continue
        groups.setdefault(pair_rep, []).append(entry)

        manifest_path = child_dir / "manifest.json"
        validation_path = child_dir / "thesis_batch_validation.json"
        manifest = load_json(manifest_path) or {}
        validation = load_json(validation_path) or {}
        bench_env = manifest.get("bench_env") if isinstance(manifest, dict) else {}

        if not child_dir.exists():
            failures.append(f"child results dir missing: {child_dir}")
        if not manifest_path.exists():
            failures.append(f"child manifest missing: {manifest_path}")
        if not validation_path.exists():
            failures.append(f"child thesis_batch_validation missing: {validation_path}")
        if validation_path.exists() and not validation.get("pass"):
            failures.append(f"child thesis_batch_validation failed: {child_dir}")

        batch_kind = str(manifest.get("batch_kind") or "").strip()
        target_endpoint = str(manifest.get("target_endpoint") or "").strip()
        parent_compare_id = str(manifest.get("parent_compare_id") or "").strip()
        child_batch_id = str(manifest.get("child_batch_id") or "").strip()

        if batch_kind != "isolated_child":
            failures.append(f"child manifest batch_kind must be isolated_child: {manifest_path}")
        if endpoint not in {"rag", "n8n"}:
            failures.append(f"pair entry endpoint must be rag or n8n: {entry}")
        if target_endpoint != endpoint:
            failures.append(f"child target_endpoint mismatch for {child_dir}: expected {endpoint}, got {target_endpoint or '<missing>'}")
        if not parent_compare_id:
            failures.append(f"child manifest missing parent_compare_id: {manifest_path}")
        elif expected_parent_compare_id and parent_compare_id != expected_parent_compare_id:
            failures.append(
                f"child manifest parent_compare_id mismatch for {child_dir}: expected {expected_parent_compare_id}, got {parent_compare_id}"
            )
        if not child_batch_id:
            failures.append(f"child manifest missing child_batch_id: {manifest_path}")
        elif child_batch_id != str(entry.get("child_batch_id") or ""):
            failures.append(
                f"child manifest child_batch_id mismatch for {child_dir}: expected {entry.get('child_batch_id')}, got {child_batch_id}"
            )

        if endpoint == "rag" and order_index == 1:
            rag_first_count += 1
        if endpoint == "n8n" and order_index == 1:
            n8n_first_count += 1

        def add_common(name: str, value: Any) -> None:
            if value is not None and str(value).strip() != "":
                common_values[name].add(str(value))

        add_common("prereg_sha", _get(manifest, "preregistration", "sha256"))
        add_common("prereg_id", _get(manifest, "preregistration", "id"))
        add_common("prompts_path", _get(bench_env, "BENCH_PROMPTS_PATH"))
        smoke_configured = smoke_configured or _is_configured(_get(bench_env, "BENCH_SWEEP_SMOKE_RPM_LIST"))
        add_common("smoke_rpms", _get(bench_env, "BENCH_SWEEP_SMOKE_RPM_LIST"))
        add_common("smoke_reps", _get(bench_env, "BENCH_SWEEP_SMOKE_REPS"))
        add_common("smoke_measure", _get(bench_env, "BENCH_SWEEP_SMOKE_MEASURE_SECONDS"))
        add_common("smoke_settle", _get(bench_env, "BENCH_SWEEP_SMOKE_SETTLE_SECONDS"))
        add_common("primary_start", _get(bench_env, "BENCH_SWEEP_PRIMARY_RPM_START"))
        add_common("primary_end", _get(bench_env, "BENCH_SWEEP_PRIMARY_RPM_END"))
        add_common("primary_step", _get(bench_env, "BENCH_SWEEP_PRIMARY_RPM_STEP"))
        add_common("primary_reps", _get(bench_env, "BENCH_SWEEP_PRIMARY_REPS"))
        add_common("primary_measure", _get(bench_env, "BENCH_SWEEP_PRIMARY_MEASURE_SECONDS"))
        add_common("primary_settle", _get(bench_env, "BENCH_SWEEP_PRIMARY_SETTLE_SECONDS"))
        add_common("stop_after_smoke", _get(bench_env, "BENCH_SWEEP_STOP_AFTER_SMOKE"))
        add_common("timeout_rate_max", _get(bench_env, "BENCH_SWEEP_TIMEOUT_RATE_MAX"))
        add_common("require_boundary_audit", _get(bench_env, "BENCH_REQUIRE_BOUNDARY_AUDIT"))
        add_common("boundary_audit_sha", _get(manifest, "artifacts", "boundary_audit_report", "sha256"))
        add_common("source_fingerprint_sha256", _get(manifest, "artifacts", "source_fingerprint", "fingerprint_sha256"))
        add_common("db_fingerprint_pre", _get(manifest, "artifacts", "db_fingerprint_pre", "fingerprint_sha256"))

        child_summaries.append(
            {
                "pair_rep": pair_rep,
                "endpoint": endpoint,
                "order_index": order_index,
                "pair_order": pair_order,
                "pair_prompt_seed": pair_seed,
                "results_dir": str(child_dir),
                "manifest": str(manifest_path),
                "validation_pass": bool(validation.get("pass")),
            }
        )

    if pair_reps_expected and len(groups) != pair_reps_expected:
        failures.append(
            f"pair plan expected {pair_reps_expected} paired repetitions, found {len(groups)}"
        )

    if expected_pair_repetitions > 0 and pair_reps_expected != expected_pair_repetitions:
        failures.append(
            f"prereg_mismatch:pair_repetitions expected={expected_pair_repetitions} got={pair_reps_expected}"
        )
    if expected_pair_order_mode and pair_order_mode != expected_pair_order_mode:
        failures.append(
            f"prereg_mismatch:pair_order_mode expected={expected_pair_order_mode} got={pair_order_mode or '<missing>'}"
        )

    for rep in sorted(groups):
        entries = sorted(groups[rep], key=lambda item: int(item.get("order_index") or 0))
        endpoints = [str(item.get("endpoint") or "").strip() for item in entries]
        orders = [int(item.get("order_index") or 0) for item in entries]
        seeds = {str(item.get("pair_prompt_seed") or "").strip() for item in entries}
        pair_orders = {str(item.get("pair_order") or "").strip() for item in entries}

        if len(entries) != 2:
            failures.append(f"pair_rep={rep} does not contain exactly two child batches")
            continue
        if sorted(endpoints) != ["n8n", "rag"]:
            failures.append(f"pair_rep={rep} must contain rag and n8n exactly once, found {endpoints}")
        if orders != [1, 2]:
            failures.append(f"pair_rep={rep} must use order_index [1,2], found {orders}")
        if len(seeds) != 1:
            failures.append(f"pair_rep={rep} must use one shared pair_prompt_seed, found {sorted(seeds)}")
        if len(pair_orders) != 1:
            failures.append(f"pair_rep={rep} must use one shared pair_order label, found {sorted(pair_orders)}")

        if pair_order_mode == "alternate_by_rep":
            expected_first = "rag" if rep % 2 == 1 else "n8n"
            if endpoints and endpoints[0] != expected_first:
                failures.append(
                    f"pair_rep={rep} must start with {expected_first} under alternate_by_rep, found {endpoints[0]}"
                )

    for name, values in common_values.items():
        if len(values) > 1:
            failures.append(f"child manifests disagree on {name}: {sorted(values)}")

    required_common = {
        "prereg_sha",
        "prereg_id",
        "prompts_path",
        "primary_start",
        "primary_end",
        "primary_step",
        "primary_reps",
        "primary_measure",
        "primary_settle",
        "stop_after_smoke",
        "timeout_rate_max",
        "require_boundary_audit",
        "boundary_audit_sha",
        "source_fingerprint_sha256",
        "db_fingerprint_pre",
    }
    if smoke_configured:
        required_common.update({"smoke_rpms", "smoke_reps", "smoke_measure", "smoke_settle"})
    for name in sorted(required_common):
        if not common_values.get(name):
            failures.append(f"child manifests missing required common value: {name}")

    primary_reps_values = common_values.get("primary_reps") or set()
    if primary_reps_values and primary_reps_values != {"1"}:
        failures.append(f"isolated child batches must use BENCH_SWEEP_PRIMARY_REPS=1, found: {sorted(primary_reps_values)}")

    def enforce_prereg_match(name: str, expected: str | None) -> None:
        if expected is None or expected == "":
            return
        actual = _single_value(common_values.get(name) or set())
        if actual is None:
            return
        if actual != expected:
            failures.append(f"prereg_mismatch:{name} expected={expected} got={actual}")

    enforce_prereg_match("prereg_id", expected_prereg_id)
    enforce_prereg_match("prereg_sha", expected_prereg_sha)
    enforce_prereg_match("prompts_path", expected_prompts_path)
    enforce_prereg_match("primary_start", expected_primary_start)
    enforce_prereg_match("primary_end", expected_primary_end)
    enforce_prereg_match("primary_step", expected_primary_step)
    enforce_prereg_match("primary_measure", expected_primary_measure)
    enforce_prereg_match("primary_settle", expected_primary_settle)
    enforce_prereg_match("primary_reps", expected_child_batch_reps)

    stop_after_smoke = _single_value(common_values.get("stop_after_smoke") or set())
    if stop_after_smoke is not None and stop_after_smoke != "0":
        failures.append(f"prereg_mismatch:stop_after_smoke expected=0 got={stop_after_smoke}")

    if expected_boundary_audit_required is not None:
        expected_boundary = "1" if bool(expected_boundary_audit_required) else "0"
        enforce_prereg_match("require_boundary_audit", expected_boundary)

    expected_rag_first = (pair_reps_expected + 1) // 2 if pair_reps_expected > 0 else None
    expected_n8n_first = pair_reps_expected // 2 if pair_reps_expected > 0 else None
    order_balance_pass = True
    if pair_order_mode == "alternate_by_rep" and expected_rag_first is not None and expected_n8n_first is not None:
        order_balance_pass = rag_first_count == expected_rag_first and n8n_first_count == expected_n8n_first
    if pair_order_mode == "alternate_by_rep" and not order_balance_pass:
        failures.append(
            "pair order balance failed: "
            f"rag_first_count={rag_first_count} (expected {expected_rag_first}), "
            f"n8n_first_count={n8n_first_count} (expected {expected_n8n_first})"
        )

    out = {
        "parent_dir": str(parent_dir),
        "pair_plan": str(pair_plan_path),
        "preregistration": {
            "path": str(prereg_path),
            "id": expected_prereg_id or None,
            "sha256": expected_prereg_sha,
        },
        "pair_order_mode": pair_order_mode,
        "pair_repetitions_expected": pair_reps_expected,
        "child_batches": child_summaries,
        "order_balance": {
            "rag_first_count": rag_first_count,
            "n8n_first_count": n8n_first_count,
            "expected_rag_first_count": expected_rag_first,
            "expected_n8n_first_count": expected_n8n_first,
            "pass": bool(order_balance_pass),
        },
        "common_values": {name: sorted(values) for name, values in common_values.items()},
        "failures": failures,
        "notes": notes,
        "pass": len(failures) == 0,
    }
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
