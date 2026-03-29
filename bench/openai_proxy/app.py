import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


CLIENT_ID = os.getenv("PROXY_CLIENT_ID", "unknown")
RUN_ID = os.getenv("PROXY_RUN_ID", "")
LOG_FILE = os.getenv("PROXY_LOG_FILE", "")


def _normalize_upstream_base(raw: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if not value:
        raise RuntimeError("UPSTREAM_OPENAI_BASE_URL is empty")
    if value.endswith("/v1"):
        value = value[:-3]
    if not (value.startswith("http://") or value.startswith("https://")):
        raise RuntimeError(
            "UPSTREAM_OPENAI_BASE_URL must start with http:// or https:// "
            f"(got: {raw!r})"
        )
    return value


UPSTREAM_BASE = _normalize_upstream_base(
    os.getenv("UPSTREAM_OPENAI_BASE_URL", "https://api.openai.com")
)

# Default timeout should be >= benchmark timeout.
TIMEOUT_S = float(os.getenv("PROXY_TIMEOUT_SECONDS", "180"))

app = FastAPI()
_lock = asyncio.Lock()


def _safe_headers(request: Request) -> dict[str, str]:
    # Forward client headers except hop-by-hop / auto-managed.
    out: dict[str, str] = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "content-length", "connection"):
            continue
        out[k] = v
    # Ensure Authorization is present if configured via env.
    if "authorization" not in {k.lower() for k in out.keys()}:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("UPSTREAM_OPENAI_API_KEY")
        if api_key:
            out["Authorization"] = f"Bearer {api_key}"
    return out


def _sha256_text(value: str | bytes) -> str:
    if isinstance(value, str):
        data = value.encode("utf-8", errors="ignore")
    else:
        data = value
    return hashlib.sha256(data).hexdigest()


def _extract_semantic_hash(req_json: Any, subpath: str) -> str | None:
    if not isinstance(req_json, dict):
        return None
    try:
        if subpath == "/v1/chat/completions":
            messages = req_json.get("messages")
            if isinstance(messages, list):
                for msg in reversed(messages):
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        content = msg.get("content")
                        if isinstance(content, str) and content.strip():
                            return _sha256_text(content)
            return None
        if subpath == "/v1/embeddings":
            inp = req_json.get("input")
            if isinstance(inp, str):
                return _sha256_text(inp)
            if isinstance(inp, list) and inp:
                first = inp[0]
                if isinstance(first, str):
                    return _sha256_text(first)
            return None
    except Exception:
        return None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _extract_chat_sampling_params(req_json: Any) -> dict[str, Any]:
    """Extract sampling params for /v1/chat/completions.

    Intentionally tolerant to upstream/client field aliases so audit scripts can
    lock model+sampling params based on proxy logs.
    """

    if not isinstance(req_json, dict):
        return {
            "temperature": None,
            "top_p": None,
            "token_limit": None,
            "token_limit_field": None,
        }

    temperature = _coerce_float(req_json.get("temperature"))

    # Accept both snake_case and common camelCase variants.
    top_p = req_json.get("top_p")
    if top_p is None and "topP" in req_json:
        top_p = req_json.get("topP")
    top_p = _coerce_float(top_p)

    token_limit_field = None
    token_limit = None
    for key in ("max_completion_tokens", "max_output_tokens", "max_tokens"):
        if key in req_json and req_json.get(key) is not None:
            token_limit_field = key
            token_limit = _coerce_int(req_json.get(key))
            break

    return {
        "temperature": temperature,
        "top_p": top_p,
        "token_limit": token_limit,
        "token_limit_field": token_limit_field,
    }


async def _append_log(entry: dict[str, Any]) -> None:
    line = json.dumps(entry, ensure_ascii=True)
    if not LOG_FILE:
        print(line, flush=True)
        return
    async with _lock:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


async def _proxy_post(request: Request, subpath: str) -> Response:
    start = time.monotonic()
    body_bytes = await request.body()
    req_json = None
    model = None
    semantic_hash = None
    sampling_params: dict[str, Any] | None = None
    benchmark_request_id = request.headers.get("x-benchmark-request-id")
    try:
        req_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else None
        if isinstance(req_json, dict):
            model = req_json.get("model")
            semantic_hash = _extract_semantic_hash(req_json, subpath)
            if subpath == "/v1/chat/completions":
                sampling_params = _extract_chat_sampling_params(req_json)
    except Exception:
        req_json = None

    url = f"{UPSTREAM_BASE}{subpath}"
    headers = _safe_headers(request)
    status_code = 0
    resp_body = b""
    upstream_request_id = None
    usage = None
    error_type = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
            resp = await client.post(url, content=body_bytes, headers=headers)
        status_code = int(resp.status_code)
        upstream_request_id = resp.headers.get("x-request-id")
        resp_body = resp.content or b""
        try:
            resp_json = resp.json()
            if isinstance(resp_json, dict):
                usage = resp_json.get("usage")
        except Exception:
            usage = None
        # Prepare response headers including token usage for k6 correlation analysis
        response_headers = {}
        content_type = resp.headers.get("content-type")
        if content_type:
            response_headers["content-type"] = content_type
        # Add X-Token-* headers from usage data (for n8n/k6 correlation)
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            if prompt_tokens is not None:
                response_headers["X-Token-Prompt"] = str(prompt_tokens)
            if completion_tokens is not None:
                response_headers["X-Token-Completion"] = str(completion_tokens)
            if total_tokens is not None:
                response_headers["X-Token-Total"] = str(total_tokens)
        return Response(content=resp_body, status_code=status_code, headers=response_headers)
    except Exception as exc:
        error_type = type(exc).__name__
        # Return OpenAI-style error envelope (minimal)
        status_code = 502
        payload = {
            "error": {
                "message": f"proxy upstream error: {error_type}",
                "type": "proxy_error",
            }
        }
        resp_body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        return Response(content=resp_body, status_code=status_code, media_type="application/json")
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        await _append_log(
            {
                "timestamp_utc": utc_now_iso(),
                "run_id": RUN_ID or None,
                "client_id": CLIENT_ID,
                "method": "POST",
                "path": subpath,
                "model": model,
                # Sampling param evidence for boundary audit locking.
                "temperature": (sampling_params or {}).get("temperature"),
                "top_p": (sampling_params or {}).get("top_p"),
                "token_limit": (sampling_params or {}).get("token_limit"),
                "token_limit_field": (sampling_params or {}).get("token_limit_field"),
                "status": status_code,
                "duration_ms": duration_ms,
                "upstream_request_id": upstream_request_id,
                "request_bytes": len(body_bytes or b""),
                "response_bytes": len(resp_body or b""),
                "usage": usage,
                "error_type": error_type,
                "benchmark_request_id": benchmark_request_id,
                "semantic_hash": semantic_hash,
            }
        )


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "client_id": CLIENT_ID, "run_id": RUN_ID}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _proxy_post(request, "/v1/chat/completions")


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    return await _proxy_post(request, "/v1/embeddings")
