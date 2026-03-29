#!/usr/bin/env python3
"""Send a small, sequential request set to both endpoints for boundary auditing.

This is NOT a performance benchmark. It exists to verify the LLM-boundary
workload: models, call counts, and token usage (via proxy logs).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_prompts(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("prompts JSON must be a list")
    out = []
    for item in data:
        if isinstance(item, str):
            out.append({"id": None, "text": item})
        elif isinstance(item, dict):
            out.append({"id": item.get("id"), "text": item.get("text")})
    return [p for p in out if isinstance(p.get("text"), str) and p["text"].strip()]


def extract_n8n_answer(body: str) -> str:
    if not body:
        return ""

    def _from_obj(obj: Any) -> str:
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            for k in ("answer", "output", "text", "response", "result"):
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    return v
            # Common n8n item envelope: {"json": {...}}
            j = obj.get("json")
            if isinstance(j, dict):
                for k in ("answer", "output", "text", "response", "result"):
                    v = j.get(k)
                    if isinstance(v, str) and v.strip():
                        return v
            return ""
        return ""

    try:
        obj = json.loads(body)
    except Exception:
        return body
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        for item in obj:
            out = _from_obj(item)
            if out.strip():
                return out
        return ""
    if isinstance(obj, dict):
        return _from_obj(obj)
    return ""


SOURCE_RE = re.compile(r"\[source:\s*([^\]]+?)\]", re.IGNORECASE)


def parse_citations(answer: str) -> list[str]:
    if not answer:
        return []
    out = []
    seen = set()
    for match in SOURCE_RE.findall(answer):
        value = str(match or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def preview_text(value: str, limit: int = 800) -> tuple[str, bool]:
    s = value or ""
    if len(s) <= limit:
        return s, False
    return s[:limit] + "...", True


def main() -> int:
    parser = argparse.ArgumentParser(description="Boundary audit request runner (sequential)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prompts", default=os.getenv("K6_PROMPTS_PATH") or "/bench/prompts.json")
    parser.add_argument("--prompt-count", type=int, default=int(os.getenv("BOUNDARY_AUDIT_PROMPT_COUNT", "15")))
    parser.add_argument("--rag-url", default=os.getenv("RAG_ENDPOINT_URL") or "http://rag-pipeline:8080/query")
    parser.add_argument("--n8n-url", default=os.getenv("N8N_WEBHOOK_URL") or "http://n8n:5678/webhook/rag-query")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("BOUNDARY_AUDIT_HTTP_TIMEOUT", "120")))
    parser.add_argument("--rag-api-token", default=os.getenv("RAG_API_TOKEN") or os.getenv("API_TOKEN") or "")
    parser.add_argument("--n8n-auth-header", default=os.getenv("N8N_AUTH_HEADER") or "")
    parser.add_argument("--n8n-auth-value", default=os.getenv("N8N_AUTH_VALUE") or "")
    parser.add_argument("--sleep-ms", type=int, default=int(os.getenv("BOUNDARY_AUDIT_SLEEP_MS", "200")))
    parser.add_argument("--output", required=True, help="Write JSONL request results")
    args = parser.parse_args()

    prompts = load_prompts(args.prompts)
    prompts = prompts[: max(0, int(args.prompt_count))]
    if not prompts:
        raise SystemExit("No prompts loaded")

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        for idx, prompt in enumerate(prompts, start=1):
            prompt_id = prompt.get("id")
            text = prompt.get("text")
            if not isinstance(text, str):
                continue
            prompt_hash = sha256_text(text)

            # --- rag_service ---
            req_id = f"boundary-rag-{args.run_id}-{idx}"
            rag_payload = {
                "chatInput": text,
                "sessionId": req_id,
                "prompt_id": prompt_id,
                "request_id": req_id,
                "request_meta": {
                    "run_id": args.run_id,
                    "prompt_index": idx - 1,
                    "prompt_id": prompt_id,
                },
            }
            t0 = time.monotonic()
            rag_status = None
            rag_answer = ""
            rag_ok = False
            rag_headers = {"Content-Type": "application/json", "X-Benchmark-Request-ID": req_id}
            if args.rag_api_token:
                rag_headers["Authorization"] = f"Bearer {args.rag_api_token}"
            try:
                res = requests.post(args.rag_url, json=rag_payload, headers=rag_headers, timeout=args.timeout)
                rag_status = res.status_code
                if res.headers.get("content-type", "").startswith("application/json"):
                    obj = res.json()
                    if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
                        rag_answer = obj.get("answer") or ""
                        rag_ok = bool(rag_answer.strip()) and (rag_status == 200)
                else:
                    rag_answer = res.text or ""
            except Exception:
                rag_status = None
            rag_ms = int((time.monotonic() - t0) * 1000)
            rag_citations = parse_citations(rag_answer)
            f.write(
                json.dumps(
                    {
                        "timestamp_utc": utc_now_iso(),
                        "run_id": args.run_id,
                        "system": "rag",
                        "request_id": req_id,
                        "prompt_index": idx - 1,
                        "prompt_id": prompt_id,
                        "prompt_sha256": prompt_hash,
                        "status": rag_status,
                        "latency_ms": rag_ms,
                        "ok": rag_ok,
                        "answer_chars": len((rag_answer or "")),
                        "answer_sha256": sha256_text(rag_answer or ""),
                        "citations": rag_citations,
                        "citation_count": len(rag_citations),
                        "auth_mode": "bearer" if args.rag_api_token else "none",
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )
            f.flush()

            time.sleep(max(args.sleep_ms, 0) / 1000.0)

            # --- n8n ---
            req_id = f"boundary-n8n-{args.run_id}-{idx}"
            n8n_payload = {
                "chatInput": text,
                "sessionId": req_id,
                "prompt_id": prompt_id,
                "request_meta": {
                    "run_id": args.run_id,
                    "prompt_index": idx - 1,
                    "prompt_id": prompt_id,
                    "request_id": req_id,
                },
            }
            t0 = time.monotonic()
            n8n_status = None
            n8n_answer = ""
            n8n_ok = False
            raw_body = ""
            res = None
            n8n_headers = {"Content-Type": "application/json", "X-Benchmark-Request-ID": req_id}
            if args.n8n_auth_header and args.n8n_auth_value:
                n8n_headers[args.n8n_auth_header] = args.n8n_auth_value
            try:
                res = requests.post(args.n8n_url, json=n8n_payload, headers=n8n_headers, timeout=args.timeout)
                n8n_status = res.status_code
                raw_body = res.text or ""
                n8n_answer = extract_n8n_answer(raw_body)
                n8n_ok = bool((n8n_answer or "").strip()) and (n8n_status == 200)
            except Exception:
                n8n_status = None
                raw_body = ""
            n8n_ms = int((time.monotonic() - t0) * 1000)
            n8n_citations = parse_citations(n8n_answer)
            body_preview, body_truncated = preview_text(raw_body)
            f.write(
                json.dumps(
                    {
                        "timestamp_utc": utc_now_iso(),
                        "run_id": args.run_id,
                        "system": "n8n",
                        "request_id": req_id,
                        "prompt_index": idx - 1,
                        "prompt_id": prompt_id,
                        "prompt_sha256": prompt_hash,
                        "status": n8n_status,
                        "latency_ms": n8n_ms,
                        "ok": n8n_ok,
                        "answer_chars": len((n8n_answer or "")),
                        "answer_sha256": sha256_text(n8n_answer or ""),
                        "response_content_type": (res.headers.get("content-type") if res is not None else None),
                        "response_chars": len(raw_body),
                        "response_preview": body_preview,
                        "response_preview_truncated": body_truncated,
                        "citations": n8n_citations,
                        "citation_count": len(n8n_citations),
                        "auth_mode": "custom_header" if args.n8n_auth_header and args.n8n_auth_value else "none",
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )
            f.flush()

            time.sleep(max(args.sleep_ms, 0) / 1000.0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
