from typing import Iterable, Sequence
import json
import logging
import os

import numpy as np
from asyncpg import Record
from asyncpg.pool import Pool

from . import db
from .cache import VectorSearchCache

logger = logging.getLogger(__name__)

# Global search cache instance
_search_cache = VectorSearchCache()


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


def _vector_search_cache_enabled() -> bool:
    return _env_bool("VECTOR_SEARCH_CACHE_ENABLED", default=True)


def invalidate_search_cache() -> None:
    """Invalidate all cached search results.
    
    Call this when documents are updated, deleted, or inserted.
    """
    _search_cache.invalidate_all()
    logger.info("Vector search cache invalidated")


def get_search_cache_stats() -> dict[str, float | int]:
    """Get vector search cache statistics.
    
    Returns:
        Dictionary with hits, misses, hit_rate, size, ttl_seconds, and maxsize
    """
    return _search_cache.get_stats()


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    text text,
    embedding vector,
    metadata jsonb
);
"""


async def ensure_table(pool: Pool, table_name: str) -> None:
    """Create the vector table if it doesn't exist."""
    await db.execute(pool, CREATE_TABLE_SQL.format(table_name=table_name))


async def delete_by_file_id(pool: Pool, table_name: str, file_id: str) -> int:
    """Delete all chunks associated with a file_id.
    
    Args:
        pool: Database connection pool
        table_name: Name of the vector table
        file_id: File ID to delete
        
    Returns:
        Number of rows deleted
    """
    result = await db.execute(
        pool,
        f"DELETE FROM {table_name} WHERE metadata->>'file_id' LIKE '%' || $1 || '%';",
        file_id,
    )
    
    # Invalidate search cache since documents changed
    invalidate_search_cache()
    
    return result


def _format_embedding(embedding: Sequence[float]) -> str:
    """Format embedding vector as PostgreSQL array string."""
    return f"[{','.join(str(x) for x in embedding)}]"


async def upsert_chunks_copy(
    pool: Pool,
    table_name: str,
    chunks: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    metadata: dict
) -> int:
    """Use COPY command for large batches (>1000 chunks) for optimal performance.
    
    Args:
        pool: Database connection pool
        table_name: Target table name
        chunks: List of text chunks
        embeddings: List of embedding vectors
        metadata: Metadata dict to attach to all chunks
        
    Returns:
        Number of rows inserted
    """
    if not chunks:
        return 0
    
    metadata_json = json.dumps(metadata)
    records = [
        (content, _format_embedding(emb), metadata_json)
        for content, emb in zip(chunks, embeddings)
    ]
    
    async with pool.acquire() as conn:
        result = await conn.copy_records_to_table(
            table_name,
            records=records,
            columns=['text', 'embedding', 'metadata']
        )
    return int(result.split()[1])


async def upsert_chunks(
    pool: Pool,
    table_name: str,
    chunks: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    metadata: dict,
    batch_size: int = 100
) -> int:
    """Batch insert chunks using executemany() for optimal performance.
    
    Automatically selects COPY method for large batches (>1000 chunks).
    Processes smaller batches using executemany() with configurable batch size.
    
    Args:
        pool: Database connection pool
        table_name: Target table name
        chunks: List of text chunks to insert
        embeddings: List of embedding vectors corresponding to chunks
        metadata: Metadata dict to attach to all chunks
        batch_size: Number of chunks per batch (default: 100)
        
    Returns:
        Total number of rows inserted
        
    Example:
        >>> count = await upsert_chunks(
        ...     pool, "documents", chunks, embeddings, 
        ...     {"file_id": "doc1"}, batch_size=100
        ... )
        >>> print(f"Inserted {count} chunks")
    """
    if not chunks:
        return 0
    
    num_chunks = len(chunks)
    
    if num_chunks > 1000:
        logger.info(f"Large batch detected ({num_chunks} chunks), using COPY method")
        return await upsert_chunks_copy(pool, table_name, chunks, embeddings, metadata)
    
    logger.info(f"Inserting {num_chunks} chunks in batches of {batch_size}")
    
    metadata_json = json.dumps(metadata)
    all_records = [
        (content, _format_embedding(emb), metadata_json)
        for content, emb in zip(chunks, embeddings)
    ]
    
    total_inserted = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for i in range(0, len(all_records), batch_size):
                batch = all_records[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(all_records) + batch_size - 1) // batch_size
                
                if total_batches > 1:
                    logger.debug(f"Processing batch {batch_num}/{total_batches} ({len(batch)} chunks)")
                
                await conn.executemany(
                    f"INSERT INTO {table_name} (text, embedding, metadata) VALUES ($1, $2::vector, $3::jsonb)",
                    batch
                )
                total_inserted += len(batch)
    
    logger.info(f"Successfully inserted {total_inserted} chunks")
    
    # Invalidate search cache since documents changed
    invalidate_search_cache()
    
    return total_inserted


async def _actual_search(
    pool: Pool, table_name: str, query_embedding: Sequence[float], top_k: int
) -> list[dict]:
    """Perform actual vector search against database.
    
    Internal function - use search() which includes caching.
    
    Args:
        pool: Database connection pool
        table_name: Name of the vector table
        query_embedding: Query embedding vector
        top_k: Number of top results to return
        
    Returns:
        List of document dicts with content, metadata, and score
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    sql = f"""
        SELECT text AS content, metadata, 1 - (embedding <=> $1::vector) AS score
        FROM {table_name}
        ORDER BY embedding <=> $1::vector
        LIMIT $2;
    """
    records = await db.fetch(pool, sql, embedding_str, top_k)
    # Convert records to list of dicts for caching
    return [
        {
            "content": r["content"],
            "metadata": r["metadata"],
            "score": r["score"],
        }
        for r in records
    ]


async def search(
    pool: Pool,
    table_name: str,
    query_embedding: Sequence[float],
    top_k: int,
    use_cache: bool | None = None,
) -> list[dict]:
    """Search for similar documents using cached results when available.
    
    Args:
        pool: Database connection pool
        table_name: Name of the vector table
        query_embedding: Query embedding vector (Sequence[float] or np.ndarray)
        top_k: Number of top results to return
        
    Returns:
        List of document dicts with content, metadata, and score
    """
    # Convert to numpy array for cache key generation
    if not isinstance(query_embedding, np.ndarray):
        query_embedding = np.array(query_embedding, dtype=np.float32)

    cache_enabled = _vector_search_cache_enabled() if use_cache is None else bool(use_cache)
    if not cache_enabled:
        return await _actual_search(pool, table_name, query_embedding, top_k)
    
    # Check cache first
    cached = _search_cache.get(query_embedding, top_k)
    if cached is not None:
        logger.debug(f"Vector search cache hit for table={table_name}, top_k={top_k}")
        return cached
    
    logger.debug(f"Vector search cache miss for table={table_name}, top_k={top_k}")
    
    # Perform actual search
    results = await _actual_search(pool, table_name, query_embedding, top_k)
    
    # Cache results
    _search_cache.set(query_embedding, top_k, results)
    
    return results
