#!/bin/bash

# PostgreSQL uses /dev/shm for dynamic shared memory during parallel queries.
# Docker's generic 64 MiB default is small for an all-in-one media server, but
# the limit belongs to the container runtime and cannot be raised by the app.
# Warn once from the container entrypoint so existing custom deployments get an
# actionable message without preventing Dispatcharr from starting.
check_dispatcharr_shared_memory() {
    if [[ "${DISPATCHARR_ENV:-aio}" == "modular" ]]; then
        return 0
    fi

    local recommended_bytes=268435456
    # An explicit value is accepted only for the small shell regression test.
    # Production callers omit it and always inspect the real tmpfs mount.
    local size_bytes="${1:-}"
    if [[ -z "$size_bytes" ]]; then
        if ! size_bytes=$(df -B1 --output=size /dev/shm 2>/dev/null | awk 'NR == 2 {print $1}'); then
            return 0
        fi
    fi

    if ! [[ "$size_bytes" =~ ^[0-9]+$ ]]; then
        return 0
    fi
    if (( size_bytes >= recommended_bytes )); then
        return 0
    fi

    local size_mib=$((size_bytes / 1024 / 1024))
    echo "" >&2
    echo "================================================================" >&2
    echo "WARNING: Dispatcharr has only ${size_mib} MiB of shared memory." >&2
    echo "  The AIO PostgreSQL database uses /dev/shm for parallel queries." >&2
    echo "  256 MiB is recommended; this is a capacity limit and is not" >&2
    echo "  allocated from host RAM until it is actually used." >&2
    echo "" >&2
    echo "  Docker Compose:  shm_size: 256mb" >&2
    echo "  docker run:      --shm-size=256m" >&2
    echo "" >&2
    echo "  Dispatcharr will continue to start, but large or concurrent" >&2
    echo "  database queries may otherwise fail with 'No space left on device'." >&2
    echo "================================================================" >&2
    echo "" >&2
}
