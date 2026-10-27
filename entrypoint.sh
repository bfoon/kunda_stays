#!/bin/sh
set -e

echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
while ! nc -z "${POSTGRES_HOST:-db}" "${POSTGRES_PORT:-5432}"; do
  sleep 1
done

# Only the web container runs migrations / collectstatic / seeding
if [ "${RUN_SETUP:-0}" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
  if [ "${SEED_DEMO:-0}" = "1" ]; then
    python manage.py seed_demo --if-empty
  fi
fi

exec "$@"
