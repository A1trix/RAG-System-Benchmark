#!/usr/bin/env bash
#
# Docker-related functions for benchmark scripts.
#
# This library provides helper functions for Docker Compose operations
# used in the benchmarking infrastructure.
#
# Expected variables (set by main scripts):
#   - COMPOSE_BASE: Path to base docker-compose file
#   - COMPOSE_BENCH: Path to benchmark docker-compose file
#   - N8N_WORKER_COUNT: Number of n8n workers to scale
#   - MINIMAL_STACK: Set to "1" for minimal stack mode
#   - CACHE_REGIME: Cache regime ("cold" or other)
#   - COLD_RESET_WAIT: Seconds to wait after cold reset
#   - COLD_RESET_N8N_WORKERS: Set to "1" to restart n8n workers
#

# Guard: prevent direct execution
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "Error: This file is a library and should not be executed directly." >&2
  exit 1
fi

docker_compose_bench() {
  docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_BENCH" "$@"
}

docker_compose_bench_exec() {
  docker_compose_bench exec -T "$@"
}

bench_python() {
  docker_compose_bench run --rm bench-runner python "$@"
}

cold_reset_before_main_run() {
  local endpoint_name="$1"

  if [ "$CACHE_REGIME" != "cold" ]; then
    return 0
  fi

  case "$endpoint_name" in
    rag)
      log_info "Cold-cache regime: restarting rag-pipeline..."
      docker_compose_bench restart rag-pipeline \
        || die "failed to restart rag-pipeline"
      ;;
    n8n)
      log_info "Cold-cache regime: restarting n8n..."
      docker_compose_bench restart n8n \
        || die "failed to restart n8n"
      if [ "$COLD_RESET_N8N_WORKERS" = "1" ]; then
        log_info "Cold-cache regime: restarting n8n-worker..."
        docker_compose_bench restart n8n-worker \
          || die "failed to restart n8n-worker"
      fi
      ;;
    *)
      die "unknown endpoint for cold reset: $endpoint_name"
      ;;
  esac

  if [ "$COLD_RESET_WAIT" -gt 0 ]; then
    log_info "Cold-cache regime: waiting ${COLD_RESET_WAIT}s after restart..."
    sleep "$COLD_RESET_WAIT"
  fi
}

compose_up_benchmark_stack() {
  if [ "$MINIMAL_STACK" = "1" ]; then
    docker_compose_bench up -d --build --force-recreate --remove-orphans \
      --scale n8n-worker="$N8N_WORKER_COUNT" \
      --scale rag-pipeline=1 \
      db db-init redis n8n n8n-worker rag-pipeline \
      prometheus grafana cadvisor node-exporter postgres-exporter redis-exporter \
      jaeger otel-collector
  else
    docker_compose_bench up -d --build --force-recreate --remove-orphans \
      --scale n8n-worker="$N8N_WORKER_COUNT" \
      --scale rag-pipeline=1 \
      --scale rag-pipeline-watcher=0
  fi
}
