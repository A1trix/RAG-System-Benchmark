#!/usr/bin/env sh
set -e

export PYTHONPATH=/app

worker_count="${WORKER_COUNT:-5}"
uvicorn_workers="${UVICORN_WORKERS:-1}"

start_worker() {
  while true; do
    rq worker --url "${REDIS_URL:-redis://redis:6379/0}" "${QUEUE_NAME:-rag-pipeline}"
    echo "rq worker exited with code $?; restarting in 2s" >&2
    sleep 2
  done
}

i=1
while [ "$i" -le "$worker_count" ]; do
  start_worker &
  i=$((i + 1))
done

exec uvicorn rag_service.app:app --host 0.0.0.0 --port "${PORT:-8080}" --workers "$uvicorn_workers"
