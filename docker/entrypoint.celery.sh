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
nice -n ${CELERY_NICE_LEVEL:-5} celery -A dispatcharr worker -l info --autoscale=6,1
