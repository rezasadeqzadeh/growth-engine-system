#!/bin/sh
# ROLE: all (default: API + workers + scheduler in this container) | api | worker | media | scheduler
set -e
ROLE="${ROLE:-all}"

api() {
  alembic upgrade head
  uvicorn growth_engine.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
}

case "$ROLE" in
  api) api ;;
  worker) exec python -m growth_engine.jobs.runner default ;;
  media) exec python -m growth_engine.jobs.runner media ;;
  scheduler) exec python -m growth_engine.jobs.scheduler ;;
  all)
    alembic upgrade head
    uvicorn growth_engine.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' &
    python -m growth_engine.jobs.runner default &
    python -m growth_engine.jobs.runner media &
    python -m growth_engine.jobs.scheduler &
    # If any process stops, stop the container so Coolify restarts it.
    while kill -0 $(jobs -p) 2>/dev/null; do
      for pid in $(jobs -p); do kill -0 "$pid" 2>/dev/null || { echo "process $pid exited"; exit 1; }; done
      sleep 5
    done
    ;;
  *) echo "unknown ROLE: $ROLE"; exit 2 ;;
esac
