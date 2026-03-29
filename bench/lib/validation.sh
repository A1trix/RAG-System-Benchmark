#!/bin/bash
# validation.sh - Validation functions for benchmark scripts
#
# This library provides validation and checking functions used by benchmark
# scripts to verify input files, run outputs, and prerequisites.
#
# Dependencies:
#   - die() function (from common.sh)
#   - bench_python() function (from docker.sh)
#   - to_container_path() function (from common.sh)
#   - ROOT_DIR variable (set by main scripts)
#   - PGVECTOR_TABLE variable (optional env var)

# Guard: prevent direct execution
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "This library should be sourced, not executed directly." >&2
  exit 1
fi

check_file_nonempty() {
  local file="$1"
  local label="$2"
  if [ ! -s "$file" ]; then
    die "$label missing or empty: $file"
  fi
}

check_run_id_in_file() {
  local file="$1"
  local run_id="$2"
  local file_container
  file_container=$(to_container_path "$file")
  bench_python /bench/helpers/run/jsonl_has_run_id.py --file "$file_container" --run-id "$run_id"
}

check_k6_summary_report() {
  local file="$1"
  local file_container
  file_container=$(to_container_path "$file")
  bench_python /bench/helpers/run/k6_summary_report.py --file "$file_container"
}

check_k6_summary_strict() {
  local file="$1"
  local file_container
  file_container=$(to_container_path "$file")
  bench_python /bench/helpers/run/k6_summary_strict.py --file "$file_container"
}

check_vectors_for_file() {
  local file_id="$1"
  local table_name="${PGVECTOR_TABLE:-documents_pg}"
  bench_python /bench/helpers/run/check_vectors_for_file.py --table "$table_name" --file-id "$file_id"
}

duration_to_seconds() {
  local d="$1"
  d="${d//[[:space:]]/}"
  if [[ "$d" =~ ^([0-9]+)s$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$d" =~ ^([0-9]+)m$ ]]; then
    printf '%s' "$((10#${BASH_REMATCH[1]} * 60))"
    return 0
  fi
  if [[ "$d" =~ ^([0-9]+)h$ ]]; then
    printf '%s' "$((10#${BASH_REMATCH[1]} * 3600))"
    return 0
  fi
  die "unsupported duration format (use Ns/Nm/Nh): $d"
}

check_warmup_prereqs() {
  # Hard gate: benchmark corpus must be present on disk and in the vector DB.
  # (End-to-end comparison is valid only if both systems query the same frozen DB state.)
  local required_files=(
    "FAQ_hTRIUS.pdf"
    "htrius_01_Unternehmen_Mission.pdf"
    "htrius_02_BionicBack_Produkt_Technik.pdf"
    "htrius_03_Studien_Zertifizierungen.pdf"
    "htrius_04_Branchen_Usecases.pdf"
    "htrius_05_Pilot_Rollout_ROI.pdf"
    "htrius_06_Service_Zubehör_Kontakt.pdf"
    "hTRIUS- Entlastungsreport- BionicBack.pdf"
  )

  for file_id in "${required_files[@]}"; do
    local file_path_rag="$ROOT_DIR/rag/files/$file_id"
    local file_path_n8n="$ROOT_DIR/n8n/files/$file_id"
    if [ -s "$file_path_rag" ]; then
      :
    elif [ -s "$file_path_n8n" ]; then
      :
    else
      die "required file missing or empty: $file_id (expected at $file_path_rag or $file_path_n8n)"
    fi
    check_vectors_for_file "$file_id"
  done
}

require_boundary_audit_inputs() {
  [ -n "${BENCH_BOUNDARY_AUDIT_REPORT_PATH:-}" ] || die "BENCH_REQUIRE_BOUNDARY_AUDIT=1 requires BENCH_BOUNDARY_AUDIT_REPORT_PATH"
  [ -n "${N8N_WORKFLOW_ID:-}" ] || die "BENCH_REQUIRE_BOUNDARY_AUDIT=1 requires N8N_WORKFLOW_ID to avoid ambiguous workflow selection"
  [ -n "${N8N_OPENAI_CREDENTIAL_ID:-}" ] || die "BENCH_REQUIRE_BOUNDARY_AUDIT=1 requires N8N_OPENAI_CREDENTIAL_ID for workflow credential verification"
  check_file_nonempty "$BOUNDARY_AUDIT_REPORT_FILE" "boundary audit report"
  local report_container
  report_container=$(to_container_path "$BOUNDARY_AUDIT_REPORT_FILE")
  bench_python /bench/helpers/run/boundary_report_pass.py --report "$report_container"
}

validate_boundary_attachment_if_required() {
  if [ "${BENCH_REQUIRE_BOUNDARY_AUDIT:-0}" != "1" ]; then
    return 0
  fi

  local boundary_report_container
  local source_fp_container
  local n8n_snap_container
  boundary_report_container=$(to_container_path "$BOUNDARY_AUDIT_REPORT_FILE")
  source_fp_container=$(to_container_path "$SOURCE_FP_FILE")
  n8n_snap_container=$(to_container_path "$N8N_WORKFLOW_SNAPSHOT_FILE")
  bench_python /bench/helpers/run/validate_boundary_attachment.py \
    --boundary-report "$boundary_report_container" \
    --source-fingerprint "$source_fp_container" \
    --workflow-snapshot "$n8n_snap_container"
}
