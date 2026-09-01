#!/bin/bash
# Helper for test-log-collector-supervision.sh. Runs one scenario in its own
# process so the caller can cap it with `timeout`: a supervisor that fails to
# degrade restarts forever, and one that degrades replaces itself with cat.
#
# Usage: _supervisor_case.sh <init-script> always-fails|slow-failures
set -uo pipefail
. "$1"
export LOG_COLLECTOR_RESTART_DELAY=0

case "$2" in
    always-fails)
        start_log_collector() { return 1; }
        printf 'a line the collector never saw\n' \
            | supervise_log_collector user python /tmp 2>&1
        ;;
    slow-failures)
        ATTEMPT=0
        start_log_collector() {
            ATTEMPT=$((ATTEMPT + 1))
            # Simulate an hour of healthy running before each failure.
            SECONDS=$((SECONDS + 3600))
            [ "$ATTEMPT" -gt 5 ]
        }
        supervise_log_collector user python /tmp 2>&1 < /dev/null
        echo "attempts=$ATTEMPT"
        ;;
esac
