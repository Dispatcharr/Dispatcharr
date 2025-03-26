#!/bin/bash
set -e  # Exit on error

# Define paths
TARGET_DIR="./Dispatcharr"
MODEL_DIR="$TARGET_DIR/media/models/all-MiniLM-L6-v2"
REPO_URL="https://github.com/Dispatcharr/Dispatcharr.git"
DOCKER_DIR="$TARGET_DIR/docker"
ENV_FILE="$DOCKER_DIR/.env"

# Detect OS and current user
if [[ "$OSTYPE" == "darwin"* ]]; then
    CURRENT_USER=$(stat -f "%Su" .)
else
    CURRENT_USER=$(stat -c "%U" .)
fi
CURRENT_UID=$(id -u "$CURRENT_USER")
CURRENT_GID=$(id -g "$CURRENT_USER")

# Check Docker and Compose
if ! command -v docker &> /dev/null || ! docker compose version &> /dev/null; then
    echo "❌ Docker or Docker Compose (v2+) not found. Please install it."
    exit 1
fi

# Clone if needed
if [ -d "$TARGET_DIR/.git" ]; then
    echo "✅ Dispatcharr repository already cloned."
else
    echo "⬇️ Cloning Dispatcharr repository into $TARGET_DIR..."
    git clone "$REPO_URL" "$TARGET_DIR"
fi

# Write UID/GID to .env
echo "📝 Writing UID/GID to $ENV_FILE..."
cat > "$ENV_FILE" <<EOF
PUID=$CURRENT_UID
PGID=$CURRENT_GID
EOF

# Download SentenceTransformer model if missing
if [ -f "$MODEL_DIR/config.json" ]; then
    echo "✅ SentenceTransformer model already exists at $MODEL_DIR"
else
    echo "📦 Downloading SentenceTransformer model..."
    python3 - <<EOF
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
model.save("$MODEL_DIR")
EOF
fi

# Set ownership
echo "🔧 Applying ownership ($CURRENT_UID:$CURRENT_GID) to $TARGET_DIR..."
chown -R "$CURRENT_UID:$CURRENT_GID" "$TARGET_DIR"

# Build and run
echo "🐳 Building Docker container..."
docker compose -f "$DOCKER_DIR/docker-compose.dev.yml" build

echo "🚀 Starting Dispatcharr containers..."
docker compose -f "$DOCKER_DIR/docker-compose.dev.yml" up -d

echo "✅ Setup complete. Dispatcharr is built and running in container: dispatcharr_dev"
