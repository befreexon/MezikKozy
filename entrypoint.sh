#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
while ! python -c "
import psycopg2, os
psycopg2.connect(
    dbname=os.environ.get('DB_NAME', 'mezikkozy'),
    user=os.environ.get('DB_USER', 'mezikkozy'),
    password=os.environ.get('DB_PASSWORD', 'mezikkozy'),
    host=os.environ.get('DB_HOST', 'db'),
    port=os.environ.get('DB_PORT', '5432')
)" 2>/dev/null; do
    echo "Database not ready, retrying in 1 second..."
    sleep 1
done

echo "Running migrations..."
python manage.py migrate --no-input

echo "Starting Daphne..."
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
