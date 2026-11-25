"""Feed a long-lived pipe from the channel TS buffer, cutting at the same places for profiles and fMP4."""

from __future__ import annotations

import time

from .pipe_restart import RestartOutcome
from .ts_pmt import PmtLayoutWatcher


def feed_chunk_with_layout_watch(
    data: bytes, watcher: PmtLayoutWatcher, write_stdin, restart, chunk_index=None
) -> bool:
    """Write one chunk, replacing the process at each PMT change.

    ``write_stdin(data)`` returns False when the writer must stop.
    ``restart(reason, flush)`` receives the bytes before the changed PMT in
    ``flush``. ``chunk_index`` is the chunk's buffer index, so another
    output's lookup of the same chunk can be reused. After a replace the new
    process is handed the PAT, then any PMT packets that started earlier,
    then the media. Returns False when the writer loop must stop.
    """
    while data:
        change_at = watcher.find_layout_change(data, chunk_index)
        # Past a cut, `data` is a remainder with packets prepended, no longer
        # the chunk the index names.
        chunk_index = None
        if change_at is None:
            return write_stdin(data)
        head, data = data[:change_at], data[change_at:]
        outcome = restart(reason="PMT/ES layout change", flush=head)
        if outcome == RestartOutcome.STOP:
            return False
        if outcome == RestartOutcome.KEPT:
            # Spawn failed. Revert so a later copy of this PMT retries.
            watcher.revert_layout_change()
            return write_stdin(data)
        watcher.accept_layout_change()
        # PAT, then a PMT section that may have started in an earlier chunk, then the media.
        data = watcher.pat_packet + watcher.leading_section + data
    return True


def run_ts_buffer_writer(
    *,
    is_running,
    ts_buffer,
    behind_seconds: float,
    watcher: PmtLayoutWatcher,
    feed_chunk,
    on_discontinuity,
    before_poll=None,
    on_feed_failure=None,
    log_debug=None,
    sleep_fn=time.sleep,
    idle_sleep=0.05,
    skip_behind=20,
    skip_to_margin=5,
):
    """Read TS chunks and feed them until stopped.

    ``on_discontinuity`` returns STOP to end the loop or REPLACED to reset
    the watcher. ``before_poll`` may return a new index, None to keep the
    current one, or False to stop. ``on_feed_failure`` returns True to retry
    the batch on the next poll, so ``before_poll`` can respawn, or False to stop.
    """
    start_index = (
        ts_buffer.find_chunk_index_by_time(behind_seconds)
        if behind_seconds > 0
        else None
    )
    if start_index is None:
        start_index = ts_buffer.index
    local_index = start_index
    if log_debug:
        log_debug(f"Writer started at index {local_index}")

    while is_running():
        if before_poll is not None:
            updated = before_poll(local_index, watcher)
            if updated is False:
                return
            if updated is not None:
                local_index = updated

        indexed, new_index = ts_buffer.get_optimized_client_data_indexed(local_index)

        if indexed:
            # Use each chunk's real Redis index. A hole in the middle
            # must not slide the following chunks onto the wrong
            # discontinuity mark.
            disc_at = set(
                ts_buffer.discontinuities_in_range(local_index, new_index)
            )
            prev_index = local_index
            for chunk_index, chunk in indexed:
                if not is_running():
                    return
                if any(prev_index < disc <= chunk_index for disc in disc_at):
                    outcome = on_discontinuity(
                        reason=f"input discontinuity at index {chunk_index}"
                    )
                    if outcome == RestartOutcome.STOP:
                        return
                    if outcome == RestartOutcome.REPLACED:
                        watcher.reset()
                if not feed_chunk(chunk, watcher, chunk_index):
                    if on_feed_failure is not None and on_feed_failure():
                        break
                    return
                prev_index = chunk_index
            else:
                # Advance only when every chunk was fed. A break leaves
                # local_index where it is so before_poll can rewind.
                local_index = new_index
        else:
            if ts_buffer.index > local_index + skip_behind:
                skip_to = ts_buffer.index - skip_to_margin
                # Source switches inside the skipped range never reach
                # the loop above, so restart for them here.
                if ts_buffer.discontinuities_in_range(local_index, skip_to):
                    outcome = on_discontinuity(
                        reason="input discontinuity in skipped range"
                    )
                    if outcome == RestartOutcome.STOP:
                        return
                    if outcome == RestartOutcome.REPLACED:
                        watcher.reset()
                local_index = skip_to
            sleep_fn(idle_sleep)
