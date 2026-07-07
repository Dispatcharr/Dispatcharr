#!/bin/bash
# Bootstrap internal Postgres/Redis (AIO-style) and run Django tests in the base image.
set -euo pipefail

REPO_ROOT="${GITHUB_WORKSPACE:-$(pwd)}"
cd "${REPO_ROOT}"

export DISPATCHARR_ENV="${DISPATCHARR_ENV:-aio}"
export PUID="${PUID:-1000}"
export PGID="${PGID:-1000}"
export POSTGRES_DB="${POSTGRES_DB:-dispatcharr}"
export POSTGRES_USER="${POSTGRES_USER:-dispatch}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-secret}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_DIR="${POSTGRES_DIR:-/tmp/dispatcharr-ci/db}"
export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export REDIS_DB="${REDIS_DB:-0}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-ci-test-secret-key}"
export DISPATCHARR_LOG_LEVEL="${DISPATCHARR_LOG_LEVEL:-WARNING}"
export PATH="/dispatcharrpy/bin:${PATH}"
export PG_VERSION
PG_VERSION="$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)"
export PG_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"

if [[ "$DISPATCHARR_ENV" == "aio" ]]; then
  export POSTGRES_HOST="${POSTGRES_HOST:-/var/run/postgresql}"
else
  export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
fi

if [[ "${SYNC_PYTHON_DEPS:-}" == "true" ]]; then
  echo "Syncing Python dependencies with uv..."
  uv sync --python /dispatcharrpy/bin/python --no-install-project --no-dev
fi

echo "Setting up CI user and PostgreSQL data directory..."
# shellcheck source=docker/init/01-user-setup.sh
. "${REPO_ROOT}/docker/init/01-user-setup.sh"
mkdir -p "${POSTGRES_DIR}"
chown "${PUID}:${PGID}" "${POSTGRES_DIR}"
chmod 700 "${POSTGRES_DIR}"
# shellcheck source=docker/init/02-postgres.sh
. "${REPO_ROOT}/docker/init/02-postgres.sh"

echo "Starting internal PostgreSQL..."
prepare_pg_socket_dir
su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 120 -o '-c port=${POSTGRES_PORT}'"
until su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
  sleep 1
done
set +e
promote_app_role
_promote_status=$?
ensure_app_database
_ensure_status=$?
set -e
if [ "$_promote_status" -ne 0 ] || [ "$_ensure_status" -ne 0 ]; then
  echo "Failed to configure PostgreSQL role/database (promote=${_promote_status}, ensure=${_ensure_status})"
  exit 1
fi

echo "Starting internal Redis..."
if redis-cli -p "${REDIS_PORT}" ping >/dev/null 2>&1; then
  echo "Redis already listening on port ${REDIS_PORT}"
else
  redis-server --daemonize yes --protected-mode no --bind 127.0.0.1 --port "${REDIS_PORT}"
fi
python "${REPO_ROOT}/scripts/wait_for_redis.py"

cleanup() {
  redis-cli -p "${REDIS_PORT}" shutdown nosave >/dev/null 2>&1 || true
  su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} stop -m fast" >/dev/null 2>&1 || true
}
trap cleanup EXIT

exec python manage.py test --keepdb "$@"
