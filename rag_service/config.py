from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_token: str | None = Field(default=None, alias="API_TOKEN")

    postgres_host: str = Field(default="db", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="postgres", alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", alias="POSTGRES_PASSWORD")

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    queue_name: str = Field(default="rag-pipeline", alias="QUEUE_NAME")
    query_timeout_seconds: int = Field(default=60, alias="QUERY_TIMEOUT_SECONDS")

    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    chat_model: str = Field(default="gpt-5-nano", alias="CHAT_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    # LLM sampling / output control (set explicitly for benchmark parity)
    llm_temperature: float | None = Field(default=1, alias="LLM_TEMPERATURE")
    llm_top_p: float | None = Field(default=1, alias="LLM_TOP_P")
    llm_max_completion_tokens: int | None = Field(default=32768, alias="LLM_MAX_COMPLETION_TOKENS")

    llm_stub: bool = Field(default=False, alias="LLM_STUB")
    retrieval_only: bool = Field(default=False, alias="RETRIEVAL_ONLY")
    timing_log_dir: str | None = Field(default=None, alias="TIMING_LOG_DIR")

    retrieve_top_k: int = Field(default=16, alias="RETRIEVE_TOP_K")
    chunk_size: int = Field(default=1000, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=150, alias="CHUNK_OVERLAP")

    watch_enabled: bool = Field(default=True, alias="WATCH_ENABLED")
    watch_path: str = Field(default="/files", alias="WATCH_PATH")
    watch_extensions: str = Field(default=".pdf,.txt,.docx,.csv,.xlsx", alias="WATCH_EXTENSIONS")
    watch_polling: bool = Field(default=True, alias="WATCH_POLLING")

    pgvector_table: str = Field(default="documents_pg", alias="PGVECTOR_TABLE")
    document_rows_table: str = Field(default="document_rows", alias="DOCUMENT_ROWS_TABLE")
    document_metadata_table: str = Field(default="document_metadata", alias="DOCUMENT_METADATA_TABLE")

    log_level: str = Field(default="info", alias="LOG_LEVEL")
    port: int = Field(default=8080, alias="PORT")

    # Chat memory settings (matching n8n behavior)
    chat_memory_enabled: bool = Field(default=True, alias="CHAT_MEMORY_ENABLED")
    chat_memory_table: str = Field(default="chat_history", alias="CHAT_MEMORY_TABLE")
    chat_memory_limit: int = Field(default=20, alias="CHAT_MEMORY_LIMIT")

    # Timing logs
    rag_timings_on_error_only: bool = Field(default=False, alias="RAG_TIMINGS_ON_ERROR_ONLY")

    # Optional audit instrumentation (disabled for performance runs)
    log_openai_usage: bool = Field(default=False, alias="LOG_OPENAI_USAGE")

    # Embedding cache settings (n8n-aligned in-process LRU caching)
    embedding_cache_maxsize: int = Field(default=1000, alias="EMBEDDING_CACHE_MAXSIZE")
    embedding_cache_enabled: bool = Field(default=True, alias="EMBEDDING_CACHE_ENABLED")

    # Vector search cache settings (in-process TTL caching)
    vector_search_cache_enabled: bool = Field(default=True, alias="VECTOR_SEARCH_CACHE_ENABLED")

    # LLM response cache settings (Task 2.2 - n8n-aligned execution result caching)
    llm_cache_enabled: bool = Field(default=True, alias="LLM_CACHE_ENABLED")
    llm_cache_maxsize: int = Field(default=500, alias="LLM_CACHE_MAXSIZE")
    llm_cache_ttl_seconds: int = Field(default=900, alias="LLM_CACHE_TTL_SECONDS")  # 15 minutes

    # Semantic LLM cache settings (embedding+context semantic cache)
    semantic_llm_cache_enabled: bool = Field(default=True, alias="SEMANTIC_LLM_CACHE_ENABLED")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
