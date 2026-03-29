#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate boundary report attachment matches current fingerprints")
    parser.add_argument("--boundary-report", required=True)
    parser.add_argument("--source-fingerprint", required=True)
    parser.add_argument("--workflow-snapshot", required=True)
    args = parser.parse_args()

    boundary = json.loads(Path(args.boundary_report).read_text(encoding="utf-8"))
    source_fp = json.loads(Path(args.source_fingerprint).read_text(encoding="utf-8"))
    wf = json.loads(Path(args.workflow_snapshot).read_text(encoding="utf-8"))

    if not boundary.get("pass"):
        print("boundary audit report pass=false")
        return 2

    # Thesis-grade gate: boundary report must include locked model/param evidence.
    locked = boundary.get("locked_params") or {}
    locked_chat = locked.get("chat") if isinstance(locked, dict) else None
    if not isinstance(locked_chat, dict):
        print("boundary audit report missing locked_params.chat (rerun boundary audit with updated tools)")
        return 2
    required_locked_fields = [
        ("locked_params.chat.model", locked_chat.get("model")),
        ("locked_params.chat.temperature", locked_chat.get("temperature")),
        ("locked_params.chat.top_p", locked_chat.get("top_p")),
        ("locked_params.chat.max_completion_tokens", locked_chat.get("max_completion_tokens")),
    ]
    missing_locked = [name for name, value in required_locked_fields if value is None]
    if missing_locked:
        print("boundary audit report missing locked param fields: " + ", ".join(missing_locked))
        return 2

    observed = boundary.get("observed_params") or {}
    if not isinstance(observed, dict):
        print("boundary audit report missing observed_params (rerun boundary audit with updated tools)")
        return 2

    def _dist_missing_zero(system: str, field: str) -> bool:
        sys_obj = observed.get(system) or {}
        chat = (sys_obj.get("chat_completions") or {}) if isinstance(sys_obj, dict) else {}
        dist = chat.get(field) if isinstance(chat, dict) else None
        if not isinstance(dist, dict):
            print(f"boundary audit report missing observed_params.{system}.chat_completions.{field}")
            return False
        missing = dist.get("missing")
        total = dist.get("total")
        if missing is None or total is None:
            print(f"boundary audit report missing observed_params.{system}.chat_completions.{field}.missing/total")
            return False
        try:
            missing_i = int(missing)
        except Exception:
            print(f"boundary audit report invalid missing count for {system}.{field}: {missing!r}")
            return False
        if missing_i != 0:
            print(
                f"boundary audit report has missing {field} evidence for system={system} "
                f"(missing={missing_i} of total={total}); rerun boundary audit with updated proxy"
            )
            return False
        return True

    if not _dist_missing_zero("rag", "temperature"):
        return 2
    if not _dist_missing_zero("rag", "top_p"):
        return 2
    if not _dist_missing_zero("rag", "token_limit"):
        return 2
    if not _dist_missing_zero("n8n", "temperature"):
        return 2
    if not _dist_missing_zero("n8n", "top_p"):
        return 2
    if not _dist_missing_zero("n8n", "token_limit"):
        return 2

    want_source = source_fp.get("fingerprint_sha256")
    want_wf = wf.get("workflow_content_sha256")

    artifacts = boundary.get("artifacts") or {}
    got_source = artifacts.get("source_fingerprint_sha256")
    got_wf = artifacts.get("n8n_workflow_content_sha256")

    missing = []
    if not got_source:
        missing.append("artifacts.source_fingerprint_sha256")
    if not got_wf:
        missing.append("artifacts.n8n_workflow_content_sha256")
    if missing:
        print("boundary audit report missing artifact hashes: " + ", ".join(missing))
        return 2

    if want_source and got_source != want_source:
        print(json.dumps({"mismatch": "source_fingerprint_sha256", "expected": want_source, "got": got_source}, indent=2))
        return 2
    if want_wf and got_wf != want_wf:
        print(json.dumps({"mismatch": "n8n_workflow_content_sha256", "expected": want_wf, "got": got_wf}, indent=2))
        return 2

    print(json.dumps({"match": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
