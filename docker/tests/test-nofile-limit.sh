#!/bin/bash
#
# Integration tests for worker RLIMIT_NOFILE after su -/pam_limits in entrypoint.sh.
#
# Prerequisites: Docker; ~5 minutes for a full run (image build).
#
# Usage:
#   bash docker/tests/test-nofile-limit.sh [--skip-build] [--keep-on-fail] [scenario_name]
#
# Scenarios: default_limit, pam_reset, env_override, above_hard_limit, compose_ulimits

set -uo pipefail

# Prevent Git Bash (MINGW) from converting Unix paths when passing arguments to
# docker exec.
export MSYS_NO_PATHCONV=1

###############################################################################
# Configuration
###############################################################################
IMAGE_NAME="dispatcharr:nofile-test"
TEST_PREFIX="nofile_test"
STARTUP_TIMEOUT=180
DEFAULT_EXPECTED_FD=65536
SKIP_BUILD=false
KEEP_ON_FAIL=false
SINGLE_SCENARIO=""
PASS=0
FAIL=0
SKIP=0
ERRORS=()

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

###############################################################################
# Parse arguments
###############################################################################
for arg in "$@"; do
    case "$arg" in
        --skip-build)   SKIP_BUILD=true ;;
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
log_skip() { echo -e "  ${YELLOW}⏭️  $1${NC}"; SKIP=$((SKIP + 1)); }
log_info() { echo -e "  ${CYAN}ℹ️  $1${NC}"; }
section()  { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; CURRENT_SCENARIO="$1"; SCENARIO_FAIL_BEFORE=$FAIL; }

track_container() { CLEANUP_ITEMS+=("container:$1"); }
track_volume()    { CLEANUP_ITEMS+=("volume:$1"); }

fresh_volume() {
    local vol="$1"
    docker rm -f $(docker ps -aq --filter "volume=${vol}") 2>/dev/null || true
    docker volume rm "$vol" 2>/dev/null || true
    docker volume create "$vol" >/dev/null
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
            container) docker stop "$name" 2>/dev/null; docker rm -f "$name" 2>/dev/null ;;
            volume)    docker volume rm "$name" 2>/dev/null ;;
        esac
    done
    CLEANUP_ITEMS=()
}

trap 'cleanup_scenario' EXIT

should_run() {
    [ -z "$SINGLE_SCENARIO" ] || [ "$SINGLE_SCENARIO" = "$1" ]
}

# Wait until uwsgi has spawned its daphne attach-daemon.
wait_for_workers() {
    local name="$1"
    local waited=0
    while [ "$waited" -lt "$STARTUP_TIMEOUT" ]; do
        if docker exec "$name" bash -c 'pgrep -f "bin/daphne" >/dev/null' 2>/dev/null; then
            return 0
        fi
        if ! docker ps --format '{{.Names}}' | grep -qx "$name"; then
            log_fail "Container $name exited during startup"
            docker logs --tail 40 "$name" 2>&1 | sed 's/^/      /'
            return 1
        fi
        sleep 3
        waited=$((waited + 3))
    done
    log_fail "Timed out after ${STARTUP_TIMEOUT}s waiting for workers in $name"
    docker logs --tail 40 "$name" 2>&1 | sed 's/^/      /'
    return 1
}

# Soft RLIMIT_NOFILE of the first process matching a pgrep pattern.
soft_nofile_of() {
    local name="$1" pattern="$2"
    docker exec "$name" bash -c "
        pid=\$(pgrep -f '$pattern' | head -1)
        [ -n \"\$pid\" ] || exit 1
        awk '/Max open files/ {print \$4}' /proc/\$pid/limits
    " 2>/dev/null
}

assert_soft_nofile() {
    local name="$1" pattern="$2" expected="$3" label="$4"
    local actual
    actual=$(soft_nofile_of "$name" "$pattern")
    if [ -z "$actual" ]; then
        log_fail "$label: no process matched '$pattern'"
    elif [ "$actual" = "$expected" ]; then
        log_pass "$label soft nofile = $actual"
    else
        log_fail "$label soft nofile = $actual (expected $expected)"
    fi
}

start_aio() {
    local name="$1"; shift
    fresh_volume "${name}_data"
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e REDIS_HOST=localhost \
        -e CELERY_BROKER_URL=redis://localhost:6379/0 \
        -v "${name}_data:/data" \
        "$@" \
        "$IMAGE_NAME" >/dev/null
    track_container "$name"
}

###############################################################################
# Build
###############################################################################
if [ "$SKIP_BUILD" = false ]; then
    echo -e "${BOLD}━━━ Building $IMAGE_NAME ━━━${NC}"
    if ! docker build -f docker/Dockerfile -t "$IMAGE_NAME" . ; then
        echo -e "${RED}Build failed${NC}"
        exit 1
    fi
else
    log_info "Skipping build (--skip-build)"
fi

###############################################################################
# Scenario: default_limit
###############################################################################
if should_run default_limit; then
    section "default_limit"
    name="${TEST_PREFIX}_default"
    docker rm -f "$name" >/dev/null 2>&1
    start_aio "$name"
    if wait_for_workers "$name"; then
        assert_soft_nofile "$name" "bin/uwsgi"  "$DEFAULT_EXPECTED_FD" "uwsgi"
        assert_soft_nofile "$name" "bin/daphne" "$DEFAULT_EXPECTED_FD" "daphne"
        assert_soft_nofile "$name" "bin/celery" "$DEFAULT_EXPECTED_FD" "celery"
    fi
    cleanup_scenario
fi

###############################################################################
# Scenario: pam_reset
# Regression: su - used to leave workers at soft 1024 via pam_limits.
###############################################################################
if should_run pam_reset; then
    section "pam_reset"
    name="${TEST_PREFIX}_pam"
    docker rm -f "$name" >/dev/null 2>&1
    start_aio "$name" --ulimit "nofile=65536:524288"
    if wait_for_workers "$name"; then
        pid1=$(docker exec "$name" bash -c 'ulimit -n' 2>/dev/null)
        if [ "$pid1" = "65536" ]; then
            log_pass "container default soft nofile = $pid1"
        else
            log_fail "container default soft nofile = $pid1 (expected 65536)"
        fi

        daphne_fd=$(soft_nofile_of "$name" "bin/daphne")
        if [ "$daphne_fd" = "1024" ]; then
            log_fail "daphne still pinned to 1024, pam_limits reset is back"
        else
            log_pass "daphne is not pinned to 1024 (got $daphne_fd)"
        fi
    fi
    cleanup_scenario
fi

###############################################################################
# Scenario: env_override
###############################################################################
if should_run env_override; then
    section "env_override"
    name="${TEST_PREFIX}_override"
    docker rm -f "$name" >/dev/null 2>&1
    start_aio "$name" -e DISPATCHARR_NOFILE=32768
    if wait_for_workers "$name"; then
        assert_soft_nofile "$name" "bin/uwsgi"  32768 "uwsgi"
        assert_soft_nofile "$name" "bin/daphne" 32768 "daphne"
    fi
    cleanup_scenario
fi

###############################################################################
# Scenario: above_hard_limit
# DISPATCHARR_NOFILE above hard must not abort startup (entrypoint uses set -e).
# After su -/pam_limits soft is 1024; the failed raise leaves that PAM soft in
# place (not the pre-su Docker soft of 4096).
###############################################################################
if should_run above_hard_limit; then
    section "above_hard_limit"
    name="${TEST_PREFIX}_toohigh"
    docker rm -f "$name" >/dev/null 2>&1
    start_aio "$name" --ulimit "nofile=4096:4096" -e DISPATCHARR_NOFILE=65536
    if wait_for_workers "$name"; then
        log_pass "container started despite DISPATCHARR_NOFILE > hard limit"
        actual=$(soft_nofile_of "$name" "bin/daphne")
        if [ "$actual" = "1024" ]; then
            log_pass "daphne kept the PAM soft limit after failed raise ($actual)"
        else
            log_fail "daphne soft nofile = $actual (expected PAM soft 1024)"
        fi
    fi
    cleanup_scenario
fi

###############################################################################
# Scenario: compose_ulimits
# Raise soft via DISPATCHARR_NOFILE up to a compose-provided hard limit.
###############################################################################
if should_run compose_ulimits; then
    section "compose_ulimits"
    name="${TEST_PREFIX}_ulimits"
    docker rm -f "$name" >/dev/null 2>&1
    start_aio "$name" --ulimit "nofile=200000:524288" -e DISPATCHARR_NOFILE=200000
    if wait_for_workers "$name"; then
        assert_soft_nofile "$name" "bin/daphne" 200000 "daphne"
    fi
    cleanup_scenario
fi

###############################################################################
# Summary
###############################################################################
echo -e "\n${BOLD}━━━ Summary ━━━${NC}"
echo -e "  ${GREEN}Passed: $PASS${NC}   ${RED}Failed: $FAIL${NC}   ${YELLOW}Skipped: $SKIP${NC}"
if [ "$FAIL" -gt 0 ]; then
    echo -e "\n${RED}Failures:${NC}"
    for err in "${ERRORS[@]}"; do
        echo "  - $err"
    done
    exit 1
fi
exit 0
