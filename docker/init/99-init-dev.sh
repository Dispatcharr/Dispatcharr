#!/bin/bash

echo "🚀 Development Mode - Setting up Frontend..."

# Install Node.js
if ! command -v node 2>&1 >/dev/null
then
    echo "=== setting up nodejs ==="
    curl -sL https://deb.nodesource.com/setup_23.x -o /tmp/nodesource_setup.sh
    bash /tmp/nodesource_setup.sh
    apt-get update
    apt-get install -y --no-install-recommends \
        nodejs
fi

# Install frontend dependencies
su - $POSTGRES_USER -c "cd /app/frontend && npm install"
# Install pip dependencies
cd /app && pip install -r requirements.txt

# Install debugpy for remote debugging
if [ "$DISPATCHARR_DEBUG" = "true" ]; then
    echo "=== setting up debugpy ==="
    pip install debugpy
fi
