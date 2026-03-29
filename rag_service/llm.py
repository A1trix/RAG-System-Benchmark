from typing import Sequence, Any, Optional
import json
import logging

from openai import AsyncOpenAI
import openai

from .embeddings import _clean_base_url
from .llm_cache import get_cache, SemanticLLMCache
from .models import RAGDecision
from .circuit_breaker import get_llm_circuit, CircuitBreakerOpenError


logger = logging.getLogger(__name__)

_PARSE_FINISH_ERROR_NAMES = {
    "LengthFinishReasonError",
    "ContentFilterFinishReasonError",
}

_TRANSIENT_OPENAI_ERRORS = tuple(
    cls
    for cls in (
        getattr(openai, "RateLimitError", None),
        getattr(openai, "APITimeoutError", None),
        getattr(openai, "APIConnectionError", None),
        getattr(openai, "InternalServerError", None),
    )
    if isinstance(cls, type)
)


def _is_parse_finish_error(exc: Exception) -> bool:
    return exc.__class__.__name__ in _PARSE_FINISH_ERROR_NAMES


RAG_SYSTEM_PROMPT = "RAG Agent: Analyze question. If retrieval needed: provide query. If not: answer directly. Output JSON with needs_retrieval (bool), retrieval_query (str|null), direct_answer (str|null), confidence (0-1)."

# System prompt for answer generation (used in the second LLM call)
RAG_GENERATE_PROMPT = "You are a helpful assistant. Answer the user's question based on the provided context documents. Use the [source: filename] citations in your answer. Be concise and accurate."

RAG_TOOL_NAME = "rag_retrieve"
RAG_TOOL_DESCRIPTION = "Use RAG to look up information in the knowledgebase."


def rag_tool_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": RAG_TOOL_NAME,
            "description": RAG_TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    }


def rag_tool_choice() -> dict[str, Any]:
    return {"type": "function", "function": {"name": RAG_TOOL_NAME}}


def format_answer_from_documents(documents: list, question: str) -> str:
    """Format answer from retrieved documents without LLM call."""
    if not documents:
        return "I couldn't find relevant information."
    
    # Extract top 2 most relevant passages
    passages = []
    for doc in documents[:2]:
        content = doc.get('content', doc.get('text', ''))[:400]
        source = doc.get('file_id', doc.get('source', 'unknown'))
        passages.append(f"[source: {source}] {content}")
    
    return f"Based on the available information: {' '.join(passages)}"


class ChatClient:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_completion_tokens: int | None = None,
        use_cache: bool = True,
    ):
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_completion_tokens = max_completion_tokens
        self.use_cache = use_cache
        self.last_usage: dict[str, int | str | None] | None = None
        self.usage_history: list[dict[str, int | str | None]] = []
        self._cache: SemanticLLMCache | None = None
        if use_cache:
            self._cache = get_cache()
        safe_base = _clean_base_url(base_url)
        if safe_base:
            self.client = AsyncOpenAI(api_key=api_key, base_url=safe_base) if api_key else AsyncOpenAI(base_url=safe_base)
        else:
            self.client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

    def _chat_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.temperature is not None:
            kwargs["temperature"] = float(self.temperature)
        if self.top_p is not None:
            kwargs["top_p"] = float(self.top_p)
        if self.max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = int(self.max_completion_tokens)
        return kwargs

    async def _call_chat_completions(self, **kwargs: Any) -> Any:
        """Make chat.completions.create call with circuit breaker protection."""
        circuit = get_llm_circuit()
        
        async def _make_request():
            return await self.client.chat.completions.create(**kwargs)
        
        return await circuit.call(_make_request)

    async def _call_chat_completions_parse(self, **kwargs: Any) -> Any:
        """Make beta.chat.completions.parse call with circuit breaker protection."""
        circuit = get_llm_circuit()
        
        async def _make_request():
            return await self.client.beta.chat.completions.parse(**kwargs)
        
        return await circuit.call(_make_request)

    def _capture_usage(self, response: Any, stage: str) -> None:
        usage = getattr(response, "usage", None)
        if not usage:
            self.last_usage = None
            return

        def _as_int(attr: str) -> int | None:
            try:
                value = getattr(usage, attr, None)
                return int(value) if value is not None else None
            except Exception:
                return None

        entry: dict[str, int | str | None] = {
            "stage": stage,
            "prompt_tokens": _as_int("prompt_tokens"),
            "completion_tokens": _as_int("completion_tokens"),
            "total_tokens": _as_int("total_tokens"),
        }
        self.last_usage = entry
        self.usage_history.append(entry)

    async def analyze_query(
        self,
        question: str,
        history_messages: list[dict] | None = None,
    ) -> RAGDecision:
        """
        Single LLM call to analyze query and determine routing.
        Uses structured output with gpt-5-nano for efficient single-call pattern.
        """
        messages = self.build_messages(question, history_messages)

        def _fallback(confidence: float = 0.35) -> RAGDecision:
            return RAGDecision(
                needs_retrieval=True,
                retrieval_query=question,
                direct_answer=None,
                confidence=confidence,
            )

        try:
            response = await self._call_chat_completions_parse(
                model=self.model,
                messages=messages,
                response_format=RAGDecision,
                **self._chat_kwargs(),
            )
            self._capture_usage(response, stage="single_call")

            parsed = response.choices[0].message.parsed
            if parsed is None:
                return _fallback(0.5)

            if isinstance(parsed, str):
                try:
                    data = json.loads(parsed)
                    return RAGDecision(**data)
                except Exception:
                    return _fallback(0.45)

            return parsed
        except Exception as exc:
            if _is_parse_finish_error(exc):
                completion = getattr(exc, "completion", None)
                if completion is not None:
                    self._capture_usage(completion, stage="single_call_truncated")
                logger.warning(
                    "chat.completions.parse ended early (%s); using retrieval fallback",
                    exc.__class__.__name__,
                )
                return _fallback(0.25)

            if _TRANSIENT_OPENAI_ERRORS and isinstance(exc, _TRANSIENT_OPENAI_ERRORS):
                logger.warning("Transient OpenAI error in analyze_query", exc_info=True)
                return _fallback(0.2)

            if exc.__class__.__name__ in {"APIStatusError", "OpenAIError"}:
                logger.exception("OpenAI SDK/API error in analyze_query")
                return _fallback(0.2)

            logger.exception("Unexpected analyze_query error")
            return _fallback(0.15)

    async def generate(
        self,
        question: str,
        contexts: Sequence[dict],
        history_messages: list[dict] | None = None,
        query_embedding: list[float] | None = None,
    ) -> str:
        # Extract context document IDs for cache key
        context_ids = [ctx.get('file_id') for ctx in contexts if ctx.get('file_id')]

        # Check cache if enabled and we have embedding + contexts
        if (
            self.use_cache
            and self._cache is not None
            and query_embedding is not None
            and context_ids
            and not history_messages  # Don't cache when history is present
        ):
            cached_response = self._cache.get(
                query_embedding=query_embedding,
                context_ids=context_ids,
                temperature=self.temperature,
                top_p=self.top_p,
                max_completion_tokens=self.max_completion_tokens,
            )
            if cached_response is not None:
                # Return cached response without API call
                return cached_response

        # Format contexts with source citation [source: filename]
        context_lines = []
        for ctx in contexts:
            source = ctx.get('file_id', 'unknown')
            text = ctx.get('text', '')
            context_lines.append(f"[source: {source}] {text}")
        context_block = "\n\n".join(context_lines)

        # Build messages list with answer generation prompt (not the routing prompt)
        messages = [{"role": "system", "content": RAG_GENERATE_PROMPT}]

        # Add chat history if provided (matching n8n behavior)
        if history_messages:
            messages.extend(history_messages)

        # Add current question with context
        messages.append({
            "role": "user",
            "content": f"Question: {question}\n\nContext:\n{context_block}"
        })

        response = await self._call_chat_completions(
            model=self.model,
            messages=messages,
            **self._chat_kwargs(),
        )
        self._capture_usage(response, stage="generate")
        content = response.choices[0].message.content or ""

        # Store in cache if enabled and conditions are met
        if (
            self.use_cache
            and self._cache is not None
            and query_embedding is not None
            and context_ids
            and not history_messages
        ):
            self._cache.set(
                query_embedding=query_embedding,
                context_ids=context_ids,
                response=content,
                temperature=self.temperature,
                top_p=self.top_p,
                max_completion_tokens=self.max_completion_tokens,
            )

        return content

    def build_messages(self, question: str, history_messages: list[dict] | None = None) -> list[dict]:
        messages = [{"role": "system", "content": RAG_SYSTEM_PROMPT}]
        if history_messages:
            messages.extend(history_messages)
        messages.append({"role": "user", "content": question})
        return messages

    async def request_tool_call(
        self,
        question: str,
        history_messages: list[dict] | None = None,
        tools: list[dict] | None = None,
        tool_choice: dict | None = None,
    ) -> tuple[list[dict], Any]:
        messages = self.build_messages(question, history_messages)
        response = await self._call_chat_completions(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **self._chat_kwargs(),
        )
        self._capture_usage(response, stage="tool_call")
        return messages, response.choices[0].message

    async def finalize_with_tool_results(
        self,
        messages: list[dict],
        tool_calls: list[Any],
        tool_outputs: dict[str, str],
    ) -> str:
        tool_calls_payload = []
        for call in tool_calls:
            if isinstance(call, dict):
                call_id = call.get("id")
                call_type = call.get("type", "function")
                func = call.get("function", {})
                func_name = func.get("name")
                func_args = func.get("arguments")
            else:
                call_id = call.id
                call_type = call.type
                func_name = call.function.name
                func_args = call.function.arguments

            tool_calls_payload.append(
                {
                    "id": call_id,
                    "type": call_type,
                    "function": {
                        "name": func_name,
                        "arguments": func_args,
                    },
                }
            )

        messages.append({"role": "assistant", "tool_calls": tool_calls_payload})
        for call in tool_calls:
            call_id = call.get("id") if isinstance(call, dict) else call.id
            if not call_id:
                call_id = RAG_TOOL_NAME
            content = tool_outputs.get(call_id, "")
            messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

        response = await self._call_chat_completions(
            model=self.model,
            messages=messages,
            **self._chat_kwargs(),
        )
        self._capture_usage(response, stage="finalize")
        return response.choices[0].message.content or ""


    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics if caching is enabled."""
        if self._cache is None:
            return {"enabled": False}
        return {"enabled": True, **self._cache.get_stats()}

    def clear_cache(self) -> None:
        """Clear the semantic cache if caching is enabled."""
        if self._cache is not None:
            self._cache.clear()


def parse_tool_arguments(tool_call: Any) -> dict[str, Any]:
    args = "{}"
    if isinstance(tool_call, dict):
        args = tool_call.get("function", {}).get("arguments", "{}")
    elif tool_call and getattr(tool_call, "function", None):
        args = tool_call.function.arguments
    try:
        return json.loads(args)
    except Exception:
        return {}
