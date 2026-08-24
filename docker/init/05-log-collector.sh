#!/bin/bash
#
# Log collector startup: archive the previous run's file, then supervise the
# collector process for the life of the container.
#
# Sourced by entrypoint.sh, which runs the supervisor inside the process
# substitution that owns the container's merged stdout.

# Shifts, never deletes: the collector prunes per the retention setting.
archive_previous_log() {
    local dir="$1" n
    mkdir -p "$dir" 2>/dev/null || true
    if [ -s "$dir/dispatcharr.log" ]; then
        # Highest index first so nothing is clobbered on the way up.
        for n in $(ls "$dir" 2>/dev/null \
                     | sed -n 's/^dispatcharr\.log\.\([0-9][0-9]*\)$/\1/p' | sort -rn); do
            mv "$dir/dispatcharr.log.$n" "$dir/dispatcharr.log.$((n + 1))" 2>/dev/null || true
        done
        mv "$dir/dispatcharr.log" "$dir/dispatcharr.log.1" 2>/dev/null || true
    fi
    touch "$dir/dispatcharr.log" 2>/dev/null || true
}

# Positional parameters, not interpolation: `su -` strips the environment, and
# an operator-set path inside the -c string would become shell input.
start_log_collector() {
    su - "$1" -c 'cd /app && exec "$0" /app/dispatcharr/log_collector.py "$1"' "$2" "$3"
}

# docker logs must outlive any collector fault: three rapid failures degrade to
# a plain cat passthrough rather than a restart loop that drops the stream.
supervise_log_collector() {
    local user="$1" python="$2" dir="$3"
    local failures=0 started
    while :; do
        started=$SECONDS
        start_log_collector "$user" "$python" "$dir" && break
        # A long-lived collector that dies is a fresh fault, not a crash loop.
        if [ $((SECONDS - started)) -ge 30 ]; then failures=0; fi
        failures=$((failures + 1))
        if [ "$failures" -ge 3 ]; then
            echo "log collector failing repeatedly; falling back to passthrough"
            exec cat
        fi
        echo "log collector exited abnormally; restarting"
        sleep "${LOG_COLLECTOR_RESTART_DELAY:-0.2}"
    done
}
