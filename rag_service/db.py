import logging
import os
import asyncio
import atexit
import threading
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_subproc_lock = threading.Lock()
_subproc_pid: int | None = None
_subproc_loop: asyncio.AbstractEventLoop | None = None
_subproc_pool = None
_subproc_pool_key: tuple | None = None
_subproc_atexit_pid: int | None = None


def _is_worker_context() -> bool:
    """Detect if running in a worker context based on process name or environment."""
    import sys

    argv0 = sys.argv[0] if sys.argv else ""
    return (
        "worker" in argv0.lower()
        or os.environ.get("RAG_WORKER_CONTEXT", "").lower() == "true"
        or "ingest_worker" in argv0
        or "tasks" in argv0
    )


async def create_pool(
    settings,
    min_size: int | None = None,
    max_size: int | None = None,
    is_worker: bool | None = None,
):
    """
    Create an optimized asyncpg connection pool with n8n-aligned configuration.
    
    Configuration optimized for:
    - 5 RQ workers + 8 concurrent VUs
    - Each worker: ~1.6 concurrent connections (8 VU / 5 workers)
    - With buffer: max_size=6 per worker (total ~30 connections across workers)
    
    Args:
        settings: Application settings with database credentials
        min_size: Minimum pool size (auto-calculated if None). 
                  Workers: 2-3 (warm connections), Main: 5 (API requests)
        max_size: Maximum pool size (auto-calculated if None).
                  Workers: 6-8 per worker, Main: 20
        is_worker: Whether this is a worker context (auto-detected if None)
    
    Returns:
        asyncpg.Pool: Configured connection pool
    """
    # Auto-detect worker context if not specified
    if is_worker is None:
        is_worker = _is_worker_context()
    
    # Auto-calculate pool sizes based on context
    # n8n-aligned sizing for production-grade connection handling
    if min_size is None:
        min_size = 2 if is_worker else 5
    if max_size is None:
        max_size = 6 if is_worker else 20
    
    dsn = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    
    # n8n-aligned production-grade pool configuration
    # Matches Supavisor-style connection pooling behavior
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        max_queries=50000,  # Recycle connections after 50k queries to prevent memory bloat
        max_inactive_connection_lifetime=300,  # Close idle connections after 5 min
        command_timeout=60,  # Query timeout
        timeout=30,  # Connection acquisition timeout
        server_settings={
            'jit': 'off',  # Disable JIT for OLTP workloads
            'application_name': f'rag_service_{"worker" if is_worker else "main"}'
        },
        init=conn_init,
    )
    
    logger.info(
        "Created asyncpg pool (worker=%s, min=%d, max=%d)",
        is_worker, min_size, max_size
    )
    
    return pool


async def conn_init(conn):
    """Initialize new connections with required settings."""
    await conn.set_type_codec(
        'json',
        encoder=lambda x: x,
        decoder=lambda x: x,
        schema='pg_catalog'
    )
    await conn.set_type_codec(
        'jsonb',
        encoder=lambda x: x,
        decoder=lambda x: x,
        schema='pg_catalog'
    )


def get_pool_stats(pool) -> dict:
    """
    Get current pool statistics for monitoring.
    
    Args:
        pool: asyncpg.Pool instance
    
    Returns:
        dict with pool metrics
    """
    if pool is None:
        return {
            'size': 0,
            'min_size': 0,
            'max_size': 0,
            'idle_size': 0,
            'acquired_size': 0,
        }
    
    return {
        'size': pool.get_size(),
        'min_size': pool.get_min_size(),
        'max_size': pool.get_max_size(),
        'idle_size': pool.get_idle_size(),
        'acquired_size': pool.get_size() - pool.get_idle_size(),
    }


async def close_pool(pool):
    """
    Gracefully close the connection pool.
    
    Args:
        pool: asyncpg.Pool instance to close
    """
    if pool is not None:
        stats = get_pool_stats(pool)
        logger.info(
            "Closing asyncpg pool (size=%d, idle=%d)",
            stats['size'], stats['idle_size']
        )
        await pool.close()
        logger.info("Pool closed successfully")


async def health_check(pool) -> dict:
    """
    Perform a health check on the pool by executing a simple query.
    
    Args:
        pool: asyncpg.Pool instance
    
    Returns:
        dict with health status and response time
    """
    import time
    
    start = time.monotonic()
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            latency_ms = (time.monotonic() - start) * 1000
            return {
                'healthy': result == 1,
                'latency_ms': round(latency_ms, 2),
                'error': None,
            }
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return {
            'healthy': False,
            'latency_ms': round(latency_ms, 2),
            'error': str(e),
        }


@asynccontextmanager
async def pooled_connection(pool):
    """
    Context manager for acquiring and releasing connections.
    
    Args:
        pool: asyncpg.Pool instance
    
    Yields:
        asyncpg.Connection: Database connection
    """
    async with pool.acquire() as conn:
        try:
            yield conn
        except Exception:
            await conn.close()
            raise


async def execute(pool, query: str, *args):
    """Execute a query and return None."""
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def fetch(pool, query: str, *args):
    """Execute a query and return all rows."""
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(pool, query: str, *args):
    """Execute a query and return the first row."""
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(pool, query: str, *args):
    """Execute a query and return a single value."""
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)


def _settings_key(settings_dict: dict[str, Any]) -> tuple:
    return tuple(sorted((k, repr(v)) for k, v in settings_dict.items()))


async def _close_subproc_pool_if_any() -> None:
    global _subproc_pool, _subproc_pool_key
    if _subproc_pool is not None:
        try:
            await close_pool(_subproc_pool)
        finally:
            _subproc_pool = None
            _subproc_pool_key = None


def _subproc_state_needs_reset() -> bool:
    pid = os.getpid()
    if _subproc_pid != pid:
        return True
    if _subproc_loop is None or _subproc_loop.is_closed():
        return True
    return False


def _cleanup_subproc_resources() -> None:
    global _subproc_loop, _subproc_pid, _subproc_atexit_pid
    loop = _subproc_loop
    if loop is None or loop.is_closed():
        _subproc_loop = None
        _subproc_pid = None
        _subproc_atexit_pid = None
        return
    try:
        loop.run_until_complete(_close_subproc_pool_if_any())
    except Exception:
        logger.exception("subprocess asyncpg cleanup failed")
    finally:
        loop.close()
        _subproc_loop = None
        _subproc_pid = None
        _subproc_atexit_pid = None


def _ensure_subproc_runtime() -> asyncio.AbstractEventLoop:
    global _subproc_pid, _subproc_loop, _subproc_atexit_pid
    pid = os.getpid()

    if _subproc_state_needs_reset():
        if _subproc_loop is not None and not _subproc_loop.is_closed():
            try:
                _subproc_loop.run_until_complete(_close_subproc_pool_if_any())
            except Exception:
                logger.exception("failed to reset inherited subprocess runtime")
            finally:
                _subproc_loop.close()
        _subproc_loop = asyncio.new_event_loop()
        _subproc_pid = pid

    if _subproc_atexit_pid != pid:
        atexit.register(_cleanup_subproc_resources)
        _subproc_atexit_pid = pid

    assert _subproc_loop is not None
    return _subproc_loop


def run_on_subprocess_loop_sync(coro):
    """Run coroutine on a process-local persistent event loop."""
    with _subproc_lock:
        loop = _ensure_subproc_runtime()
        return loop.run_until_complete(coro)


def get_or_create_subprocess_pool_sync(settings, settings_dict: dict[str, Any]):
    """Return process-local asyncpg pool for subprocess query execution."""
    global _subproc_pool, _subproc_pool_key
    key = _settings_key(settings_dict)

    async def _get_pool():
        global _subproc_pool, _subproc_pool_key
        if _subproc_pool is None:
            _subproc_pool = await create_pool(settings, min_size=1, max_size=4, is_worker=True)
            _subproc_pool_key = key
            return _subproc_pool

        if _subproc_pool_key != key:
            await _close_subproc_pool_if_any()
            _subproc_pool = await create_pool(settings, min_size=1, max_size=4, is_worker=True)
            _subproc_pool_key = key
            return _subproc_pool

        return _subproc_pool

    return run_on_subprocess_loop_sync(_get_pool())
