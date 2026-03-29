#!/usr/bin/env bash
set -euo pipefail

# run_compare_pair.sh: Run paired comparison benchmarks for RAG vs n8n endpoints.
# This script orchestrates isolated child batches for comparative analysis,
# validates pair results, and generates comparison reports.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BENCH_DIR="$ROOT_DIR/bench"

source "$BENCH_DIR/lib/common.sh"
source "$BENCH_DIR/lib/docker.sh"

load_env_defaults "$BENCH_DIR/.env"

COMPOSE_BASE="$ROOT_DIR/docker-compose.yml"
COMPOSE_BENCH="$ROOT_DIR/docker-compose.bench.yml"
if command -v cygpath >/dev/null 2>&1; then
  COMPOSE_BASE=$(cygpath -w "$COMPOSE_BASE")
  COMPOSE_BENCH=$(cygpath -w "$COMPOSE_BENCH")
fi

export HOST_UID HOST_GID
HOST_UID=$(id -u)
HOST_GID=$(id -g)

[ -x "$BENCH_DIR/run_all.sh" ] || die "missing child benchmark runner: $BENCH_DIR/run_all.sh"

PAIR_REPS="${BENCH_PAIR_REPS:-${BENCH_SWEEP_PRIMARY_REPS:-3}}"
PAIR_ORDER_MODE="${BENCH_PAIR_ORDER_MODE:-alternate_by_rep}"
PAIR_VALIDATE_STRICT="${BENCH_PAIR_VALIDATE_STRICT:-1}"
PREREG_EVAL="${BENCH_PREREG_EVAL:-1}"
PREREG_ENFORCE="${BENCH_PREREG_ENFORCE:-0}"
COMPARE_TS="${BENCH_COMPARE_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"
COMPARE_ID="compare_${COMPARE_TS}"
PARENT_REL="results/${COMPARE_ID}"
PARENT_DIR="$BENCH_DIR/$PARENT_REL"
ANALYSIS_DIR="$PARENT_DIR/analysis"
PAIR_PLAN_FILE="$PARENT_DIR/pair_plan.json"
PAIR_PLAN_ENTRIES_TMP="$PARENT_DIR/pair_plan_entries.jsonl"
PAIR_VALIDATION_FILE="$ANALYSIS_DIR/pair_validation.json"
PAIR_COMPARISON_JSON="$ANALYSIS_DIR/pair_comparison.json"
PARENT_MANIFEST_FILE="$PARENT_DIR/manifest.json"
PARENT_RUNS_FILE="$PARENT_DIR/runs.jsonl"
PREREG_FILE="$BENCH_DIR/preregistration.json"

[[ "$PAIR_REPS" =~ ^[0-9]+$ ]] || die "BENCH_PAIR_REPS must be an integer, got: $PAIR_REPS"
[ "$PAIR_REPS" -gt 0 ] || die "BENCH_PAIR_REPS must be > 0, got: $PAIR_REPS"
case "$PAIR_ORDER_MODE" in
  alternate_by_rep)
    ;;
  *)
    die "BENCH_PAIR_ORDER_MODE must be 'alternate_by_rep', got: $PAIR_ORDER_MODE"
    ;;
esac

[ "${BENCH_REQUIRE_BOUNDARY_AUDIT:-0}" = "1" ] || die "run_compare_pair.sh requires BENCH_REQUIRE_BOUNDARY_AUDIT=1"
[ -n "${BENCH_BOUNDARY_AUDIT_REPORT_PATH:-}" ] || die "run_compare_pair.sh requires BENCH_BOUNDARY_AUDIT_REPORT_PATH"
[ -f "$BENCH_BOUNDARY_AUDIT_REPORT_PATH" ] || die "boundary audit report not found: $BENCH_BOUNDARY_AUDIT_REPORT_PATH"

mkdir -p "$ANALYSIS_DIR" "$PARENT_DIR/children"
: > "$PAIR_PLAN_ENTRIES_TMP"
: > "$PARENT_RUNS_FILE"

BASE_PROMPT_SEED="${PROMPT_BASE_SEED:-20260219}"
child_manifest_args=()

append_pair_plan_entry() {
  local pair_rep="$1"
  local endpoint="$2"
  local order_index="$3"
  local pair_order="$4"
  local pair_prompt_seed="$5"
  local child_batch_id="$6"
  local child_dir="$7"
  python3 - <<'PY' "$PAIR_PLAN_ENTRIES_TMP" "$COMPARE_ID" "$pair_rep" "$endpoint" "$order_index" "$pair_order" "$pair_prompt_seed" "$child_batch_id" "$child_dir"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
entry = {
    "parent_compare_id": sys.argv[2],
    "pair_rep": int(sys.argv[3]),
    "endpoint": sys.argv[4],
    "order_index": int(sys.argv[5]),
    "pair_order": sys.argv[6],
    "pair_prompt_seed": int(sys.argv[7]),
    "child_batch_id": sys.argv[8],
    "results_dir": sys.argv[9],
}
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry) + "\n")
PY
}

write_pair_plan() {
  python3 - <<'PY' "$PAIR_PLAN_ENTRIES_TMP" "$PAIR_PLAN_FILE" "$COMPARE_ID" "$PAIR_ORDER_MODE" "$PAIR_REPS"
import json
import sys
from pathlib import Path

entries_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
children = []
for line in entries_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    children.append(json.loads(line))
children.sort(key=lambda item: (int(item.get("pair_rep") or 0), int(item.get("order_index") or 0)))
obj = {
    "parent_compare_id": sys.argv[3],
    "pair_order_mode": sys.argv[4],
    "pair_repetitions": int(sys.argv[5]),
    "children": children,
}
out_path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

run_child_batch() {
  local endpoint="$1"
  local pair_rep="$2"
  local order_index="$3"
  local pair_order="$4"
  local pair_prompt_seed="$5"
  local child_batch_id="$6"
  local child_rel="$7"
  local child_dir="$BENCH_DIR/$child_rel"

  log_info "Running isolated child batch: endpoint=$endpoint pair_rep=$pair_rep order=$order_index child_batch_id=$child_batch_id"
  rm -rf "$child_dir"
  BENCH_RESULTS_RELATIVE_DIR="$child_rel" \
  BENCH_TARGET_ENDPOINT="$endpoint" \
  BENCH_PARENT_COMPARE_ID="$COMPARE_ID" \
  BENCH_CHILD_BATCH_ID="$child_batch_id" \
  BENCH_PAIR_REP="$pair_rep" \
  BENCH_PAIR_ORDER="$pair_order" \
  BENCH_PAIR_PROMPT_SEED="$pair_prompt_seed" \
  BENCH_SWEEP_STOP_AFTER_SMOKE=$BENCH_SWEEP_STOP_AFTER_SMOKE \
  PROMPT_BASE_SEED="$pair_prompt_seed" \
  BENCH_SWEEP_PRIMARY_REPS=1 \
  BENCH_REQUIRE_BOUNDARY_AUDIT="${BENCH_REQUIRE_BOUNDARY_AUDIT:-1}" \
  BENCH_PREREG_ENFORCE="${BENCH_PREREG_ENFORCE:-0}" \
  BENCH_PREREG_EVAL="${BENCH_PREREG_EVAL:-1}" \
  "$BENCH_DIR/run_all.sh"

  append_pair_plan_entry "$pair_rep" "$endpoint" "$order_index" "$pair_order" "$pair_prompt_seed" "$child_batch_id" "$child_dir"
  child_manifest_args+=(--child-manifest "$child_dir/manifest.json")
}

for pair_rep in $(seq 1 "$PAIR_REPS"); do
  pair_prompt_seed=$((10#$BASE_PROMPT_SEED + pair_rep - 1))
  if [ $((pair_rep % 2)) -eq 1 ]; then
    pair_order="rag_first"
    first_endpoint="rag"
    second_endpoint="n8n"
  else
    pair_order="n8n_first"
    first_endpoint="n8n"
    second_endpoint="rag"
  fi

  first_child_id=$(printf 'rep%02d-%s' "$pair_rep" "$first_endpoint")
  second_child_id=$(printf 'rep%02d-%s' "$pair_rep" "$second_endpoint")
  run_child_batch "$first_endpoint" "$pair_rep" 1 "$pair_order" "$pair_prompt_seed" "$first_child_id" "$PARENT_REL/children/$first_child_id"
  run_child_batch "$second_endpoint" "$pair_rep" 2 "$pair_order" "$pair_prompt_seed" "$second_child_id" "$PARENT_REL/children/$second_child_id"
done

write_pair_plan

if [ -n "${BENCH_BOUNDARY_AUDIT_REPORT_PATH:-}" ] && [ -f "$BENCH_BOUNDARY_AUDIT_REPORT_PATH" ]; then
  cp "$BENCH_BOUNDARY_AUDIT_REPORT_PATH" "$PARENT_DIR/boundary_audit_report.json"
fi

set +e
python3 "$BENCH_DIR/helpers/artifacts/validate_thesis_pair.py" "$PARENT_DIR" --pair-plan "$PAIR_PLAN_FILE" --prereg "$PREREG_FILE" --output "$PAIR_VALIDATION_FILE"
pair_validation_rc=$?
set -e
if [ "$pair_validation_rc" -ne 0 ]; then
  if [ "$PAIR_VALIDATE_STRICT" = "1" ]; then
    die "pair validation failed (see $PAIR_VALIDATION_FILE)"
  fi
  log_warn "pair validation failed (see $PAIR_VALIDATION_FILE)"
fi

parent_dir_container=$(to_container_path "$PARENT_DIR")
pair_plan_container=$(to_container_path "$PAIR_PLAN_FILE")
prereg_container=$(to_container_path "$PREREG_FILE")
bench_python /bench/helpers/analysis/compare_isolated_batches.py "$parent_dir_container" --pair-plan "$pair_plan_container" --prereg "$prereg_container"

python3 "$BENCH_DIR/helpers/artifacts/manifest.py" \
  --runs "$PARENT_RUNS_FILE" \
  --prereg "$PREREG_FILE" \
  --batch-kind "isolated_parent_compare" \
  --parent-compare-id "$COMPARE_ID" \
  --pair-plan "$PAIR_PLAN_FILE" \
  --pair-validation "$PAIR_VALIDATION_FILE" \
  --pair-comparison "$PAIR_COMPARISON_JSON" \
  "${child_manifest_args[@]}" \
  --output "$PARENT_MANIFEST_FILE"

if [ "$PREREG_EVAL" = "1" ]; then
  prereg_out="$ANALYSIS_DIR/prereg_decision.json"
  prereg_txt="$ANALYSIS_DIR/prereg_decision.txt"
  prereg_args=("$BENCH_DIR/helpers/analysis/prereg_decision.py" "$PARENT_DIR" --prereg "$PREREG_FILE" --output "$prereg_out")
  if [ "$PREREG_ENFORCE" = "1" ]; then
    prereg_args+=(--enforce)
  fi
  set +e
  python3 "${prereg_args[@]}" > "$prereg_txt"
  prereg_rc=$?
  set -e
  if [ "$prereg_rc" -ne 0 ]; then
    if [ "$PREREG_ENFORCE" = "1" ]; then
      die "prereg decision failed (see $prereg_txt)"
    fi
    log_warn "prereg decision failed (see $prereg_txt)"
  fi
fi

log_info "Isolated comparison cohort complete: $PARENT_DIR"
