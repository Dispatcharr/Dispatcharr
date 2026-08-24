#!/bin/bash
#
# Unit tests for docker/init/05-log-collector.sh: the boot archive shift and the
# collector supervision loop. The collector invocation is stubbed, so no Docker
# and no image build.
#
# Usage:
#   bash docker/tests/test-log-collector-supervision.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INIT_SCRIPT="$SCRIPT_DIR/../init/05-log-collector.sh"
PASSED=0
FAILED=0

# Keep the restart backoff out of the runtime.
export LOG_COLLECTOR_RESTART_DELAY=0

check() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo "  PASS  $label"
        PASSED=$((PASSED + 1))
    else
        echo "  FAIL  $label"
        echo "        expected: $expected"
        echo "        actual:   $actual"
        FAILED=$((FAILED + 1))
    fi
}

contains() {
    local label="$1" needle="$2" haystack="$3"
    case "$haystack" in
        *"$needle"*) echo "  PASS  $label"; PASSED=$((PASSED + 1)) ;;
        *) echo "  FAIL  $label"; echo "        wanted to find: $needle"
           echo "        in: $haystack"; FAILED=$((FAILED + 1)) ;;
    esac
}

absent() {
    local label="$1" needle="$2" haystack="$3"
    case "$haystack" in
        *"$needle"*) echo "  FAIL  $label"; echo "        unexpectedly found: $needle"
                     FAILED=$((FAILED + 1)) ;;
        *) echo "  PASS  $label"; PASSED=$((PASSED + 1)) ;;
    esac
}

###############################################################################
echo "archive_previous_log"
###############################################################################
# shellcheck source=../init/05-log-collector.sh
. "$INIT_SCRIPT"

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

printf 'live\n' > "$DIR/dispatcharr.log"
printf 'one\n' > "$DIR/dispatcharr.log.1"
printf 'two\n' > "$DIR/dispatcharr.log.2"
archive_previous_log "$DIR"

check "live log becomes .1" "live" "$(cat "$DIR/dispatcharr.log.1")"
check "old .1 shifts to .2" "one" "$(cat "$DIR/dispatcharr.log.2")"
check "old .2 shifts to .3, nothing clobbered" "two" "$(cat "$DIR/dispatcharr.log.3")"
check "a fresh live log is left in place" "0" "$(stat -c %s "$DIR/dispatcharr.log")"

# With persistence off the collector never writes, so shifting on every boot
# would walk real archives off the end of the retention.
rm -f "$DIR"/dispatcharr.log*
: > "$DIR/dispatcharr.log"
printf 'keep me\n' > "$DIR/dispatcharr.log.1"
archive_previous_log "$DIR"
check "an empty live log does not shift the archives" "keep me" "$(cat "$DIR/dispatcharr.log.1")"

NEW="$DIR/fresh/logs"
archive_previous_log "$NEW"
check "creates the log directory on first boot" "0" "$(stat -c %s "$NEW/dispatcharr.log")"

###############################################################################
echo "supervise_log_collector"
###############################################################################

# A clean exit means the container is shutting down, not a fault.
run_clean_exit() {
    . "$INIT_SCRIPT"
    start_log_collector() { return 0; }
    supervise_log_collector user python /tmp 2>&1
    echo "supervisor returned"
}
OUT="$(run_clean_exit)"
contains "a clean exit returns" "supervisor returned" "$OUT"
absent "a clean exit does not restart" "restarting" "$OUT"

run_two_failures() {
    . "$INIT_SCRIPT"
    ATTEMPT=0
    start_log_collector() {
        ATTEMPT=$((ATTEMPT + 1))
        [ "$ATTEMPT" -gt 2 ]
    }
    supervise_log_collector user python /tmp 2>&1
    echo "attempts=$ATTEMPT"
}
OUT="$(run_two_failures)"
contains "restarts after a failure" "log collector exited abnormally; restarting" "$OUT"
contains "recovers on the third attempt" "attempts=3" "$OUT"
absent "does not degrade after two failures" "falling back to passthrough" "$OUT"

# The timeout is an assertion: a supervisor that never degrades restarts
# forever, so a timeout here is a failure, not a flake.
OUT="$(timeout 5 bash "$SCRIPT_DIR/_supervisor_case.sh" "$INIT_SCRIPT" always-fails 2>&1)"
DEGRADE_RC=$?
check "degradation terminates rather than restarting forever" "0" "$DEGRADE_RC"
contains "degrades after three rapid failures" "falling back to passthrough" "$OUT"
contains "passthrough carries stdin to stdout" "a line the collector never saw" "$OUT"

# Capped for the same reason: if the counter stops resetting this degrades,
# and a degraded supervisor replaces itself with cat.
OUT="$(timeout 5 bash "$SCRIPT_DIR/_supervisor_case.sh" "$INIT_SCRIPT" slow-failures 2>&1)"
SLOW_RC=$?
check "a long-lived collector is restarted, not degraded" "0" "$SLOW_RC"
absent "long-lived failures never degrade" "falling back to passthrough" "$OUT"
contains "keeps restarting a long-lived collector" "attempts=6" "$OUT"

###############################################################################
echo
echo "passed: $PASSED  failed: $FAILED"
[ "$FAILED" -eq 0 ]
