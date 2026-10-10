#!/bin/sh
# ROLE: all (default: API + workers + scheduler in this container) | api | worker | media | meta | scheduler
# Run exactly one `meta` worker: it serializes every Meta Graph API call of the platform.
set -e
ROLE="${ROLE:-all}"

# The API applies pending migrations itself on start (growth_engine/migrate.py).
api() {
  uvicorn growth_engine.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
}

case "$ROLE" in
  api) api ;;
  worker) exec python -m growth_engine.jobs.runner default ;;
  media) exec python -m growth_engine.jobs.runner media ;;
  meta) exec python -m growth_engine.jobs.runner meta ;;
  scheduler) exec python -m growth_engine.jobs.scheduler ;;
  all)
    uvicorn growth_engine.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' &
    python -m growth_engine.jobs.runner default &
    python -m growth_engine.jobs.runner media &
    python -m growth_engine.jobs.runner meta &
    python -m growth_engine.jobs.scheduler &
    # If any process stops, stop the container so Coolify restarts it.
    while kill -0 $(jobs -p) 2>/dev/null; do
      for pid in $(jobs -p); do kill -0 "$pid" 2>/dev/null || { echo "process $pid exited"; exit 1; }; done
      sleep 5
    done
    ;;
  *) echo "unknown ROLE: $ROLE"; exit 2 ;;
esac
