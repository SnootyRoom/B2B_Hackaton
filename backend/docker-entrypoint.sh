#!/bin/sh
set -e
case "$1" in
  api)
    # Секрет подписи сессий: значение из .env.example известно всем. Не задан или
    # «change-me» — генерируем случайный один раз и храним в томе, вход переживает перезапуск.
    if [ -z "$JWT_SECRET" ] || [ "$JWT_SECRET" = "change-me" ]; then
      secret_file="${UPLOAD_DIR:-/data/uploads}/.jwt_secret"
      if [ ! -s "$secret_file" ]; then
        mkdir -p "$(dirname "$secret_file")"
        (umask 077 && python -c "import secrets; print(secrets.token_urlsafe(48))" > "$secret_file")
        echo "JWT_SECRET не задан: сгенерирован случайный ключ"
      fi
      JWT_SECRET="$(cat "$secret_file")"
      export JWT_SECRET
    fi
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
