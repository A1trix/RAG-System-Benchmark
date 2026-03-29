#!/usr/bin/env bash
# Common utility functions for benchmark scripts
# This file is meant to be sourced, not executed directly

# Guard: prevent direct execution
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "Error: This script should be sourced, not executed directly." >&2
  exit 1
fi

set -euo pipefail

# MSYS exports for Windows path handling compatibility
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

to_container_path() {
  local path="$1"
  if [[ "$path" == "$BENCH_DIR"* ]]; then
    printf '/bench%s' "${path#"$BENCH_DIR"}"
    return
  fi
  printf '%s' "$path"
}

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
