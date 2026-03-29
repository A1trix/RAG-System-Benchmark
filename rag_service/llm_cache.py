"""Semantic caching for LLM responses using embedding similarity."""

from dataclasses import dataclass, field
import hashlib
import time
from typing import Optional

import numpy as np
from cachetools import TTLCache


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""

    query_embedding: np.ndarray
    context_ids: list
    response: str
    timestamp: float
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_completion_tokens: Optional[int] = None
    hit_count: int = 0

    def to_dict(self) -> dict:
        """Convert entry to dictionary for stats."""
        return {
            "timestamp": self.timestamp,
            "age_seconds": time.time() - self.timestamp,
            "hit_count": self.hit_count,
            "context_ids_count": len(self.context_ids),
            "has_temperature": self.temperature is not None,
            "has_top_p": self.top_p is not None,
        }


@dataclass
class CacheStats:
    """Cache statistics tracker."""

    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0
    last_hit_at: Optional[float] = None
    last_miss_at: Optional[float] = None
    last_set_at: Optional[float] = None

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        total = self.total_requests
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "evictions": self.evictions,
            "hit_rate": round(self.hit_rate, 4),
            "total_requests": self.total_requests,
            "last_hit_at": self.last_hit_at,
            "last_miss_at": self.last_miss_at,
            "last_set_at": self.last_set_at,
        }


class SemanticLLMCache:
    """
    Semantic cache for LLM responses using embedding similarity.

    Matches queries by cosine similarity on embeddings, ensuring
    semantically similar questions return cached responses.
    """

    def __init__(
        self,
        maxsize: int = 5000,
        ttl: int = 900,
        threshold: float = 0.92,
        temperature_tolerance: float = 0.01,
    ):
        """
        Initialize semantic cache.

        Args:
            maxsize: Maximum number of cached entries (LRU eviction)
            ttl: Time-to-live in seconds for each entry
            threshold: Cosine similarity threshold for matching (0.0-1.0)
            temperature_tolerance: Tolerance for temperature parameter matching
        """
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self.threshold = threshold
        self.temperature_tolerance = temperature_tolerance
        self._stats = CacheStats()
        # Note: TTLCache doesn't support callbacks in cachetools >= 7.0
        # Eviction tracking disabled - evictions still occur via TTL/maxsize

    def _compute_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            emb1: First embedding vector
            emb2: Second embedding vector

        Returns:
            Cosine similarity score between 0.0 and 1.0
        """
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(emb1, emb2) / (norm1 * norm2))

    def _params_match(
        self,
        entry: CacheEntry,
        temperature: Optional[float],
        top_p: Optional[float],
        max_completion_tokens: Optional[int],
    ) -> bool:
        """
        Check if model parameters match within tolerance.

        Args:
            entry: Cached entry to compare
            temperature: Requested temperature
            top_p: Requested top_p
            max_completion_tokens: Requested max completion tokens

        Returns:
            True if parameters match
        """
        # Temperature match (with tolerance for float comparison)
        if temperature is not None and entry.temperature is not None:
            if abs(temperature - entry.temperature) > self.temperature_tolerance:
                return False
        elif (temperature is None) != (entry.temperature is None):
            return False

        # Top_p match
        if top_p is not None and entry.top_p is not None:
            if abs(top_p - entry.top_p) > self.temperature_tolerance:
                return False
        elif (top_p is None) != (entry.top_p is None):
            return False

        # Max completion tokens match (exact)
        if max_completion_tokens != entry.max_completion_tokens:
            return False

        return True

    def _make_key(
        self,
        query_embedding: np.ndarray,
        context_ids: list,
        temperature: Optional[float],
        top_p: Optional[float],
        max_completion_tokens: Optional[int],
    ) -> str:
        """
        Create a deterministic cache key.

        Args:
            query_embedding: Query embedding vector
            context_ids: List of context document IDs
            temperature: Model temperature parameter
            top_p: Model top_p parameter
            max_completion_tokens: Max tokens parameter

        Returns:
            String key for cache storage
        """
        # Normalize context IDs for consistent hashing
        sorted_ids = sorted(str(cid) for cid in context_ids)
        ids_str = ",".join(sorted_ids)

        # Include model params in key
        params_str = f"{temperature}:{top_p}:{max_completion_tokens}"

        # Create hash from embedding bytes + context + params
        embedding_bytes = query_embedding.astype(np.float32).tobytes()
        key_data = embedding_bytes + ids_str.encode() + params_str.encode()
        return hashlib.sha256(key_data).hexdigest()

    def get(
        self,
        query_embedding: np.ndarray,
        context_ids: list,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Retrieve cached response for semantically similar query.

        Iterates through cache entries and finds the first entry where:
        1. Cosine similarity > threshold
        2. Context document IDs match exactly
        3. Model parameters match

        Args:
            query_embedding: Embedding vector of the query
            context_ids: List of context document IDs
            temperature: Model temperature parameter
            top_p: Model top_p parameter
            max_completion_tokens: Max tokens parameter

        Returns:
            Cached response string if found, None otherwise
        """
        if not context_ids:
            self._stats.misses += 1
            self._stats.last_miss_at = time.time()
            return None

        # Convert to numpy array if needed
        if not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding, dtype=np.float32)

        # Search for semantically similar entry
        for key, entry in self._cache.items():
            # Check context IDs match exactly
            if set(entry.context_ids) != set(context_ids):
                continue

            # Check model parameters match
            if not self._params_match(entry, temperature, top_p, max_completion_tokens):
                continue

            # Check embedding similarity
            similarity = self._compute_similarity(query_embedding, entry.query_embedding)
            if similarity >= self.threshold:
                entry.hit_count += 1
                self._stats.hits += 1
                self._stats.last_hit_at = time.time()
                return entry.response

        self._stats.misses += 1
        self._stats.last_miss_at = time.time()
        return None

    def set(
        self,
        query_embedding: np.ndarray,
        context_ids: list,
        response: str,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> None:
        """
        Store response in cache.

        Args:
            query_embedding: Embedding vector of the query
            context_ids: List of context document IDs
            response: LLM response to cache
            temperature: Model temperature parameter
            top_p: Model top_p parameter
            max_completion_tokens: Max tokens parameter
        """
        if not context_ids or not response:
            return

        # Convert to numpy array if needed
        if not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding, dtype=np.float32)

        # Create deterministic key
        key = self._make_key(
            query_embedding, context_ids, temperature, top_p, max_completion_tokens
        )

        # Store entry
        entry = CacheEntry(
            query_embedding=query_embedding,
            context_ids=list(context_ids),
            response=response,
            timestamp=time.time(),
            temperature=temperature,
            top_p=top_p,
            max_completion_tokens=max_completion_tokens,
            hit_count=0,
        )

        self._cache[key] = entry
        self._stats.sets += 1
        self._stats.last_set_at = time.time()

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    def get_stats(self) -> dict:
        """Get current cache statistics."""
        stats = self._stats.to_dict()
        stats.update(
            {
                "current_size": len(self._cache),
                "max_size": self._cache.maxsize,
                "threshold": self.threshold,
            }
        )
        return stats

    def get_entries_summary(self, limit: int = 100) -> list[dict]:
        """Get summary of cached entries for debugging."""
        entries = []
        for key, entry in list(self._cache.items())[:limit]:
            entries.append(
                {
                    "key_prefix": key[:16] + "...",
                    "timestamp": entry.timestamp,
                    "age_seconds": time.time() - entry.timestamp,
                    "hit_count": entry.hit_count,
                    "context_ids_count": len(entry.context_ids),
                    "response_length": len(entry.response),
                }
            )
        return entries


# Singleton cache instance for the RAG service
_cache_instance: Optional[SemanticLLMCache] = None


def get_cache() -> SemanticLLMCache:
    """Get or create the singleton cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SemanticLLMCache()
    return _cache_instance


def reset_cache() -> None:
    """Reset the singleton cache instance."""
    global _cache_instance
    _cache_instance = None
