#!/usr/bin/env bash
# Reproducibility artifact helpers for benchmark runner scripts.

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "Error: This file is a library and should not be executed directly." >&2
  exit 1
fi

capture_source_fingerprint() {
  local source_fp_container
  local volume_args
  source_fp_container=$(to_container_path "$SOURCE_FP_FILE")
  volume_args=(
    -v "$ROOT_DIR/rag_service:/src/rag_service:ro"
    -v "$ROOT_DIR/n8n_workflows:/src/n8n_workflows:ro"
    -v "$ROOT_DIR/docker-compose.yml:/src/docker-compose.yml:ro"
    -v "$ROOT_DIR/docker-compose.bench.yml:/src/docker-compose.bench.yml:ro"
  )

  docker_compose_bench run --rm \
    "${volume_args[@]}" \
    bench-runner python /bench/helpers/artifacts/source_fingerprint.py \
    --root-map rag_service=/src/rag_service \
    --root-map n8n_workflows=/src/n8n_workflows \
    --root-map bench=/bench \
    --root-map docker-compose.yml=/src/docker-compose.yml \
    --root-map docker-compose.bench.yml=/src/docker-compose.bench.yml \
    --output "$source_fp_container" || die "failed to generate source fingerprint"

  check_file_nonempty "$SOURCE_FP_FILE" "source fingerprint"
}

capture_n8n_workflow_snapshot() {
  local n8n_workflow_snap_container
  n8n_workflow_snap_container=$(to_container_path "$N8N_WORKFLOW_SNAPSHOT_FILE")
  bench_python /bench/helpers/audit/n8n_workflow_snapshot.py \
    --output "$n8n_workflow_snap_container" \
    --workflow-id "${N8N_WORKFLOW_ID:-}" \
    --webhook-url "${N8N_WEBHOOK_URL:-}" \
    --expected-openai-credential-id "${N8N_OPENAI_CREDENTIAL_ID:-}" \
    --expected-openai-credential-name "${N8N_OPENAI_CREDENTIAL_NAME:-}" \
    --require-unique \
    --limit 10 || die "failed to snapshot n8n workflow from DB"

  check_file_nonempty "$N8N_WORKFLOW_SNAPSHOT_FILE" "n8n workflow runtime snapshot"
}

capture_n8n_constraints_validation() {
  local n8n_constraints_container
  local n8n_workflow_snap_container
  n8n_constraints_container=$(to_container_path "$N8N_CONSTRAINTS_FILE")
  n8n_workflow_snap_container=$(to_container_path "$N8N_WORKFLOW_SNAPSHOT_FILE")
  bench_python /bench/helpers/audit/validate_n8n_workflow_constraints.py \
    --workflow-snapshot "$n8n_workflow_snap_container" \
    --expected-chat-model "${N8N_CHAT_MODEL:-gpt-5-nano}" \
    --expected-temperature "${LLM_TEMPERATURE:-1}" \
    --expected-top-p "${LLM_TOP_P:-1}" \
    --expected-max-tokens "${LLM_MAX_COMPLETION_TOKENS:-32768}" \
    --output "$n8n_constraints_container" \
    || die "n8n workflow constraints validation failed"

  check_file_nonempty "$N8N_CONSTRAINTS_FILE" "n8n constraints validation"
}

capture_runtime_repro_artifacts() {
  docker_compose_bench ps --format json > "$COMPOSE_PS_FILE" 2>/dev/null \
    || docker_compose_bench ps > "$COMPOSE_PS_FILE" \
    || true

  docker_compose_bench_exec rag-pipeline python -m pip freeze > "$RAG_PIP_FREEZE_FILE" 2>/dev/null || true

  docker_compose_bench_exec rag-pipeline sh -c '
    echo "WORKER_COUNT=${WORKER_COUNT}";
    echo "UVICORN_WORKERS=${UVICORN_WORKERS}";
    echo "CHAT_MODEL=${CHAT_MODEL}";
    echo "EMBEDDING_MODEL=${EMBEDDING_MODEL}";
    echo "OPENAI_BASE_URL=${OPENAI_BASE_URL}";
    echo "RETRIEVE_TOP_K=${RETRIEVE_TOP_K}";
    echo "LLM_TEMPERATURE=${LLM_TEMPERATURE}";
    echo "LLM_TOP_P=${LLM_TOP_P}";
    echo "LLM_MAX_COMPLETION_TOKENS=${LLM_MAX_COMPLETION_TOKENS}";
    echo "EMBEDDING_CACHE_ENABLED=${EMBEDDING_CACHE_ENABLED}";
    echo "VECTOR_SEARCH_CACHE_ENABLED=${VECTOR_SEARCH_CACHE_ENABLED}";
    echo "SEMANTIC_LLM_CACHE_ENABLED=${SEMANTIC_LLM_CACHE_ENABLED}";
    echo "LLM_CACHE_ENABLED=${LLM_CACHE_ENABLED}";
  ' > "$RAG_RUNTIME_ENV_FILE" 2>/dev/null || true

  db_fp_pre_container=$(to_container_path "$DB_FP_PRE_FILE")
  bench_python /bench/helpers/artifacts/db_fingerprint.py --output "$db_fp_pre_container"
  check_file_nonempty "$DB_FP_PRE_FILE" "db fingerprint (pre)"
}

capture_reproducibility_artifacts() {
  capture_source_fingerprint
  capture_n8n_workflow_snapshot
  capture_n8n_constraints_validation
  validate_boundary_attachment_if_required
  capture_runtime_repro_artifacts
}
