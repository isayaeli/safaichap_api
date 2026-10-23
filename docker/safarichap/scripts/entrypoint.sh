#!/bin/sh
set -e

echo "⏳ Waiting for Postgres..."
until python -c "
import psycopg2, os, sys
try:
    psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )
    sys.exit(0)
except Exception as e:
    sys.exit(1)
"; do
  echo "  Postgres unavailable – retrying in 1s"
  sleep 1
done
echo "✅ Postgres is up"

# Only the service with RUN_MIGRATIONS=true migrates (avoids races between replicas).
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "🔄 Running migrations..."
    python manage.py migrate --noinput

    echo "📦 Collecting static files..."
    python manage.py collectstatic --noinput
fi

echo "🚀 Starting: $*"
exec "$@"
