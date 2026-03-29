#!/usr/bin/env bash
# k6 arrival-run helpers for benchmark runner scripts.

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "Error: This file is a library and should not be executed directly." >&2
  exit 1
fi

maybe_resume_k6_arrival_run() {
  local run_id="$1"
  local summary_file_host="$2"

  if [ ! -s "$summary_file_host" ]; then
    return 1
  fi

  log_info "Resume: summary exists, skipping k6 run: $run_id"
  if [ ! -s "$RUNS_FILE" ]; then
    return 1
  fi

  if check_run_id_in_file "$RUNS_FILE" "$run_id" >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

execute_k6_arrival_run() {
  local endpoint_name="$1"
  local rpm="$2"
  local repetition="$3"
  local prompt_set="$4"
  local prompts_path="$5"
  local duration_env="$6"
  local k6_settle_env="$7"
  local k6_measure_env="$8"
  local run_id="$9"
  local summary_file_container="${10}"

  cold_reset_before_main_run "$endpoint_name"
  docker_compose_bench run --rm \
    -e DURATION="$duration_env" \
    -e K6_ARR_RATE="$rpm" \
    -e K6_ARR_TIME_UNIT="$ARRIVAL_TIME_UNIT" \
    -e K6_ARR_PREALLOCATED_VUS="$ARRIVAL_PREALLOCATED_VUS" \
    -e K6_ARR_MAX_VUS="$ARRIVAL_MAX_VUS" \
    -e K6_PROMPT_SCHEDULER="arrival_global" \
    -e K6_SETTLE_SECONDS="$k6_settle_env" \
    -e K6_MEASURE_SECONDS="$k6_measure_env" \
    -e BENCH_RUN_ID="$run_id" \
    -e BENCH_PROMPT_SET="$prompt_set" \
    -e K6_PROMPTS_PATH="$prompts_path" \
    -e PROMPT_BASE_SEED="${PROMPT_BASE_SEED:-}" \
    -e PROMPT_REP="$repetition" \
    -e K6_ARTIFACT_DIR="$CONTAINER_RESULTS_DIR" \
    k6 run "/bench/k6/${endpoint_name}.js" --summary-export "$summary_file_container"
}

append_k6_arrival_record() {
  local run_id="$1"
  local endpoint_name="$2"
  local duration_env="$3"
  local k6_settle_env="$4"
  local k6_measure_env="$5"
  local start_ts="$6"
  local end_ts="$7"
  local summary_file_host="$8"
  local run_tag="$9"
  local prompt_set="${10}"
  local prompts_path="${11}"
  local run_order="${12}"
  local rpm="${13}"
  local repetition="${14}"
  local strict_for_run="${15}"
  local summary_metrics="${16}"

  local runs_file_container
  local cmd
  runs_file_container=$(to_container_path "$RUNS_FILE")
  cmd=(
    /bench/helpers/run/append_run_entry.py
    --runs-file "$runs_file_container"
    --run-id "$run_id"
    --endpoint "$endpoint_name"
    --vus "$ARRIVAL_MAX_VUS"
    --duration "$duration_env"
    --settle-seconds "$k6_settle_env"
    --measure-seconds "$k6_measure_env"
    --start "$start_ts"
    --end "$end_ts"
    --summary-file "$summary_file_host"
    --run-tag "$run_tag"
    --prompt-set "$prompt_set"
    --prompts-path "$prompts_path"
    --run-order "$run_order"
    --offered-rpm "$rpm"
    --repetition-index "$repetition"
    --target-endpoint "$TARGET_ENDPOINT"
    --child-batch-id "$BENCH_CHILD_BATCH_ID"
    --strict "$strict_for_run"
    --summary-metrics "$summary_metrics"
  )
  if [ -n "$BENCH_PARENT_COMPARE_ID" ]; then
    cmd+=(--parent-compare-id "$BENCH_PARENT_COMPARE_ID")
  fi
  if [ -n "$BENCH_PAIR_REP" ]; then
    cmd+=(--pair-rep "$BENCH_PAIR_REP")
  fi
  if [ -n "$BENCH_PAIR_ORDER" ]; then
    cmd+=(--pair-order "$BENCH_PAIR_ORDER")
  fi
  if [ -n "$BENCH_PAIR_PROMPT_SEED" ]; then
    cmd+=(--pair-prompt-seed "$BENCH_PAIR_PROMPT_SEED")
  fi
  bench_python "${cmd[@]}"

  check_file_nonempty "$RUNS_FILE" "runs file"
  check_run_id_in_file "$RUNS_FILE" "$run_id"
}

collect_optional_n8n_timings() {
  local endpoint_name="$1"
  local run_id="$2"
  local start_ts="$3"
  local end_ts="$4"

  if [ "$endpoint_name" != "n8n" ] || [ "$RUN_N8N_TIMINGS" != "1" ]; then
    return 0
  fi

  docker_compose_bench run --rm \
    -e RUN_ID="$run_id" \
    bench-runner python /bench/helpers/run/n8n_timings.py \
    --since "$start_ts" \
    --until "$end_ts" \
    --output "$CONTAINER_RESULTS_DIR/n8n_timings.jsonl" \
    --append \
    --run-id "$run_id"

  if [ -s "$N8N_TIMINGS_FILE" ]; then
    check_run_id_in_file "$N8N_TIMINGS_FILE" "$run_id"
  else
    log_warn "n8n timings file missing or empty; execution_data may be disabled"
  fi
}

run_k6_arrival() {
  local endpoint_name="$1"
  local rpm="$2"
  local repetition="${3:-1}"
  local prompt_set="${4:-in_scope}"
  local prompts_path="${5:-/bench/prompts.json}"
  local run_order="${6:-0}"
  local run_tag="${7:-arrival}"
  local settle_seconds="${8:-}"
  local measure_seconds="${9:-}"
  local run_id_ts="${10:-}"
  local strict_override="${11:-}"

  [[ "$rpm" =~ ^[0-9]+$ ]] || die "K6_ARR_RATE must be an integer RPM, got: $rpm"
  [ "$rpm" -gt 0 ] || die "K6_ARR_RATE must be > 0, got: $rpm"
  [[ "$ARRIVAL_MAX_VUS" =~ ^[0-9]+$ ]] || die "BENCH_ARRIVAL_MAX_VUS must be an integer, got: $ARRIVAL_MAX_VUS"

  local timestamp
  if [ -n "$run_id_ts" ]; then
    timestamp="$run_id_ts"
  else
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  fi
  local run_id="arrival-${endpoint_name}-${prompt_set}-${rpm}rpm-rep${repetition}-${timestamp}-${CACHE_REGIME}"
  local summary_file_container="$CONTAINER_RESULTS_DIR/${run_id}.json"
  local summary_file_host="$RESULTS_DIR/${run_id}.json"

  local start_ts
  start_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local strict_for_run="$STRICT"
  if [ -n "$strict_override" ]; then
    strict_for_run="$strict_override"
  fi

  local duration_env="$ARRIVAL_DURATION"
  local k6_settle_env="0"
  local k6_measure_env
  k6_measure_env=$(duration_to_seconds "$ARRIVAL_DURATION")
  if [ -n "$settle_seconds" ] || [ -n "$measure_seconds" ]; then
    [[ "$settle_seconds" =~ ^[0-9]+$ ]] || die "settle_seconds must be integer seconds, got: $settle_seconds"
    [[ "$measure_seconds" =~ ^[0-9]+$ ]] || die "measure_seconds must be integer seconds, got: $measure_seconds"
    [ "$measure_seconds" -gt 0 ] || die "measure_seconds must be > 0, got: $measure_seconds"
    local total_seconds=$((10#$settle_seconds + 10#$measure_seconds))
    duration_env="${total_seconds}s"
    k6_settle_env="$settle_seconds"
    k6_measure_env="$measure_seconds"
  fi

  if maybe_resume_k6_arrival_run "$run_id" "$summary_file_host"; then
    return 0
  fi

  execute_k6_arrival_run \
    "$endpoint_name" \
    "$rpm" \
    "$repetition" \
    "$prompt_set" \
    "$prompts_path" \
    "$duration_env" \
    "$k6_settle_env" \
    "$k6_measure_env" \
    "$run_id" \
    "$summary_file_container"

  check_file_nonempty "$summary_file_host" "k6 summary"
  if [ "$strict_for_run" = "1" ]; then
    check_k6_summary_strict "$summary_file_host"
  fi
  summary_metrics=$(check_k6_summary_report "$summary_file_host")

  warn_msg=$(bench_python /bench/helpers/run/k6_summary_warning.py --summary-metrics "$summary_metrics")
  if [ -n "$warn_msg" ] && [ "$strict_for_run" != "1" ]; then
    log_warn "$warn_msg"
  fi

  no_activity=$(python3 -c 'import json,sys; print(1 if json.loads(sys.argv[1]).get("no_requests_or_iterations") else 0)' "$summary_metrics" 2>/dev/null || printf '0')
  if [ "$no_activity" = "1" ]; then
    if [ "$strict_for_run" = "1" ]; then
      die "k6 recorded no requests/iterations for run_id=$run_id (strict mode)."
    fi
    log_warn "k6 recorded no requests/iterations for run_id=$run_id; marking point invalid in analysis"
  fi

  local end_ts
  end_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  append_k6_arrival_record \
    "$run_id" \
    "$endpoint_name" \
    "$duration_env" \
    "$k6_settle_env" \
    "$k6_measure_env" \
    "$start_ts" \
    "$end_ts" \
    "$summary_file_host" \
    "$run_tag" \
    "$prompt_set" \
    "$prompts_path" \
    "$run_order" \
    "$rpm" \
    "$repetition" \
    "$strict_for_run" \
    "$summary_metrics"

  collect_optional_n8n_timings "$endpoint_name" "$run_id" "$start_ts" "$end_ts"
}
