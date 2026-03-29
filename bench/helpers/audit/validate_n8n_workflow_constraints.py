#!/usr/bin/env python3
"""Validate thesis-grade constraints on an n8n workflow snapshot.

This is a static validator over the JSON snapshot exported from the n8n DB
(`n8n_workflow_runtime_snapshot.json`). It enforces:

- No forbidden references to the rag_service/rag-pipeline HTTP query endpoint.
- Locked chat model + sampling parameters on lmChatOpenAi nodes.

Embedding model lock is intentionally NOT enforced here (proxy audit enforces it).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


CHAT_NODE_TYPE = "@n8n/n8n-nodes-langchain.lmChatOpenAi"


def _json_path(parts: list[Any]) -> str:
    out = ""
    for p in parts:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            if not out:
                out = str(p)
            else:
                out += "." + str(p)
    return out or "$"


def _iter_strings(obj: Any, path: list[Any] | None = None) -> Iterable[tuple[list[Any], str]]:
    if path is None:
        path = []

    if isinstance(obj, str):
        yield (path, obj)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, path + [k])
        return
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, path + [i])
        return


def _as_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _as_int(x: Any) -> int | None:
    if x is None:
        return None
    try:
        # Accept numeric strings like "32768" or "32768.0".
        f = float(x)
        i = int(f)
        if abs(f - float(i)) > 1e-9:
            return None
        return i
    except Exception:
        return None


def _extract_chat_model_value(model_field: Any) -> str | None:
    if model_field is None:
        return None
    if isinstance(model_field, str):
        return model_field
    if isinstance(model_field, dict):
        v = model_field.get("value")
        if isinstance(v, str):
            return v
    return None


def _is_close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _forbidden_hits_for_string(s: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    low = s.lower()

    if "rag-pipeline" in low:
        hits.append({"pattern": "contains:rag-pipeline"})
    if ":8080/query" in low:
        hits.append({"pattern": "contains::8080/query"})

    # URL-specific rule: /query with host rag-pipeline
    try:
        p = urlparse(s)
        host = (p.hostname or "").lower()
        path = (p.path or "").lower()
        if host == "rag-pipeline" and "/query" in path:
            hits.append({"pattern": "url:host=rag-pipeline path_contains=/query"})
    except Exception:
        pass

    return hits


def _truncate(s: str, limit: int = 400) -> tuple[str, bool]:
    if len(s) <= limit:
        return s, False
    return s[:limit] + "...", True


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate n8n workflow constraints")
    parser.add_argument("--workflow-snapshot", required=True)
    parser.add_argument("--expected-chat-model", required=True)
    parser.add_argument("--expected-temperature", required=True, type=float)
    parser.add_argument("--expected-top-p", required=True, type=float)
    parser.add_argument("--expected-max-tokens", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    failures: list[str] = []
    notes: list[str] = []
    forbidden_hits: list[dict[str, Any]] = []
    checked_nodes_count = 0

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    snap_path = Path(args.workflow_snapshot)
    if not snap_path.exists() or snap_path.stat().st_size == 0:
        failures.append(f"missing_or_empty: {snap_path}")
        report = {
            "pass": False,
            "failures": failures,
            "notes": notes,
            "checked_nodes_count": checked_nodes_count,
            "forbidden_hits": forbidden_hits,
        }
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return 2

    try:
        root = _load_json(snap_path)
    except Exception as e:
        failures.append(f"invalid_json: {snap_path} ({type(e).__name__})")
        report = {
            "pass": False,
            "failures": failures,
            "notes": notes,
            "checked_nodes_count": checked_nodes_count,
            "forbidden_hits": forbidden_hits,
        }
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return 2

    workflow = None
    if isinstance(root, dict) and isinstance(root.get("workflow"), dict):
        workflow = root.get("workflow")
        notes.append("input looks like n8n_workflow_snapshot.py output (root.workflow)")
    elif isinstance(root, dict) and isinstance(root.get("nodes"), list):
        workflow = root
        notes.append("input looks like an n8n workflow export (root.nodes)")
    else:
        failures.append("could_not_locate_workflow_nodes (expected root.workflow.nodes or root.nodes)")
        workflow = {}

    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    if not isinstance(nodes, list):
        failures.append("workflow.nodes is not a list")
        nodes = []

    # Forbidden endpoint references: scan all strings in each node.
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_ctx = {
            "node_index": idx,
            "node_id": node.get("id"),
            "node_name": node.get("name"),
            "node_type": node.get("type"),
        }
        for pth, s in _iter_strings(node, ["nodes", idx]):
            hits = _forbidden_hits_for_string(s)
            if not hits:
                continue
            preview, truncated = _truncate(s)
            for h in hits:
                forbidden_hits.append(
                    {
                        **node_ctx,
                        "json_path": _json_path(pth),
                        "value": preview,
                        "value_len": len(s),
                        "value_truncated": truncated,
                        **h,
                    }
                )

    # Also scan non-node workflow fields (settings/meta/etc.).
    if isinstance(workflow, dict):
        wf_shallow = dict(workflow)
        wf_shallow.pop("nodes", None)
        for pth, s in _iter_strings(wf_shallow, ["workflow"]):
            hits = _forbidden_hits_for_string(s)
            if not hits:
                continue
            preview, truncated = _truncate(s)
            for h in hits:
                forbidden_hits.append(
                    {
                        "node_index": None,
                        "node_id": None,
                        "node_name": None,
                        "node_type": None,
                        "json_path": _json_path(pth),
                        "value": preview,
                        "value_len": len(s),
                        "value_truncated": truncated,
                        **h,
                    }
                )

    if forbidden_hits:
        failures.append(f"forbidden_endpoint_reference_hits: {len(forbidden_hits)}")

    # Locked chat model + sampling params.
    chat_nodes = [n for n in nodes if isinstance(n, dict) and str(n.get("type") or "") == CHAT_NODE_TYPE]
    if not chat_nodes:
        failures.append(f"no_chat_nodes_found: type={CHAT_NODE_TYPE}")
    for node in chat_nodes:
        checked_nodes_count += 1
        name = str(node.get("name") or node.get("id") or "<unknown>")
        params = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        model_val = _extract_chat_model_value(params.get("model") if isinstance(params, dict) else None)
        if model_val != args.expected_chat_model:
            failures.append(
                "chat_model_mismatch: "
                + json.dumps(
                    {"node": name, "expected": args.expected_chat_model, "observed": model_val},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )

        options_obj = params.get("options") if isinstance(params, dict) else None
        options: dict[str, Any] = options_obj if isinstance(options_obj, dict) else {}
        obs_temp = _as_float(options.get("temperature"))
        obs_top_p = _as_float(options.get("topP"))
        obs_max_tok = _as_int(options.get("maxTokens"))

        if obs_temp is None or not _is_close(obs_temp, float(args.expected_temperature)):
            failures.append(
                "chat_temperature_mismatch: "
                + json.dumps(
                    {"node": name, "expected": float(args.expected_temperature), "observed": obs_temp},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        if obs_top_p is None or not _is_close(obs_top_p, float(args.expected_top_p)):
            failures.append(
                "chat_top_p_mismatch: "
                + json.dumps(
                    {"node": name, "expected": float(args.expected_top_p), "observed": obs_top_p},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        if obs_max_tok is None or int(obs_max_tok) != int(args.expected_max_tokens):
            failures.append(
                "chat_max_tokens_mismatch: "
                + json.dumps(
                    {"node": name, "expected": int(args.expected_max_tokens), "observed": obs_max_tok},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )

    report = {
        "pass": len(failures) == 0,
        "failures": failures,
        "notes": notes,
        "checked_nodes_count": checked_nodes_count,
        "forbidden_hits": forbidden_hits,
    }
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
