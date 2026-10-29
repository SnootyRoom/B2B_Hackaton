#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    python -m app.seed
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec celery -A app.tasks.celery_app worker --loglevel=INFO --concurrency="${WORKER_CONCURRENCY:-4}"
    ;;
  *)
    exec "$@"
    ;;
esac
