#!/usr/bin/env bash
# Sweep configuration and execution helpers for benchmark runner scripts.

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "Error: This file is a library and should not be executed directly." >&2
  exit 1
fi

sweep_rpm_list_from_range() {
  local start="$1"
  local end="$2"
  local step="$3"
  [[ "$start" =~ ^[0-9]+$ ]] || die "rpm start must be integer, got: $start"
  [[ "$end" =~ ^[0-9]+$ ]] || die "rpm end must be integer, got: $end"
  [[ "$step" =~ ^[0-9]+$ ]] || die "rpm step must be integer, got: $step"
  [ "$start" -gt 0 ] || die "rpm start must be > 0, got: $start"
  [ "$end" -ge "$start" ] || die "rpm end must be >= start, got: $start..$end"
  [ "$step" -gt 0 ] || die "rpm step must be > 0, got: $step"
  seq "$start" "$step" "$end" | paste -sd, -
}

run_sweep_stage() {
  local run_tag="$1"
  local rpm_csv="$2"
  local settle_seconds="$3"
  local measure_seconds="$4"
  local reps="$5"
  local prompt_set="${6:-in_scope}"
  local prompts_path="${7:-$PROMPTS_CONTAINER}"

  if [ -z "${rpm_csv//[[:space:]]/}" ]; then
    log_warn "Sweep stage: empty RPM list for tag=$run_tag; skipping"
    return 0
  fi
  if ! [[ "$reps" =~ ^[0-9]+$ ]]; then
    die "Sweep stage reps must be integer, got: $reps"
  fi
  if [ "$reps" -le 0 ]; then
    log_warn "Sweep stage: reps=$reps for tag=$run_tag; skipping"
    return 0
  fi

  IFS="," read -r -a RPM_ARRAY <<< "$rpm_csv"
  for RPM in "${RPM_ARRAY[@]}"; do
    RPM="${RPM//[[:space:]]/}"
    [ -n "$RPM" ] || continue
    for REP in $(seq 1 "$reps"); do
      log_info "Sweep stage: endpoint=$TARGET_ENDPOINT tag=$run_tag rpm=$RPM rep $REP/$reps settle=${settle_seconds}s measure=${measure_seconds}s"
      run_k6_arrival "$TARGET_ENDPOINT" "$RPM" "$REP" "$prompt_set" "$prompts_path" 1 "$run_tag" "$settle_seconds" "$measure_seconds" "$RUN_TS"

      if [ "$REP" -lt "$reps" ]; then
        log_info "Cooldown before next repetition: 10s..."
        sleep 10
      fi
    done

    log_info "Cooldown before next RPM: 10s..."
    sleep 10
  done
}

load_sweep_config() {
  sweep_smoke_rpms="$BENCH_SWEEP_SMOKE_RPM_LIST"
  sweep_smoke_settle_s="$BENCH_SWEEP_SMOKE_SETTLE_SECONDS"
  sweep_smoke_measure_s="$BENCH_SWEEP_SMOKE_MEASURE_SECONDS"
  sweep_smoke_reps="$BENCH_SWEEP_SMOKE_REPS"

  sweep_primary_start="$BENCH_SWEEP_PRIMARY_RPM_START"
  sweep_primary_end="$BENCH_SWEEP_PRIMARY_RPM_END"
  sweep_primary_step="$BENCH_SWEEP_PRIMARY_RPM_STEP"
  sweep_primary_settle_s="$BENCH_SWEEP_PRIMARY_SETTLE_SECONDS"
  sweep_primary_measure_s="$BENCH_SWEEP_PRIMARY_MEASURE_SECONDS"
  sweep_primary_reps="$BENCH_SWEEP_PRIMARY_REPS"

  sweep_timeout_rate_max="$BENCH_SWEEP_TIMEOUT_RATE_MAX"
  sweep_stop_after_smoke="$BENCH_SWEEP_STOP_AFTER_SMOKE"
}

validate_sweep_config() {
  smoke_enabled=0
  if [ -n "${sweep_smoke_rpms//[[:space:]]/}" ]; then
    smoke_enabled=1
  fi

  if [ "$sweep_stop_after_smoke" != "0" ] && [ "$sweep_stop_after_smoke" != "1" ]; then
    die "BENCH_SWEEP_STOP_AFTER_SMOKE must be 0 or 1, got: $sweep_stop_after_smoke"
  fi

  if [ "$sweep_stop_after_smoke" = "1" ] && [ "$smoke_enabled" = "0" ]; then
    die "BENCH_SWEEP_STOP_AFTER_SMOKE=1 requires BENCH_SWEEP_SMOKE_RPM_LIST to be configured"
  fi
}

analyze_sweep_stage() {
  local run_tag="$1"
  local knee_run_tag="$2"
  local measure_seconds="$3"
  local expected_reps="$4"
  shift 4

  mkdir -p "$ANALYSIS_DIR"
  local results_dir_container
  results_dir_container=$(to_container_path "$RESULTS_DIR")
  bench_python /bench/helpers/analysis/analyze_sweep.py \
    "$results_dir_container" \
    --run-tag "$run_tag" \
    --knee-run-tag "$knee_run_tag" \
    --measure-seconds "$measure_seconds" \
    --expected-reps "$expected_reps" \
    "$@"
}

run_smoke_stage_if_enabled() {
  if [ "$smoke_enabled" != "1" ]; then
    log_info "BENCH_SWEEP_SMOKE_RPM_LIST empty; skipping smoke runs"
    return 0
  fi

  run_sweep_stage "sweep_smoke" "$sweep_smoke_rpms" "$sweep_smoke_settle_s" "$sweep_smoke_measure_s" "$sweep_smoke_reps" "in_scope" "$PROMPTS_CONTAINER"
  if ! analyze_sweep_stage \
    "sweep_smoke" \
    "sweep_smoke" \
    "$sweep_smoke_measure_s" \
    "$sweep_smoke_reps" \
    --no-plots \
    --enforce-validity; then
    die "sweep_smoke validity checks failed. Reduce BENCH_SWEEP_SMOKE_RPM_LIST and/or increase ARRIVAL_MAX_VUS ($ARRIVAL_MAX_VUS) and ARRIVAL_PREALLOCATED_VUS ($ARRIVAL_PREALLOCATED_VUS), then rerun."
  fi
}

run_primary_stage_if_enabled() {
  if [ "$sweep_stop_after_smoke" = "1" ]; then
    log_info "BENCH_SWEEP_STOP_AFTER_SMOKE=1 set; exiting after successful smoke validity checks"
    return 0
  fi

  local primary_rpms
  primary_rpms=$(sweep_rpm_list_from_range "$sweep_primary_start" "$sweep_primary_end" "$sweep_primary_step")
  run_sweep_stage "sweep_primary" "$primary_rpms" "$sweep_primary_settle_s" "$sweep_primary_measure_s" "$sweep_primary_reps" "in_scope" "$PROMPTS_CONTAINER"
  analyze_sweep_stage \
    "sweep_primary" \
    "sweep_primary" \
    "$sweep_primary_measure_s" \
    "$sweep_primary_reps" \
    --timeout-rate-max "$sweep_timeout_rate_max" \
    || log_warn "sweep analysis failed"
}

run_configured_sweeps() {
  load_sweep_config
  validate_sweep_config
  log_info "Sweep profile: endpoint=${TARGET_ENDPOINT} smoke=${sweep_smoke_rpms} primary=${sweep_primary_start}..${sweep_primary_end} step=${sweep_primary_step} reps=${sweep_primary_reps}"
  run_smoke_stage_if_enabled
  run_primary_stage_if_enabled
}
