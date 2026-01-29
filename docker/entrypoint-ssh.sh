#!/bin/bash

# SSH-enabled entrypoint script
# This extends the original entrypoint with SSH capabilities

set -e

echo "Starting SSH-enabled Dispatcharr container..."
printenv

# Setup SSH access
/app/docker/setup-ssh.sh

# Run the original entrypoint script
exec /app/docker/entrypoint.sh "$@"