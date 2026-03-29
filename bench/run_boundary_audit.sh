#!/usr/bin/env bash
set -euo pipefail

export MSYS2_ARG_CONV_EXCL="*"
export MSYS_NO_PATHCONV=1

timestamp() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

log_info() {
  printf '[%s] INFO  %s\n' "$(timestamp)" "$*"
}

log_warn() {
  printf '[%s] WARN  %s\n' "$(timestamp)" "$*" >&2
}

log_error() {
  printf '[%s] ERROR %s\n' "$(timestamp)" "$*" >&2
}

die() {
  log_error "$*"
  exit 1
}

check_file_nonempty() {
  local file="$1"
  local label="$2"
  if [ ! -s "$file" ]; then
    die "$label missing or empty: $file"
  fi
}

trap 'die "Unexpected error in: $BASH_COMMAND"' ERR

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BENCH_DIR="$ROOT_DIR/bench"

HOST_UID=$(id -u)
HOST_GID=$(id -g)
export HOST_UID
export HOST_GID

if [ -f "$BENCH_DIR/.env" ]; then
  load_env_defaults() {
    local env_file="$1"
    [ -f "$env_file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        ''|\#*)
          continue
          ;;
      esac
      if [[ "$line" != *=* ]]; then
        continue
      fi
      local key="${line%%=*}"
      local value="${line#*=}"
      key="${key#"${key%%[![:space:]]*}"}"
      key="${key%"${key##*[![:space:]]}"}"
      if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        continue
      fi
      if [ "${!key+x}" = "x" ]; then
        continue
      fi
      eval "export $key=$value"
    done < "$env_file"
  }
  load_env_defaults "$BENCH_DIR/.env"
fi

AUDIT_PROMPTS_CONTAINER="${BOUNDARY_AUDIT_PROMPTS_PATH:-/bench/prompts.json}"
AUDIT_PROMPTS_HOST="$AUDIT_PROMPTS_CONTAINER"
if [[ "$AUDIT_PROMPTS_CONTAINER" == /bench/* ]]; then
  AUDIT_PROMPTS_HOST="$BENCH_DIR/${AUDIT_PROMPTS_CONTAINER#/bench/}"
fi
check_file_nonempty "$AUDIT_PROMPTS_HOST" "boundary audit prompts"

RUN_TS=$(date -u +%Y%m%dT%H%M%SZ)
RESULTS_DIR="$BENCH_DIR/results/boundary_${RUN_TS}"
CONTAINER_RESULTS_DIR="/bench/results/boundary_${RUN_TS}"

mkdir -p "$RESULTS_DIR"
# Best-effort permission fix for files owned by current user.
# Avoid failing on legacy root-owned artifacts from earlier runs.
if ! find "$BENCH_DIR/results" -uid "$HOST_UID" -exec chmod a+rwx {} + 2>/dev/null; then
  log_warn "Could not fully chmod owned files under $BENCH_DIR/results"
fi

# Warn once if legacy root-owned files exist (common when previous runs were executed as root).
if find "$BENCH_DIR/results" -uid 0 -print -quit 2>/dev/null | grep -q .; then
  log_warn "Detected root-owned artifacts under $BENCH_DIR/results; run: sudo chown -R $(id -u):$(id -g) $BENCH_DIR/results"
fi

COMPOSE_BASE="$ROOT_DIR/docker-compose.yml"
COMPOSE_BENCH="$ROOT_DIR/docker-compose.bench.yml"
COMPOSE_AUDIT="$ROOT_DIR/docker-compose.audit.yml"
if command -v cygpath >/dev/null 2>&1; then
  COMPOSE_BASE=$(cygpath -w "$COMPOSE_BASE")
  COMPOSE_BENCH=$(cygpath -w "$COMPOSE_BENCH")
  COMPOSE_AUDIT=$(cygpath -w "$COMPOSE_AUDIT")
fi

COMPOSE_ARGS=( -f "$COMPOSE_BASE" -f "$COMPOSE_BENCH" -f "$COMPOSE_AUDIT" )

BOOT_WAIT="${BENCH_BOOT_WAIT:-30}"
N8N_WORKER_COUNT="${BENCH_N8N_WORKERS:-1}"
MINIMAL_STACK="${BENCH_MINIMAL_STACK:-1}"
BOUNDARY_AUDIT_STRICT="${BOUNDARY_AUDIT_STRICT:-1}"
# Boundary audit always runs in validity mode (verifies models and parameters)
BOUNDARY_AUDIT_MODE="validity"

[ -n "${N8N_WORKFLOW_ID:-}" ] || die "N8N_WORKFLOW_ID must be set for boundary audit"
PRIMARY_OPENAI_CRED_ID="${N8N_OPENAI_CREDENTIAL_ID:-}"
[ -n "$PRIMARY_OPENAI_CRED_ID" ] || die "Set N8N_OPENAI_CREDENTIAL_ID for boundary audit"
AUDIT_OPENAI_CRED_ID="${N8N_AUDIT_OPENAI_CREDENTIAL_ID:-}"
[ -n "$AUDIT_OPENAI_CRED_ID" ] || die "Set N8N_AUDIT_OPENAI_CREDENTIAL_ID to a dedicated audit credential"
[ "$AUDIT_OPENAI_CRED_ID" != "$PRIMARY_OPENAI_CRED_ID" ] || die "N8N_AUDIT_OPENAI_CREDENTIAL_ID must be different from N8N_OPENAI_CREDENTIAL_ID"

export BOUNDARY_AUDIT_DIR="boundary_${RUN_TS}"
export BOUNDARY_AUDIT_RUN_ID="boundary-${RUN_TS}"

log_info "Starting boundary audit stack (run_id=$BOUNDARY_AUDIT_RUN_ID)"

compose_up_boundary_stack() {
  if [ "$MINIMAL_STACK" = "1" ]; then
    docker compose "${COMPOSE_ARGS[@]}" up -d --build \
      --scale n8n-worker="$N8N_WORKER_COUNT" \
      --scale rag-pipeline=1 \
      db db-init redis n8n n8n-worker rag-pipeline openai-proxy-rag openai-proxy-n8n
  else
    docker compose "${COMPOSE_ARGS[@]}" up -d --build \
      --scale n8n-worker="$N8N_WORKER_COUNT" \
      --scale rag-pipeline=1 \
      --scale rag-pipeline-watcher=0
  fi
}

compose_up_boundary_stack

log_info "Waiting for services to boot: ${BOOT_WAIT}s"
sleep "$BOOT_WAIT"

to_container_path() {
  local path="$1"
  if [[ "$path" == "$RESULTS_DIR"* ]]; then
    printf '%s%s' "$CONTAINER_RESULTS_DIR" "${path#"$RESULTS_DIR"}"
    return
  fi
  printf '%s' "$path"
}

bench_python() {
  docker compose "${COMPOSE_ARGS[@]}" run --rm bench-runner python "$@"
}

# Enforce dedicated audit credential usage for all OpenAI nodes in the selected workflow.
bench_python /bench/helpers/audit/n8n_set_workflow_openai_credential.py \
  --workflow-id "${N8N_WORKFLOW_ID:-}" \
  --source-credential-id "$PRIMARY_OPENAI_CRED_ID" \
  --credential-id "$AUDIT_OPENAI_CRED_ID" \
  --credential-name "${N8N_AUDIT_OPENAI_CREDENTIAL_NAME:-${N8N_OPENAI_CREDENTIAL_NAME:-}}" \
  --output "$(to_container_path "$RESULTS_DIR")/n8n_audit_credential_switch.json" || die "failed to switch n8n workflow to audit OpenAI credential"

# --- Helper: source fingerprint (no secrets) ---
SOURCE_FP_FILE="$RESULTS_DIR/source_fingerprint.json"
source_fp_container=$(to_container_path "$SOURCE_FP_FILE")
volume_args=(
  -v "$ROOT_DIR/rag_service:/src/rag_service:ro"
  -v "$ROOT_DIR/n8n_workflows:/src/n8n_workflows:ro"
  -v "$ROOT_DIR/docker-compose.yml:/src/docker-compose.yml:ro"
  -v "$ROOT_DIR/docker-compose.bench.yml:/src/docker-compose.bench.yml:ro"
)

generate_source_fingerprint() {
  docker compose "${COMPOSE_ARGS[@]}" run --rm \
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

# --- Helper: n8n workflow runtime snapshot ---
N8N_WORKFLOW_SNAPSHOT_FILE="$RESULTS_DIR/n8n_workflow_runtime_snapshot.json"
n8n_snap_container=$(to_container_path "$N8N_WORKFLOW_SNAPSHOT_FILE")

snapshot_n8n_workflow() {
  local expected_id="$1"
  local expected_name="$2"
  local output_path="$3"
  bench_python /bench/helpers/audit/n8n_workflow_snapshot.py \
    --output "$output_path" \
    --workflow-id "${N8N_WORKFLOW_ID:-}" \
    --webhook-url "${N8N_WEBHOOK_URL:-}" \
    --expected-openai-credential-id "$expected_id" \
    --expected-openai-credential-name "$expected_name" \
    --require-unique \
    --limit 10 || die "failed to snapshot n8n workflow from DB"
  check_file_nonempty "$RESULTS_DIR/$(basename "$output_path")" "n8n workflow runtime snapshot"
}

# Capture the audit-state workflow snapshot for traceability.
N8N_WORKFLOW_SNAPSHOT_AUDIT_FILE="$RESULTS_DIR/n8n_workflow_runtime_snapshot_audit.json"
n8n_snap_audit_container=$(to_container_path "$N8N_WORKFLOW_SNAPSHOT_AUDIT_FILE")
snapshot_n8n_workflow \
  "$AUDIT_OPENAI_CRED_ID" \
  "${N8N_AUDIT_OPENAI_CREDENTIAL_NAME:-${N8N_OPENAI_CREDENTIAL_NAME:-}}" \
  "$n8n_snap_audit_container"

# --- Run sequential requests ---
REQ_LOG_FILE="$RESULTS_DIR/boundary_requests.jsonl"
req_log_container=$(to_container_path "$REQ_LOG_FILE")

bench_python /bench/helpers/audit/boundary_audit_requests.py \
  --run-id "$BOUNDARY_AUDIT_RUN_ID" \
  --prompts "$AUDIT_PROMPTS_CONTAINER" \
  --prompt-count "${BOUNDARY_AUDIT_PROMPT_COUNT:-15}" \
  --rag-url "${RAG_ENDPOINT_URL:-http://rag-pipeline:8080/query}" \
  --n8n-url "${N8N_WEBHOOK_URL:-http://n8n:5678/webhook/call_openwebui}" \
  --timeout "${BOUNDARY_AUDIT_HTTP_TIMEOUT:-120}" \
  --rag-api-token "${RAG_API_TOKEN:-${API_TOKEN:-}}" \
  --n8n-auth-header "${N8N_AUTH_HEADER:-}" \
  --n8n-auth-value "${N8N_AUTH_VALUE:-}" \
  --sleep-ms "${BOUNDARY_AUDIT_SLEEP_MS:-200}" \
  --output "$req_log_container" || die "boundary request runner failed"

check_file_nonempty "$REQ_LOG_FILE" "boundary request log"

# Restore primary n8n OpenAI credential so benchmark runs can continue immediately
# with the normal credential.
bench_python /bench/helpers/audit/n8n_set_workflow_openai_credential.py \
  --workflow-id "${N8N_WORKFLOW_ID:-}" \
  --source-credential-id "$AUDIT_OPENAI_CRED_ID" \
  --credential-id "$PRIMARY_OPENAI_CRED_ID" \
  --credential-name "${N8N_OPENAI_CREDENTIAL_NAME:-}" \
  --output "$(to_container_path "$RESULTS_DIR")/n8n_post_audit_credential_restore.json" || die "failed to restore n8n workflow to primary OpenAI credential"

# Build attachment artifacts from post-restore state (what run_all.sh will validate).
generate_source_fingerprint
snapshot_n8n_workflow \
  "$PRIMARY_OPENAI_CRED_ID" \
  "${N8N_OPENAI_CREDENTIAL_NAME:-}" \
  "$n8n_snap_container"

# --- Build report from proxy logs ---
REPORT_FILE="$RESULTS_DIR/boundary_audit_report.json"
report_container=$(to_container_path "$REPORT_FILE")

PROXY_RAG_FILE="$CONTAINER_RESULTS_DIR/openai_proxy_rag.jsonl"
PROXY_N8N_FILE="$CONTAINER_RESULTS_DIR/openai_proxy_n8n.jsonl"

report_args=(
  --run-id "$BOUNDARY_AUDIT_RUN_ID"
  --proxy-rag "$PROXY_RAG_FILE"
  --proxy-n8n "$PROXY_N8N_FILE"
  --requests "$req_log_container"
  --source-fingerprint "$source_fp_container"
  --workflow-snapshot "$n8n_snap_container"
  --output "$report_container"
  --expected-chat-model "${N8N_CHAT_MODEL:-gpt-5-nano}"
  --expected-embedding-model "${N8N_EMBEDDING_MODEL:-text-embedding-3-small}"
  --require-param-evidence
  --min-proxy-ok-rate "${BOUNDARY_AUDIT_MIN_PROXY_OK_RATE:-0.99}"
)

EXPECTED_TEMP="${BOUNDARY_AUDIT_EXPECTED_TEMPERATURE:-${LLM_TEMPERATURE:-}}"
EXPECTED_TOP_P="${BOUNDARY_AUDIT_EXPECTED_TOP_P:-${LLM_TOP_P:-}}"
EXPECTED_MAX_TOK="${BOUNDARY_AUDIT_EXPECTED_MAX_COMPLETION_TOKENS:-${LLM_MAX_COMPLETION_TOKENS:-}}"

if [ -n "$EXPECTED_TEMP" ]; then
  report_args+=(--expected-temperature "$EXPECTED_TEMP")
fi
if [ -n "$EXPECTED_TOP_P" ]; then
  report_args+=(--expected-top-p "$EXPECTED_TOP_P")
fi
if [ -n "$EXPECTED_MAX_TOK" ]; then
  report_args+=(--expected-max-completion-tokens "$EXPECTED_MAX_TOK")
fi
if [ "${BOUNDARY_AUDIT_REQUIRE_ALL_USER_REQUESTS_OK:-1}" = "1" ]; then
  report_args+=(--require-all-user-requests-ok)
fi

BOUNDARY_REPORT_RC=0
build_boundary_report() {
  # boundary_audit_report.py uses exit code 2 for "report produced but failed".
  # Avoid triggering the ERR trap by capturing failures via an if-statement.
  if bench_python /bench/helpers/audit/boundary_audit_report.py "${report_args[@]}"; then
    BOUNDARY_REPORT_RC=0
  else
    BOUNDARY_REPORT_RC=$?
  fi
  return 0
}

set +e
build_boundary_report
report_rc=$BOUNDARY_REPORT_RC
set -e

check_file_nonempty "$REPORT_FILE" "boundary audit report"

if [ "$report_rc" -ne 0 ]; then
  if [ "$BOUNDARY_AUDIT_STRICT" = "1" ]; then
    die "Boundary audit report failed (exit=$report_rc). See $REPORT_FILE"
  fi
  log_warn "Boundary audit report indicates failure (see $REPORT_FILE)"
fi

log_info "Boundary audit complete: $REPORT_FILE"
log_info "Proxy logs: $RESULTS_DIR/openai_proxy_rag.jsonl and $RESULTS_DIR/openai_proxy_n8n.jsonl"
log_info "n8n audit workflow snapshot: $N8N_WORKFLOW_SNAPSHOT_AUDIT_FILE"
log_info "n8n credential restore: $RESULTS_DIR/n8n_post_audit_credential_restore.json"
log_info "Attach to an isolated comparison cohort with: export BENCH_BOUNDARY_AUDIT_REPORT_PATH=$REPORT_FILE"
