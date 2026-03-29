#!/usr/bin/env python3
"""Build a boundary audit report from OpenAI proxy logs + request outcomes."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def sum_usage(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for r in rows:
        usage = r.get("usage")
        if not isinstance(usage, dict):
            continue
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                v = usage.get(k)
                if v is None:
                    continue
                totals[k] += int(v)
            except Exception:
                continue
    return totals


def summarize_proxy(rows: list[dict[str, Any]], run_id: str | None) -> dict[str, Any]:
    if run_id:
        rows = [r for r in rows if r.get("run_id") == run_id]
    by_path = Counter([r.get("path") for r in rows if isinstance(r.get("path"), str)])
    by_model = Counter([r.get("model") for r in rows if isinstance(r.get("model"), str)])
    statuses = Counter([str(r.get("status")) for r in rows if r.get("status") is not None])
    return {
        "total_calls": len(rows),
        "calls_by_path": dict(by_path),
        "calls_by_model": dict(by_model),
        "status_counts": dict(statuses),
        "usage_totals": sum_usage(rows),
    }


def count_user_requests(request_rows: list[dict[str, Any]], system: str, run_id: str | None) -> dict[str, Any]:
    rows = [r for r in request_rows if r.get("system") == system]
    if run_id:
        rows = [r for r in rows if r.get("run_id") == run_id]
    total = len(rows)
    ok = sum(1 for r in rows if r.get("ok") is True)
    return {"total": total, "ok": ok, "rows": rows}


def _safe_div(num: float, den: float) -> float | None:
    if den == 0:
        return None
    return num / den


def _norm_decimal_str(value: Any) -> str | None:
    """Normalize numeric-ish values into stable strings.

    Proxy logs can contain ints/floats/strings; audits need stable equality.
    """

    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _param_distribution(
    rows: list[dict[str, Any]],
    field: str,
    *,
    coerce: str,
) -> dict[str, Any]:
    total = len(rows)
    missing = 0
    invalid = 0
    counts: Counter[str] = Counter()
    for r in rows:
        v = r.get(field)
        if v is None:
            missing += 1
            continue
        if coerce == "str":
            key = str(v)
            if not key:
                invalid += 1
                continue
        elif coerce == "int":
            try:
                vv = int(v)
            except Exception:
                invalid += 1
                continue
            key = str(vv)
        else:
            key = _norm_decimal_str(v)
            if key is None:
                invalid += 1
                continue
        counts[key] += 1

    def _sort_key(x: str):
        try:
            return (0, Decimal(x))
        except Exception:
            return (1, x)

    values = sorted(counts.keys(), key=_sort_key)
    return {
        "field": field,
        "total": total,
        "missing": missing,
        "invalid": invalid,
        "distinct": len(values),
        "values": values,
        "counts_by_value": dict(counts),
    }


def _filter_proxy_rows(rows: list[dict[str, Any]], run_id: str | None) -> list[dict[str, Any]]:
    if not run_id:
        return list(rows)
    return [r for r in rows if r.get("run_id") == run_id]


def _proxy_chat_rows(rows: list[dict[str, Any]], run_id: str | None) -> list[dict[str, Any]]:
    rows = _filter_proxy_rows(rows, run_id)
    return [r for r in rows if r.get("path") == "/v1/chat/completions"]


def _sampling_evidence(
    proxy_rows: list[dict[str, Any]],
    run_id: str | None,
) -> dict[str, Any]:
    chat_rows = _proxy_chat_rows(proxy_rows, run_id)
    return {
        "chat_completions": {
            "calls": len(chat_rows),
            "temperature": _param_distribution(chat_rows, "temperature", coerce="float"),
            "top_p": _param_distribution(chat_rows, "top_p", coerce="float"),
            "token_limit": _param_distribution(chat_rows, "token_limit", coerce="int"),
            "token_limit_field": _param_distribution(chat_rows, "token_limit_field", coerce="str"),
        }
    }


def _proxy_request_status_stats(summary: dict[str, Any]) -> dict[str, Any]:
    status_counts = summary.get("status_counts") or {}
    total = 0
    ok = 0
    for k, v in status_counts.items():
        try:
            code = int(k)
            count = int(v)
        except Exception:
            continue
        total += count
        if 200 <= code < 300:
            ok += count
    return {
        "total": total,
        "ok_2xx": ok,
        "ok_rate": _safe_div(ok, total),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a boundary audit report")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--proxy-rag", required=True)
    parser.add_argument("--proxy-n8n", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--source-fingerprint", default=None, help="Optional source_fingerprint.json path")
    parser.add_argument("--workflow-snapshot", default=None, help="Optional n8n_workflow_runtime_snapshot.json path")
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-chat-model", default="gpt-5-nano")
    parser.add_argument("--expected-embedding-model", default="text-embedding-3-small")

    # Locked sampling params for validity runs.
    parser.add_argument("--expected-temperature", type=float, default=None)
    parser.add_argument("--expected-top-p", type=float, default=None)
    parser.add_argument("--expected-max-completion-tokens", type=int, default=None)
    parser.add_argument("--require-param-evidence", action="store_true")

    parser.add_argument("--require-all-user-requests-ok", action="store_true")
    parser.add_argument("--min-proxy-ok-rate", type=float, default=0.99)
    args = parser.parse_args()

    proxy_rag = read_jsonl(Path(args.proxy_rag))
    proxy_n8n = read_jsonl(Path(args.proxy_n8n))
    reqs = read_jsonl(Path(args.requests))

    rag_user = count_user_requests(reqs, "rag", args.run_id)
    n8n_user = count_user_requests(reqs, "n8n", args.run_id)

    rag_sum = summarize_proxy(proxy_rag, args.run_id)
    n8n_sum = summarize_proxy(proxy_n8n, args.run_id)

    rag_proxy_status = _proxy_request_status_stats(rag_sum)
    n8n_proxy_status = _proxy_request_status_stats(n8n_sum)

    failures: list[str] = []

    def require(cond: bool, msg: str):
        if not cond:
            failures.append(msg)

    # Must have proxy evidence for both systems.
    require(rag_sum["total_calls"] > 0, "rag proxy log is empty for run_id")
    require(n8n_sum["total_calls"] > 0, "n8n proxy log is empty for run_id (n8n may not respect base-url env)")

    # Both systems should process the same number of user requests in audit.
    require(rag_user["total"] > 0, "rag: zero user requests")
    require(n8n_user["total"] > 0, "n8n: zero user requests")
    require(
        rag_user["total"] == n8n_user["total"],
        f"user request count mismatch rag={rag_user['total']} n8n={n8n_user['total']}",
    )

    # Must see both endpoint types.
    require(rag_sum["calls_by_path"].get("/v1/embeddings", 0) > 0, "rag: no /v1/embeddings calls observed")
    require(rag_sum["calls_by_path"].get("/v1/chat/completions", 0) > 0, "rag: no /v1/chat/completions calls observed")
    require(n8n_sum["calls_by_path"].get("/v1/embeddings", 0) > 0, "n8n: no /v1/embeddings calls observed")
    require(n8n_sum["calls_by_path"].get("/v1/chat/completions", 0) > 0, "n8n: no /v1/chat/completions calls observed")

    # Model expectations (proxy captures the model in the request JSON).
    require(args.expected_chat_model in rag_sum["calls_by_model"], f"rag: expected chat model not observed: {args.expected_chat_model}")
    require(args.expected_chat_model in n8n_sum["calls_by_model"], f"n8n: expected chat model not observed: {args.expected_chat_model}")
    require(args.expected_embedding_model in rag_sum["calls_by_model"], f"rag: expected embedding model not observed: {args.expected_embedding_model}")
    require(args.expected_embedding_model in n8n_sum["calls_by_model"], f"n8n: expected embedding model not observed: {args.expected_embedding_model}")

    rag_sampling = _sampling_evidence(proxy_rag, args.run_id)
    n8n_sampling = _sampling_evidence(proxy_n8n, args.run_id)

    # Sampling param locks (validity mode).
    def _require_locked_param(
        system: str,
        dist: dict[str, Any],
        expected: Any,
        label: str,
    ):
        values = list(dist.get("values") or [])
        missing = int(dist.get("missing") or 0)
        total = int(dist.get("total") or 0)

        if args.require_param_evidence and expected is None:
            require(False, f"{system}: expected {label} not provided but --require-param-evidence is set")
            return

        if args.require_param_evidence:
            require(
                total > 0,
                f"{system}: no chat/completions calls found to verify {label}",
            )
            require(
                missing == 0,
                f"{system}: missing {label} evidence in proxy logs ({missing}/{total})",
            )

        # Consistency among observed values (even if evidence is partial).
        require(len(values) <= 1, f"{system}: inconsistent {label} observed: {values}")

        # Expected match when we have an expectation and at least one observed value.
        if expected is not None and values:
            exp_key = _norm_decimal_str(expected)
            require(
                values[0] == exp_key,
                f"{system}: {label} mismatch expected={exp_key} observed={values[0]}",
            )

        # In strict mode, we also require an observed value (not just 'no missing').
        if args.require_param_evidence and expected is not None:
            require(
                bool(values),
                f"{system}: no {label} observations found in proxy logs",
            )

    rag_chat = (rag_sampling.get("chat_completions") or {})
    n8n_chat = (n8n_sampling.get("chat_completions") or {})
    _require_locked_param("rag", rag_chat.get("temperature") or {}, args.expected_temperature, "temperature")
    _require_locked_param("rag", rag_chat.get("top_p") or {}, args.expected_top_p, "top_p")
    _require_locked_param(
        "rag",
        rag_chat.get("token_limit") or {},
        args.expected_max_completion_tokens,
        "token_limit",
    )
    _require_locked_param("n8n", n8n_chat.get("temperature") or {}, args.expected_temperature, "temperature")
    _require_locked_param("n8n", n8n_chat.get("top_p") or {}, args.expected_top_p, "top_p")
    _require_locked_param(
        "n8n",
        n8n_chat.get("token_limit") or {},
        args.expected_max_completion_tokens,
        "token_limit",
    )

    # Basic user-level success.
    require(rag_user["ok"] > 0, "rag: zero successful user requests")
    require(n8n_user["ok"] > 0, "n8n: zero successful user requests")
    if args.require_all_user_requests_ok:
        require(
            rag_user["ok"] == rag_user["total"],
            f"rag: not all user requests succeeded ({rag_user['ok']}/{rag_user['total']})",
        )
        require(
            n8n_user["ok"] == n8n_user["total"],
            f"n8n: not all user requests succeeded ({n8n_user['ok']}/{n8n_user['total']})",
        )

    require(
        (rag_proxy_status["ok_rate"] or 0.0) >= args.min_proxy_ok_rate,
        f"rag: proxy upstream 2xx rate below threshold ({rag_proxy_status['ok_rate']})",
    )
    require(
        (n8n_proxy_status["ok_rate"] or 0.0) >= args.min_proxy_ok_rate,
        f"n8n: proxy upstream 2xx rate below threshold ({n8n_proxy_status['ok_rate']})",
    )

    report = {
        "generated_at": utc_now_iso(),
        "run_id": args.run_id,
        "artifacts": {},
        "expected": {
            "chat_model": args.expected_chat_model,
            "embedding_model": args.expected_embedding_model,
        },
        "locked_params": {
            "chat": {
                "model": args.expected_chat_model,
                "temperature": args.expected_temperature,
                "top_p": args.expected_top_p,
                "max_completion_tokens": args.expected_max_completion_tokens,
            },
            "embeddings": {"model": args.expected_embedding_model},
        },
        "observed_params": {
            "rag": rag_sampling,
            "n8n": n8n_sampling,
        },
        "user_requests": {
            "rag": {"total": rag_user["total"], "ok": rag_user["ok"]},
            "n8n": {"total": n8n_user["total"], "ok": n8n_user["ok"]},
        },
        "proxy_summary": {
            "rag": rag_sum,
            "n8n": n8n_sum,
        },
        "proxy_status": {
            "rag": rag_proxy_status,
            "n8n": n8n_proxy_status,
        },
        "pass": len(failures) == 0,
        "failures": failures,
        "notes": [
            "This report verifies the LLM boundary based on proxy logs + request outcomes.",
            "Verifies both systems use the same models and sampling parameters.",
            "It is not a performance benchmark and should not be mixed into latency results.",
        ],
    }

    # Attach reproducibility anchors when available.
    def _maybe_attach_json_field(path_str: str | None, field: str, out_key: str):
        if not path_str:
            return
        p = Path(path_str)
        if not p.exists():
            return
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(obj, dict) and field in obj:
            report["artifacts"][out_key] = obj.get(field)

    _maybe_attach_json_field(args.source_fingerprint, "fingerprint_sha256", "source_fingerprint_sha256")
    _maybe_attach_json_field(args.workflow_snapshot, "workflow_content_sha256", "n8n_workflow_content_sha256")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
