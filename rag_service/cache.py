"""Embedding cache module for in-memory LRU caching of embeddings.

Aligns with n8n's architecture by using in-memory caching without external services.
"""

import hashlib
import os
import threading
from functools import wraps
from typing import Callable, TypeVar, Optional
from datetime import datetime, timezone

import numpy as np
from cachetools import LRUCache, TTLCache

# ============================================================================
# LLM Response Cache (Task 2.2)
# ============================================================================

# TTL cache for LLM responses (15 min TTL, 500 entries)
# Only caches deterministic responses (temperature=0)
llm_response_cache: TTLCache[str, dict] = TTLCache(maxsize=500, ttl=900)
_llm_cache_lock = threading.Lock()
_llm_cache_hits = 0
_llm_cache_misses = 0
_llm_cache_metrics_lock = threading.Lock()


def get_llm_cache_key(query: str, context: list[str], model: str) -> str:
    """Generate cache key for LLM responses.
    
    Uses SHA256 hash of query, context, and model for exact matching.
    
    Args:
        query: User query text
        context: List of context strings from retrieved documents
        model: LLM model name (e.g., "gpt-5-nano")
        
    Returns:
        SHA256-based cache key string
    """
    # Hash context for consistent key generation
    context_hash = hashlib.sha256("".join(context).encode()).hexdigest()[:16]
    cache_key = f"{query}:{context_hash}:{model}"
    return hashlib.sha256(cache_key.encode()).hexdigest()


def get_cached_llm_response(query: str, context: list[str], model: str, temperature: float | None = None) -> Optional[str]:
    """Retrieve cached LLM response if available.
    
    Only returns cached responses for deterministic settings (temperature=0).
    
    Args:
        query: User query text
        context: List of context strings from retrieved documents
        model: LLM model name
        temperature: LLM temperature setting
        
    Returns:
        Cached response string or None if not found/non-deterministic
    """
    # Only cache deterministic responses (temperature=0)
    if temperature is not None and temperature != 0:
        return None
    
    key = get_llm_cache_key(query, context, model)
    
    with _llm_cache_lock:
        if key in llm_response_cache:
            with _llm_cache_metrics_lock:
                global _llm_cache_hits
                _llm_cache_hits += 1
            return llm_response_cache[key]["response"]
    
    with _llm_cache_metrics_lock:
        global _llm_cache_misses
        _llm_cache_misses += 1
    
    return None


def cache_llm_response(query: str, context: list[str], model: str, response: str, temperature: float | None = None) -> bool:
    """Store LLM response in cache.
    
    Only caches deterministic responses (temperature=0).
    
    Args:
        query: User query text
        context: List of context strings from retrieved documents
        model: LLM model name
        response: LLM response text to cache
        temperature: LLM temperature setting
        
    Returns:
        True if response was cached, False otherwise
    """
    # Only cache deterministic responses (temperature=0)
    if temperature is not None and temperature != 0:
        return False
    
    key = get_llm_cache_key(query, context, model)
    
    with _llm_cache_lock:
        llm_response_cache[key] = {
            "response": response,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
        }
    
    return True


def get_llm_cache_stats() -> dict[str, float | int]:
    """Get LLM cache statistics.
    
    Returns:
        Dictionary with hits, misses, hit_rate, size, ttl_seconds, and maxsize
    """
    with _llm_cache_metrics_lock:
        total = _llm_cache_hits + _llm_cache_misses
        return {
            "hits": float(_llm_cache_hits),
            "misses": float(_llm_cache_misses),
            "hit_rate": float(_llm_cache_hits / total if total > 0 else 0.0),
            "size": float(len(llm_response_cache)),
            "maxsize": float(llm_response_cache.maxsize),
            "ttl_seconds": float(llm_response_cache.ttl),
        }


def reset_llm_cache_stats() -> None:
    """Reset LLM cache statistics counters."""
    global _llm_cache_hits, _llm_cache_misses
    with _llm_cache_metrics_lock:
        _llm_cache_hits = 0
        _llm_cache_misses = 0


def clear_llm_cache() -> None:
    """Clear all cached LLM responses."""
    with _llm_cache_lock:
        llm_response_cache.clear()


class LLMResponseCache:
    """Cache for LLM responses with hit/miss metrics.
    
    Caches LLM responses for 15 minutes (900 seconds) with 500 entry limit.
    Only caches deterministic responses (temperature=0).
    """
    
    def __init__(self, maxsize: int = 500, ttl: int = 900) -> None:
        """Initialize LLM response cache with metrics counters.
        
        Args:
            maxsize: Maximum number of cached entries (default: 500)
            ttl: Time-to-live in seconds (default: 900 = 15 minutes)
        """
        self.cache: TTLCache[str, dict] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._hits = 0
        self._misses = 0
        self._metrics_lock = threading.Lock()
        self._cache_lock = threading.Lock()
    
    def get(self, query: str, context: list[str], model: str, temperature: float | None = None) -> Optional[str]:
        """Retrieve cached LLM response.
        
        Args:
            query: User query text
            context: List of context strings
            model: LLM model name
            temperature: LLM temperature setting
            
        Returns:
            Cached response string or None
        """
        if temperature is not None and temperature != 0:
            return None
        
        key = get_llm_cache_key(query, context, model)
        
        with self._cache_lock:
            if key in self.cache:
                with self._metrics_lock:
                    self._hits += 1
                return self.cache[key]["response"]
        
        with self._metrics_lock:
            self._misses += 1
        
        return None
    
    def set(self, query: str, context: list[str], model: str, response: str, temperature: float | None = None) -> bool:
        """Store LLM response in cache.
        
        Args:
            query: User query text
            context: List of context strings
            model: LLM model name
            response: LLM response text
            temperature: LLM temperature setting
            
        Returns:
            True if cached, False otherwise
        """
        if temperature is not None and temperature != 0:
            return False
        
        key = get_llm_cache_key(query, context, model)
        
        with self._cache_lock:
            self.cache[key] = {
                "response": response,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "model": model,
            }
        
        return True
    
    def invalidate_all(self) -> None:
        """Clear all cached LLM responses."""
        with self._cache_lock:
            self.cache.clear()
    
    def get_stats(self) -> dict[str, float | int]:
        """Get cache statistics.
        
        Returns:
            Dictionary with hits, misses, hit_rate, size, ttl_seconds, and maxsize
        """
        with self._metrics_lock:
            total = self._hits + self._misses
            return {
                "hits": float(self._hits),
                "misses": float(self._misses),
                "hit_rate": float(self._hits / total if total > 0 else 0.0),
                "size": float(len(self.cache)),
                "maxsize": float(self.cache.maxsize),
                "ttl_seconds": float(self.cache.ttl),
            }
    
    def reset_stats(self) -> None:
        """Reset hit/miss statistics counters."""
        with self._metrics_lock:
            self._hits = 0
            self._misses = 0


# ============================================================================
# Vector Search Cache (Phase 2C)
# ============================================================================

# TTL cache with 2000 entries, 5 minute TTL (300 seconds)
search_cache: TTLCache[str, list] = TTLCache(maxsize=2000, ttl=300)


def get_search_cache_key(embedding: np.ndarray, top_k: int) -> str:
    """Generate cache key for vector search results.
    
    Args:
        embedding: Query embedding vector
        top_k: Number of top results requested
        
    Returns:
        SHA256-based cache key string
    """
    embedding_hash = hashlib.sha256(embedding.tobytes()).hexdigest()[:16]
    return f"search:{embedding_hash}:k{top_k}"


class VectorSearchCache:
    """Cache for vector search results with hit/miss metrics.
    
    Caches embedding → top-k document mappings for 5 minutes (300 seconds).
    Supports cache invalidation and hit rate tracking.
    """
    
    def __init__(self) -> None:
        """Initialize vector search cache with metrics counters."""
        self.cache = search_cache
        self._hits = 0
        self._misses = 0
        self._metrics_lock = threading.Lock()
    
    def get(self, embedding: np.ndarray, top_k: int) -> list | None:
        """Retrieve cached search results.
        
        Args:
            embedding: Query embedding vector
            top_k: Number of top results requested
            
        Returns:
            Cached list of document dicts or None if not found
        """
        key = get_search_cache_key(embedding, top_k)
        if key in self.cache:
            with self._metrics_lock:
                self._hits += 1
            return self.cache[key]
        with self._metrics_lock:
            self._misses += 1
        return None
    
    def set(self, embedding: np.ndarray, top_k: int, results: list) -> None:
        """Cache search results.
        
        Args:
            embedding: Query embedding vector
            top_k: Number of top results requested
            results: List of document dicts to cache
        """
        key = get_search_cache_key(embedding, top_k)
        self.cache[key] = results
    
    def invalidate_all(self) -> None:
        """Clear all cached search results. Called when documents are updated."""
        self.cache.clear()
    
    def get_stats(self) -> dict[str, float | int]:
        """Get cache statistics.
        
        Returns:
            Dictionary with hits, misses, hit_rate, size, ttl_seconds, and maxsize
        """
        with self._metrics_lock:
            total = self._hits + self._misses
            return {
                "hits": float(self._hits),
                "misses": float(self._misses),
                "hit_rate": float(self._hits / total if total > 0 else 0.0),
                "size": float(len(self.cache)),
                "maxsize": float(self.cache.maxsize),
                "ttl_seconds": float(self.cache.ttl),
            }
    
    def reset_stats(self) -> None:
        """Reset hit/miss statistics counters."""
        with self._metrics_lock:
            self._hits = 0
            self._misses = 0


# ============================================================================
# Embedding Cache (Phase 2A)
# ============================================================================

# LRU cache with 1,000 entries and thread-safe access
# Aligned with n8n's in-memory caching pattern - no external dependencies
embedding_cache: LRUCache[str, np.ndarray] = LRUCache(maxsize=1000)
_cache_lock = threading.Lock()

# Metrics counters
_cache_hits = 0
_cache_misses = 0
_metrics_lock = threading.Lock()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value == "":
        return default
    if value in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _embedding_cache_enabled() -> bool:
    return _env_bool("EMBEDDING_CACHE_ENABLED", default=True)


def get_embedding_key(text: str) -> str:
    """Generate cache key from text using MD5 hash of normalized text.
    
    Args:
        text: Input text to hash
        
    Returns:
        MD5 hex digest of normalized (lowercase, stripped) text
    """
    normalized = text.lower().strip()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def get_cache_stats() -> dict[str, int | float]:
    """Get cache statistics.
    
    Returns:
        Dictionary with hits, misses, and current size
    """
    with _metrics_lock:
        with _cache_lock:
            return {
                "hits": _cache_hits,
                "misses": _cache_misses,
                "size": len(embedding_cache),
                "maxsize": embedding_cache.maxsize,
            }


def reset_cache_stats() -> None:
    """Reset cache statistics counters."""
    global _cache_hits, _cache_misses
    with _metrics_lock:
        _cache_hits = 0
        _cache_misses = 0


def clear_cache() -> None:
    """Clear all cached embeddings."""
    with _cache_lock:
        embedding_cache.clear()


F = TypeVar("F", bound=Callable[..., np.ndarray])


def cached_embedding(func: F) -> F:
    """Decorator to cache embedding function results.
    
    Args:
        func: Async function that generates embeddings
        
    Returns:
        Wrapped function with caching
    """
    @wraps(func)
    async def wrapper(text: str, *args, **kwargs) -> np.ndarray:
        if not _embedding_cache_enabled():
            result = await func(text, *args, **kwargs)
            if not isinstance(result, np.ndarray):
                result = np.array(result, dtype=np.float32)
            return result

        key = get_embedding_key(text)
        
        with _cache_lock:
            if key in embedding_cache:
                with _metrics_lock:
                    global _cache_hits
                    _cache_hits += 1
                return embedding_cache[key]
        
        with _metrics_lock:
            global _cache_misses
            _cache_misses += 1
        
        result = await func(text, *args, **kwargs)
        
        # Store as numpy array for consistency
        if not isinstance(result, np.ndarray):
            result = np.array(result, dtype=np.float32)
        
        with _cache_lock:
            embedding_cache[key] = result
        
        return result
    
    return wrapper  # type: ignore[return-value]


def cached_embedding_batch(func: F) -> F:
    """Decorator to cache batch embedding function results.
    
    For batch operations, caches each text individually to maximize hit rate.
    
    Args:
        func: Async function that generates embeddings for multiple texts
        
    Returns:
        Wrapped function with caching
    """
    @wraps(func)
    async def wrapper(self_or_texts, texts_or_none=None, *args, **kwargs) -> list[np.ndarray]:
        # Handle both instance methods (self, texts) and standalone functions (texts)
        if texts_or_none is not None:
            # Instance method: self_or_texts is self, texts_or_none is texts
            self = self_or_texts
            texts = texts_or_none
        else:
            # Standalone function: self_or_texts is texts
            self = None
            texts = self_or_texts

        if not _embedding_cache_enabled():
            if not texts:
                return []
            if self is not None:
                fetched = await func(self, texts, *args, **kwargs)
            else:
                fetched = await func(texts, *args, **kwargs)
            out: list[np.ndarray] = []
            for emb in fetched:
                if not isinstance(emb, np.ndarray):
                    emb = np.array(emb, dtype=np.float32)
                out.append(emb)
            return out
        
        if not texts:
            return []
        
        keys = [get_embedding_key(text) for text in texts]
        results: list[np.ndarray | None] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []
        
        # Check cache for each text
        with _cache_lock:
            for i, key in enumerate(keys):
                if key in embedding_cache:
                    results[i] = embedding_cache[key]
                    with _metrics_lock:
                        global _cache_hits
                        _cache_hits += 1
                else:
                    with _metrics_lock:
                        global _cache_misses
                        _cache_misses += 1
                    missing_indices.append(i)
                    missing_texts.append(texts[i])
        
        # Fetch missing embeddings
        if missing_texts:
            if self is not None:
                fetched = await func(self, missing_texts, *args, **kwargs)
            else:
                fetched = await func(missing_texts, *args, **kwargs)
            
            # Ensure numpy arrays and store in cache
            with _cache_lock:
                for idx, emb in zip(missing_indices, fetched):
                    if not isinstance(emb, np.ndarray):
                        emb = np.array(emb, dtype=np.float32)
                    results[idx] = emb
                    embedding_cache[keys[idx]] = emb
        
        return [r for r in results if r is not None]
    
    return wrapper  # type: ignore[return-value]
