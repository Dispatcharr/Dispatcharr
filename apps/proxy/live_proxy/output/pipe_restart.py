"""Replace a long-lived output process at a stream boundary.

Spawn the replacement first, drain the old process, then mark the output
discontinuous. Output profiles and the fMP4 remux share this.
"""

from __future__ import annotations

import enum
import select
import threading
import time


# Time the old process gets to flush after stdin closes, before it is killed.
# Measured drains: ~2 ms (copy), ~90 ms (AAC), ~110-130 ms (x264 veryfast).
DRAIN_TIMEOUT_SECONDS = 0.25

# Bounds a reader stuck in a slow write. After the kill, pipes hit EOF at once.
RETIRE_JOIN_SECONDS = 1.0


class RestartOutcome(enum.Enum):
    """STOP: the writer must end (stopping, or the process had already exited).
    REPLACED: the new process owns stdin.
    KEPT: spawn failed. The current process continues, and a layout change
    is retried when the next PMT arrives.
    """

    STOP = enum.auto()
    REPLACED = enum.auto()
    KEPT = enum.auto()


class ProcessSlot:
    """closing: stdin was closed on purpose, so stdout EOF is not the end of the stream.
    abandoned: this process was retired, so stop forwarding its output.
    """

    __slots__ = ("process", "closing", "abandoned", "reader", "stderr")

    def __init__(self, process):
        self.process = process
        self.closing = threading.Event()
        self.abandoned = threading.Event()
        self.reader = None
        self.stderr = None


def write_all(process, data: bytes, *, is_running, deadline=None) -> bool:
    """Write every byte, looping on a short write.

    With a deadline, give up and return False when it passes. Otherwise block
    until the pipe takes everything or ``is_running`` is false.
    """
    view = memoryview(data)
    offset = 0
    total = len(view)
    while offset < total:
        if not is_running():
            return False
        if deadline is not None and time.monotonic() >= deadline:
            return False
        n = process.stdin.write(view[offset:])
        if n is None:
            # Pipe full (EAGAIN on non-blocking FD); yield cooperatively.
            wait = 1.0
            if deadline is not None:
                wait = max(0.0, min(wait, deadline - time.monotonic()))
            select.select([], [process.stdin], [], wait)
        elif n <= 0:
            raise OSError("stdin write returned no bytes")
        else:
            offset += n
    return True


def replace_piped_process(
    *,
    is_running,
    current_slot: ProcessSlot,
    spawn,
    set_current,
    start_slot_threads,
    after_old_retired=None,
    flush: bytes = b"",
    drain_timeout: float | None = None,
    retire_join: float | None = None,
    log_warning=None,
    log_error=None,
    log_info=None,
    reason: str = "",
    noun: str = "process",
) -> RestartOutcome:
    """Spawn the replacement before the old process is touched, so ``_process`` is never published dead.

    A process that has already exited returns STOP and is left for the caller.
    ``after_old_retired`` runs once the old reader has stopped and before the
    new readers start, so a discontinuity mark is not followed by old output.
    On KEPT, ``flush`` is written to the process that was kept.
    """
    # Resolved here, not in the signature, so the module constants can be
    # tuned (or patched in tests) after import.
    if drain_timeout is None:
        drain_timeout = DRAIN_TIMEOUT_SECONDS
    if retire_join is None:
        retire_join = RETIRE_JOIN_SECONDS

    if not is_running():
        return RestartOutcome.STOP

    if current_slot.process.poll() is not None:
        if log_warning:
            log_warning(
                f"{noun.capitalize()} already exited ({reason}); "
                f"leaving restart to the server"
            )
        return RestartOutcome.STOP

    try:
        new_process = spawn()
    except (FileNotFoundError, OSError) as e:
        if log_error:
            log_error(
                f"Failed to restart {noun} ({reason}), keeping current process: {e}"
            )
        # Nothing else will write the pre-boundary bytes, so the kept process gets them.
        if flush:
            try:
                write_all(current_slot.process, flush, is_running=is_running)
                current_slot.process.stdin.flush()
            except (BrokenPipeError, OSError):
                return RestartOutcome.STOP
        return RestartOutcome.KEPT

    if log_info:
        log_info(f"Restarting {noun} ({reason})")

    started = time.monotonic()
    deadline = started + drain_timeout
    old = current_slot
    new = ProcessSlot(new_process)
    set_current(new_process, new)

    old.closing.set()
    if flush:
        try:
            write_all(
                old.process,
                flush,
                is_running=is_running,
                deadline=deadline,
            )
        except (BrokenPipeError, OSError):
            pass  # the old process is already gone
    try:
        old.process.stdin.close()
    except Exception:
        pass
    if old.reader and old.reader.is_alive():
        old.reader.join(timeout=max(0.0, deadline - time.monotonic()))
    drained = not (old.reader and old.reader.is_alive())

    old.abandoned.set()
    try:
        if old.process.poll() is None:
            old.process.kill()
            old.process.wait(timeout=1)
    except Exception:
        pass
    for t in (old.reader, old.stderr):
        if t and t.is_alive():
            try:
                t.join(timeout=retire_join)
            except Exception:
                pass

    if not is_running():
        # stop() ran while we were swapping; it only knows the new process.
        try:
            new_process.kill()
        except Exception:
            pass
        return RestartOutcome.STOP

    if after_old_retired is not None:
        after_old_retired()

    start_slot_threads(new)
    if log_info:
        log_info(
            f"{noun.capitalize()} restarted (pid={new_process.pid}, {reason}, "
            f"old process {'drained' if drained else 'killed'} in "
            f"{(time.monotonic() - started) * 1000:.0f} ms)"
        )
    return RestartOutcome.REPLACED
