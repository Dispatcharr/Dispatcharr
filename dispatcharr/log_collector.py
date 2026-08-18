"""Everything logger: the container's merged stdout flows through this
process, which forwards each (filtered) line to the real stdout for docker
logs and files the same bytes, so redaction reaches both sinks.

Runs standalone (python -m dispatcharr.log_collector <logdir>); no application
process ever performs log file I/O. The reader owns stdin from the first
instant and touches only stdout, so a dead /data can never back-pressure the
producers; bounded memory with drop-oldest and an explicit dropped-lines
marker absorbs disk stalls (markers are file-only: the forwarded stream never
dropped anything). Owns rotation and pruning. Django-free; configured via
<logdir>/collector.conf and SIGHUP through apply_settings().
"""

import collections
import importlib
import os
import signal
import sys
import threading
import time

LIVE_NAME = "dispatcharr.log"
CONF_NAME = "collector.conf"
PID_NAME = "collector.pid"

_FLUSH_INTERVAL_SECONDS = 0.25
_BATCH_BYTES = 128 * 1024
_BUFFER_BYTES = 2 * 1024 * 1024
_MAX_LINE_BYTES = 256 * 1024
_FILTER_BUDGET_SECONDS = 0.1
_FILTER_STRIKES = 3

_DEFAULT_CONF = {"persist": True, "max_mb": 10, "keep": 5, "filters": ""}


def conf_path(log_dir):
    return os.path.join(log_dir, CONF_NAME)


def pid_path(log_dir):
    return os.path.join(log_dir, PID_NAME)


def write_conf(log_dir, persist, max_mb, keep, filters=""):
    """Write collector.conf atomically; called from the app (safe contexts only)."""
    if not log_dir:
        return
    tmp = f"{conf_path(log_dir)}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(
                f"persist={1 if persist else 0}\n"
                f"max_mb={int(max_mb)}\n"
                f"keep={int(keep)}\n"
                f"filters={filters}\n"
            )
        os.replace(tmp, conf_path(log_dir))
    except OSError:
        pass


def apply_settings(log_dir, values):
    """Push the system-settings log keys to the collector (conf + SIGHUP).

    Runs on settings saves and process boot — rare, small writes. No-op in
    modular mode: /data is shared across containers there and no collector
    runs, so a stale pidfile must never be signalled.
    """
    if os.environ.get("DISPATCHARR_ENV") == "modular":
        return
    values = values or {}
    write_conf(
        log_dir,
        values.get("log_persist", True) is not False,
        values.get("log_max_mb", 10) or 10,
        values.get("log_keep", 5) or 5,
        values.get("log_filters", ""),
    )
    signal_reload(log_dir)


def signal_reload(log_dir):
    """SIGHUP the collector so it rereads collector.conf; quiet on any failure."""
    sighup = getattr(signal, "SIGHUP", None)
    if not log_dir or sighup is None:
        return
    try:
        with open(pid_path(log_dir), encoding="utf-8") as f:
            pid = int(f.read().strip())
        # Never signal a recycled pid: the target must still be a collector.
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"log_collector" not in f.read():
                return
        os.kill(pid, sighup)
    except (OSError, ValueError):
        pass


def read_conf(log_dir):
    conf = dict(_DEFAULT_CONF)
    try:
        with open(conf_path(log_dir), encoding="utf-8") as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep and key in conf:
                    conf[key] = value
    except OSError:
        return conf
    conf["persist"] = str(conf["persist"]).strip() not in ("0", "false", "")
    for key, cap in (("max_mb", 1000), ("keep", 50)):
        try:
            conf[key] = min(max(int(conf[key]), 1), cap)
        except (TypeError, ValueError):
            conf[key] = _DEFAULT_CONF[key]
    return conf


def load_filters(spec):
    """Resolve 'module:callable,module:callable' into line filters, skipping bad ones."""
    filters = []
    for item in str(spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            module_name, _, attr = item.partition(":")
            fn = getattr(importlib.import_module(module_name), attr)
            if callable(fn):
                filters.append(fn)
        except Exception as exc:
            print(
                f"[log_collector] WARNING: cannot load filter {item!r}: {exc}",
                file=sys.stderr,
                flush=True,
            )
    return filters


def _stamp():
    now = time.time()
    local = time.localtime(now)
    base = time.strftime("%Y-%m-%d %H:%M:%S", local) + f",{int(now * 1000) % 1000:03d}"
    offset = time.strftime("%z", local)
    if offset and offset != "+0000":
        return f"{base} {offset}"
    return base


class _WriteFailure(Exception):
    def __init__(self, written, cause):
        super().__init__(cause)
        self.written = written
        self.cause = cause


class Collector:
    def __init__(self, log_dir, out_fd=1):
        self.log_dir = log_dir
        self.out_fd = out_fd
        self.live_path = os.path.join(log_dir, LIVE_NAME)
        self._buf = collections.deque()
        self._buf_bytes = 0
        self._dropped = 0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self._reload = True
        self._force_rotate = False
        self._fd = None
        self._tail_open = False
        self._fs_ready = False
        self._filter_strikes = 0
        self._filters_broken = False
        self.conf = dict(_DEFAULT_CONF)
        self.filters = []

    def install_signals(self):
        # Handlers set plain flags only: threading primitives are not
        # signal-safe, and the writer's 250ms tick bounds the latency.
        signal.signal(signal.SIGHUP, lambda *_: setattr(self, "_reload", True))
        signal.signal(signal.SIGALRM, lambda *_: setattr(self, "_force_rotate", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_stop", True))

    # ── reader thread: stdin -> filter -> forward to stdout -> buffer ──────

    def reader(self, stream):
        while True:
            line = stream.readline(_MAX_LINE_BYTES)
            if not line:
                break
            line = self._filter(line)
            if line is None:
                continue
            self._forward(line)
            if not self.conf["persist"]:
                # Keep forwarding; only the file sink honours the toggle.
                continue
            with self._lock:
                while self._buf_bytes + len(line) > _BUFFER_BYTES and self._buf:
                    old = self._buf.popleft()
                    self._buf_bytes -= len(old)
                    self._dropped += 1
                self._buf.append(line)
                self._buf_bytes += len(line)
                over = self._buf_bytes >= _BATCH_BYTES
            if over:
                self._wake.set()
        self._stop = True
        self._wake.set()

    def _forward(self, line):
        # Same blocking semantics the producers had writing stdout directly.
        try:
            view = memoryview(line)
            while view:
                view = view[os.write(self.out_fd, view) :]
        except OSError:
            pass

    def _filter(self, raw):
        filters = self.filters
        if not filters or self._filters_broken:
            return raw
        started = time.monotonic()
        try:
            text = raw.decode("utf-8", "replace").rstrip("\n")
            for fn in filters:
                text = fn(text)
                if text is None:
                    result = None
                    break
            else:
                result = (text + "\n").encode("utf-8", "replace")
        except Exception:
            # A broken filter must never lose the stream: keep the line.
            result = raw
        # Circuit breaker: filters sit on the docker-logs path now, so a
        # pathological one (catastrophic regex) must latch off, not stall.
        if time.monotonic() - started > _FILTER_BUDGET_SECONDS:
            self._filter_strikes += 1
            if self._filter_strikes >= _FILTER_STRIKES:
                self._filters_broken = True
                print(
                    "[log_collector] WARNING: line filters repeatedly "
                    "exceeded their time budget - filtering disabled.",
                    file=sys.stderr,
                    flush=True,
                )
                self._enqueue(
                    (
                        _stamp()
                        + " WARNING dispatcharr.log_collector line filters "
                        + "disabled after repeated time-budget overruns\n"
                    ).encode()
                )
        return result

    # ── writer thread: batches, markers, rotation ─────────────────────────

    def writer(self):
        while True:
            self._wake.wait(_FLUSH_INTERVAL_SECONDS)
            self._wake.clear()
            if self._reload:
                self._apply_conf()
            try:
                self._drain()
            except OSError:
                time.sleep(1.0)
            if self._stop:
                try:
                    self._drain()
                except OSError:
                    pass
                self._close_fd()
                self._remove_pidfile()
                return

    def _apply_conf(self):
        self._reload = False
        self._setup_fs()
        self.conf = read_conf(self.log_dir)
        self.filters = load_filters(self.conf["filters"])
        self._filter_strikes = 0
        self._filters_broken = False
        self._prune()

    def _setup_fs(self):
        # All filesystem setup is tolerant and retried on every reload, so a
        # dead /data degrades to drain-and-drop instead of a crash loop.
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            with open(pid_path(self.log_dir), "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            if not self._fs_ready:
                self._fs_ready = True
                self._enqueue(f"{_stamp()} INFO dispatcharr.log_collector started\n".encode())
        except OSError:
            pass

    def _remove_pidfile(self):
        try:
            os.remove(pid_path(self.log_dir))
        except OSError:
            pass

    def _enqueue(self, data):
        with self._lock:
            self._buf.append(data)
            self._buf_bytes += len(data)

    def _drain(self):
        while not self._reload:
            with self._lock:
                batch, batch_bytes = [], 0
                while self._buf and batch_bytes < _BATCH_BYTES:
                    item = self._buf.popleft()
                    batch.append(item)
                    batch_bytes += len(item)
                self._buf_bytes -= batch_bytes
                dropped, self._dropped = self._dropped, 0
            # A marker or rotation must not splice into an unterminated line.
            marker_count = 0
            if dropped and not self._tail_open:
                marker = (
                    f"{_stamp()} WARNING dispatcharr.log_collector {dropped} "
                    f"log lines dropped (buffer full - slow disk or log burst)\n"
                ).encode("utf-8", "replace")
                batch.insert(0, marker)
                marker_count = dropped
            elif dropped:
                with self._lock:
                    self._dropped += dropped
            if not batch and not self._force_rotate:
                return
            if batch:
                try:
                    self._write_batch(batch)
                except _WriteFailure as failure:
                    self._requeue(batch, failure.written, marker_count)
                    raise failure.cause
            if not self._tail_open:
                self._maybe_rotate()
            if self._stop:
                return

    def _requeue(self, batch, written, marker_count=0):
        # Requeue only the unwritten tail; a torn item stays whole, so its
        # flushed prefix repeats on retry (accepted trade). An unwritten
        # marker folds back into the counter so it can never be evicted.
        idx = 0
        for item in batch:
            if written < len(item):
                break
            written -= len(item)
            idx += 1
        remainder = batch[idx:]
        with self._lock:
            if marker_count and idx == 0 and remainder:
                remainder = remainder[1:]
                self._dropped += marker_count
            self._buf.extendleft(reversed(remainder))
            self._buf_bytes += sum(len(i) for i in remainder)

    def _write_batch(self, batch):
        data = b"".join(batch)
        written = 0
        try:
            if self._fd is None:
                self._fd = os.open(
                    self.live_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644
                )
            try:
                os.stat(self.live_path)
            except FileNotFoundError:
                self._close_fd()
                self._fd = os.open(
                    self.live_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644
                )
            view = memoryview(data)
            while view:
                n = os.write(self._fd, view)
                view = view[n:]
                written += n
            self._tail_open = not data.endswith(b"\n")
        except OSError as exc:
            prefix = data[:written]
            self._tail_open = bool(prefix) and not prefix.endswith(b"\n")
            raise _WriteFailure(written, exc) from exc

    def _maybe_rotate(self):
        force, self._force_rotate = self._force_rotate, False
        max_bytes = self.conf["max_mb"] * 1024 * 1024
        try:
            size = os.path.getsize(self.live_path)
        except OSError:
            self._force_rotate = force
            return
        if (not force and size <= max_bytes) or size == 0:
            return
        self._close_fd()
        try:
            for n in sorted(self._archive_indices(), reverse=True):
                if n >= self.conf["keep"]:
                    os.remove(f"{self.live_path}.{n}")
                else:
                    os.replace(f"{self.live_path}.{n}", f"{self.live_path}.{n + 1}")
            os.replace(self.live_path, f"{self.live_path}.1")
            # Recreate immediately so the viewer never sees the live file missing.
            os.close(os.open(self.live_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644))
        except OSError:
            return

    def _prune(self):
        # Runs on every conf apply: boot-shift archives and a lowered keep
        # must converge without waiting for a size-cap rotation.
        try:
            for n in self._archive_indices():
                if n > self.conf["keep"]:
                    os.remove(f"{self.live_path}.{n}")
        except OSError:
            pass

    def _archive_indices(self):
        indices = []
        prefix = LIVE_NAME + "."
        try:
            names = os.listdir(self.log_dir)
        except OSError:
            return indices
        for name in names:
            if name.startswith(prefix) and name[len(prefix) :].isdigit():
                indices.append(int(name[len(prefix) :]))
        return indices

    def _close_fd(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def run(self, stream):
        # Signals first, then the reader owns stdin before any filesystem
        # work: a dead /data must never leave the pipe undrained.
        self.install_signals()
        reader = threading.Thread(target=self.reader, args=(stream,), daemon=True)
        reader.start()
        self.writer()


def main(argv):
    if len(argv) != 2:
        print("usage: python -m dispatcharr.log_collector <logdir>", file=sys.stderr)
        return 2
    Collector(argv[1]).run(sys.stdin.buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
