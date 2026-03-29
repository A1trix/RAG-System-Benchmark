#!/usr/bin/env bash
set -euo pipefail

# Main benchmark runner script.
# Keeps the high-level benchmark workflow readable while delegating
# implementation-heavy helper logic to bench/lib/.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BENCH_DIR="$ROOT_DIR/bench"

source "$BENCH_DIR/lib/common.sh"
source "$BENCH_DIR/lib/docker.sh"
source "$BENCH_DIR/lib/validation.sh"
source "$BENCH_DIR/lib/bootstrap.sh"
source "$BENCH_DIR/lib/repro.sh"
source "$BENCH_DIR/lib/k6_arrival.sh"
source "$BENCH_DIR/lib/sweep.sh"
source "$BENCH_DIR/lib/finalize.sh"

trap 'die "Unexpected error in: $BASH_COMMAND"' ERR

# ============================================================================
# SECTION 1: INITIALIZATION & SETUP
# ============================================================================

initialize_benchmark_context

# ============================================================================
# SECTION 2: INFRASTRUCTURE STARTUP
# ============================================================================

compose_up_benchmark_stack
sleep "$BOOT_WAIT"
check_warmup_prereqs

# ============================================================================
# SECTION 3: REPRODUCIBILITY ARTIFACTS
# ============================================================================

capture_reproducibility_artifacts

# ============================================================================
# SECTION 4: LOAD TEST SWEEPS
# ============================================================================

run_configured_sweeps

# ============================================================================
# SECTION 5: POST-PROCESSING & FINAL VALIDATION
# ============================================================================

finalize_child_batch
