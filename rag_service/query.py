from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from .embeddings import EmbeddingClient
from .llm import ChatClient
from .vector_store import search
from .models import ContextChunk, QueryResponse
from .chat_memory import (
    ensure_chat_memory_table,
    get_chat_history,
    save_chat_message,
    format_history_for_llm,
)
from .cache import get_cached_llm_response, cache_llm_response


def _timing_log_path(settings, endpoint: str) -> Path | None:
    if not settings.timing_log_dir:
        return None
    return Path(settings.timing_log_dir) / f"timings-{endpoint}.jsonl"


def write_timing_log(settings, entry: dict, endpoint: str = "rag") -> None:
    path = _timing_log_path(settings, endpoint)
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


async def run_query(request, settings, pool) -> QueryResponse:
    request_id = request.request_id or str(uuid.uuid4())
    start_ts = time.monotonic()
    retrieval_ms = None
    llm_ms = None
    post_ms = None
    chat_memory_read_ms = None
    chat_memory_write_ms = None
    chat_memory_messages_count = 0
    status = "ok"
    error_type = None
    answer: str = ""
    contexts = []
    retrieve_top_k_limit = int(getattr(settings, "retrieve_top_k", 16) or 16)
    retrieve_top_k_used = max(retrieve_top_k_limit - 1, 1)
    
    # Metrics to return for Prometheus tracking
    total_prompt_tokens = 0
    total_completion_tokens = 0
    llm_cache_hit = None

    # Optional audit instrumentation (disabled by default)
    openai_chat_calls = 0
    openai_chat_prompt_tokens = 0
    openai_chat_completion_tokens = 0
    openai_chat_total_tokens = 0
    openai_embedding_calls = 0
    openai_embedding_total_tokens = 0

    mode = "full"
    if settings.retrieval_only:
        mode = "retrieval_only"
    elif settings.llm_stub:
        mode = "stub"

    def log_timing():
        end_ts = time.monotonic()
        entry = {
            "request_id": request_id,
            "endpoint": "rag",
            "mode": mode,
            "status": status,
            "error_type": error_type,
            "prompt_id": request.prompt_id,
            "session_id": request.sessionId,
            "request_meta": request.request_meta,
            "queue_wait_ms": request.queue_wait_ms,
            "retrieval_ms": retrieval_ms,
            "llm_ms": llm_ms,
            "post_ms": post_ms,
            "retrieve_top_k_limit": retrieve_top_k_limit,
            "retrieve_top_k_used": retrieve_top_k_used,
            "retrieved_chunks": len(contexts),
            "chat_memory_read_ms": chat_memory_read_ms,
            "chat_memory_write_ms": chat_memory_write_ms,
            "chat_memory_messages_count": chat_memory_messages_count,
            "openai_chat_calls": openai_chat_calls if settings.log_openai_usage else None,
            "openai_chat_prompt_tokens": openai_chat_prompt_tokens if settings.log_openai_usage else None,
            "openai_chat_completion_tokens": openai_chat_completion_tokens if settings.log_openai_usage else None,
            "openai_chat_total_tokens": openai_chat_total_tokens if settings.log_openai_usage else None,
            "openai_embedding_calls": openai_embedding_calls if settings.log_openai_usage else None,
            "openai_embedding_total_tokens": openai_embedding_total_tokens if settings.log_openai_usage else None,
            "total_ms": int((end_ts - start_ts) * 1000),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        if settings.rag_timings_on_error_only and entry["status"] == "ok":
            return
        write_timing_log(settings, entry)

    try:
        # Ensure chat memory table exists (if enabled)
        if settings.chat_memory_enabled:
            await ensure_chat_memory_table(pool)
        
        def _as_meta(obj):
            if isinstance(obj, dict):
                return obj
            if isinstance(obj, str):
                try:
                    return json.loads(obj)
                except Exception:
                    return {"raw": obj}
            return {}

        async def retrieve_contexts(query_text: str) -> tuple[list[ContextChunk], list[float]]:
            nonlocal retrieval_ms
            nonlocal openai_embedding_calls, openai_embedding_total_tokens
            retrieval_start = time.monotonic()
            embedder = EmbeddingClient(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                base_url=settings.openai_base_url,
            )
            query_embedding = (await embedder.embed([query_text]))[0]

            if settings.log_openai_usage:
                openai_embedding_calls += 1
                if embedder.last_usage:
                    try:
                        openai_embedding_total_tokens += int(embedder.last_usage.get("total_tokens") or 0)
                    except Exception:
                        pass

            # Parity note: In n8n, the PGVector node is configured with topK=16 but observed
            # to return 15 items. For benchmark parity, we query the configured limit but only
            # use (limit - 1) contexts.
            results = list(
                await search(
                    pool,
                    settings.pgvector_table,
                    query_embedding,
                    retrieve_top_k_limit,
                    use_cache=bool(getattr(settings, "vector_search_cache_enabled", True)),
                )
            )
            results = results[:retrieve_top_k_used]

            retrieval_ms = int((time.monotonic() - retrieval_start) * 1000)
            contexts = [
                ContextChunk(
                    file_id=_as_meta(row["metadata"]).get("file_id", ""),
                    title=_as_meta(row["metadata"]).get("file_title"),
                    text=row["content"],
                    score=float(row["score"]),
                )
                for row in results
            ]
            return contexts, query_embedding

        if settings.retrieval_only:
            contexts, _ = await retrieve_contexts(request.chatInput)
            answer = "retrieval-only mode: no LLM call executed."
            return QueryResponse(answer=answer)

        post_start = time.monotonic()
        if settings.llm_stub:
            contexts, _ = await retrieve_contexts(request.chatInput)
            answer = "stubbed response: no LLM call executed."
        else:
            # Retrieve chat history before LLM call (if enabled and session exists)
            history_messages = None
            if settings.chat_memory_enabled and request.sessionId:
                history, chat_memory_read_ms = await get_chat_history(
                    pool,
                    request.sessionId,
                    limit=settings.chat_memory_limit,
                )
                history_messages = format_history_for_llm(history)
                chat_memory_messages_count = len(history_messages)

            llm = ChatClient(
                api_key=settings.openai_api_key,
                model=settings.chat_model,
                base_url=settings.openai_base_url,
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
                max_completion_tokens=settings.llm_max_completion_tokens,
                use_cache=bool(getattr(settings, "semantic_llm_cache_enabled", True)),
            )

            def _accumulate_chat_usage():
                nonlocal openai_chat_calls, openai_chat_prompt_tokens, openai_chat_completion_tokens, openai_chat_total_tokens
                nonlocal total_prompt_tokens, total_completion_tokens
                if not settings.log_openai_usage:
                    return
                openai_chat_calls += 1
                usage = llm.last_usage or {}
                try:
                    prompt = int(usage.get("prompt_tokens") or 0)
                    completion = int(usage.get("completion_tokens") or 0)
                    total = int(usage.get("total_tokens") or 0)
                    openai_chat_prompt_tokens += prompt
                    openai_chat_completion_tokens += completion
                    openai_chat_total_tokens += total
                    # Also track in metrics for Prometheus
                    total_prompt_tokens += prompt
                    total_completion_tokens += completion
                except Exception:
                    pass

            # PHASE 3A: Single-call pattern with structured output
            llm_start = time.monotonic()
            
            # Check LLM response cache first (only for deterministic responses, temp=0)
            cache_hit = False
            cached_answer: str | None = None
            contexts_texts: list[str] = []
            
            if settings.llm_cache_enabled:
                # Try to get cached response (only works if temperature=0)
                cached_answer = get_cached_llm_response(
                    request.chatInput, 
                    contexts_texts,  # Will be populated after retrieval
                    settings.chat_model,
                    settings.llm_temperature
                )
                if cached_answer:
                    cache_hit = True
                    llm_cache_hit = True
                    answer = str(cached_answer)
                    llm_ms = int((time.monotonic() - llm_start) * 1000)
            
            if not cache_hit:
                llm_cache_hit = False
                # Single LLM call to analyze query and determine routing
                analysis = await llm.analyze_query(
                    request.chatInput,
                    history_messages=history_messages,
                )
                _accumulate_chat_usage()
                
                if analysis.needs_retrieval:
                    # Use the optimized search query from the analysis
                    search_query = analysis.retrieval_query or request.chatInput
                    
                    # Retrieve documents
                    contexts, query_embedding = await retrieve_contexts(search_query)
                    
                    # Generate answer using second LLM call (matching n8n behavior)
                    answer = await llm.generate(
                        request.chatInput,
                        contexts=[{"file_id": c.file_id, "text": c.text} for c in contexts],
                        history_messages=history_messages,
                        query_embedding=query_embedding,
                    )
                    _accumulate_chat_usage()
                else:
                    # Use direct answer from structured output
                    answer = analysis.direct_answer or "I don't have enough information to answer that."
                    
                    # Cache the response if deterministic (temperature=0)
                    if settings.llm_cache_enabled:
                        cache_llm_response(
                            request.chatInput,
                            contexts_texts,
                            settings.chat_model,
                            str(answer),
                            settings.llm_temperature
                        )
            
            llm_ms = int((time.monotonic() - llm_start) * 1000)

            # Save user query and AI response to chat history
            if settings.chat_memory_enabled and request.sessionId:
                write_start = time.monotonic()
                await save_chat_message(
                    pool,
                    request.sessionId,
                    "human",
                    request.chatInput,
                )
                await save_chat_message(
                    pool,
                    request.sessionId,
                    "ai",
                    answer,
                )
                chat_memory_write_ms = int((time.monotonic() - write_start) * 1000)

        post_ms = int((time.monotonic() - post_start) * 1000)

        # Contract: never return an empty answer string.
        # Some models can spend the entire token budget on internal reasoning and produce
        # no visible content; this breaks both audit and benchmark checks.
        answer = (answer or "").strip()
        if not answer:
            answer = "I don't have enough information to answer that."

        # Return QueryResponse with metrics stored for Prometheus tracking and k6 correlation analysis
        response = QueryResponse(
            answer=answer,
            prompt_tokens=total_prompt_tokens if total_prompt_tokens > 0 else None,
            completion_tokens=total_completion_tokens if total_completion_tokens > 0 else None,
            total_tokens=(total_prompt_tokens + total_completion_tokens) if (total_prompt_tokens > 0 or total_completion_tokens > 0) else None,
        )
        # Store cache hit metric internally
        response._metrics_cache_hit = llm_cache_hit
        return response
    except Exception as exc:
        status = "error"
        error_type = type(exc).__name__
        raise
    finally:
        log_timing()
