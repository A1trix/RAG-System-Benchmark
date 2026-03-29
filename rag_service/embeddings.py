from typing import Sequence

import numpy as np
from openai import AsyncOpenAI

from rag_service.cache import cached_embedding, cached_embedding_batch, get_cache_stats
from rag_service.circuit_breaker import get_embedding_circuit, CircuitBreakerOpenError


def _clean_base_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if not url.startswith("http://") and not url.startswith("https://"):
        return None
    return url


class EmbeddingClient:
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        self.last_usage: dict[str, int] | None = None
        self.usage_history: list[dict[str, int]] = []
        safe_base = _clean_base_url(base_url)
        if safe_base:
            self.client = AsyncOpenAI(api_key=api_key, base_url=safe_base) if api_key else AsyncOpenAI(base_url=safe_base)
        else:
            self.client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

    async def _call_api(self, texts: list[str]) -> tuple[list[np.ndarray], dict | None]:
        """Make the actual OpenAI API call with circuit breaker protection."""
        circuit = get_embedding_circuit()
        
        async def _make_request():
            return await self.client.embeddings.create(model=self.model, input=texts)
        
        response = await circuit.call(_make_request)
        
        usage = getattr(response, "usage", None)
        usage_entry = None
        if usage:
            try:
                usage_entry = {"total_tokens": int(getattr(usage, "total_tokens", 0) or 0)}
            except Exception:
                usage_entry = None
            if usage_entry is not None:
                self.last_usage = usage_entry
                self.usage_history.append(usage_entry)
        
        embeddings = [np.array(item.embedding, dtype=np.float32) for item in response.data]
        return embeddings, usage_entry

    @cached_embedding
    async def embed_one(self, text: str) -> np.ndarray:
        """Generate embedding for a single text with caching.
        
        Args:
            text: Input text to embed
            
        Returns:
            Embedding as numpy array
            
        Raises:
            CircuitBreakerOpenError: If circuit breaker is open (503 response)
        """
        embeddings, _ = await self._call_api([text])
        return embeddings[0]

    @cached_embedding_batch
    async def _embed_batch_raw(self, texts: list[str]) -> list[np.ndarray]:
        """Raw batch embedding without caching logic.
        
        Raises:
            CircuitBreakerOpenError: If circuit breaker is open (503 response)
        """
        embeddings, _ = await self._call_api(texts)
        return embeddings

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts with caching.
        
        Args:
            texts: Sequence of texts to embed
            
        Returns:
            List of embeddings as float lists
        """
        if not texts:
            return []
        
        # Use batch caching for efficiency
        text_list = list(texts)
        embeddings = await self._embed_batch_raw(text_list)
        return [emb.tolist() for emb in embeddings]

    def get_cache_metrics(self) -> dict[str, int]:
        """Get embedding cache statistics.
        
        Returns:
            Dictionary with cache hits, misses, size, and maxsize
        """
        return get_cache_stats()
