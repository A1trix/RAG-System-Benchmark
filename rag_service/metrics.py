"""Prometheus metrics for RAG service.

Aligns with n8n's metrics exposure pattern when N8N_METRICS=true.
Key metrics:
- Request count by endpoint (rag_requests_total)
- Request duration histogram (rag_request_duration_seconds)
- LLM token usage counter (rag_llm_tokens_total)
- Cache hit rate gauge (rag_cache_hit_rate)
"""

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

# Use the default registry for automatic metric collection
registry = CollectorRegistry()

# Request metrics
REQUEST_COUNT = Counter(
    "rag_requests_total",
    "Total requests by endpoint and status",
    ["endpoint", "status"],
    registry=registry,
)

REQUEST_DURATION = Histogram(
    "rag_request_duration_seconds",
    "Request duration in seconds by endpoint",
    ["endpoint"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    registry=registry,
)

# LLM token metrics
LLM_TOKENS = Counter(
    "rag_llm_tokens_total",
    "Total LLM tokens used by model and type",
    ["model", "type"],
    registry=registry,
)

# Cache metrics
CACHE_HIT_RATE = Gauge(
    "rag_cache_hit_rate",
    "Cache hit rate (0.0 to 1.0)",
    registry=registry,
)

CACHE_HITS = Counter(
    "rag_cache_hits_total",
    "Total cache hits",
    registry=registry,
)

CACHE_MISSES = Counter(
    "rag_cache_misses_total",
    "Total cache misses",
    registry=registry,
)

# Queue metrics
INGEST_QUEUE_DEPTH = Gauge(
    "rag_ingest_queue_depth",
    "Current depth of ingest job queue",
    registry=registry,
)

# Chat memory metrics
CHAT_MEMORY_READ_LATENCY = Histogram(
    "rag_chat_memory_read_seconds",
    "Chat history read latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    registry=registry,
)

CHAT_MEMORY_WRITE_LATENCY = Histogram(
    "rag_chat_memory_write_seconds",
    "Chat history write latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    registry=registry,
)

CHAT_MEMORY_MESSAGES = Gauge(
    "rag_chat_memory_messages",
    "Number of messages in chat history by session",
    ["session_id"],
    registry=registry,
)

# Endpoints to exclude from timing metrics
EXCLUDED_ENDPOINTS = {"/metrics", "/health", "/ready"}


def is_excluded_endpoint(path: str) -> bool:
    """Check if an endpoint should be excluded from timing metrics."""
    return path in EXCLUDED_ENDPOINTS


def update_cache_metrics(hit_rate: float) -> None:
    """Update cache hit rate gauge."""
    CACHE_HIT_RATE.set(hit_rate)


def record_cache_hit() -> None:
    """Record a cache hit."""
    CACHE_HITS.inc()


def record_cache_miss() -> None:
    """Record a cache miss."""
    CACHE_MISSES.inc()


def record_llm_tokens(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Record LLM token usage."""
    LLM_TOKENS.labels(model=model, type="prompt").inc(prompt_tokens)
    LLM_TOKENS.labels(model=model, type="completion").inc(completion_tokens)


def get_registry():
    """Get the metrics registry."""
    return registry
