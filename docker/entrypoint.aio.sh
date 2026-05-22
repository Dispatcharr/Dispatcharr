#!/bin/bash

# CRITICAL: Install missing dependencies BEFORE any Django commands
echo "🔍 Installing missing dependencies..."
pip install --quiet django-redis 2>/dev/null || true

# Run Django migrations and collect static files
python manage.py collectstatic --noinput
python manage.py migrate --noinput

# Function to clean up only running processes
cleanup() {
    echo "🔥 Cleanup triggered! Stopping services..."
    for pid in "${pids[@]}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "⛔ Stopping process (PID: $pid)..."
            kill -TERM "$pid" 2>/dev/null
        else
            echo "✅ Process (PID: $pid) already stopped."
        fi
    done
    wait
}

# Catch termination signals (CTRL+C, Docker Stop, etc.)
trap cleanup TERM INT

# Initialize an array to store PIDs
pids=()

GUNICORN_PORT=9191

# If running in development mode, install and start frontend
if [ "$DISPATCHARR_ENV" = "dev" ]; then
    echo "🚀 Development Mode - Setting up Frontend..."
    GUNICORN_PORT=5656

    # Install Node.js
    apt-get update && apt-get install -y nodejs

    # Install frontend dependencies
    cd /app/frontend && npm install
    cd /app

    # Start React development server
    echo "🚀 Starting React Dev Server..."
    cd /app/frontend
    PORT=9191 ./node_modules/pm2/bin/pm2 --name test start npm -- start
    ./node_modules/pm2/bin/pm2 logs &
    react_pid=$!
    echo "✅ React started with PID $react_pid"
    pids+=("$react_pid")
    cd /app
fi

# If running in `dev` or `aio`, start Redis and Celery
if [ "$DISPATCHARR_ENV" = "dev" ] || [ "$DISPATCHARR_ENV" = "aio" ]; then
    echo "🚀 Running Redis and Celery for '$DISPATCHARR_ENV'..."

    # Start Redis
    echo "🚀 Starting Redis..."
    redis-server --daemonize no &
    sleep 1  # Give Redis time to start
    redis_pid=$(pgrep -x redis-server)
    if [ -n "$redis_pid" ]; then
        echo "✅ Redis started with PID $redis_pid"
        pids+=("$redis_pid")
    else
        echo "❌ Redis failed to start!"
    fi

    # Start Celery
    echo "🚀 Starting Celery..."
    celery -A dispatcharr worker -l info &
    celery_pid=$!
    echo "✅ Celery started with PID $celery_pid"
    pids+=("$celery_pid")
fi

# Always start Gunicorn
echo "🚀 Starting Gunicorn..."
gunicorn --workers=4 --worker-class=gevent --timeout=300 --bind 0.0.0.0:${GUNICORN_PORT} dispatcharr.wsgi:application &
gunicorn_pid=$!
echo "✅ Gunicorn started with PID $gunicorn_pid"
pids+=("$gunicorn_pid")

# Log PIDs
echo "📝 Process PIDs: ${pids[*]}"

# Wait for at least one process to exit and log the process that exited first
if [ ${#pids[@]} -gt 0 ]; then
    echo "⏳ Waiting for processes to exit..."
    ps -aux | grep -E 'redis-server|celery|gunicorn|npm'
    wait -n "${pids[@]}"
    echo "🚨 One of the processes exited! Checking which one..."

    for pid in "${pids[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            process_name=$(ps -p "$pid" -o comm=)
            echo "❌ Process $process_name (PID: $pid) has exited!"
        fi
    done
else
    echo "❌ No processes started. Exiting."
    exit 1
fi

# Cleanup and stop remaining processes
cleanup
