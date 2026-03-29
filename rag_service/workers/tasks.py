import asyncio
from datetime import datetime, timezone
import logging
import re
import time
import uuid

from pydantic import ValidationError

from rag_service.config import Settings
from rag_service.db import (
    create_pool,
    get_or_create_subprocess_pool_sync,
    run_on_subprocess_loop_sync,
)
from rag_service.ingest import ingest_document
from rag_service.delete import delete_document
from rag_service.models import IngestRequest, DeleteRequest, QueryRequest
from rag_service.query import run_query, write_timing_log

settings = Settings()
_pool = None


async def _pool_cached():
    global _pool
    if _pool is None:
        # Explicitly use worker pool sizing - runs in RQ worker context
        _pool = await create_pool(settings, is_worker=True)
    return _pool


_ALLOWED_ERROR_TYPES = {
    "TooManyConnectionsError",
    "PoolAcquireTimeoutError",
    "PostgresConnectionError",
    "ConnectionDoesNotExistError",
    "CannotConnectNowError",
    "TimeoutError",
    "ValidationError",
    "RateLimitError",
    "CircuitBreakerOpenError",
}
_ERROR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")


def _sanitize_error_name(name: str | None) -> str:
    if not name:
        return "QueryExecutionError"
    cleaned = str(name).strip()
    if not _ERROR_NAME_RE.fullmatch(cleaned):
        return "QueryExecutionError"
    return cleaned


def _sanitize_error_message(message: object, max_len: int = 512) -> str:
    text = str(message or "").replace("\x00", "").strip()
    if not text:
        return "subprocess query failed"
    return text[:max_len]


def _exception_chain(exc: BaseException, max_depth: int = 8) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    for _ in range(max_depth):
        if current is None or current in chain:
            break
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _canonical_error_type(exc: BaseException) -> str:
    chain = _exception_chain(exc)
    names = [type(item).__name__ for item in chain]
    for name in names:
        if name in _ALLOWED_ERROR_TYPES:
            return name
    if names:
        return _sanitize_error_name(names[-1])
    return "QueryExecutionError"


def _serialize_subprocess_error(exc: BaseException, request_id: str) -> dict:
    chain = _exception_chain(exc)
    root = chain[-1] if chain else exc
    return {
        "_error": True,
        "_error_type": _canonical_error_type(exc),
        "_error_message": _sanitize_error_message(root),
        "_error_chain": [_sanitize_error_name(type(item).__name__) for item in chain],
        "request_id": request_id,
    }


async def _ingest(payload: dict):
    pool = await _pool_cached()
    req = IngestRequest(**payload)
    await ingest_document(req, settings, pool)


async def _delete(payload: dict):
    pool = await _pool_cached()
    req = DeleteRequest(**payload)
    await delete_document(req.file_id, settings, pool)


def _parse_enqueued_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except Exception:
        return None


async def _query(payload: dict):
    pool = await _pool_cached()
    start_ts = time.monotonic()
    enqueued_at = _parse_enqueued_at(payload.get("enqueued_at"))
    queue_wait_ms = None
    if enqueued_at:
        queue_wait_ms = int((datetime.now(timezone.utc) - enqueued_at).total_seconds() * 1000)
    request_id = payload.get("request_id") or str(uuid.uuid4())
    logging.getLogger(__name__).info(
        "query start request_id=%s queue_wait_ms=%s",
        request_id,
        queue_wait_ms,
    )
    try:
        req = QueryRequest(**payload)
    except ValidationError as exc:
        mode = "full"
        if settings.retrieval_only:
            mode = "retrieval_only"
        elif settings.llm_stub:
            mode = "stub"
        entry = {
            "request_id": request_id,
            "endpoint": "rag",
            "mode": mode,
            "status": "error",
            "error_type": "ValidationError",
            "prompt_id": payload.get("prompt_id"),
            "session_id": payload.get("sessionId"),
            "request_meta": payload.get("request_meta"),
            "queue_wait_ms": queue_wait_ms,
            "retrieval_ms": None,
            "llm_ms": None,
            "post_ms": None,
            "total_ms": int((time.monotonic() - start_ts) * 1000),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_timing_log(settings, entry)
        logging.getLogger(__name__).error("query validation error request_id=%s error=%s", request_id, exc)
        raise
    req.request_id = request_id
    req.queue_wait_ms = queue_wait_ms
    try:
        result = await run_query(req, settings, pool)
    except Exception as exc:
        logging.getLogger(__name__).error("query error request_id=%s error_type=%s", request_id, type(exc).__name__)
        raise
    duration_ms = int((time.monotonic() - start_ts) * 1000)
    logging.getLogger(__name__).info(
        "query done request_id=%s duration_ms=%s",
        request_id,
        duration_ms,
    )
    return result.model_dump()


def ingest_job(payload: dict):
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_ingest(payload))


def delete_job(payload: dict):
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_delete(payload))


def query_job(payload: dict):
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_query(payload))


def run_query_sync(payload_dict: dict, settings_dict: dict) -> dict:
    """Run query in subprocess to avoid blocking event loop.
    
    This is the entry point for ProcessPoolExecutor execution.
    It creates its own event loop in the subprocess and runs the query.
    """
    import logging

    logging.basicConfig(level=logging.INFO)

    settings = Settings(**settings_dict)
    pool = get_or_create_subprocess_pool_sync(settings, settings_dict)

    async def _execute():

        start_ts = time.monotonic()
        request_id = payload_dict.get("request_id") or str(uuid.uuid4())
        logging.getLogger(__name__).info("query start request_id=%s", request_id)

        try:
            req = QueryRequest(**payload_dict)
        except ValidationError as exc:
            mode = "full"
            if settings.retrieval_only:
                mode = "retrieval_only"
            elif settings.llm_stub:
                mode = "stub"
            entry = {
                "request_id": request_id,
                "endpoint": "rag",
                "mode": mode,
                "status": "error",
                "error_type": "ValidationError",
                "prompt_id": payload_dict.get("prompt_id"),
                "session_id": payload_dict.get("sessionId"),
                "request_meta": payload_dict.get("request_meta"),
                "queue_wait_ms": 0,  # Direct execution - no queue wait
                "retrieval_ms": None,
                "llm_ms": None,
                "post_ms": None,
                "total_ms": int((time.monotonic() - start_ts) * 1000),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            write_timing_log(settings, entry)
            logging.getLogger(__name__).error("query validation error request_id=%s error=%s", request_id, exc)
            raise

        req.request_id = request_id
        req.queue_wait_ms = 0  # Direct execution - no queue wait

        try:
            result = await run_query(req, settings, pool)
        except Exception as exc:
            logging.getLogger(__name__).error("query error request_id=%s error_type=%s", request_id, type(exc).__name__)
            return _serialize_subprocess_error(exc, request_id)

        duration_ms = int((time.monotonic() - start_ts) * 1000)
        logging.getLogger(__name__).info(
            "query done request_id=%s duration_ms=%s",
            request_id,
            duration_ms,
        )

        # Extract metrics for Prometheus tracking and include in response
        result_dict = result.model_dump()
        result_dict["_metrics_prompt_tokens"] = getattr(result, "_metrics_prompt_tokens", None)
        result_dict["_metrics_completion_tokens"] = getattr(result, "_metrics_completion_tokens", None)
        result_dict["_metrics_cache_hit"] = getattr(result, "_metrics_cache_hit", None)
        return result_dict

    return run_on_subprocess_loop_sync(_execute())
