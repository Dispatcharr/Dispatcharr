#!/bin/bash
set -e

cd /app
source /dispatcharrpy/bin/activate

# Wait for Django secret key
echo 'Waiting for Django secret key...'
while [ ! -f /data/jwt ]; do sleep 1; done
export DJANGO_SECRET_KEY="$(tr -d '\r\n' < /data/jwt)"

# Wait for migrations to complete (check that NO unapplied migrations remain)
echo 'Waiting for migrations to complete...'
until ! python manage.py showmigrations 2>&1 | grep -q '\[ \]'; do
    echo 'Migrations not ready yet, waiting...'
    sleep 2
done

# Start Celery
echo 'Migrations complete, starting Celery...'
celery -A dispatcharr beat -l info &

# Default to nice level 5 (lower priority) - safe for unprivileged containers
# Negative values require SYS_NICE capability
NICE_LEVEL="${CELERY_NICE_LEVEL:-5}"
if [ "$NICE_LEVEL" -lt 0 ] 2>/dev/null; then
    echo "Warning: CELERY_NICE_LEVEL=$NICE_LEVEL is negative, requires SYS_NICE capability"
fi
nice -n "$NICE_LEVEL" celery -A dispatcharr worker -l info --autoscale=6,1
