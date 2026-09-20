#!/bin/bash
#
# Integration tests for PostgreSQL data directory ownership reconciliation
# in docker/init/02-postgres.sh (issue #1453).
#
# Prerequisites: Docker; ghcr.io/dispatcharr/dispatcharr:base-dev pulled;
# ~3-5 minutes for a full run.
#
# Usage:
#   bash docker/tests/test-postgres-directory-ownership.sh [--keep-on-fail] [scenario_name]
#
# Scenarios: top_level_uid_mismatch, top_level_gid_mismatch, healthy_restart,
#   missing_sentinel, stale_sentinel_deep_mismatch, custom_ids_path, modular_skip

set -uo pipefail

# Prevent Git Bash (MINGW) from converting Unix paths like /data/db to
# C:/Program Files/Git/data/db when passing arguments to docker.
export MSYS_NO_PATHCONV=1

###############################################################################
# Configuration
###############################################################################
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-ghcr.io/dispatcharr/dispatcharr:base-dev}"
# Directory mounted at /app/docker inside the test containers. Overridable
# to run the suite against a different copy of the scripts.
DOCKER_DIR="${DOCKER_DIR:-${REPO_ROOT}/docker}"
# Keep concurrent runs on separate volumes.
TEST_PREFIX="pgdir_test_$(date +%s)_$$"
KEEP_ON_FAIL=false
SINGLE_SCENARIO=""
PASS=0
FAIL=0
ERRORS=()

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; CYAN=''; BOLD=''; NC=''
fi

###############################################################################
# Parse arguments
###############################################################################
for arg in "$@"; do
    case "$arg" in
        --keep-on-fail) KEEP_ON_FAIL=true ;;
        -*)             echo "Unknown option: $arg"; exit 1 ;;
        *)              SINGLE_SCENARIO="$arg" ;;
    esac
done

###############################################################################
# Helpers
###############################################################################
CURRENT_SCENARIO=""
CLEANUP_ITEMS=()

log_pass() { echo -e "  ${GREEN}✅ $1${NC}"; PASS=$((PASS + 1)); }
log_fail() { echo -e "  ${RED}❌ $1${NC}"; FAIL=$((FAIL + 1)); ERRORS+=("[$CURRENT_SCENARIO] $1"); }
log_info() { echo -e "  ${CYAN}ℹ️  $1${NC}"; }
section()  { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; SCENARIO_FAIL_BEFORE=$FAIL; }

# Track resources for cleanup
track_volume() { CLEANUP_ITEMS+=("volume:$1"); }

fresh_volume() {
    local vol="$1"
    if ! docker volume create "$vol" >/dev/null; then
        log_fail "Could not create volume $vol"
        return 1
    fi
    track_volume "$vol"
}

cleanup_scenario() {
    if [ "$KEEP_ON_FAIL" = true ] && [ "$FAIL" -gt "${SCENARIO_FAIL_BEFORE:-0}" ]; then
        log_info "Keeping resources for debugging (--keep-on-fail)"
        CLEANUP_ITEMS=()
        return
    fi
    for item in "${CLEANUP_ITEMS[@]}"; do
        local type="${item%%:*}"
        local name="${item#*:}"
        case "$type" in
            volume) docker volume rm "$name" 2>/dev/null ;;
        esac
    done
    CLEANUP_ITEMS=()
}

# Ensure cleanup on script exit
trap 'cleanup_scenario; [ -n "${RUN_LOG:-}" ] && rm -f "$RUN_LOG"' EXIT

# Run initialization, then verify PostgreSQL starts and answers a query.
read -r -d '' CONTAINER_HARNESS <<'EOF' || true
set -o pipefail
export PUID=${PUID:-1000}
export PGID=${PGID:-1000}
export POSTGRES_USER=${POSTGRES_USER:-dispatch}
export POSTGRES_DB=${POSTGRES_DB:-dispatcharr}
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export POSTGRES_DIR=${POSTGRES_DIR:-/data/db}
export DISPATCHARR_ENV=${DISPATCHARR_ENV:-aio}
export PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
export PG_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"

. /app/docker/init/01-user-setup.sh
. /app/docker/init/02-postgres.sh

if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
    exit 0
fi

prepare_pg_socket_dir
if ! su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 60 -o '-c port=${POSTGRES_PORT}'"; then
    echo "PostgreSQL failed to start"
    exit 1
fi
if ! su - "$POSTGRES_USER" -c "psql -p ${POSTGRES_PORT} -d postgres -tAc 'SELECT 1;'" | grep -qx 1; then
    echo "PostgreSQL started but did not answer a query"
    su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} stop -w -m fast" 2>/dev/null
    exit 1
fi
su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} stop -w -m fast" >/dev/null || exit 1
exit 0
EOF

# Extra arguments are passed to docker run.
RUN_LOG=""
run_init() {
    local vol="$1"; shift
    [ -n "$RUN_LOG" ] && rm -f "$RUN_LOG"
    RUN_LOG=$(mktemp)
    docker run --rm \
        -v "${DOCKER_DIR}:/app/docker:ro" \
        -v "${vol}:/data" \
        -e PUID=1000 -e PGID=1000 "$@" \
        --entrypoint bash "$IMAGE_NAME" -c "$CONTAINER_HARNESS" > "$RUN_LOG" 2>&1
}

# Run a one-off command against a volume (setup/tampering/inspection)
run_cmd() {
    local vol="$1" cmd="$2"
    docker run --rm -v "${vol}:/data" --entrypoint bash "$IMAGE_NAME" -c "$cmd"
}

# PostgreSQL does not touch this root-owned marker. A recursive chown
# changes its owner and ctime.
plant_canary() {
    local vol="$1" dir="${2:-/data/db}"
    run_cmd "$vol" "touch '$dir/.chown_canary' && chown 0:0 '$dir/.chown_canary'" >/dev/null
}
canary_state() {
    local vol="$1" dir="${2:-/data/db}"
    run_cmd "$vol" "stat -c '%u:%g %z' '$dir/.chown_canary'"
}
check_canary_untouched() {
    local vol="$1" before="$2" dir="${3:-/data/db}"
    local after
    after=$(canary_state "$vol" "$dir")
    if [ -n "$before" ] && [ "$before" = "$after" ]; then
        log_pass "Marker file unchanged (no recursive chown)"
    else
        log_fail "Marker file changed (unexpected recursive chown)"
    fi
}

# Assertions on the captured run output
check_run_contains() {
    local pattern="$1" description="$2"
    if grep -q "$pattern" "$RUN_LOG"; then
        log_pass "$description"
    else
        log_fail "$description (pattern not found: $pattern)"
    fi
}
check_run_absent() {
    local pattern="$1" description="$2"
    if grep -q "$pattern" "$RUN_LOG"; then
        log_fail "$description (unexpected pattern found: $pattern)"
    else
        log_pass "$description"
    fi
}

# Verify volume-side ownership without a running container
check_vol_ownership() {
    local vol="$1" path="$2" expected="$3"
    local actual
    actual=$(run_cmd "$vol" "stat -c '%u:%g' '$path'" 2>/dev/null)
    if [ "$actual" = "$expected" ]; then
        log_pass "Ownership $path = $actual"
    else
        log_fail "Ownership $path: expected $expected, got ${actual:-<error>}"
    fi
}

# Initialize a database for restart scenarios.
setup_healthy_cluster() {
    local vol="$1" pgdir="${2:-/data/db}"
    shift; [ $# -gt 0 ] && shift || true
    log_info "Initializing healthy cluster at $pgdir..."
    if ! run_init "$vol" -e POSTGRES_DIR="$pgdir" "$@"; then
        log_fail "Setup failed: fresh install did not start PostgreSQL"
        cleanup_scenario
        return 1
    fi
}

###############################################################################
# Test Scenarios
###############################################################################

test_top_level_uid_mismatch() {
    CURRENT_SCENARIO="top_level_uid_mismatch"
    section "Top-level directory UID mismatch (issue #1453)"

    local vol="${TEST_PREFIX}_uidmix_data"
    cleanup_scenario
    fresh_volume "$vol" || return
    setup_healthy_cluster "$vol" || return

    plant_canary "$vol"
    local before
    before=$(canary_state "$vol")

    # Change only the data directory; leave its contents and sentinel intact.
    run_cmd "$vol" "chown 568:568 /data/db" >/dev/null

    if run_init "$vol"; then
        log_pass "PostgreSQL started after top-level repair"
    else
        log_fail "PostgreSQL failed to start with mismatched top-level owner"
    fi
    check_run_contains "Fixing ownership for /data/db (non-recursive)" \
        "Non-recursive directory repair logged"
    check_run_absent "Migrating PostgreSQL data ownership" \
        "No recursive ownership migration"
    check_vol_ownership "$vol" "/data/db" "1000:1000"
    check_canary_untouched "$vol" "$before"
    cleanup_scenario
}

test_top_level_gid_mismatch() {
    CURRENT_SCENARIO="top_level_gid_mismatch"
    section "Top-level directory GID mismatch (group only)"

    local vol="${TEST_PREFIX}_gidmix_data"
    cleanup_scenario
    fresh_volume "$vol" || return
    setup_healthy_cluster "$vol" || return

    run_cmd "$vol" "chown 1000:568 /data/db" >/dev/null

    if run_init "$vol"; then
        log_pass "PostgreSQL started after top-level group repair"
    else
        log_fail "PostgreSQL failed to start with mismatched top-level group"
    fi
    check_run_contains "Fixing ownership for /data/db (non-recursive)" \
        "Non-recursive directory repair logged"
    check_run_absent "Migrating PostgreSQL data ownership" \
        "No recursive ownership migration"
    check_vol_ownership "$vol" "/data/db" "1000:1000"
    cleanup_scenario
}

test_healthy_restart() {
    CURRENT_SCENARIO="healthy_restart"
    section "Healthy restart — no directory repair, idempotent"

    local vol="${TEST_PREFIX}_healthy_data"
    cleanup_scenario
    fresh_volume "$vol" || return
    setup_healthy_cluster "$vol" || return

    plant_canary "$vol"
    local before
    before=$(canary_state "$vol")

    if run_init "$vol"; then
        log_pass "PostgreSQL started on healthy restart"
    else
        log_fail "PostgreSQL failed to start on healthy restart"
    fi
    check_run_absent "Fixing ownership for /data/db" \
        "No directory repair on healthy restart"
    check_run_absent "Migrating PostgreSQL data ownership" \
        "No recursive ownership migration on healthy restart"
    check_canary_untouched "$vol" "$before"
    cleanup_scenario
}

test_missing_sentinel() {
    CURRENT_SCENARIO="missing_sentinel"
    section "Missing sentinel — rewritten without recursive chown"

    local vol="${TEST_PREFIX}_nosent_data"
    cleanup_scenario
    fresh_volume "$vol" || return
    setup_healthy_cluster "$vol" || return

    run_cmd "$vol" "rm /data/db/.owner_puid" >/dev/null
    plant_canary "$vol"
    local before
    before=$(canary_state "$vol")

    if run_init "$vol"; then
        log_pass "PostgreSQL started with missing sentinel"
    else
        log_fail "PostgreSQL failed to start with missing sentinel"
    fi
    check_run_absent "Migrating PostgreSQL data ownership" \
        "No recursive ownership migration"
    check_run_absent "Fixing ownership for /data/db" \
        "No directory repair"

    local sentinel_val
    sentinel_val=$(run_cmd "$vol" "cat /data/db/.owner_puid" 2>/dev/null | tr -d '[:space:]')
    if [ "$sentinel_val" = "1000:1000" ]; then
        log_pass "Sentinel rewritten (1000:1000)"
    else
        log_fail "Sentinel: expected 1000:1000, got ${sentinel_val:-<missing>}"
    fi
    check_canary_untouched "$vol" "$before"
    cleanup_scenario
}

test_stale_sentinel_deep_mismatch() {
    CURRENT_SCENARIO="stale_sentinel_deep_mismatch"
    section "Stale sentinel + deep mismatch — recursive migration still works"

    local vol="${TEST_PREFIX}_stale_data"
    cleanup_scenario
    fresh_volume "$vol" || return
    setup_healthy_cluster "$vol" || return

    # Leave base/ owned by the previous user with a stale sentinel.
    run_cmd "$vol" "echo '999:999' > /data/db/.owner_puid && chown -R 999:999 /data/db/base" >/dev/null

    if run_init "$vol"; then
        log_pass "PostgreSQL started after recursive migration"
    else
        log_fail "PostgreSQL failed to start after recursive migration"
    fi
    check_run_contains "Migrating PostgreSQL data ownership" \
        "Recursive ownership migration logged"
    check_vol_ownership "$vol" "/data/db" "1000:1000"
    check_vol_ownership "$vol" "/data/db/base" "1000:1000"

    local sentinel_val
    sentinel_val=$(run_cmd "$vol" "cat /data/db/.owner_puid" 2>/dev/null | tr -d '[:space:]')
    if [ "$sentinel_val" = "1000:1000" ]; then
        log_pass "Sentinel updated after migration (1000:1000)"
    else
        log_fail "Sentinel: expected 1000:1000, got ${sentinel_val:-<missing>}"
    fi
    cleanup_scenario
}

test_custom_ids_path() {
    CURRENT_SCENARIO="custom_ids_path"
    section "Custom PUID/PGID=1500 and POSTGRES_DIR=/data/customdb"

    local vol="${TEST_PREFIX}_custom_data"
    local pgdir="/data/customdb"
    cleanup_scenario
    fresh_volume "$vol" || return
    setup_healthy_cluster "$vol" "$pgdir" -e PUID=1500 -e PGID=1500 || return

    run_cmd "$vol" "chown 568:568 $pgdir" >/dev/null

    if run_init "$vol" -e PUID=1500 -e PGID=1500 -e POSTGRES_DIR="$pgdir"; then
        log_pass "PostgreSQL started after top-level repair (custom IDs/path)"
    else
        log_fail "PostgreSQL failed to start with custom IDs/path"
    fi
    check_run_contains "Fixing ownership for $pgdir (non-recursive)" \
        "Non-recursive directory repair logged"
    check_vol_ownership "$vol" "$pgdir" "1500:1500"
    cleanup_scenario
}

test_modular_skip() {
    CURRENT_SCENARIO="modular_skip"
    section "Modular mode — internal PostgreSQL data untouched"

    local vol="${TEST_PREFIX}_modular_data"
    cleanup_scenario
    fresh_volume "$vol" || return

    run_cmd "$vol" "mkdir -p /data/db && chown 568:568 /data/db" >/dev/null

    if run_init "$vol" -e DISPATCHARR_ENV=modular; then
        log_pass "Modular init completed (external PostgreSQL)"
    else
        log_fail "Modular init failed"
    fi
    check_run_absent "Fixing ownership" \
        "No ownership repair attempted in modular mode"
    check_run_absent "Migrating PostgreSQL data ownership" \
        "No ownership migration in modular mode"
    check_vol_ownership "$vol" "/data/db" "568:568"
    cleanup_scenario
}

###############################################################################
# Main
###############################################################################

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════╗"
echo "║   PG Directory Ownership Test Suite      ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"

# Define scenario list
SCENARIOS=(
    top_level_uid_mismatch
    top_level_gid_mismatch
    healthy_restart
    missing_sentinel
    stale_sentinel_deep_mismatch
    custom_ids_path
    modular_skip
)

# Reject an unknown scenario before doing any Docker work — otherwise a
# typo would silently run nothing and report success.
if [ -n "$SINGLE_SCENARIO" ]; then
    _known=false
    for scenario in "${SCENARIOS[@]}"; do
        if [ "$scenario" = "$SINGLE_SCENARIO" ]; then
            _known=true
            break
        fi
    done
    if [ "$_known" = false ]; then
        echo -e "${RED}Unknown scenario: $SINGLE_SCENARIO${NC}"
        echo "Available scenarios: ${SCENARIOS[*]}"
        exit 1
    fi
fi

if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    log_info "Pulling $IMAGE_NAME..."
    if ! docker pull "$IMAGE_NAME"; then
        echo -e "${RED}Image $IMAGE_NAME not available. Aborting.${NC}"
        exit 1
    fi
fi
log_info "Using image: $IMAGE_NAME"
log_info "Init scripts from: $DOCKER_DIR"

# Run scenarios
for scenario in "${SCENARIOS[@]}"; do
    if [ -n "$SINGLE_SCENARIO" ] && [ "$scenario" != "$SINGLE_SCENARIO" ]; then
        continue
    fi
    "test_${scenario}"
done

# Summary
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗"
echo -e "║               RESULTS                    ║"
echo -e "╚══════════════════════════════════════════╝${NC}"
echo -e "  ${GREEN}Passed:  $PASS${NC}"
echo -e "  ${RED}Failed:  $FAIL${NC}"

if [ ${#ERRORS[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Failures:${NC}"
    for err in "${ERRORS[@]}"; do
        echo -e "  ${RED}• $err${NC}"
    done
fi

echo ""
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}$FAIL test(s) failed.${NC}"
    exit 1
fi
