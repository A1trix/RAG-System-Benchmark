from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .io_utils import load_json
from .metrics import as_float, as_int, _sorted_prompt_ids


def _normalize_prompt_counter_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for key, raw in value.items():
        if key is None:
            continue
        parsed = as_int(raw)
        if parsed is None:
            continue
        out[str(key)] = int(parsed)
    return out


def load_prompt_metrics(results_dir: Path, run_id: str) -> dict[str, Any]:
    path = results_dir / f"prompt_metrics_{run_id}.json"
    data = load_json(path)
    if not isinstance(data, dict):
        return {}

    prompt_ids_raw = data.get("prompt_ids")
    prompt_ids: list[str] = []
    if isinstance(prompt_ids_raw, list):
        for value in prompt_ids_raw:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                prompt_ids.append(text)

    return {
        "prompt_ids": prompt_ids,
        "attempts_by_prompt": _normalize_prompt_counter_map(data.get("attempts_by_prompt")),
        "successes_by_prompt": _normalize_prompt_counter_map(data.get("successes_by_prompt")),
        "timeouts_by_prompt": _normalize_prompt_counter_map(data.get("timeouts_by_prompt")),
        "errors_non_timeout_by_prompt": _normalize_prompt_counter_map(data.get("errors_non_timeout_by_prompt")),
    }


def load_prompt_order_prompt_ids(results_dir: Path, run_id: str) -> list[str]:
    path = results_dir / f"prompt_order_{run_id}.json"
    data = load_json(path)
    if not isinstance(data, dict):
        return []
    seq = data.get("permutation_prompt_ids")
    if not isinstance(seq, list) or not seq:
        seq = data.get("prompt_ids")
    if not isinstance(seq, list):
        return []
    out: list[str] = []
    for v in seq:
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        out.append(s)
    return out

def build_prompt_counts_from_schedule(prompt_ids: list[str], attempts: int) -> dict[str, int]:
    if attempts <= 0 or not prompt_ids:
        return {}
    n = len(prompt_ids)
    base = attempts // n
    rem = attempts % n
    out = {pid: int(base) for pid in prompt_ids}
    for i in range(rem):
        out[prompt_ids[i]] = int(out.get(prompt_ids[i], 0) + 1)
    return out

def resolve_expected_prompt_ids(
    args: argparse.Namespace,
    discovered_prompt_ids: set[str],
    warnings: list[str],
) -> list[str]:
    expected_prompt_ids: list[str] = []
    if args.expected_prompts is not None:
        n = max(int(args.expected_prompts), 0)
        if n > 0:
            # Default assumption: numeric prompt_id scheme 0..N-1.
            all_numeric = (not discovered_prompt_ids) or all(as_int(pid) is not None for pid in discovered_prompt_ids)
            if all_numeric:
                expected_prompt_ids = [str(i) for i in range(n)]
            else:
                expected_prompt_ids = _sorted_prompt_ids(discovered_prompt_ids)
                if len(expected_prompt_ids) != n:
                    warnings.append(
                        f"--expected-prompts={n} but discovered prompt_ids={len(expected_prompt_ids)} ({expected_prompt_ids}); prompt-mix verification may be partial"
                    )
    else:
        expected_prompt_ids = _sorted_prompt_ids(discovered_prompt_ids)
    return expected_prompt_ids

def validate_prompt_mix(
    rep_rows: list[dict[str, Any]],
    expected_prompt_ids: list[str],
    args: argparse.Namespace,
    warnings: list[str],
) -> None:
    prompt_tags_unavailable_warning_emitted = False
    for r in rep_rows:
        attempts_cnt = as_int(r.get("attempts_measure_count"))
        ms = as_float(r.get("measure_seconds"))
        has_ms = bool(ms is not None and float(ms) > 0.0)
        has_attempts = bool(attempts_cnt is not None and int(attempts_cnt) > 0)
        measure_ok = bool(has_ms and has_attempts)
        r["measure_ok"] = measure_ok
        try:
            attempts_by_prompt = json.loads(str(r.get("prompt_attempts_by_id") or "{}"))
        except Exception:
            attempts_by_prompt = {}
        if not isinstance(attempts_by_prompt, dict):
            attempts_by_prompt = {}
        # Normalize counts.
        abp: dict[str, int] = {}
        for k, v in attempts_by_prompt.items():
            iv = as_int(v)
            if iv is None:
                continue
            abp[str(k)] = int(iv)

        prompt_mix_source = str(r.get("prompt_mix_source") or "unverifiable")

        if not expected_prompt_ids:
            if args.require_prompt_tags and attempts_cnt is not None and int(attempts_cnt) > 0:
                invalid_reasons: set[str] = set(str(r.get("invalid_reasons") or "").split(",")) if str(r.get("invalid_reasons") or "") else set()
                invalid_reasons.add("prompt_metrics_missing")
                invalid_reasons.add("prompt_mix_unverifiable")
                r["prompt_mix_checked"] = True
                r["prompt_mix_ok"] = False
                r["prompt_mix_source"] = "unverifiable"
                r["rep_valid"] = False
                r["invalid_reasons"] = ",".join(sorted({x for x in invalid_reasons if x}))
            else:
                r["prompt_mix_checked"] = False
                r["prompt_mix_ok"] = True
                r["prompt_mix_source"] = "unverifiable"
                if (attempts_cnt is not None and int(attempts_cnt) > 0) and (not prompt_tags_unavailable_warning_emitted):
                    warnings.append(
                        "prompt-tagged counters were not found; prompt-mix validation could not be performed from summary metrics"
                    )
                    prompt_tags_unavailable_warning_emitted = True
            continue

        r["prompt_mix_checked"] = True
        invalid_reasons: set[str] = set(str(r.get("invalid_reasons") or "").split(",")) if str(r.get("invalid_reasons") or "") else set()
        prompt_reasons: set[str] = set()

        if not has_ms:
            invalid_reasons.add("measure_seconds_missing")
        if has_ms and not has_attempts:
            # queue_saturation is already in invalid_reasons from rep_analysis
            # Only add no_measure_requests if not already classified as queue_saturation
            if "queue_saturation" not in invalid_reasons:
                invalid_reasons.add("no_measure_requests")

        total_tagged = sum(abp.values())
        if (attempts_cnt is not None and int(attempts_cnt) > 0) and total_tagged == 0:
            r["prompt_mix_ok"] = False
            r["prompt_mix_max_minus_min"] = None
            prompt_reasons.add("prompt_metrics_missing")
            prompt_reasons.add("prompt_mix_mismatch")
        else:
            prompt_counts = [int(abp.get(pid, 0)) for pid in expected_prompt_ids]
            # If we have at least one full round of prompts, expect all prompts to appear.
            if total_tagged >= len(expected_prompt_ids) and any(c == 0 for c in prompt_counts):
                prompt_reasons.add("prompt_mix_mismatch")
            # Balance: max-min <= 1, but if total attempts < N allow absent prompts.
            if total_tagged < len(expected_prompt_ids):
                nonzero = [c for c in prompt_counts if c > 0]
                considered = nonzero
            else:
                considered = prompt_counts
            if considered:
                diff = max(considered) - min(considered)
                r["prompt_mix_max_minus_min"] = int(diff)
                if diff > 1:
                    prompt_reasons.add("prompt_mix_mismatch")
            else:
                r["prompt_mix_max_minus_min"] = 0

            if attempts_cnt is not None and total_tagged != int(attempts_cnt):
                prompt_reasons.add("prompt_attempt_total_mismatch")
                prompt_reasons.add("prompt_mix_mismatch")

            r["prompt_mix_ok"] = not bool(prompt_reasons)

        if prompt_reasons:
            invalid_reasons |= prompt_reasons

        loadgen_valid = bool(r.get("loadgen_valid"))
        prompt_mix_ok = bool(r.get("prompt_mix_ok"))
        r["rep_valid"] = bool(measure_ok and loadgen_valid and prompt_mix_ok)
        r["prompt_mix_source"] = prompt_mix_source
        reasons_clean = sorted({x for x in invalid_reasons if x})
        r["invalid_reasons"] = ",".join(reasons_clean)
