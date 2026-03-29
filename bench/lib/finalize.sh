#!/usr/bin/env bash
# Finalization helpers for benchmark runner scripts.

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "Error: This file is a library and should not be executed directly." >&2
  exit 1
fi

write_child_manifest() {
  docker_compose_bench run --rm \
    bench-runner python /bench/helpers/artifacts/manifest.py \
    --runs "$CONTAINER_RESULTS_DIR/runs.jsonl" \
    --images "$CONTAINER_RESULTS_DIR/docker_images.json" \
    --prereg "/bench/preregistration.json" \
    --batch-kind "isolated_child" \
    --target-endpoint "$TARGET_ENDPOINT" \
    --parent-compare-id "$BENCH_PARENT_COMPARE_ID" \
    --child-batch-id "$BENCH_CHILD_BATCH_ID" \
    --prompts-path "$PROMPTS_CONTAINER" \
    --smoke-rpm-list "$sweep_smoke_rpms" \
    --smoke-settle-seconds "$sweep_smoke_settle_s" \
    --smoke-measure-seconds "$sweep_smoke_measure_s" \
    --smoke-reps "$sweep_smoke_reps" \
    --primary-rpm-start "$sweep_primary_start" \
    --primary-rpm-end "$sweep_primary_end" \
    --primary-rpm-step "$sweep_primary_step" \
    --primary-settle-seconds "$sweep_primary_settle_s" \
    --primary-measure-seconds "$sweep_primary_measure_s" \
    --primary-reps "$sweep_primary_reps" \
    --stop-after-smoke "$sweep_stop_after_smoke" \
    --timeout-rate-max "$sweep_timeout_rate_max" \
    --output "$CONTAINER_RESULTS_DIR/manifest.json"

  check_file_nonempty "$MANIFEST_FILE" "manifest"
}

collect_rag_timeout_analysis_if_available() {
  docker_compose_bench logs --since "$RUN_START_TS" rag-pipeline > "$RAG_LOG_FILE" || true
  mkdir -p "$ANALYSIS_DIR"
  if [ -s "$RESULTS_DIR/timings-rag.jsonl" ]; then
    local rag_log_container
    local timings_rag_container
    local slow_requests_container
    rag_log_container=$(to_container_path "$RAG_LOG_FILE")
    timings_rag_container=$(to_container_path "$RESULTS_DIR/timings-rag.jsonl")
    slow_requests_container=$(to_container_path "$ANALYSIS_DIR/slow_requests.csv")
    bench_python /bench/helpers/analysis/analyze_timeouts.py \
      --log-file "$rag_log_container" \
      --timings "$timings_rag_container" \
      --output "$slow_requests_container" \
      --top 50 || true
    return 0
  fi

  local rag_timings_expected=0
  case "${RAG_TIMINGS_ON_ERROR_ONLY:-false}" in
    1|true|TRUE|yes|on)
      rag_timings_expected=0
      ;;
    *)
      if [ -n "${TIMING_LOG_DIR:-}" ]; then
        rag_timings_expected=1
      fi
      ;;
  esac
  if [ "$rag_timings_expected" = "1" ]; then
    log_info "timings-rag.jsonl missing or empty; timeout analysis skipped"
  fi
}

collect_post_run_artifacts() {
  db_fp_post_container=$(to_container_path "$DB_FP_POST_FILE")
  bench_python /bench/helpers/artifacts/db_fingerprint.py --output "$db_fp_post_container" --compare "$db_fp_pre_container"
  check_file_nonempty "$DB_FP_POST_FILE" "db fingerprint (post)"

  python3 "$BENCH_DIR/helpers/artifacts/collect_active_images.py" \
    --compose-ps "$COMPOSE_PS_FILE" \
    --output "$IMAGES_FILE" || die "failed to collect active docker images"
  check_file_nonempty "$IMAGES_FILE" "docker images"

  collect_rag_timeout_analysis_if_available
}

run_thesis_batch_validation_if_required() {
  if [ "${BENCH_REQUIRE_BOUNDARY_AUDIT:-0}" != "1" ]; then
    return 0
  fi
  if [ "$sweep_stop_after_smoke" = "1" ]; then
    log_info "Skipping thesis batch validation for smoke-only technical run"
    return 0
  fi

  VALIDATION_STRICT="${BENCH_VALIDATE_BATCH_STRICT:-1}"
  local results_dir_container
  results_dir_container=$(to_container_path "$RESULTS_DIR")
  rm -f "$THESIS_VALIDATION_FILE"
  if bench_python /bench/helpers/artifacts/validate_thesis_batch.py "$results_dir_container" > "$THESIS_VALIDATION_FILE"; then
    return 0
  fi

  local validation_rc=$?
  if [ -s "$THESIS_VALIDATION_FILE" ]; then
    python3 "$BENCH_DIR/helpers/run/print_failures.py" "$THESIS_VALIDATION_FILE" >&2
  fi
  return "$validation_rc"
}

finalize_child_batch() {
  collect_post_run_artifacts
  write_child_manifest

  local validation_rc=0
  if run_thesis_batch_validation_if_required; then
    validation_rc=0
  else
    validation_rc=$?
  fi

  write_child_manifest

  if [ "${BENCH_REQUIRE_BOUNDARY_AUDIT:-0}" = "1" ] && [ "$validation_rc" -ne 0 ]; then
    if [ "$VALIDATION_STRICT" = "1" ]; then
      die "thesis batch validation failed (see $THESIS_VALIDATION_FILE)"
    fi
    log_warn "thesis batch validation failed (see $THESIS_VALIDATION_FILE)"
  fi
}
