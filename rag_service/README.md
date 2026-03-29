# RAG Pipeline Service

FastAPI service aligned with the n8n agentic RAG flow.

- `/query` executes synchronously (structured decision -> optional retrieval -> answer generation) using a local subprocess pool (ProcessPoolExecutor) for query execution.
- `/ingest` and `/delete` are background jobs executed via Redis + RQ.

Uses Postgres/pgvector for storage and Redis for background job queueing.

## Endpoints
- `POST /ingest` `{file_id, title?, url?, type?, content?, path?, schema?, rows?}` queues ingestion.
- `POST /delete` `{file_id}` queues deletion.
- `POST /query` `{chatInput, sessionId?}` performs agentic RAG (structured analysis -> optional retrieval -> answer generation) synchronously (direct execution; not an RQ job).
  - Response contract (benchmark): `{ "answer": "..." }` (no retrieved contexts returned)
  - Response header: `X-Request-Id`
- `GET /health`, `GET /metrics`.

Authentication: Bearer token via `API_TOKEN` (if unset, endpoints are open).

## Runtime Model

Container entrypoint `rag_service/start.sh` starts:

- `WORKER_COUNT` RQ worker processes for background jobs (`/ingest`, `/delete`)
- Uvicorn for the HTTP API with `UVICORN_WORKERS`

`/query` execution runs in a ProcessPoolExecutor inside each Uvicorn worker process (currently `max_workers=4` per Uvicorn worker). `WORKER_COUNT` does not control `/query` parallelism.

## Environment
Key variables (all can be set in `.env` unless provided by compose):

- Server: `PORT`, `LOG_LEVEL`, `UVICORN_WORKERS`
- API auth: `API_TOKEN`
- DB: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Redis/RQ: `REDIS_URL`, `QUEUE_NAME`, `WORKER_COUNT`
- Models: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `EMBEDDING_MODEL`, `CHAT_MODEL`
- LLM params: `LLM_TEMPERATURE`, `LLM_TOP_P`, `LLM_MAX_COMPLETION_TOKENS`
- Query modes: `LLM_STUB`, `RETRIEVAL_ONLY`
- Chat memory: `CHAT_MEMORY_ENABLED`, `CHAT_MEMORY_LIMIT` (`CHAT_MEMORY_TABLE` currently ignored; table name is `chat_history`)
- Query: `QUERY_TIMEOUT_SECONDS`
- Retrieval: `RETRIEVE_TOP_K`
- Caching (in-process): `LLM_CACHE_ENABLED` is honored; cache sizes/TTLs are currently fixed in code (embedding LRU=1000; LLM cache max=500, ttl=900s). `EMBEDDING_CACHE_ENABLED`, `EMBEDDING_CACHE_MAXSIZE`, `LLM_CACHE_MAXSIZE`, `LLM_CACHE_TTL_SECONDS` are currently not wired.
- Watcher (optional): `WATCH_ENABLED`, `WATCH_PATH`, `WATCH_EXTENSIONS`, `WATCH_POLLING`
- Timing logs: `TIMING_LOG_DIR`, `RAG_TIMINGS_ON_ERROR_ONLY`
- Optional audit logging: `LOG_OPENAI_USAGE` (token/usage fields in timing logs)
- RAG tables: `PGVECTOR_TABLE`, `DOCUMENT_ROWS_TABLE`, `DOCUMENT_METADATA_TABLE`
- Chunking: `CHUNK_SIZE`, `CHUNK_OVERLAP`
- Tracing (optional): `OTEL_TRACES_EXPORTER`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_SERVICE_VERSION`, `OTEL_SERVICE_NAMESPACE`

## Running locally
```bash
docker build -t rag-pipeline -f rag_service/Dockerfile .
docker run --rm -p 8080:8080 --env-file .env -v ${PWD}/rag/files:/files rag-pipeline
```

## Database prerequisites

The service auto-creates the pgvector table (`PGVECTOR_TABLE`, default `documents_pg`) and the chat-memory table (`chat_history`, when `CHAT_MEMORY_ENABLED=true`).

You must create `DOCUMENT_METADATA_TABLE` and `DOCUMENT_ROWS_TABLE` yourself (the service assumes they exist). Minimal schema:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS document_metadata (
  id text PRIMARY KEY,
  title text NOT NULL,
  url text,
  schema jsonb
);

CREATE TABLE IF NOT EXISTS document_rows (
  id bigserial PRIMARY KEY,
  dataset_id text NOT NULL,
  row_data jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_rows_dataset_id ON document_rows(dataset_id);
```

## Notes
- Files dropped into host `./rag/files` are available inside the container at `/files` for ingestion via `path`.
- RQ workers process the `rag-pipeline` queue jobs for `/ingest` and `/delete`.
- `/query` does not enqueue an RQ job; it runs directly in the API process via a subprocess pool and is bounded by `QUERY_TIMEOUT_SECONDS`.
- Chat memory parity with n8n is implemented using the shared `chat_history` table.
- In the base `docker-compose.yml`, `rag-pipeline` is internal-only (no host `ports:`); access it from other containers via `http://rag-pipeline:8080` or add a port mapping.
- PDF OCR fallback uses Tesseract (`pytesseract`); the current Docker image does not install `tesseract-ocr`.

Benchmark parity notes:

- `RETRIEVE_TOP_K=16` is used to match n8n's PGVector tool configuration; the service uses 15 contexts for answer generation (limit - 1) to mirror observed n8n behavior.
