#!/usr/bin/env bash
# Bootstrap helpers for benchmark runner scripts.

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "Error: This file is a library and should not be executed directly." >&2
  exit 1
fi

init_run_context() {
  RUN_TS="${BENCH_RUN_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"
  RESULTS_RELATIVE_DIR="${BENCH_RESULTS_RELATIVE_DIR:-results/run_${RUN_TS}}"
  if [[ "$RESULTS_RELATIVE_DIR" = /* ]]; then
    die "BENCH_RESULTS_RELATIVE_DIR must be bench-relative, got absolute path: $RESULTS_RELATIVE_DIR"
  fi
  RESULTS_RELATIVE_DIR="${RESULTS_RELATIVE_DIR#./}"
  RESULTS_DIR="$BENCH_DIR/$RESULTS_RELATIVE_DIR"
  CONTAINER_RESULTS_DIR="/bench/$RESULTS_RELATIVE_DIR"
  export RUN_TS
  export HOST_UID
  export HOST_GID
  HOST_UID=$(id -u)
  HOST_GID=$(id -g)
  RUN_START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  mkdir -p "$RESULTS_DIR"
  chmod -R a+rwx "$BENCH_DIR/results" || log_warn "Could not chmod $BENCH_DIR/results; check ownership"
}

init_compose_paths() {
  COMPOSE_BASE="$ROOT_DIR/docker-compose.yml"
  COMPOSE_BENCH="$ROOT_DIR/docker-compose.bench.yml"
  if command -v cygpath >/dev/null 2>&1; then
    COMPOSE_BASE=$(cygpath -w "$COMPOSE_BASE")
    COMPOSE_BENCH=$(cygpath -w "$COMPOSE_BENCH")
  fi
}

init_target_endpoint_context() {
  BENCH_MODE="${BENCH_MODE:-perf}"
  case "$BENCH_MODE" in
    perf|profile)
      ;;
    *)
      die "BENCH_MODE must be 'perf' or 'profile', got: $BENCH_MODE"
      ;;
  esac
  export BENCH_MODE

  TARGET_ENDPOINT="${BENCH_TARGET_ENDPOINT:-}"
  case "$TARGET_ENDPOINT" in
    rag|n8n)
      ;;
    "")
      die "BENCH_TARGET_ENDPOINT must be set to 'rag' or 'n8n'"
      ;;
    *)
      die "BENCH_TARGET_ENDPOINT must be 'rag' or 'n8n', got: $TARGET_ENDPOINT"
      ;;
  esac
  export BENCH_TARGET_ENDPOINT="$TARGET_ENDPOINT"
}

init_pair_context() {
  BENCH_PARENT_COMPARE_ID="${BENCH_PARENT_COMPARE_ID:-}"
  export BENCH_PARENT_COMPARE_ID
  BENCH_CHILD_BATCH_ID="${BENCH_CHILD_BATCH_ID:-run_${RUN_TS}-${TARGET_ENDPOINT}}"
  export BENCH_CHILD_BATCH_ID
  BENCH_PAIR_REP="${BENCH_PAIR_REP:-}"
  export BENCH_PAIR_REP
  BENCH_PAIR_ORDER="${BENCH_PAIR_ORDER:-}"
  export BENCH_PAIR_ORDER
  BENCH_PAIR_PROMPT_SEED="${BENCH_PAIR_PROMPT_SEED:-${PROMPT_BASE_SEED:-}}"
  export BENCH_PAIR_PROMPT_SEED
}

init_bench_mode_context() {
  RUN_N8N_TIMINGS=0
  if [ "$BENCH_MODE" = "profile" ]; then
    export TIMING_LOG_DIR="$CONTAINER_RESULTS_DIR"
    export N8N_EXECUTIONS_DATA_SAVE_ON_SUCCESS="all"
    RUN_N8N_TIMINGS=1
  else
    export TIMING_LOG_DIR=""
    export N8N_EXECUTIONS_DATA_SAVE_ON_SUCCESS="none"
  fi
}

init_artifact_paths() {
  RUNS_FILE="$RESULTS_DIR/runs.jsonl"
  IMAGES_FILE="$RESULTS_DIR/docker_images.json"
  MANIFEST_FILE="$RESULTS_DIR/manifest.json"
  N8N_TIMINGS_FILE="$RESULTS_DIR/n8n_timings.jsonl"
  ANALYSIS_DIR="$RESULTS_DIR/analysis"
  RAG_LOG_FILE="$RESULTS_DIR/rag-pipeline.log"
  DB_FP_PRE_FILE="$RESULTS_DIR/db_fingerprint_pre.json"
  DB_FP_POST_FILE="$RESULTS_DIR/db_fingerprint_post.json"
  COMPOSE_PS_FILE="$RESULTS_DIR/compose_ps.json"
  RAG_PIP_FREEZE_FILE="$RESULTS_DIR/pip_freeze_rag-pipeline.txt"
  RAG_RUNTIME_ENV_FILE="$RESULTS_DIR/rag_runtime_env.txt"
  N8N_WORKFLOW_SHA_FILE="$RESULTS_DIR/n8n_workflow_chatbot_sha256.txt"
  SOURCE_FP_FILE="$RESULTS_DIR/source_fingerprint.json"
  N8N_WORKFLOW_SNAPSHOT_FILE="$RESULTS_DIR/n8n_workflow_runtime_snapshot.json"
  N8N_CONSTRAINTS_FILE="$RESULTS_DIR/n8n_constraints_validation.json"
  BOUNDARY_AUDIT_REPORT_FILE="$RESULTS_DIR/boundary_audit_report.json"
  THESIS_VALIDATION_FILE="$RESULTS_DIR/thesis_batch_validation.json"
}

attach_boundary_audit_report_if_present() {
  if [ -n "${BENCH_BOUNDARY_AUDIT_REPORT_PATH:-}" ]; then
    if [ -f "$BENCH_BOUNDARY_AUDIT_REPORT_PATH" ]; then
      cp "$BENCH_BOUNDARY_AUDIT_REPORT_PATH" "$BOUNDARY_AUDIT_REPORT_FILE"
    else
      die "BENCH_BOUNDARY_AUDIT_REPORT_PATH set but file not found: $BENCH_BOUNDARY_AUDIT_REPORT_PATH"
    fi
  fi
}

record_n8n_workflow_hash() {
  local n8n_workflow_file="$ROOT_DIR/n8n_workflows/PGVector/chatbot.json"
  if [ -f "$n8n_workflow_file" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum "$n8n_workflow_file" > "$N8N_WORKFLOW_SHA_FILE" || true
    elif command -v shasum >/dev/null 2>&1; then
      shasum -a 256 "$n8n_workflow_file" > "$N8N_WORKFLOW_SHA_FILE" || true
    else
      log_warn "Neither sha256sum nor shasum found; skipping n8n workflow hash"
    fi
  else
    log_warn "n8n workflow export missing: $n8n_workflow_file"
  fi
}

load_runtime_benchmark_config() {
  BOOT_WAIT="${BENCH_BOOT_WAIT:-30}"
  N8N_WORKER_COUNT="${BENCH_N8N_WORKERS:-5}"
  STRICT="${BENCH_STRICT:-1}"

  ARRIVAL_DURATION="${BENCH_ARRIVAL_DURATION:-5m}"
  ARRIVAL_TIME_UNIT="${BENCH_ARRIVAL_TIME_UNIT:-1m}"
  ARRIVAL_PREALLOCATED_VUS="${BENCH_ARRIVAL_PREALLOCATED_VUS:-100}"
  ARRIVAL_MAX_VUS="${BENCH_ARRIVAL_MAX_VUS:-600}"

  PROMPTS_CONTAINER="${BENCH_PROMPTS_PATH:-/bench/prompts.json}"
  PROMPTS_HOST="$PROMPTS_CONTAINER"
  if [[ "$PROMPTS_CONTAINER" == /bench/* ]]; then
    PROMPTS_HOST="$BENCH_DIR/${PROMPTS_CONTAINER#/bench/}"
  fi

  MINIMAL_STACK="${BENCH_MINIMAL_STACK:-1}"
  CACHE_REGIME="${BENCH_CACHE_REGIME:-warm}"
  COLD_RESET_WAIT="${BENCH_COLD_RESET_WAIT:-10}"
  COLD_RESET_N8N_WORKERS="${BENCH_COLD_RESET_N8N_WORKERS:-1}"
}

validate_runtime_benchmark_config() {
  check_file_nonempty "$PROMPTS_HOST" "prompts"

  case "$CACHE_REGIME" in
    warm|cold)
      ;;
    *)
      die "BENCH_CACHE_REGIME must be 'warm' or 'cold', got: $CACHE_REGIME"
      ;;
  esac

  if ! [[ "$COLD_RESET_WAIT" =~ ^[0-9]+$ ]]; then
    die "BENCH_COLD_RESET_WAIT must be an integer seconds value, got: $COLD_RESET_WAIT"
  fi

  case "$COLD_RESET_N8N_WORKERS" in
    0|1)
      ;;
    *)
      die "BENCH_COLD_RESET_N8N_WORKERS must be 0 or 1, got: $COLD_RESET_N8N_WORKERS"
      ;;
  esac
}

initialize_benchmark_context() {
  load_env_defaults "$BENCH_DIR/.env"
  init_run_context
  init_compose_paths
  init_target_endpoint_context
  init_pair_context
  init_bench_mode_context
  init_artifact_paths
  attach_boundary_audit_report_if_present
  if [ "${BENCH_REQUIRE_BOUNDARY_AUDIT:-0}" = "1" ]; then
    require_boundary_audit_inputs
  fi
  record_n8n_workflow_hash
  load_runtime_benchmark_config
  validate_runtime_benchmark_config
}
