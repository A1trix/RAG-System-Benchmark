# Workflow: PGVector Chatbot

Reference export:

- `n8n_workflows/PGVector/chatbot.json`

## Entry Point

- Webhook path: `/webhook/call_openwebui`
- Method: `POST`

## Request / Response Contract (Benchmark)

- Request: JSON with `chatInput` and `sessionId` (k6 also sends `prompt_id` and `request_meta`).
- Response: JSON array; first item contains `output` (k6 extracts the answer text and validates the expected shape).

## Benchmark-Critical Parameters

- Vector search: PGVector with `topK=16`
- Models: embedding `text-embedding-3-small`, chat `gpt-5-nano`
- Reranking: none

Note: credential IDs inside the export are instance-specific. The benchmark harness snapshots the active workflow from the n8n DB at runtime (`bench/results/run_*/n8n_workflow_runtime_snapshot.json`).
