#!/bin/bash
# Helper for test-log-collector-supervision.sh: stop_log_collector unblocks wait.
set -euo pipefail

INIT_SCRIPT="$1"
DIR="$2"
. "$INIT_SCRIPT"

exec 3>&1
exec > >({
    trap 'exit 0' TERM
    while IFS= read -r _line; do :; done
} >&3) 2>&1

cleanup() {
    stop_log_collector
    wait
    echo cleanup-done
    exit 0
}
trap cleanup TERM

while true; do sleep 1; done
