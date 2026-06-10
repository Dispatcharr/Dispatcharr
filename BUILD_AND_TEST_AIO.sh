#!/bin/bash
set -e

echo "======================================"
echo "Dispatcharr v0.26.0 - Build & Test AIO"
echo "======================================"
echo ""

# Cleanup alte Images (optional)
read -p "Remove old images? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "=== Removing old images ==="
    docker rmi sbeimel/dispatcharr:base 2>/dev/null || true
    docker rmi sbeimel/dispatcharr:0.26.0 2>/dev/null || true
fi

echo ""
echo "=== Step 1: Building Base Image ==="
docker build -t sbeimel/dispatcharr:base -f docker/DispatcharrBase .

echo ""
echo "=== Step 2: Testing Base Image ==="
echo "Testing django-db-geventpool..."
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import django_db_geventpool; print('✓ django-db-geventpool')" || {
    echo "❌ ERROR: django-db-geventpool not found in base image!"
    exit 1
}

echo "Testing drf-spectacular..."
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import drf_spectacular; print('✓ drf-spectacular')" || {
    echo "❌ ERROR: drf-spectacular not found in base image!"
    exit 1
}

echo "Testing gevent..."
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import gevent; print('✓ gevent')" || {
    echo "❌ ERROR: gevent not found in base image!"
    exit 1
}

echo "Testing psycopg..."
docker run --rm sbeimel/dispatcharr:base /dispatcharrpy/bin/python -c "import psycopg; print('✓ psycopg')" || {
    echo "❌ ERROR: psycopg not found in base image!"
    exit 1
}

echo ""
echo "✓✓✓ Base Image: All packages verified!"
echo ""

echo "=== Step 3: Building Final Image ==="
docker build -t sbeimel/dispatcharr:0.26.0 -f docker/Dockerfile \
    --build-arg BASE_TAG=base \
    --build-arg REPO_OWNER=sbeimel \
    --build-arg REPO_NAME=dispatcharr .

echo ""
echo "=== Step 4: Testing Final Image ==="
echo "Testing with SQLite..."
docker run --rm -e USE_SQLITE=true sbeimel/dispatcharr:0.26.0 \
    /dispatcharrpy/bin/python manage.py check || {
    echo "❌ ERROR: Django check failed!"
    exit 1
}

echo ""
echo "✓✓✓ Final Image: Django check passed!"
echo ""

echo "=== Step 5: Starting AIO Container ==="
cd docker
docker-compose -f docker-compose.aio.local.yml down 2>/dev/null || true
docker-compose -f docker-compose.aio.local.yml up -d

echo ""
echo "Waiting for container to start (10 seconds)..."
sleep 10

echo ""
echo "=== Container Logs (last 50 lines) ==="
docker logs dispatcharr --tail 50

echo ""
echo "=== Checking for errors ==="
if docker logs dispatcharr 2>&1 | grep -q "ModuleNotFoundError.*django_db_geventpool"; then
    echo "❌ ERROR: django_db_geventpool still not found!"
    echo ""
    echo "Full logs:"
    docker logs dispatcharr
    exit 1
elif docker logs dispatcharr 2>&1 | grep -qi "error"; then
    echo "⚠️ WARNING: Errors found in logs (check above)"
else
    echo "✓ No critical errors found"
fi

echo ""
echo "=== Container Status ==="
docker-compose -f docker-compose.aio.local.yml ps

echo ""
echo "======================================"
echo "✓✓✓ BUILD AND TEST COMPLETE! ✓✓✓"
echo "======================================"
echo ""
echo "Container is running at: http://localhost:9191"
echo ""
echo "Useful commands:"
echo "  - View logs:     docker logs -f dispatcharr"
echo "  - Stop:          cd docker && docker-compose -f docker-compose.aio.local.yml down"
echo "  - Restart:       cd docker && docker-compose -f docker-compose.aio.local.yml restart"
echo "  - Shell access:  docker exec -it dispatcharr bash"
echo ""
