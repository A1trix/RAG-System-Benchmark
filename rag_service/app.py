import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import uuid
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest
import time

from rag_service.config import Settings
from rag_service.models import IngestRequest, IngestResponse, DeleteRequest, DeleteResponse, QueryRequest, QueryResponse
from rag_service.query import write_timing_log
from rag_service.db import create_pool
from rag_service import vector_store
from rag_service.workers.queue import get_queue
from rag_service.workers.tasks import ingest_job, delete_job, run_query_sync
from rag_service.watcher import Watcher
from rag_service.otel import configure_logging, setup_tracing
from rag_service.middleware import add_rate_limiting
from rag_service.circuit_breaker import CircuitBreakerOpenError
from rag_service.metrics import (
    REQUEST_COUNT,
    REQUEST_DURATION,
    LLM_TOKENS,
    CACHE_HIT_RATE,
    CACHE_HITS,
    CACHE_MISSES,
    INGEST_QUEUE_DEPTH,
    is_excluded_endpoint,
    get_registry,
)

# ProcessPoolExecutor for CPU-bound query execution (n8n-style direct async)
_process_pool: ProcessPoolExecutor | None = None
_process_pool_lock = asyncio.Lock()


class SubprocessPayloadError(Exception):
    """Structured subprocess error reconstructed from serialized payload."""

    def __init__(
        self,
        error_type: str,
        message: str,
        request_id: str | None = None,
        error_chain: list[str] | None = None,
    ):
        self.error_type = error_type or "query_error"
        self.message = message or "subprocess query failed"
        self.request_id = request_id
        self.error_chain = error_chain or []
        super().__init__(self.message)

    @classmethod
    def from_result(cls, result: dict) -> "SubprocessPayloadError":
        raw_error_type = result.get("_error_type")
        if isinstance(raw_error_type, str) and _ERROR_NAME_RE.fullmatch(raw_error_type.strip()):
            error_type = raw_error_type.strip()
        else:
            error_type = "query_error"

        raw_message = result.get("_error_message")
        if isinstance(raw_message, str):
            message = raw_message.replace("\x00", "").strip()[:512]
        else:
            message = "subprocess query failed"
        if not message:
            message = "subprocess query failed"

        raw_chain = result.get("_error_chain")
        chain: list[str] = []
        if isinstance(raw_chain, list):
            for item in raw_chain[:8]:
                if isinstance(item, str):
                    cleaned = item.strip()
                    if _ERROR_NAME_RE.fullmatch(cleaned):
                        chain.append(cleaned)

        return cls(
            error_type=error_type,
            message=message,
            request_id=result.get("request_id") if isinstance(result.get("request_id"), str) else None,
            error_chain=chain,
        )


_ERROR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")

_ERROR_STATUS_MAP = {
    "TooManyConnectionsError": 503,
    "PoolAcquireTimeoutError": 503,
    "PostgresConnectionError": 503,
    "ConnectionDoesNotExistError": 503,
    "CannotConnectNowError": 503,
    "CircuitBreakerOpenError": 503,
    "RateLimitError": 429,
    "ValidationError": 422,
    "TimeoutError": 504,
}


def _error_type_for_exception(exc: Exception) -> str:
    if isinstance(exc, SubprocessPayloadError):
        return exc.error_type
    return type(exc).__name__


def _http_exception_for_query_error(exc: Exception, detail_prefix: str = "query failed") -> HTTPException:
    if isinstance(exc, SubprocessPayloadError):
        if exc.error_type == "TooManyConnectionsError":
            return HTTPException(status_code=503, detail="query unavailable: too many database connections")
        status_code = _ERROR_STATUS_MAP.get(exc.error_type, 500)
        return HTTPException(status_code=status_code, detail=f"{detail_prefix}: {exc.error_type}: {exc.message}")
    return HTTPException(status_code=500, detail=f"{detail_prefix}: {exc}")


def get_process_pool() -> ProcessPoolExecutor:
    """Get or create the process pool executor for CPU-bound work."""
    global _process_pool
    if _process_pool is None:
        _process_pool = ProcessPoolExecutor(max_workers=4)
    return _process_pool


async def reset_process_pool() -> ProcessPoolExecutor:
    """Reset broken process pool safely and return a fresh executor."""
    global _process_pool
    async with _process_pool_lock:
        old_pool = _process_pool
        _process_pool = ProcessPoolExecutor(max_workers=4)
    if old_pool is not None:
        try:
            old_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logging.getLogger(__name__).warning("failed to shutdown old process pool", exc_info=True)
    return _process_pool


def get_settings():
    return Settings()


configure_logging()
app = FastAPI(title="RAG Pipeline", version="0.1.0")
setup_tracing(app)

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v == "":
        return default
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


# Add rate limiting middleware (in-process token bucket).
# Benchmark suites should disable this to avoid turning the limiter into a fake "knee".
if _env_bool("RATE_LIMIT_ENABLED", default=True):
    # Config: query=100 req/min, ingest/delete=20 req/min
    add_rate_limiting(app)

_pool = None
_queue = None
_watcher: Watcher | None = None


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start_ts = time.monotonic()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        if request.url.path == "/query":
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            request_id = getattr(request.state, "request_id", None)
            status_code = response.status_code if response else 500
            logging.getLogger(__name__).info(
                "query request_id=%s status=%s duration_ms=%s",
                request_id,
                status_code,
                duration_ms,
            )


@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    """Track request count and duration for Prometheus metrics.
    
    Excludes /metrics, /health, and /ready endpoints from timing.
    """
    path = request.url.path
    if is_excluded_endpoint(path):
        return await call_next(request)
    
    # Extract endpoint name from path (e.g., /query -> query)
    endpoint = path.strip("/").split("/")[0] if path.strip("/") else "unknown"
    
    with REQUEST_DURATION.labels(endpoint=endpoint).time():
        response = await call_next(request)
        status = "ok" if response.status_code < 400 else "error"
        REQUEST_COUNT.labels(endpoint=endpoint, status=status).inc()
        return response


async def get_pool(settings: Settings = Depends(get_settings)):
    global _pool
    if _pool is None:
        _pool = await create_pool(settings)
        await vector_store.ensure_table(_pool, settings.pgvector_table)
    return _pool


def get_queue_dep(settings: Settings = Depends(get_settings)):
    global _queue
    if _queue is None:
        _queue = get_queue(settings.redis_url, settings.queue_name)
    return _queue


@app.on_event("startup")
async def startup_event():
    global _watcher
    settings = Settings()
    queue = get_queue(settings.redis_url, settings.queue_name)
    watcher = Watcher(settings, queue)
    try:
        watcher.start()
    except Exception as exc:  # pragma: no cover
        import logging

        logging.getLogger(__name__).exception("File watcher failed to start: %s", exc)
    _watcher = watcher


@app.on_event("shutdown")
async def shutdown_event():
    global _watcher, _process_pool, _pool
    if _watcher:
        _watcher.stop()
    if _process_pool:
        _process_pool.shutdown(wait=True)
    if _pool:
        from rag_service.db import close_pool
        await close_pool(_pool)


def require_auth(request: Request, settings: Settings):
    if not settings.api_token:
        return
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header.split(" ", 1)[1]
    if token != settings.api_token:
        raise HTTPException(status_code=403, detail="invalid token")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(get_registry()).decode("utf-8"))


@app.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(
    payload: IngestRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    queue=Depends(get_queue_dep),
):
    require_auth(request, settings)
    job = queue.enqueue(ingest_job, payload.model_dump())
    INGEST_QUEUE_DEPTH.set(queue.count)
    REQUEST_COUNT.labels(endpoint="ingest", status="queued").inc()
    return IngestResponse(status="queued", file_id=payload.file_id, job_id=job.id)


@app.post("/delete", response_model=DeleteResponse)
async def delete_endpoint(
    payload: DeleteRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    queue=Depends(get_queue_dep),
):
    require_auth(request, settings)
    job = queue.enqueue(delete_job, payload.model_dump())
    INGEST_QUEUE_DEPTH.set(queue.count)
    REQUEST_COUNT.labels(endpoint="delete", status="queued").inc()
    return DeleteResponse(status="queued", file_id=payload.file_id, job_id=job.id)


@app.post("/query", response_model=QueryResponse)
async def query_endpoint(
    payload: QueryRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    """Execute query directly using ProcessPoolExecutor (n8n-style direct async).
    
    Removes RQ dependency for query execution - RQ is only used for background
    tasks (ingest/delete). Uses ProcessPoolExecutor to run CPU-bound work
    (embeddings, LLM calls) in separate processes without blocking the event loop.
    """
    require_auth(request, settings)
    payload_dict = payload.model_dump()
    if not payload_dict.get("request_id"):
        payload_dict["request_id"] = str(uuid.uuid4())
    request.state.request_id = payload_dict["request_id"]
    
    timeout_seconds = settings.query_timeout_seconds
    start_ts = time.monotonic()

    async def _execute_once() -> dict:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                get_process_pool(),
                run_query_sync,
                payload_dict,
                settings.model_dump(),
            ),
            timeout=timeout_seconds,
        )
        if isinstance(result, dict) and result.get("_error"):
            raise SubprocessPayloadError.from_result(result)
        return result
    
    with REQUEST_DURATION.labels(endpoint="query").time():
        try:
            # Execute query directly using ProcessPoolExecutor (non-blocking)
            result = await _execute_once()
        except BrokenProcessPool:
            logging.getLogger(__name__).warning(
                "broken process pool for request_id=%s; recreating pool and retrying once",
                payload_dict.get("request_id"),
            )
            await reset_process_pool()
            try:
                result = await _execute_once()
            except Exception as exc:
                REQUEST_COUNT.labels(endpoint="query", status="error").inc()
                elapsed_ms = int((time.monotonic() - start_ts) * 1000)
                entry = {
                    "request_id": payload_dict.get("request_id"),
                    "endpoint": "rag",
                    "mode": "retrieval_only" if settings.retrieval_only else "stub" if settings.llm_stub else "full",
                    "status": "error",
                    "error_type": _error_type_for_exception(exc),
                    "prompt_id": payload_dict.get("prompt_id"),
                    "session_id": payload_dict.get("sessionId"),
                    "request_meta": payload_dict.get("request_meta"),
                    "queue_wait_ms": 0,
                    "retrieval_ms": None,
                    "llm_ms": None,
                    "post_ms": None,
                    "total_ms": elapsed_ms,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
                write_timing_log(settings, entry)
                raise _http_exception_for_query_error(exc, detail_prefix="query failed after pool recovery")
        except asyncio.TimeoutError:
            REQUEST_COUNT.labels(endpoint="query", status="timeout").inc()
            elapsed_ms = int((time.monotonic() - start_ts) * 1000)
            entry = {
                "request_id": payload_dict.get("request_id"),
                "endpoint": "rag",
                "mode": "retrieval_only" if settings.retrieval_only else "stub" if settings.llm_stub else "full",
                "status": "timeout",
                "error_type": "client_timeout",
                "prompt_id": payload_dict.get("prompt_id"),
                "session_id": payload_dict.get("sessionId"),
                "request_meta": payload_dict.get("request_meta"),
                "queue_wait_ms": 0,  # Direct execution - no queue wait
                "retrieval_ms": None,
                "llm_ms": None,
                "post_ms": None,
                "total_ms": elapsed_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            write_timing_log(settings, entry)
            logging.getLogger(__name__).warning(
                "query timeout request_id=%s",
                payload_dict.get("request_id"),
            )
            raise HTTPException(status_code=504, detail="query timed out")
        except CircuitBreakerOpenError as exc:
            REQUEST_COUNT.labels(endpoint="query", status="circuit_open").inc()
            elapsed_ms = int((time.monotonic() - start_ts) * 1000)
            entry = {
                "request_id": payload_dict.get("request_id"),
                "endpoint": "rag",
                "mode": "retrieval_only" if settings.retrieval_only else "stub" if settings.llm_stub else "full",
                "status": "circuit_open",
                "error_type": "circuit_breaker_open",
                "prompt_id": payload_dict.get("prompt_id"),
                "session_id": payload_dict.get("sessionId"),
                "request_meta": payload_dict.get("request_meta"),
                "queue_wait_ms": 0,
                "retrieval_ms": None,
                "llm_ms": None,
                "post_ms": None,
                "total_ms": elapsed_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            write_timing_log(settings, entry)
            logging.getLogger(__name__).warning(
                "circuit breaker open request_id=%s",
                payload_dict.get("request_id"),
            )
            raise HTTPException(status_code=503, detail="OpenAI API temporarily unavailable - circuit breaker open")
        except Exception as exc:
            REQUEST_COUNT.labels(endpoint="query", status="error").inc()
            elapsed_ms = int((time.monotonic() - start_ts) * 1000)
            entry = {
                "request_id": payload_dict.get("request_id"),
                "endpoint": "rag",
                "mode": "retrieval_only" if settings.retrieval_only else "stub" if settings.llm_stub else "full",
                "status": "error",
                "error_type": _error_type_for_exception(exc),
                "prompt_id": payload_dict.get("prompt_id"),
                "session_id": payload_dict.get("sessionId"),
                "request_meta": payload_dict.get("request_meta"),
                "queue_wait_ms": 0,  # Direct execution - no queue wait
                "retrieval_ms": None,
                "llm_ms": None,
                "post_ms": None,
                "total_ms": elapsed_ms,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            write_timing_log(settings, entry)
            logging.getLogger(__name__).error(
                "query error request_id=%s error_type=%s",
                payload_dict.get("request_id"),
                _error_type_for_exception(exc),
            )
            raise _http_exception_for_query_error(exc)
    
    REQUEST_COUNT.labels(endpoint="query", status="ok").inc()
    
    # Track LLM tokens and cache metrics from result if available
    if isinstance(result, dict):
        # Track LLM token usage
        prompt_tokens = result.get("_metrics_prompt_tokens")
        completion_tokens = result.get("_metrics_completion_tokens")
        if prompt_tokens and completion_tokens:
            LLM_TOKENS.labels(model=settings.chat_model, type="prompt").inc(int(prompt_tokens))
            LLM_TOKENS.labels(model=settings.chat_model, type="completion").inc(int(completion_tokens))
        
        # Track cache hit/miss
        cache_hit = result.get("_metrics_cache_hit")
        if cache_hit is True:
            CACHE_HITS.inc()
            CACHE_HIT_RATE.set(1.0)
        elif cache_hit is False:
            CACHE_MISSES.inc()
            # Update hit rate based on hits vs total
            hit_rate = CACHE_HITS._value.get() / (CACHE_HITS._value.get() + CACHE_MISSES._value.get()) if (CACHE_HITS._value.get() + CACHE_MISSES._value.get()) > 0 else 0.0
            CACHE_HIT_RATE.set(hit_rate)
    
    response.headers["X-Request-Id"] = payload_dict.get("request_id", "")
    # Add token usage headers for k6 correlation analysis
    if isinstance(result, dict):
        prompt_tokens = result.get("prompt_tokens")
        completion_tokens = result.get("completion_tokens")
        total_tokens = result.get("total_tokens")
        if prompt_tokens is not None:
            response.headers["X-Token-Prompt"] = str(prompt_tokens)
        if completion_tokens is not None:
            response.headers["X-Token-Completion"] = str(completion_tokens)
        if total_tokens is not None:
            response.headers["X-Token-Total"] = str(total_tokens)
    # Remove internal metrics from response before returning
    if isinstance(result, dict):
        result = {k: v for k, v in result.items() if not k.startswith("_metrics_")}
    return QueryResponse(**result) if isinstance(result, dict) else result


def create_app():
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("rag_service.app:app", host="0.0.0.0", port=Settings().port, reload=True)
