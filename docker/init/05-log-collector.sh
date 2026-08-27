#!/bin/bash
#
# Log collector startup: archive the previous run's file, then supervise the
# collector process for the life of the container.
#
# Sourced by entrypoint.sh, which runs the supervisor inside the process
# substitution that owns the container's merged stdout.

# Each container collects under its own name; /data is shared in modular mode.
collector_log_name() {
    local role
    role="$(printf '%s' "${DISPATCHARR_LOG_ROLE:-}" | tr -cd 'A-Za-z0-9' | cut -c1-16)"
    printf 'dispatcharr.log%s' "${role:+-$role}"
}

# Shifts, never deletes: the collector prunes per the retention setting.
archive_previous_log() {
    local dir="$1" n name esc
    name="$(collector_log_name)"
    esc="${name//./\\.}"
    mkdir -p "$dir" 2>/dev/null || true
    if [ -s "$dir/$name" ]; then
        # Highest index first so nothing is clobbered on the way up.
        for n in $(ls "$dir" 2>/dev/null \
                     | sed -n "s/^$esc\.\([0-9][0-9]*\)$/\1/p" | sort -rn); do
            mv "$dir/$name.$n" "$dir/$name.$((n + 1))" 2>/dev/null || true
        done
        mv "$dir/$name" "$dir/$name.1" 2>/dev/null || true
    fi
    touch "$dir/$name" 2>/dev/null || true
}

# Run as a module from /app, the way uwsgi loads the app: by path it would get
# /app/dispatcharr on sys.path instead of /app, and any import of a sibling
# module would fail. Positional parameters, not interpolation: `su -` strips the
# environment, and an operator-set path inside the -c string would be shell input.
start_log_collector() {
    if [ -z "$1" ]; then
        # No application user here, and `su -` would strip the role.
        (cd /app && exec "$2" -m dispatcharr.log_collector "$3")
    else
        su - "$1" -c 'cd /app && exec "$0" -m dispatcharr.log_collector "$1"' "$2" "$3"
    fi
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
