#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_SCRIPT="$SCRIPT_DIR/../init/00-check-shm.sh"
. "$CHECK_SCRIPT"

low_output=$(
    DISPATCHARR_ENV=aio check_dispatcharr_shared_memory 67108864 2>&1
)
grep -q "only 64 MiB of shared memory" <<<"$low_output"
grep -q "shm_size: 256mb" <<<"$low_output"

recommended_output=$(
    DISPATCHARR_ENV=aio check_dispatcharr_shared_memory 268435456 2>&1
)
test -z "$recommended_output"

modular_output=$(
    DISPATCHARR_ENV=modular check_dispatcharr_shared_memory 67108864 2>&1
)
test -z "$modular_output"

echo "Shared-memory startup warning tests passed"
