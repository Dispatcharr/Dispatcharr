"""
Simple read-only FUSE client for Dispatcharr VOD.

Usage:
  python fuse_client.py --mode movies --backend-url http://localhost:9191 --mountpoint /mnt/vod_movies
  python fuse_client.py --mode tv --backend-url http://localhost:9191 --mountpoint /mnt/vod_tv

Requires: fusepy (Linux/macOS) or WinFsp with fusepy on Windows.
"""
import argparse
import errno
import hashlib
import logging
import os
import socket
import subprocess
import stat
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Set
from urllib.parse import urljoin

import requests
from fuse import FUSE, FuseOSError, LoggingMixIn, Operations, fuse_get_context

log = logging.getLogger("dispatcharr_fuse")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Use a generous fake size when we cannot learn the real length so players keep requesting data.
DEFAULT_FAKE_SIZE = 5 * 1024 * 1024 * 1024  # 5 GiB
# Keep image sidecars small when size cannot be discovered.
DEFAULT_FAKE_IMAGE_SIZE = 512 * 1024  # 512 KiB
# Keep sessions warm so we don't rebuild upstream sessions between reads.
SESSION_IDLE_TTL = 300  # seconds
# Ignore tiny first reads (Finder/thumbnail probes) to avoid creating upstream sessions.
DEFAULT_PROBE_READ_BYTES = 512 * 1024  # 512 KiB
# Keep synchronous fetch chunks modest; large chunks can cause periodic playback stalls.
DEFAULT_READAHEAD_BYTES = 1 * 1024 * 1024  # 1 MiB
# Plex transcoder reads are latency-sensitive; keep chunks smaller to avoid periodic stalls.
TRANSCODER_READAHEAD_BYTES = 256 * 1024  # 256 KiB
# Keep a larger buffered window for transcoder reads so we avoid frequent micro-range fetches.
TRANSCODER_PREFETCH_BYTES = max(
    TRANSCODER_READAHEAD_BYTES,
    int(os.getenv("TRANSCODER_PREFETCH_BYTES", str(4 * 1024 * 1024))),  # 4 MiB
)
# Cap upstream fetch size for transcoder-driven reads.
TRANSCODER_MAX_FETCH_BYTES = max(
    TRANSCODER_PREFETCH_BYTES,
    int(os.getenv("TRANSCODER_MAX_FETCH_BYTES", str(8 * 1024 * 1024))),  # 8 MiB
)
# Keep more than one buffered window so MKV metadata probes (often near EOF)
# do not evict the active playback chunk.
DEFAULT_BUFFER_CACHE_BYTES = max(
    DEFAULT_READAHEAD_BYTES,
    int(os.getenv("BUFFER_CACHE_BYTES", str(32 * 1024 * 1024))),  # 32 MiB
)
# MKV files are more seek-heavy in Plex direct play/transcode paths; keep a larger local window.
MKV_PREFETCH_BYTES = max(
    DEFAULT_READAHEAD_BYTES,
    int(os.getenv("MKV_PREFETCH_BYTES", str(16 * 1024 * 1024))),  # 16 MiB
)
MKV_MAX_FETCH_BYTES = max(
    MKV_PREFETCH_BYTES,
    int(os.getenv("MKV_MAX_FETCH_BYTES", str(32 * 1024 * 1024))),  # 32 MiB
)
MKV_BUFFER_CACHE_BYTES = max(
    MKV_PREFETCH_BYTES,
    int(os.getenv("MKV_BUFFER_CACHE_BYTES", str(96 * 1024 * 1024))),  # 96 MiB
)
# When sequential playback gets close to the end of a cached segment, proactively
# fetch the next segment so transcoders do not block at hard range boundaries.
PREFETCH_TRIGGER_BYTES = max(
    64 * 1024,
    int(os.getenv("PREFETCH_TRIGGER_BYTES", str(2 * 1024 * 1024))),  # 2 MiB
)
CACHE_HIT_LOGGING = str(os.getenv("FUSE_LOG_CACHE_HITS", "false")).strip().lower() in {
    "1", "true", "yes", "on"
}
ACCESS_EVENT_LOGGING = str(os.getenv("FUSE_LOG_ACCESS_EVENTS", "false")).strip().lower() in {
    "1", "true", "yes", "on"
}
PROBE_READ_LOGGING = str(os.getenv("FUSE_LOG_PROBE_READS", "false")).strip().lower() in {
    "1", "true", "yes", "on"
}
# Smooth buffering mode:
# - keeps an async read-ahead worker running during active playback
# - optionally blocks initial playback briefly to build a startup buffer
SMOOTH_BUFFERING_ENABLED = str(
    os.getenv("SMOOTH_BUFFERING_ENABLED", "true")
).strip().lower() in {"1", "true", "yes", "on"}
INITIAL_PREBUFFER_BYTES = max(
    0,
    int(os.getenv("INITIAL_PREBUFFER_BYTES", str(32 * 1024 * 1024))),  # 32 MiB
)
INITIAL_PREBUFFER_TIMEOUT_SECONDS = max(
    0.0,
    float(os.getenv("INITIAL_PREBUFFER_TIMEOUT_SECONDS", "20")),
)
TARGET_BUFFER_AHEAD_BYTES = max(
    1 * 1024 * 1024,
    int(os.getenv("TARGET_BUFFER_AHEAD_BYTES", str(128 * 1024 * 1024))),  # 128 MiB
)
LOW_WATERMARK_BYTES = max(
    64 * 1024,
    int(os.getenv("LOW_WATERMARK_BYTES", str(16 * 1024 * 1024))),  # 16 MiB
)
MAX_TOTAL_BUFFER_BYTES = max(
    TARGET_BUFFER_AHEAD_BYTES,
    int(os.getenv("MAX_TOTAL_BUFFER_BYTES", str(1024 * 1024 * 1024))),  # 1 GiB
)
PREFETCH_LOOP_SLEEP_SECONDS = max(
    0.02,
    float(os.getenv("PREFETCH_LOOP_SLEEP_SECONDS", "0.12")),
)
SEEK_RESET_THRESHOLD_BYTES = max(
    512 * 1024,
    int(os.getenv("SEEK_RESET_THRESHOLD_BYTES", str(4 * 1024 * 1024))),  # 4 MiB
)
BUFFER_RELEASE_ON_CLOSE = str(
    os.getenv("BUFFER_RELEASE_ON_CLOSE", "true")
).strip().lower() in {"1", "true", "yes", "on"}
# Retry 5xx range failures with smaller windows so a transient/provider-side
# chunk failure does not immediately abort transcoder playback.
RANGE_5XX_RETRIES = max(
    0,
    int(os.getenv("RANGE_5XX_RETRIES", "4")),
)
RANGE_5XX_BACKOFF_SECONDS = max(
    0.0,
    float(os.getenv("RANGE_5XX_BACKOFF_SECONDS", "0.15")),
)
MIN_RANGE_FETCH_BYTES = max(
    4 * 1024,
    int(os.getenv("MIN_RANGE_FETCH_BYTES", str(128 * 1024))),  # 128 KiB
)
# Reduce scanner probe log volume so active scans do not saturate journald/CPU.
PROBE_LOG_INITIAL_HITS = max(
    0,
    int(os.getenv("PROBE_LOG_INITIAL_HITS", "0")),
)
PROBE_LOG_EVERY_N_HITS = max(
    0,
    int(os.getenv("PROBE_LOG_EVERY_N_HITS", "0")),
)
# Process-name cache is short-lived to avoid stale PID reuse and to re-attempt blank lookups.
PROCESS_NAME_CACHE_TTL = 30  # seconds
# Directory browse cache TTL; refresh periodically so newly added VODs show up without remounting.
# Set to 0 to disable directory caching entirely.
DIR_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.getenv("DIR_CACHE_TTL_SECONDS", "15")),
)
# Disabled by default: unknown-process probe simulation can break real playback startup.
# Keep this small so unknown/kernel-triggered probe bursts do not consume provider slots.
UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES = max(
    0,
    int(os.getenv("UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES", str(2 * 1024 * 1024))),  # 2 MiB
)
UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES = max(
    0,
    int(os.getenv("UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES", str(4 * 1024 * 1024))),  # 4 MiB
)
# If Plex scanner hits the same path repeatedly in a short window, treat it as real playback probing.
PLEX_SCANNER_REPEAT_WINDOW_SECONDS = 15
# Keep per-path probe counters long enough to survive rapid open/release loops.
PATH_PROBE_TRACKER_TTL_SECONDS = max(
    float(SESSION_IDLE_TTL),
    float(
        os.getenv(
            "PATH_PROBE_TRACKER_TTL_SECONDS",
            str(PLEX_SCANNER_REPEAT_WINDOW_SECONDS * 4),
        )
    ),
)
# When Plex Media Server has just touched a specific media path, prioritize
# playability by allowing scanner reads for that same path.
PLAYBACK_INTENT_WINDOW_SECONDS = max(
    5.0,
    float(os.getenv("PLAYBACK_INTENT_WINDOW_SECONDS", "20")),
)
# Number of initial Plex scanner-style reads to simulate with zero-bytes before allowing real reads.
# Keep this low so genuine playback can recover quickly if process names are ambiguous.
PLEX_SCANNER_PROBE_READS = max(
    0,
    int(os.getenv("PLEX_SCANNER_PROBE_READS", "1")),
)
# Dedicated scanner workers should stay probe-only by default so indexing does not
# consume upstream profile slots needed for real playback.
PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS = str(
    os.getenv("PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS", "false")
).strip().lower() in {"1", "true", "yes", "on"}
# Keep dedicated Plex scanner workers probe-only regardless of playback intent.
PLEX_DEDICATED_SCANNER_ALWAYS_PROBE = str(
    os.getenv("PLEX_DEDICATED_SCANNER_ALWAYS_PROBE", "true")
).strip().lower() in {"1", "true", "yes", "on"}
# When dedicated scanner reads are blocked, simulate only the first few scanner
# reads and then allow real bytes so Plex can finalize media playability.
PLEX_DEDICATED_SCANNER_PROBE_READS = max(
    0,
    int(os.getenv("PLEX_DEDICATED_SCANNER_PROBE_READS", "8")),
)
# Keep Plex Media Server startup probe simulation disabled by default to avoid
# suppressing genuine direct-play startup reads. Fake-EOF probes remain simulated.
PLEX_MEDIA_SERVER_PROBE_READS = max(
    0,
    int(os.getenv("PLEX_MEDIA_SERVER_PROBE_READS", "0")),
)
# Allow scanner probe simulation for short offsets near the start of the file.
PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES = max(
    0,
    int(os.getenv("PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES", str(4 * 1024 * 1024))),  # 4 MiB
)
# Cap scanner probe simulation by read size. Plex scan reads can be large (for example 32 MiB).
PLEX_SCANNER_PROBE_MAX_READ_BYTES = max(
    DEFAULT_PROBE_READ_BYTES,
    int(os.getenv("PLEX_SCANNER_PROBE_MAX_READ_BYTES", str(64 * 1024 * 1024))),  # 64 MiB
)
# Scanner metadata checks often seek close to the synthetic 5 GiB tail; keep those simulated.
PLEX_FAKE_EOF_PROBE_TAIL_BYTES = max(
    64 * 1024,
    int(os.getenv("PLEX_FAKE_EOF_PROBE_TAIL_BYTES", str(4 * 1024 * 1024))),  # 4 MiB
)
PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES = max(
    4 * 1024,
    int(os.getenv("PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES", str(512 * 1024))),  # 512 KiB
)
FUSE_CLIENT_USER_AGENT = os.getenv(
    "FUSE_CLIENT_USER_AGENT",
    "Dispatcharr-FUSE/1.0",
)
FUSE_CLIENT_BUILD = os.getenv(
    "FUSE_CLIENT_BUILD",
    "2026-02-19-scan-playback-coexist-v3",
)
FUSE_CLIENT_HOSTNAME = os.getenv("FUSE_CLIENT_HOSTNAME", socket.gethostname())
FUSE_HOST_TOKEN = os.getenv("FUSE_HOST_TOKEN", "").strip()


def _sanitize_client_token(value: str, *, fallback: str = "fuse") -> str:
    cleaned = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in ("-", "_", "."))
    cleaned = cleaned.strip("._-")
    if cleaned:
        return cleaned[:128]
    return fallback


def _default_fuse_client_id() -> str:
    configured = _sanitize_client_token(os.getenv("FUSE_CLIENT_ID", ""), fallback="")
    if configured:
        return configured

    hostname = _sanitize_client_token(FUSE_CLIENT_HOSTNAME.lower(), fallback="fuse-host")
    digest = hashlib.sha1(hostname.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{hostname}-{digest}"


FUSE_CLIENT_ID = _default_fuse_client_id()
FUSE_CLIENT_HOSTNAME_SANITIZED = _sanitize_client_token(FUSE_CLIENT_HOSTNAME, fallback="unknown")

BACKGROUND_PROBE_PROCESSES = {
    "mds",
    "mdworker",
    "mdworker_shared",
    "spotlight",
    "quicklookd",
    "qlmanage",
    "photolibraryd",
    "photoanalysisd",
}

# Linux process names are often truncated in /proc/comm, so match short markers.
PLEX_SCANNER_MARKERS = (
    "plex media scan",
    "plex media sca",
    "plex scanner",
    "plex script host",
    "plex script hos",
    "plex script",
    "plex tuner service",
    "plex tuner serv",
    "plex tuner",
    "plex plug-in",
    "plex plug in",
    "plex plugin",
    "plex metadata",
    "plex agent",
)


class UpstreamRangeError(Exception):
    def __init__(self, status_code: int, url: str, byte_range: str, headers: Dict[str, Any]):
        self.status_code = int(status_code)
        self.url = str(url)
        self.byte_range = str(byte_range)
        self.headers = dict(headers or {})
        super().__init__(
            f"upstream_status={self.status_code} url={self.url} range={self.byte_range}"
        )


class FuseAPIClient:
    """HTTP bridge to the backend FUSE API."""

    def __init__(self, backend_url: str, mode: str, mountpoint: str = ""):
        self.base = backend_url.rstrip("/")
        self.mode = mode
        self.session = requests.Session()
        session_headers = {
            "User-Agent": FUSE_CLIENT_USER_AGENT,
            "X-Dispatcharr-Client": "fuse",
            "X-Dispatcharr-Fuse-Client-Id": FUSE_CLIENT_ID,
            "X-Dispatcharr-Fuse-Hostname": FUSE_CLIENT_HOSTNAME_SANITIZED,
            "X-Dispatcharr-Fuse-Build": FUSE_CLIENT_BUILD,
            "X-Dispatcharr-Fuse-Mode": _sanitize_client_token(mode, fallback="unknown"),
        }
        if mountpoint:
            session_headers["X-Dispatcharr-Fuse-Mountpoint"] = str(mountpoint)
        if FUSE_HOST_TOKEN:
            session_headers["X-Dispatcharr-Fuse-Token"] = FUSE_HOST_TOKEN
        self.session.headers.update(session_headers)

    def browse(self, path: str) -> Dict:
        try:
            resp = self.session.get(
                f"{self.base}/api/fuse/browse/{self.mode}/",
                params={"path": path},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            log.error("Browse failed for %s: %s", path, exc)
            raise FuseOSError(errno.ECONNREFUSED) from exc

    def stream_url(self, content_type: str, content_id: str) -> str:
        try:
            resp = self.session.get(
                f"{self.base}/api/fuse/stream/{content_type}/{content_id}/",
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("stream_url")
        except requests.RequestException as exc:
            log.error("Stream URL lookup failed for %s:%s: %s", content_type, content_id, exc)
            raise FuseOSError(errno.ECONNREFUSED) from exc

    def head_stream(self, url: str) -> Dict[str, Optional[int]]:
        """
        Get content length and optional session URL via HEAD.
        """
        next_url = url
        for _ in range(5):
            resp = self.session.head(next_url, allow_redirects=False, timeout=5)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                next_url = urljoin(next_url, resp.headers["Location"])
                continue
            resp.raise_for_status()
            size = resp.headers.get("Content-Length")
            session_url = resp.headers.get("X-Session-URL")
            if session_url:
                session_url = urljoin(next_url, session_url)
            return {
                "size": int(size) if size and str(size).isdigit() else None,
                "session_url": session_url,
            }
        raise FuseOSError(errno.EIO)

    def ranged_get(self, session: requests.Session, url: str, offset: int, size: int):
        headers = {"Range": f"bytes={offset}-{offset + size - 1}"}
        next_url = url
        for _ in range(5):  # follow a few redirects manually to preserve Range
            try:
                resp = session.get(
                    next_url,
                    headers=headers,
                    stream=True,
                    timeout=30,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                log.error(
                    "Upstream range request failed url=%s range=%s err=%s",
                    next_url,
                    headers["Range"],
                    exc,
                )
                raise FuseOSError(errno.EIO) from exc
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                # The proxy returns relative redirects; urljoin keeps the original host/scheme.
                next_url = urljoin(next_url, resp.headers["Location"])
                continue
            if resp.status_code == 416:
                # Gracefully treat unsatisfiable ranges as EOF instead of hard I/O errors.
                total_size = None
                cr = resp.headers.get("Content-Range")
                if cr and "/" in cr:
                    try:
                        total_size = int(cr.split("/")[-1])
                    except Exception:
                        total_size = None
                resp.close()
                log.debug(
                    "Upstream returned 416 (EOF) url=%s range=%s total=%s",
                    next_url,
                    headers["Range"],
                    total_size,
                )
                return b"", next_url, total_size
            if resp.status_code not in (200, 206):
                status = resp.status_code
                resp_headers = dict(resp.headers)
                resp.close()
                log.error(
                    "Unexpected upstream status=%s url=%s range=%s headers=%s",
                    status,
                    next_url,
                    headers["Range"],
                    resp_headers,
                )
                if 500 <= status < 600:
                    raise UpstreamRangeError(
                        status_code=status,
                        url=next_url,
                        byte_range=headers["Range"],
                        headers=resp_headers,
                    )
                raise FuseOSError(errno.EIO)
            total_size = None
            # Parse Content-Range: bytes start-end/total
            cr = resp.headers.get("Content-Range")
            if cr and "/" in cr:
                try:
                    total_size = int(cr.split("/")[-1])
                except Exception:
                    total_size = None

            # Never consume an unbounded response body here. Some upstreams ignore Range and return 200;
            # reading resp.content would then block until the full asset is downloaded.
            remaining = max(1, int(size))
            parts = []
            try:
                for chunk in resp.iter_content(chunk_size=min(remaining, 64 * 1024)):
                    if not chunk:
                        continue
                    if len(chunk) >= remaining:
                        parts.append(chunk[:remaining])
                        remaining = 0
                        break
                    parts.append(chunk)
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
            finally:
                resp.close()

            # Return both content and the final URL we ended up at (sessionized path) and optional total size
            return b"".join(parts), next_url, total_size
        raise FuseOSError(errno.EIO)


class VODFuse(LoggingMixIn, Operations):
    """Read-only filesystem exposing VOD Movies or TV."""

    def __init__(self, api_client: FuseAPIClient, readahead_bytes: int, probe_read_bytes: int):
        self.api = api_client
        self.readahead_bytes = readahead_bytes
        self.probe_read_bytes = probe_read_bytes
        self.fs_started_at = time.time()
        self.cache_lock = threading.RLock()
        # path -> {"data": browse_payload, "cached_at": epoch_seconds, "child_paths": set("/a/b", ...)}
        self.dir_cache: Dict[str, Dict[str, Any]] = {}
        self.path_index: Dict[str, Dict] = {}
        # Stable stat timestamps by path so scanner getattr loops do not see
        # every file as "just modified" on every call.
        self.path_stat_times: Dict[str, float] = {}
        # shared session pool across opens of the same path to avoid repeated upstream sessions
        # path -> {"session", "session_url", "size", "refcount", "last_used"}
        self.session_pool: Dict[str, Dict] = {}
        self.pool_lock = threading.RLock()
        self.open_handles_lock = threading.RLock()
        self.open_handles: Dict[int, Dict[str, Any]] = {}
        self.next_open_handle_id = 1
        self.proc_name_cache: Dict[int, tuple[str, float]] = {}
        self.access_log_once: set = set()
        self.plex_scanner_last_seen = 0.0
        # Per-path probe tracking survives handle/session churn so dedicated scanner
        # probe thresholds can advance across rapid reopen cycles.
        self.path_probe_lock = threading.RLock()
        self.path_probe_counters: Dict[str, Dict[str, Any]] = {}
        self.playback_intent_lock = threading.RLock()
        self.path_playback_intent: Dict[str, float] = {}

    def _read_proc_text(self, pid: int, name: str) -> str:
        try:
            with open(f"/proc/{pid}/{name}", "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read().strip()
        except Exception:
            return ""

    def _read_proc_cmdline(self, pid: int):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                raw = handle.read()
            return [part.decode("utf-8", errors="ignore") for part in raw.split(b"\0") if part]
        except Exception:
            return []

    def _linux_process_name(self, pid: int) -> str:
        status_text = self._read_proc_text(pid, "status")
        status_name = ""
        tgid = pid
        if status_text:
            for line in status_text.splitlines():
                if line.startswith("Name:"):
                    status_name = line.split(":", 1)[1].strip()
                elif line.startswith("Tgid:"):
                    try:
                        tgid = int(line.split(":", 1)[1].strip())
                    except Exception:
                        tgid = pid

        thread_comm = self._read_proc_text(pid, "comm")
        process_comm = self._read_proc_text(tgid, "comm") if tgid != pid else thread_comm

        cmdline = self._read_proc_cmdline(pid)
        if not cmdline and tgid != pid:
            cmdline = self._read_proc_cmdline(tgid)
        cmd_name = os.path.basename(cmdline[0]).strip() if cmdline else ""

        for candidate in (cmd_name, process_comm, thread_comm, status_name):
            if candidate:
                return candidate
        return ""

    def _process_name(self, pid: int) -> str:
        now = time.time()
        cached = self.proc_name_cache.get(pid)
        if cached and (now - cached[1]) < PROCESS_NAME_CACHE_TTL:
            return cached[0]

        name = ""
        if sys.platform.startswith("linux"):
            name = self._linux_process_name(pid)
        if not name:
            try:
                import psutil  # type: ignore

                name = psutil.Process(pid).name()
            except Exception:
                try:
                    out = subprocess.check_output(["ps", "-p", str(pid), "-o", "comm="], text=True)
                    name = out.strip()
                except Exception:
                    name = ""

        if name:
            self.proc_name_cache[pid] = (name, now)
        else:
            self.proc_name_cache.pop(pid, None)
        return name

    def _current_process_name(self) -> str:
        try:
            uid, gid, pid = fuse_get_context()
        except Exception:
            return ""
        if not pid or pid < 2:
            return ""
        return self._process_name(pid)

    def _is_background_process_name(self, process_name: str) -> bool:
        return process_name.lower() in BACKGROUND_PROBE_PROCESSES

    def _normalize_process_name(self, process_name: str) -> str:
        return " ".join((process_name or "").lower().replace("_", " ").split())

    def _is_plex_scanner_process_name(self, process_name: str) -> bool:
        normalized = self._normalize_process_name(process_name)
        if any(marker in normalized for marker in PLEX_SCANNER_MARKERS):
            return True
        return "plex" in normalized and ("scan" in normalized or "scanner" in normalized)

    def _is_plex_dedicated_scanner_process_name(self, process_name: str) -> bool:
        normalized = self._normalize_process_name(process_name)
        # Dedicated scanner/metadata workers should never consume provider slots.
        return "plex" in normalized and any(
            marker in normalized
            for marker in (
                "scan",
                "scanner",
                "script",
                "plugin",
                "plug-in",
                "metadata",
                "agent",
                "tuner",
            )
        )

    def _is_plex_transcoder_process_name(self, process_name: str) -> bool:
        normalized = self._normalize_process_name(process_name)
        return "plex" in normalized and ("transcoder" in normalized or "transcode" in normalized)

    def _is_plex_media_server_process_name(self, process_name: str) -> bool:
        normalized = self._normalize_process_name(process_name)
        if normalized in {"plex media server", "plex media serv", "plexmediaserver"}:
            return True
        return "plex media server" in normalized

    def _log_access(self, event: str, path: str, detail: str = ""):
        if not ACCESS_EVENT_LOGGING:
            return
        try:
            uid, gid, pid = fuse_get_context()
        except Exception:
            uid = gid = pid = -1
        name = self._current_process_name()
        key = (event, path, pid)
        if key in self.access_log_once:
            return
        self.access_log_once.add(key)
        log.info("FUSE %s pid=%s proc=%s uid=%s path=%s %s", event, pid, name, uid, path, detail)

    def _is_background_process(self) -> bool:
        """
        Detect Spotlight/QuickLook/mdworker probes so we can serve zeros without opening upstream.
        """
        return self._is_background_process_name(self._current_process_name())

    def _is_image_entry(self, entry: Dict) -> bool:
        content_type = str(entry.get("content_type") or "").lower()
        extension = str(entry.get("extension") or "").lower().lstrip(".")
        file_name = str(entry.get("name") or "").lower()

        if content_type == "image":
            return True
        if extension in {"jpg", "jpeg", "png", "webp", "gif", "tbn"}:
            return True
        return file_name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".tbn"))

    def _default_fake_size_for_entry(self, entry: Dict) -> int:
        if self._is_image_entry(entry):
            return DEFAULT_FAKE_IMAGE_SIZE
        return DEFAULT_FAKE_SIZE

    def _coerce_timestamp(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
        else:
            text = str(value).strip()
            if not text:
                return None
            try:
                ts = float(text)
            except Exception:
                try:
                    # Backend/API timestamps are typically ISO-8601.
                    ts = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
                except Exception:
                    return None

        # Convert millisecond epoch when needed.
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        if ts <= 0:
            return None
        return ts

    def _entry_timestamp(self, entry: Any) -> Optional[float]:
        if not isinstance(entry, dict):
            return None
        for key in (
            "mtime",
            "modified",
            "modified_at",
            "updated_at",
            "created_at",
            "ctime",
            "timestamp",
            "date_added",
        ):
            if key not in entry:
                continue
            ts = self._coerce_timestamp(entry.get(key))
            if ts is not None:
                return ts
        return None

    def _stable_stat_time(self, path: str, entry: Any) -> float:
        now = time.time()
        with self.cache_lock:
            cached = self.path_stat_times.get(path)
            if cached is not None:
                return cached

            ts = self._entry_timestamp(entry)
            if ts is None:
                ts = self.fs_started_at if path == "/" else now
            self.path_stat_times[path] = ts
            return ts

    def _prune_path_probe_counters_locked(self, now: float):
        for stale_path, tracker in list(self.path_probe_counters.items()):
            last_seen = float(tracker.get("last_seen", 0.0) or 0.0)
            if (now - last_seen) > PATH_PROBE_TRACKER_TTL_SECONDS:
                self.path_probe_counters.pop(stale_path, None)

    def _get_or_create_path_probe_counter_locked(self, path: str, now: float) -> Dict[str, Any]:
        tracker = self.path_probe_counters.get(path)
        if tracker is None:
            tracker = {
                "scanner_window_start": 0.0,
                "scanner_hits": 0,
                "media_server_window_start": 0.0,
                "media_server_hits": 0,
                "last_seen": now,
            }
            self.path_probe_counters[path] = tracker
        tracker["last_seen"] = now
        return tracker

    def _bump_path_probe_hits(self, path: str, process_group: str, now: float) -> int:
        if process_group not in {"scanner", "media_server"}:
            return 0
        with self.path_probe_lock:
            self._prune_path_probe_counters_locked(now)
            tracker = self._get_or_create_path_probe_counter_locked(path, now)
            window_key = f"{process_group}_window_start"
            hits_key = f"{process_group}_hits"
            window_start = float(tracker.get(window_key, 0.0) or 0.0)
            if (now - window_start) > PLEX_SCANNER_REPEAT_WINDOW_SECONDS:
                tracker[window_key] = now
                tracker[hits_key] = 0
            tracker[hits_key] = int(tracker.get(hits_key, 0) or 0) + 1
            return int(tracker[hits_key])

    def _get_path_probe_hits(self, path: str, process_group: str, now: float) -> int:
        if process_group not in {"scanner", "media_server"}:
            return 0
        with self.path_probe_lock:
            self._prune_path_probe_counters_locked(now)
            tracker = self._get_or_create_path_probe_counter_locked(path, now)
            return int(tracker.get(f"{process_group}_hits", 0) or 0)

    def _prune_playback_intent_locked(self, now: float):
        for stale_path, seen_at in list(self.path_playback_intent.items()):
            if (now - float(seen_at or 0.0)) > PLAYBACK_INTENT_WINDOW_SECONDS:
                self.path_playback_intent.pop(stale_path, None)

    def _mark_playback_intent(self, path: str):
        if not path or path == "/":
            return
        now = time.time()
        with self.playback_intent_lock:
            self._prune_playback_intent_locked(now)
            self.path_playback_intent[path] = now

    def _has_recent_playback_intent(self, path: str, now: float) -> bool:
        if not path or path == "/":
            return False
        with self.playback_intent_lock:
            self._prune_playback_intent_locked(now)
            seen_at = self.path_playback_intent.get(path)
            if seen_at is None:
                return False
            return (now - float(seen_at or 0.0)) <= PLAYBACK_INTENT_WINDOW_SECONDS

    def _clear_handle_buffers(self, handle: Dict):
        lock = handle.get("lock")
        if lock is None:
            handle["buffers"] = []
            handle["buffered_bytes"] = 0
            return
        with lock:
            handle["buffers"] = []
            handle["buffered_bytes"] = 0
            handle["last_prefetch_offset"] = None
            handle["last_prefetch_time"] = 0.0

    def _stop_prefetch_worker(self, handle: Dict, wait: bool = True):
        stop_event = handle.get("prefetch_stop")
        worker = handle.get("prefetch_thread")
        if stop_event is not None:
            stop_event.set()
        if wait and worker is not None and worker.is_alive():
            worker.join(timeout=1.5)
        handle["prefetch_thread"] = None
        handle["prefetch_running"] = False

    def _contiguous_cached_end(self, handle: Dict, start_offset: int) -> int:
        lock = handle.get("lock")
        if lock is None:
            return start_offset
        with lock:
            buffers = list(handle.get("buffers") or [])
        if not buffers:
            return start_offset

        cursor = max(0, int(start_offset))
        for segment in sorted(buffers, key=lambda item: item["offset"]):
            seg_offset = int(segment["offset"])
            seg_end = seg_offset + len(segment["data"])
            if seg_end <= cursor:
                continue
            if seg_offset > cursor:
                break
            cursor = max(cursor, seg_end)
        return cursor

    def _buffered_ahead(self, handle: Dict, offset: int) -> int:
        return max(0, self._contiguous_cached_end(handle, offset) - max(0, int(offset)))

    def _trim_global_buffers(self):
        if MAX_TOTAL_BUFFER_BYTES <= 0:
            return

        with self.pool_lock:
            while True:
                total_buffered = sum(
                    max(0, int(state.get("buffered_bytes", 0) or 0))
                    for state in self.session_pool.values()
                )
                if total_buffered <= MAX_TOTAL_BUFFER_BYTES:
                    return

                candidate_path = None
                candidate_state = None
                candidate_sort_key = None
                for path, state in self.session_pool.items():
                    buffered_bytes = max(0, int(state.get("buffered_bytes", 0) or 0))
                    if buffered_bytes <= 0:
                        continue
                    # Prefer trimming idle sessions first; then oldest active.
                    sort_key = (
                        0 if int(state.get("refcount", 0) or 0) <= 0 else 1,
                        float(state.get("last_used", 0.0) or 0.0),
                    )
                    if candidate_sort_key is None or sort_key < candidate_sort_key:
                        candidate_sort_key = sort_key
                        candidate_path = path
                        candidate_state = state

                if candidate_state is None or candidate_path is None:
                    return

                lock = candidate_state.get("lock")
                if lock is None:
                    return

                with lock:
                    buffers = candidate_state.get("buffers") or []
                    if not buffers:
                        candidate_state["buffered_bytes"] = 0
                        continue
                    oldest = buffers.pop(0)
                    candidate_state["buffered_bytes"] = max(
                        0,
                        int(candidate_state.get("buffered_bytes", 0) or 0) - len(oldest["data"]),
                    )

    def _prefetch_worker_loop(self, path: str, entry: Dict, handle: Dict):
        stop_event = handle.get("prefetch_stop")
        if stop_event is None:
            return

        while not stop_event.is_set():
            lock = handle.get("lock")
            if lock is None:
                break

            with lock:
                active = bool(handle.get("activated"))
                enabled = bool(handle.get("prefetch_enabled"))
                cursor = int(handle.get("playback_cursor", 0) or 0)
                effective_readahead = max(1, int(handle.get("effective_readahead", self.readahead_bytes) or 1))
                cache_budget = max(
                    effective_readahead,
                    int(handle.get("cache_budget", DEFAULT_BUFFER_CACHE_BYTES) or effective_readahead),
                )
                max_fetch_cap = int(handle.get("max_fetch_cap", 0) or 0)
                total_size = int(handle.get("size", 0) or 0)
                target_ahead = max(
                    effective_readahead,
                    int(handle.get("target_buffer_ahead", TARGET_BUFFER_AHEAD_BYTES) or effective_readahead),
                )
                low_watermark = max(
                    64 * 1024,
                    int(handle.get("low_watermark", LOW_WATERMARK_BYTES) or (64 * 1024)),
                )

            if not active or not enabled:
                stop_event.wait(PREFETCH_LOOP_SLEEP_SECONDS)
                continue

            contiguous_end = self._contiguous_cached_end(handle, cursor)
            buffered_ahead = max(0, contiguous_end - cursor)
            if buffered_ahead >= target_ahead:
                stop_event.wait(PREFETCH_LOOP_SLEEP_SECONDS)
                continue
            if buffered_ahead > low_watermark and buffered_ahead >= (target_ahead // 2):
                stop_event.wait(PREFETCH_LOOP_SLEEP_SECONDS)
                continue
            if total_size > 0 and contiguous_end >= total_size:
                stop_event.wait(PREFETCH_LOOP_SLEEP_SECONDS)
                continue

            fetch_offset = max(0, contiguous_end)
            fetch_size = max(effective_readahead, target_ahead - buffered_ahead)
            if max_fetch_cap > 0:
                fetch_size = min(fetch_size, max_fetch_cap)
            if total_size > 0:
                remaining = int(total_size) - int(fetch_offset)
                if remaining <= 0:
                    stop_event.wait(PREFETCH_LOOP_SLEEP_SECONDS)
                    continue
                fetch_size = min(fetch_size, remaining)
            fetch_size = int(fetch_size)
            if fetch_size <= 0:
                stop_event.wait(PREFETCH_LOOP_SLEEP_SECONDS)
                continue

            try:
                self._fetch_and_cache_range(
                    handle=handle,
                    entry=entry,
                    fetch_offset=fetch_offset,
                    fetch_size=fetch_size,
                    max_cache_bytes=cache_budget,
                )
            except Exception as exc:
                log.debug(
                    "FUSE background prefetch failed path=%s offset=%s size=%s err=%s",
                    path,
                    fetch_offset,
                    fetch_size,
                    exc,
                )
                stop_event.wait(0.35)
                continue

            stop_event.wait(0.01)

    def _start_prefetch_worker(self, path: str, entry: Dict, handle: Dict):
        if not SMOOTH_BUFFERING_ENABLED:
            return

        lock = handle.get("lock")
        if lock is None:
            return

        with lock:
            if not handle.get("prefetch_enabled"):
                return
            worker = handle.get("prefetch_thread")
            if worker is not None and worker.is_alive():
                return
            stop_event = handle.get("prefetch_stop")
            if stop_event is None:
                stop_event = threading.Event()
                handle["prefetch_stop"] = stop_event
            stop_event.clear()
            worker = threading.Thread(
                target=self._prefetch_worker_loop,
                args=(path, entry, handle),
                name=f"dispatcharr-prefetch-{abs(hash(path)) % 100000}",
                daemon=True,
            )
            handle["prefetch_thread"] = worker
            handle["prefetch_running"] = True
            worker.start()

    def _ensure_initial_prebuffer(
        self,
        *,
        path: str,
        entry: Dict,
        handle: Dict,
        current_offset: int,
    ):
        if not SMOOTH_BUFFERING_ENABLED or INITIAL_PREBUFFER_BYTES <= 0:
            return

        lock = handle.get("lock")
        if lock is None:
            return

        with lock:
            if handle.get("initial_prebuffer_done"):
                return
            if handle.get("initial_prebuffer_started"):
                return
            handle["initial_prebuffer_started"] = True
            effective_readahead = max(1, int(handle.get("effective_readahead", self.readahead_bytes) or 1))
            cache_budget = max(
                effective_readahead,
                int(handle.get("cache_budget", DEFAULT_BUFFER_CACHE_BYTES) or effective_readahead),
            )
            max_fetch_cap = int(handle.get("max_fetch_cap", 0) or 0)

        target = min(
            max(INITIAL_PREBUFFER_BYTES, effective_readahead),
            max(cache_budget, effective_readahead),
        )
        deadline = time.time() + INITIAL_PREBUFFER_TIMEOUT_SECONDS
        start_offset = max(0, int(current_offset))

        while time.time() < deadline:
            buffered = self._buffered_ahead(handle, start_offset)
            if buffered >= target:
                break

            contiguous_end = self._contiguous_cached_end(handle, start_offset)
            fetch_offset = max(0, contiguous_end)
            fetch_size = max(effective_readahead, target - buffered)
            if max_fetch_cap > 0:
                fetch_size = min(fetch_size, max_fetch_cap)

            total_size = int(handle.get("size", 0) or 0)
            if total_size > 0:
                remaining = int(total_size) - int(fetch_offset)
                if remaining <= 0:
                    break
                fetch_size = min(fetch_size, remaining)
            fetch_size = int(fetch_size)
            if fetch_size <= 0:
                break

            try:
                self._fetch_and_cache_range(
                    handle=handle,
                    entry=entry,
                    fetch_offset=fetch_offset,
                    fetch_size=fetch_size,
                    max_cache_bytes=cache_budget,
                )
            except Exception as exc:
                log.debug(
                    "FUSE initial prebuffer failed path=%s offset=%s size=%s err=%s",
                    path,
                    fetch_offset,
                    fetch_size,
                    exc,
                )
                break

        buffered = self._buffered_ahead(handle, start_offset)
        with lock:
            handle["initial_prebuffer_done"] = buffered >= max(effective_readahead, target // 2)
            handle["initial_prebuffer_started"] = False
        log.info(
            "FUSE initial prebuffer path=%s start_offset=%s buffered=%s target=%s done=%s",
            path,
            start_offset,
            buffered,
            target,
            bool(handle.get("initial_prebuffer_done")),
        )

    # Helpers
    def _cache_is_fresh(self, record: Optional[Dict[str, Any]], now: Optional[float] = None) -> bool:
        if not record:
            return False
        if DIR_CACHE_TTL_SECONDS <= 0:
            return False
        if now is None:
            now = time.time()
        cached_at = float(record.get("cached_at", 0.0) or 0.0)
        return (now - cached_at) < DIR_CACHE_TTL_SECONDS

    def _parent_path(self, path: str) -> str:
        parent = "/" + "/".join([p for p in path.strip("/").split("/")[:-1]])
        if parent == "":
            parent = "/"
        return parent

    def _update_dir_cache(self, path: str, data: Dict):
        entries = data.get("entries", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            entries = []
        child_paths: Set[str] = {
            str(entry.get("path"))
            for entry in entries
            if isinstance(entry, dict) and entry.get("path")
        }

        old_record = self.dir_cache.get(path)
        old_children = old_record.get("child_paths", set()) if old_record else set()
        if not isinstance(old_children, set):
            old_children = set(old_children)

        # Remove stale child entries from the fast path index.
        for stale_path in (old_children - child_paths):
            self.path_index.pop(stale_path, None)
            self.path_stat_times.pop(stale_path, None)

        # Index current children.
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_path = entry.get("path")
            if entry_path:
                self.path_index[str(entry_path)] = entry

        self.dir_cache[path] = {
            "data": data if isinstance(data, dict) else {"entries": []},
            "cached_at": time.time(),
            "child_paths": child_paths,
        }
        # Keep directory stat timestamps stable for scanner compatibility.
        self.path_stat_times.setdefault(path, self.fs_started_at if path == "/" else time.time())

    def _get_entries(self, path: str, force_refresh: bool = False):
        stale_data = None
        now = time.time()
        with self.cache_lock:
            cached = self.dir_cache.get(path)
            if not force_refresh and self._cache_is_fresh(cached, now):
                return cached["data"]
            if cached:
                stale_data = cached.get("data")

        try:
            data = self.api.browse(path)
        except Exception as exc:
            # If the backend is briefly unavailable, keep serving stale browse data.
            if stale_data is not None:
                log.debug("FUSE browse refresh failed for %s; using stale cache (%s)", path, exc)
                return stale_data
            raise

        with self.cache_lock:
            self._update_dir_cache(path, data)
            return self.dir_cache[path]["data"]

    def _find_entry(self, path: str, *, allow_stale_parent: bool = False) -> Optional[Dict]:
        if path == "/":
            return {"is_dir": True}
        parent = self._parent_path(path)
        now = time.time()
        with self.cache_lock:
            cached_entry = self.path_index.get(path)
            parent_cache = self.dir_cache.get(parent)
            if cached_entry is not None and self._cache_is_fresh(parent_cache, now):
                return cached_entry
            if allow_stale_parent and cached_entry is not None:
                return cached_entry

        # Entry missing or parent listing stale: refresh parent so adds/removes are noticed.
        self._get_entries(parent, force_refresh=True)
        with self.cache_lock:
            return self.path_index.get(path)

    def _ensure_file_metadata(self, entry: Dict, *, allow_head: bool):
        """
        Populate size/stream_url if missing so players can stream.
        allow_head=False keeps getattr fast (fallbacks to fake size).
        """
        if entry.get("is_dir"):
            return

        # Ensure we have a base stream URL
        if not entry.get("stream_url") and entry.get("uuid"):
            entry["stream_url"] = self.api.stream_url(entry["content_type"], entry["uuid"])

        # If size already reasonable, skip
        if entry.get("size") and entry["size"] > 1 and entry.get("stream_url"):
            return

        url = entry.get("stream_url")
        if not url:
            return

        # If we're not allowed to HEAD (e.g., getattr from Finder), just set a fake size.
        if not allow_head:
            if not entry.get("size") or entry.get("size") <= 1:
                entry["size"] = self._default_fake_size_for_entry(entry)
            return

        # Try to learn the true size (and session URL) via HEAD when the client is actually reading.
        if not entry.get("size") or entry["size"] <= 1 or not entry.get("session_url"):
            try:
                info = self.api.head_stream(url)
                if info.get("size"):
                    entry["size"] = info["size"]
                if info.get("session_url"):
                    entry["session_url"] = info["session_url"]
            except Exception as exc:  # pragma: no cover
                log.warning("HEAD failed for %s: %s", url, exc)

        if not entry.get("size") or entry["size"] <= 1:
            entry["size"] = self._default_fake_size_for_entry(entry)

    def _ensure_handle_upstream_session(self, handle: Dict, entry: Dict):
        session = handle.get("session")
        if session is None:
            session = requests.Session()
            session.headers.update(self.api.session.headers)
            handle["session"] = session

        stream_url = handle.get("stream_url") or entry.get("stream_url")
        if (not stream_url) and entry.get("uuid"):
            stream_url = self.api.stream_url(entry["content_type"], entry["uuid"])
            entry["stream_url"] = stream_url
        if not stream_url:
            raise FuseOSError(errno.EIO)
        handle["stream_url"] = stream_url
        if (not handle.get("session_url")) and entry.get("session_url"):
            handle["session_url"] = entry.get("session_url")

    def _refresh_handle_session_url(self, handle: Dict, entry: Dict):
        try:
            self._ensure_handle_upstream_session(handle, entry)
        except Exception:
            return

        stream_url = handle.get("stream_url")
        if not stream_url:
            return

        try:
            info = self.api.head_stream(stream_url)
        except Exception as exc:
            log.debug("Session refresh HEAD failed url=%s err=%s", stream_url, exc)
            return

        refreshed_session_url = info.get("session_url")
        if refreshed_session_url:
            handle["session_url"] = refreshed_session_url
            entry["session_url"] = refreshed_session_url

        refreshed_size = info.get("size")
        if refreshed_size and int(refreshed_size) > 0:
            handle["size"] = int(refreshed_size)
            entry["size"] = int(refreshed_size)

    def _get_handle(self, path: str, entry: Dict, *, acquire_ref: bool = True):
        """
        Ensure we have per-path session state. Upstream session/url initialization
        is deferred until a real non-probe read needs it.
        """
        now = time.time()
        with self.pool_lock:
            # Evict stale idle sessions
            for stale_path, state in list(self.session_pool.items()):
                if state.get("refcount", 0) <= 0 and (now - state.get("last_used", now)) > SESSION_IDLE_TTL:
                    self._stop_prefetch_worker(state, wait=False)
                    self._clear_handle_buffers(state)
                    sess = state.get("session")
                    if sess:
                        try:
                            sess.close()
                        except Exception:
                            pass
                    self.session_pool.pop(stale_path, None)

            if path in self.session_pool:
                state = self.session_pool[path]
                if acquire_ref:
                    state["refcount"] = state.get("refcount", 0) + 1
                state["last_used"] = now
                return state

            state = {
                "session": None,
                "stream_url": entry.get("stream_url"),
                "session_url": entry.get("session_url"),
                "size": entry.get("size") or self._default_fake_size_for_entry(entry),
                "refcount": 1 if acquire_ref else 0,
                "last_used": now,
                "activated": False,   # becomes True after we decide to hit upstream
                "served_fake": False, # we served a fake stub read already
                "unknown_probe_reads": 0,
                "plex_scanner_window_start": 0.0,
                "plex_scanner_hits": 0,
                "plex_media_server_window_start": 0.0,
                "plex_media_server_hits": 0,
                "buffers": [],  # list[{"offset": int, "data": bytes}]
                "buffered_bytes": 0,
                "lock": threading.RLock(),
                "fetch_lock": threading.Lock(),
                "prefetch_stop": threading.Event(),
                "prefetch_thread": None,
                "prefetch_running": False,
                "prefetch_enabled": False,
                "initial_prebuffer_started": False,
                "initial_prebuffer_done": False,
                "playback_cursor": 0,
                "last_read_offset": None,
                "last_read_end": 0,
                "effective_readahead": self.readahead_bytes,
                "max_fetch_cap": 0,
                "cache_budget": DEFAULT_BUFFER_CACHE_BYTES,
                "target_buffer_ahead": TARGET_BUFFER_AHEAD_BYTES,
                "low_watermark": LOW_WATERMARK_BYTES,
            }
            self.session_pool[path] = state
            return state

    def _get_cached_slice(self, handle: Dict, offset: int, size: int):
        lock = handle.get("lock")
        if lock is None:
            return None
        with lock:
            buffers = handle.get("buffers") or []
            # Check newest first; recently accessed ranges are most likely to hit.
            for segment in reversed(buffers):
                seg_offset = segment["offset"]
                seg_data = segment["data"]
                seg_end = seg_offset + len(seg_data)
                if offset >= seg_offset and (offset + size) <= seg_end:
                    start = offset - seg_offset
                    end = start + size
                    return seg_data[start:end]
        return None

    def _get_cached_segment(self, handle: Dict, offset: int, size: int):
        """
        Return (slice, segment_offset, segment_end) when a full cached hit exists.
        """
        lock = handle.get("lock")
        if lock is None:
            return None
        with lock:
            buffers = handle.get("buffers") or []
            for segment in reversed(buffers):
                seg_offset = segment["offset"]
                seg_data = segment["data"]
                seg_end = seg_offset + len(seg_data)
                if offset >= seg_offset and (offset + size) <= seg_end:
                    start = offset - seg_offset
                    end = start + size
                    return seg_data[start:end], seg_offset, seg_end
        return None

    def _store_buffer_segment(self, handle: Dict, offset: int, data: bytes, max_cache_bytes: int):
        if not data:
            return

        lock = handle.get("lock")
        if lock is None:
            return

        with lock:
            buffers = handle.setdefault("buffers", [])
            buffered_bytes = int(handle.get("buffered_bytes", 0) or 0)

            # Drop identical segments before appending fresh data.
            new_len = len(data)
            deduped = []
            for segment in buffers:
                if segment["offset"] == offset and len(segment["data"]) == new_len:
                    buffered_bytes -= len(segment["data"])
                    continue
                deduped.append(segment)
            buffers[:] = deduped

            buffers.append({"offset": offset, "data": data})
            buffered_bytes += new_len

            # Evict oldest segments until under budget.
            while len(buffers) > 1 and buffered_bytes > max_cache_bytes:
                oldest = buffers.pop(0)
                buffered_bytes -= len(oldest["data"])

            handle["buffered_bytes"] = max(0, buffered_bytes)

        self._trim_global_buffers()

    def _fetch_and_cache_range(
        self,
        handle: Dict,
        entry: Dict,
        fetch_offset: int,
        fetch_size: int,
        max_cache_bytes: int,
        min_fetch_size: int = 0,
    ):
        """
        Fetch a range from upstream and store it in the segment cache.
        """
        fetch_size = int(fetch_size)
        if fetch_size <= 0:
            return b""

        cached = self._get_cached_slice(handle, fetch_offset, fetch_size)
        if cached is not None:
            return cached

        fetch_lock = handle.get("fetch_lock")
        if fetch_lock is None:
            raise FuseOSError(errno.EIO)

        with fetch_lock:
            # Another thread may have already fetched this range while we waited.
            cached = self._get_cached_slice(handle, fetch_offset, fetch_size)
            if cached is not None:
                return cached

            min_fetch = max(1, int(min_fetch_size or 0))
            min_fetch = max(min_fetch, MIN_RANGE_FETCH_BYTES)
            min_fetch = min(fetch_size, min_fetch)
            attempt_size = int(fetch_size)
            retries_remaining = int(RANGE_5XX_RETRIES)
            refreshed_session = False

            while True:
                self._ensure_handle_upstream_session(handle, entry)
                stream_url = (
                    handle.get("session_url")
                    or entry.get("session_url")
                    or handle.get("stream_url")
                    or entry.get("stream_url")
                )
                if not stream_url:
                    raise FuseOSError(errno.EIO)
                session = handle.get("session")
                if session is None:
                    raise FuseOSError(errno.EIO)

                try:
                    content, final_url, total_size = self.api.ranged_get(
                        session, stream_url, fetch_offset, attempt_size
                    )
                    handle["session_url"] = final_url
                    if total_size:
                        handle["size"] = total_size
                        entry["size"] = total_size
                    self._store_buffer_segment(handle, fetch_offset, content, max_cache_bytes)
                    return content
                except UpstreamRangeError as exc:
                    if retries_remaining <= 0 or exc.status_code < 500:
                        raise FuseOSError(errno.EIO) from exc

                    if not refreshed_session:
                        self._refresh_handle_session_url(handle, entry)
                        refreshed_session = True

                    next_attempt_size = max(min_fetch, attempt_size // 2)
                    if next_attempt_size >= attempt_size:
                        raise FuseOSError(errno.EIO) from exc

                    retries_remaining -= 1
                    log.warning(
                        (
                            "Upstream 5xx range failure path=%s offset=%s "
                            "attempt_size=%s next_attempt_size=%s retries_left=%s"
                        ),
                        entry.get("path"),
                        fetch_offset,
                        attempt_size,
                        next_attempt_size,
                        retries_remaining,
                    )
                    attempt_size = int(next_attempt_size)
                    if RANGE_5XX_BACKOFF_SECONDS > 0:
                        time.sleep(RANGE_5XX_BACKOFF_SECONDS)

    def _maybe_prefetch_next_range(
        self,
        handle: Dict,
        entry: Dict,
        current_segment_end: int,
        effective_readahead: int,
        max_cache_bytes: int,
        path: str,
    ):
        total_size = handle.get("size")
        if total_size and total_size > 0 and current_segment_end >= total_size:
            return

        next_offset = current_segment_end
        if self._get_cached_slice(handle, next_offset, 1) is not None:
            return

        now = time.time()
        if (
            handle.get("last_prefetch_offset") == next_offset
            and (now - float(handle.get("last_prefetch_time", 0) or 0)) < 3.0
        ):
            return

        prefetch_size = max(1, int(effective_readahead))
        if total_size and total_size > 0:
            prefetch_size = min(prefetch_size, max(0, total_size - next_offset))
        if prefetch_size <= 0:
            return

        handle["last_prefetch_offset"] = next_offset
        handle["last_prefetch_time"] = now
        try:
            self._fetch_and_cache_range(
                handle,
                entry,
                next_offset,
                prefetch_size,
                max_cache_bytes,
            )
            log.debug(
                "FUSE prefetch succeeded path=%s offset=%s size=%s",
                path,
                next_offset,
                prefetch_size,
            )
        except Exception as exc:
            log.debug(
                "FUSE prefetch failed path=%s offset=%s size=%s err=%s",
                path,
                next_offset,
                prefetch_size,
                exc,
            )

    # FUSE operations
    def getattr(self, path, fh=None):
        self._log_access("getattr", path)
        process_name = self._current_process_name()
        allow_stale_lookup = self._is_plex_scanner_process_name(
            process_name
        ) or self._is_background_process_name(process_name)
        entry = self._find_entry(path, allow_stale_parent=allow_stale_lookup)
        if not entry:
            raise FuseOSError(errno.ENOENT)

        # getattr is called frequently by Finder; avoid network HEAD here.
        self._ensure_file_metadata(entry, allow_head=False)

        stat_time = self._stable_stat_time(path, entry)
        if entry.get("is_dir"):
            return dict(
                st_mode=(stat.S_IFDIR | 0o755),
                st_nlink=2,
                st_ctime=stat_time,
                st_mtime=stat_time,
                st_atime=stat_time,
            )

        size = entry.get("size") or 0
        return dict(
            st_mode=(stat.S_IFREG | 0o444),
            st_nlink=1,
            st_size=size,
            st_ctime=stat_time,
            st_mtime=stat_time,
            st_atime=stat_time,
        )

    def readdir(self, path, fh):
        self._log_access("readdir", path)
        data = self._get_entries(path)
        entries = [".", ".."] + [e["name"] for e in data.get("entries", [])]
        for entry in entries:
            yield entry

    def open(self, path, flags):
        self._log_access("open", path, detail=f"flags={flags}")
        process_name = self._current_process_name()
        allow_stale_lookup = self._is_plex_scanner_process_name(
            process_name
        ) or self._is_background_process_name(process_name)
        entry = self._find_entry(path, allow_stale_parent=allow_stale_lookup)
        if not entry or entry.get("is_dir"):
            raise FuseOSError(errno.EISDIR if entry else errno.ENOENT)
        if (
            self._is_plex_media_server_process_name(process_name)
            and (not self._is_image_entry(entry))
        ):
            now = time.time()
            scanner_recently_active = (
                (now - float(self.plex_scanner_last_seen or 0.0))
                <= PLEX_SCANNER_REPEAT_WINDOW_SECONDS
            )
            if not scanner_recently_active:
                self._mark_playback_intent(path)
        state = self._get_handle(path, entry, acquire_ref=True)
        with self.open_handles_lock:
            fh_id = self.next_open_handle_id
            self.next_open_handle_id += 1
            self.open_handles[fh_id] = {
                "path": path,
                "state": state,
                "opened_at": time.time(),
            }
        return fh_id

    def read(self, path, size, offset, fh):
        self._log_access("read", path, detail=f"size={size} offset={offset}")
        process_name = self._current_process_name()
        allow_stale_lookup = self._is_plex_scanner_process_name(
            process_name
        ) or self._is_background_process_name(process_name)
        entry = self._find_entry(path, allow_stale_parent=allow_stale_lookup)
        if not entry:
            raise FuseOSError(errno.ENOENT)
        handle = None
        fh_key = None
        try:
            fh_key = int(fh)
        except Exception:
            fh_key = None

        with self.open_handles_lock:
            opened = self.open_handles.get(fh_key) if fh_key is not None else None
            if opened and opened.get("path") == path:
                handle = opened.get("state")
        if handle is None:
            # Fallback path for platforms that do not pass a stable fh through read().
            # Do not increment refcount here because release() may only fire once.
            handle = self._get_handle(path, entry, acquire_ref=False)
        handle["last_used"] = time.time()

        is_plex_transcoder = self._is_plex_transcoder_process_name(process_name)
        entry_is_image = self._is_image_entry(entry)
        entry_extension = str(entry.get("extension") or "").lower().lstrip(".")
        is_mkv_entry = entry_extension == "mkv" or path.lower().endswith(".mkv")
        plex_scanner_process = self._is_plex_scanner_process_name(process_name)
        plex_dedicated_scanner_process = self._is_plex_dedicated_scanner_process_name(process_name)
        plex_media_server_process = self._is_plex_media_server_process_name(process_name)
        entry_size = int(entry.get("size", 0) or 0)

        current_time = time.time()
        if plex_scanner_process:
            self.plex_scanner_last_seen = current_time
        scanner_recently_active = (
            (current_time - float(self.plex_scanner_last_seen or 0.0))
            <= PLEX_SCANNER_REPEAT_WINDOW_SECONDS
        )
        playback_intent_active = self._has_recent_playback_intent(path, current_time)

        probe_size_limit = max(self.probe_read_bytes, PLEX_SCANNER_PROBE_MAX_READ_BYTES)
        media_server_probe_size_limit = max(4 * 1024, int(self.probe_read_bytes))
        scanner_probe_read = False
        scanner_hits = self._get_path_probe_hits(path, "scanner", current_time)
        dedicated_scanner_force_probe = False
        if (not entry_is_image) and plex_scanner_process:
            scanner_hits = self._bump_path_probe_hits(path, "scanner", current_time)
            handle["plex_scanner_hits"] = scanner_hits
            dedicated_scanner_force_probe = bool(
                plex_dedicated_scanner_process and (not PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS)
                and (PLEX_DEDICATED_SCANNER_ALWAYS_PROBE or (not playback_intent_active))
            )
            scanner_fake_eof_probe_read = (
                entry_size >= DEFAULT_FAKE_SIZE
                and offset >= max(0, entry_size - PLEX_FAKE_EOF_PROBE_TAIL_BYTES)
                and size <= PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES
            )
            if dedicated_scanner_force_probe:
                if PLEX_DEDICATED_SCANNER_ALWAYS_PROBE:
                    scanner_probe_read = True
                else:
                    scanner_probe_read = (
                        (not handle.get("activated"))
                        and (
                            scanner_fake_eof_probe_read
                            or (
                                PLEX_DEDICATED_SCANNER_PROBE_READS > 0
                                and scanner_hits <= PLEX_DEDICATED_SCANNER_PROBE_READS
                                and offset <= PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES
                                and size <= probe_size_limit
                            )
                        )
                    )
            else:
                scanner_probe_read = (
                    (not handle.get("activated"))
                    and (
                        scanner_fake_eof_probe_read
                        or (
                            (
                                PLEX_SCANNER_PROBE_READS > 0
                                and scanner_hits <= PLEX_SCANNER_PROBE_READS
                            )
                            and offset <= PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES
                            and size <= probe_size_limit
                        )
                    )
                )

        media_server_fake_eof_probe_read = False
        media_server_probe_read = False
        media_server_hits = self._get_path_probe_hits(path, "media_server", current_time)
        if (not entry_is_image) and plex_media_server_process:
            media_server_hits = self._bump_path_probe_hits(path, "media_server", current_time)
            handle["plex_media_server_hits"] = media_server_hits
            media_server_fake_eof_probe_read = (
                entry_size >= DEFAULT_FAKE_SIZE
                and offset >= max(0, entry_size - PLEX_FAKE_EOF_PROBE_TAIL_BYTES)
                and size <= PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES
            )
            media_server_probe_read = (
                (not handle.get("activated"))
                and (not playback_intent_active)
                and (
                    media_server_fake_eof_probe_read
                    or (
                        scanner_recently_active
                        and PLEX_MEDIA_SERVER_PROBE_READS > 0
                        and media_server_hits <= PLEX_MEDIA_SERVER_PROBE_READS
                        and offset <= PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES
                        and size <= media_server_probe_size_limit
                    )
                )
            )

        # Treat scanner/indexing processes as probes for video files to avoid consuming upstream slots.
        known_probe_read = (not entry_is_image) and (
            self._is_background_process_name(process_name)
            or scanner_probe_read
            or media_server_probe_read
        )
        unknown_probe_read = (
            (not entry_is_image)
            and (not process_name)
            and (not is_plex_transcoder)
            and UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES > 0
            and (not handle.get("activated"))
            and handle.get("unknown_probe_reads", 0) < 1
            and offset <= UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES
            and size <= UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES
        )
        is_probe_read = known_probe_read or unknown_probe_read

        if (
            PROBE_READ_LOGGING
            and
            (plex_scanner_process or plex_media_server_process or (not process_name))
            and (not is_probe_read)
            and (not handle.get("activated"))
        ):
            log.info(
                (
                    "Probe read not simulated path=%s proc=%s offset=%s size=%s "
                    "hits=%s scanner_read_limit=%s scanner_offset_limit=%s "
                    "dedicated_force_probe=%s dedicated_allow_reads=%s dedicated_probe_reads=%s "
                    "dedicated_always_probe=%s "
                    "playback_intent_active=%s "
                    "media_server_hits=%s media_server_read_limit=%s scanner_recent=%s "
                    "media_server_fake_eof=%s fake_eof_tail=%s fake_eof_read_limit=%s "
                    "unknown_read_limit=%s unknown_offset_limit=%s"
                ),
                path,
                process_name,
                offset,
                size,
                scanner_hits,
                PLEX_SCANNER_PROBE_READS,
                PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES,
                dedicated_scanner_force_probe,
                PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS,
                PLEX_DEDICATED_SCANNER_PROBE_READS,
                PLEX_DEDICATED_SCANNER_ALWAYS_PROBE,
                playback_intent_active,
                media_server_hits,
                PLEX_MEDIA_SERVER_PROBE_READS,
                scanner_recently_active,
                media_server_fake_eof_probe_read,
                PLEX_FAKE_EOF_PROBE_TAIL_BYTES,
                PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES,
                UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES,
                UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES,
            )

        # Only issue HEAD when we believe this is a real playback request.
        self._ensure_file_metadata(entry, allow_head=not is_probe_read)

        # If this is a scan probe, serve zeros and stay idle upstream.
        if is_probe_read:
            handle["served_fake"] = True
            should_log_probe = bool(PROBE_READ_LOGGING)
            if plex_scanner_process:
                should_log_probe = (
                    scanner_hits <= PROBE_LOG_INITIAL_HITS
                    or (
                        PROBE_LOG_EVERY_N_HITS > 0
                        and (scanner_hits % PROBE_LOG_EVERY_N_HITS) == 0
                    )
                    or scanner_hits in {
                        PLEX_SCANNER_PROBE_READS,
                        PLEX_DEDICATED_SCANNER_PROBE_READS,
                    }
                )
            elif plex_media_server_process:
                should_log_probe = (
                    media_server_hits <= PROBE_LOG_INITIAL_HITS
                    or (
                        PROBE_LOG_EVERY_N_HITS > 0
                        and (media_server_hits % PROBE_LOG_EVERY_N_HITS) == 0
                    )
                    or (
                        PLEX_MEDIA_SERVER_PROBE_READS > 0
                        and media_server_hits == PLEX_MEDIA_SERVER_PROBE_READS
                    )
                )
            elif unknown_probe_read:
                should_log_probe = handle.get("unknown_probe_reads", 0) <= 0

            if unknown_probe_read:
                handle["unknown_probe_reads"] = handle.get("unknown_probe_reads", 0) + 1
            if should_log_probe and (
                plex_scanner_process or plex_media_server_process or unknown_probe_read
            ):
                log.info(
                    (
                        "Probe read simulated path=%s proc=%s offset=%s size=%s "
                        "scanner_hits=%s scanner_limit=%s dedicated_force_probe=%s dedicated_allow_reads=%s "
                        "dedicated_probe_reads=%s "
                        "dedicated_always_probe=%s "
                        "playback_intent_active=%s "
                        "media_server_hits=%s media_server_limit=%s scanner_recent=%s "
                        "media_server_fake_eof=%s unknown_probe=%s"
                    ),
                    path,
                    process_name,
                    offset,
                    size,
                    scanner_hits,
                    PLEX_SCANNER_PROBE_READS,
                    dedicated_scanner_force_probe,
                    PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS,
                    PLEX_DEDICATED_SCANNER_PROBE_READS,
                    PLEX_DEDICATED_SCANNER_ALWAYS_PROBE,
                    playback_intent_active,
                    media_server_hits,
                    PLEX_MEDIA_SERVER_PROBE_READS,
                    scanner_recently_active,
                    media_server_fake_eof_probe_read,
                    unknown_probe_read,
                )
            return b"\0" * size

        if plex_media_server_process and (not entry_is_image):
            self._mark_playback_intent(path)

        handle["activated"] = True
        known_size = int(handle.get("size", 0) or entry.get("size", 0) or 0)
        if known_size > 0 and int(offset) >= known_size:
            return b""

        # Align fetch to readahead boundary to maximize sequential throughput.
        effective_readahead = self.readahead_bytes
        if is_mkv_entry and (not plex_scanner_process) and (not plex_media_server_process):
            effective_readahead = max(effective_readahead, MKV_PREFETCH_BYTES)
        if is_plex_transcoder:
            effective_readahead = max(
                effective_readahead,
                size,
                min(self.readahead_bytes, TRANSCODER_READAHEAD_BYTES),
                TRANSCODER_PREFETCH_BYTES,
            )

        cache_budget = MKV_BUFFER_CACHE_BYTES if is_mkv_entry else DEFAULT_BUFFER_CACHE_BYTES
        if is_plex_transcoder:
            cache_budget = max(cache_budget, MKV_BUFFER_CACHE_BYTES)

        max_fetch_cap = 0
        if is_mkv_entry and (not plex_scanner_process) and (not plex_media_server_process):
            max_fetch_cap = MKV_MAX_FETCH_BYTES
        if is_plex_transcoder:
            max_fetch_cap = max(max_fetch_cap or 0, TRANSCODER_MAX_FETCH_BYTES)

        handle_lock = handle.get("lock")
        if handle_lock is not None:
            with handle_lock:
                # Detect large seek jumps and restart startup prebuffer for the new cursor.
                last_end = int(handle.get("last_read_end", 0) or 0)
                seek_jump = last_end > 0 and abs(offset - last_end) > SEEK_RESET_THRESHOLD_BYTES
                if last_end > 0 and abs(offset - last_end) > SEEK_RESET_THRESHOLD_BYTES:
                    handle["initial_prebuffer_done"] = False

                handle["last_read_offset"] = int(offset)
                handle["last_read_end"] = int(offset + size)
                if seek_jump:
                    handle["playback_cursor"] = int(offset + size)
                else:
                    handle["playback_cursor"] = max(
                        int(handle.get("playback_cursor", 0) or 0),
                        int(offset + size),
                    )
                handle["effective_readahead"] = int(effective_readahead)
                handle["cache_budget"] = int(cache_budget)
                handle["max_fetch_cap"] = int(max_fetch_cap)
                handle["prefetch_enabled"] = bool(
                    SMOOTH_BUFFERING_ENABLED
                    and (is_mkv_entry or is_plex_transcoder)
                    and (not plex_scanner_process)
                    and (not plex_media_server_process)
                )
                handle["target_buffer_ahead"] = int(
                    max(TARGET_BUFFER_AHEAD_BYTES, effective_readahead)
                )
                handle["low_watermark"] = int(
                    max(LOW_WATERMARK_BYTES, PREFETCH_TRIGGER_BYTES)
                )

        if handle.get("prefetch_enabled"):
            self._start_prefetch_worker(path, entry, handle)
            self._ensure_initial_prebuffer(
                path=path,
                entry=entry,
                handle=handle,
                current_offset=offset,
            )

        # Serve from cached segments when possible.
        cached_segment = self._get_cached_segment(handle, offset, size)
        if cached_segment is not None:
            cached, _segment_offset, segment_end = cached_segment
            if CACHE_HIT_LOGGING and (is_mkv_entry or is_plex_transcoder):
                cache_pid = -1
                try:
                    _uid, _gid, cache_pid = fuse_get_context()
                except Exception:
                    pass
                log.info(
                    "FUSE cache-hit pid=%s proc=%s path=%s size=%s offset=%s",
                    cache_pid,
                    process_name,
                    path,
                    size,
                    offset,
                )

            # Proactive readahead for MKV/transcoder streams to avoid stalling at
            # segment boundaries (for example every 8 MiB window).
            remaining_in_segment = max(0, segment_end - (offset + size))
            if (
                (is_mkv_entry or is_plex_transcoder)
                and (not handle.get("prefetch_enabled"))
                and remaining_in_segment <= PREFETCH_TRIGGER_BYTES
            ):
                self._maybe_prefetch_next_range(
                    handle=handle,
                    entry=entry,
                    current_segment_end=segment_end,
                    effective_readahead=effective_readahead,
                    max_cache_bytes=cache_budget,
                    path=path,
                )
            return cached

        if is_mkv_entry or is_plex_transcoder:
            # For MKV/transcoder reads, avoid aligning backwards; fetch forward to reduce overlap churn.
            fetch_offset = max(0, offset)
        else:
            fetch_offset = max(0, offset - (offset % effective_readahead))
        fetch_size = max(size, effective_readahead)
        # Ensure the fetched span fully covers [offset, offset+size) even when aligned backwards.
        required_window = (offset - fetch_offset) + size
        fetch_size = max(fetch_size, required_window)
        if max_fetch_cap:
            fetch_size = max(required_window, min(fetch_size, max_fetch_cap))
        # If we know the size, avoid requesting past EOF.
        total_size = int(handle.get("size", 0) or 0)
        if total_size > 0:
            remaining = total_size - int(fetch_offset)
            if remaining <= 0:
                return b""
            fetch_size = min(fetch_size, remaining)
        fetch_size = int(fetch_size)
        if fetch_size <= 0:
            return b""

        try:
            content = self._fetch_and_cache_range(
                handle=handle,
                entry=entry,
                fetch_offset=fetch_offset,
                fetch_size=fetch_size,
                max_cache_bytes=cache_budget,
                min_fetch_size=required_window,
            )
            start = offset - fetch_offset
            end = start + size
            return content[start:end]
        except Exception:  # pragma: no cover
            log.exception(
                "Stream error path=%s process=%s offset=%s size=%s fetch_offset=%s fetch_size=%s",
                path,
                process_name,
                offset,
                size,
                fetch_offset,
                fetch_size,
            )
            raise FuseOSError(errno.EIO)

    # Read-only filesystem: block writes
    def write(self, path, data, offset, fh):
        raise FuseOSError(errno.EROFS)

    def mkdir(self, path, mode):
        raise FuseOSError(errno.EROFS)

    def rmdir(self, path):
        raise FuseOSError(errno.EROFS)

    def unlink(self, path):
        raise FuseOSError(errno.EROFS)

    def release(self, path, fh):
        """
        Close per-path session when the file handle is released to avoid
        leaving provider connections open (important when max_streams is low).
        """
        self._log_access("release", path)
        state = None
        fh_key = None
        try:
            fh_key = int(fh)
        except Exception:
            fh_key = None
        with self.open_handles_lock:
            opened = self.open_handles.pop(fh_key, None) if fh_key is not None else None
            if opened:
                state = opened.get("state")

        with self.pool_lock:
            if state is None:
                state = self.session_pool.get(path)
            if not state:
                return 0
            if int(state.get("refcount", 0) or 0) > 0:
                state["refcount"] -= 1
            if state["refcount"] <= 0:
                if (not state.get("activated")) and state.get("served_fake"):
                    # Scanner/probe-only handles do not need to linger in the pool.
                    self._stop_prefetch_worker(state, wait=False)
                    if BUFFER_RELEASE_ON_CLOSE:
                        self._clear_handle_buffers(state)
                    sess = state.get("session")
                    if sess:
                        try:
                            sess.close()
                        except Exception:
                            pass
                    self.session_pool.pop(path, None)
                    return 0

                state["refcount"] = 0
                state["last_used"] = time.time()
                state["activated"] = False
                state["served_fake"] = False
                state["unknown_probe_reads"] = 0
                # Keep scanner/media-server probe counters across rapid reopen cycles
                # so probe-read thresholds can advance instead of restarting at 0.
                state["playback_cursor"] = 0
                state["last_read_offset"] = None
                state["last_read_end"] = 0
                state["prefetch_enabled"] = False
                state["initial_prebuffer_started"] = False
                state["initial_prebuffer_done"] = False
                self._stop_prefetch_worker(state, wait=False)
                if BUFFER_RELEASE_ON_CLOSE:
                    self._clear_handle_buffers(state)
                # Do not immediately close to allow rapid reopen to reuse the same session URL.
                # Cleanup happens opportunistically in _get_handle after SESSION_IDLE_TTL.
        return 0


def parse_args():
    parser = argparse.ArgumentParser(description="Dispatcharr VOD FUSE client")
    parser.add_argument("--mode", choices=["movies", "tv"], required=True, help="movies or tv")
    parser.add_argument("--backend-url", required=True, help="Base URL to the Dispatcharr backend (e.g., http://localhost:9191)")
    parser.add_argument("--mountpoint", required=True, help="Mountpoint on the host")
    parser.add_argument(
        "--readahead-bytes",
        type=int,
        default=DEFAULT_READAHEAD_BYTES,
        help="Upstream range size to fetch and buffer per read (bytes)",
    )
    parser.add_argument(
        "--probe-read-bytes",
        type=int,
        default=DEFAULT_PROBE_READ_BYTES,
        help="Serve zeros for the first small read (<= this) to avoid accidental playback from background scans",
    )
    parser.add_argument(
        "--max-read",
        type=int,
        default=4 * 1024 * 1024,
        help="Max read size in bytes for FUSE (helps avoid tons of tiny range requests)",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in foreground (useful for debugging)",
    )
    parser.add_argument(
        "--single-thread",
        action="store_true",
        help="Run FUSE in single-threaded mode (default is multithreaded for better transcoder concurrency)",
    )
    parser.add_argument(
        "--disable-kernel-cache",
        action="store_true",
        help="Disable kernel page cache for mounted files (enabled by default for smoother playback)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not FUSE_HOST_TOKEN:
        log.warning(
            "FUSE_HOST_TOKEN is not set. Backend may reject unauthenticated FUSE requests."
        )
    log.info("FUSE client build=%s platform=%s", FUSE_CLIENT_BUILD, sys.platform)
    log.info(
        (
            "FUSE tuning active: readahead=%s max_read=%s "
            "mkv_prefetch=%s mkv_max_fetch=%s mkv_cache=%s "
            "transcoder_prefetch=%s transcoder_max_fetch=%s "
            "prefetch_trigger=%s smooth=%s initial_prebuffer=%s target_ahead=%s "
            "max_total_buffer=%s release_buffers_on_close=%s dir_cache_ttl=%ss "
            "range_5xx_retries=%s min_range_fetch=%s range_5xx_backoff=%ss "
            "access_log=%s probe_log=%s probe_log_initial_hits=%s probe_log_every_n=%s"
        ),
        args.readahead_bytes,
        args.max_read,
        MKV_PREFETCH_BYTES,
        MKV_MAX_FETCH_BYTES,
        MKV_BUFFER_CACHE_BYTES,
        TRANSCODER_PREFETCH_BYTES,
        TRANSCODER_MAX_FETCH_BYTES,
        PREFETCH_TRIGGER_BYTES,
        SMOOTH_BUFFERING_ENABLED,
        INITIAL_PREBUFFER_BYTES,
        TARGET_BUFFER_AHEAD_BYTES,
        MAX_TOTAL_BUFFER_BYTES,
        BUFFER_RELEASE_ON_CLOSE,
        DIR_CACHE_TTL_SECONDS,
        RANGE_5XX_RETRIES,
        MIN_RANGE_FETCH_BYTES,
        RANGE_5XX_BACKOFF_SECONDS,
        ACCESS_EVENT_LOGGING,
        PROBE_READ_LOGGING,
        PROBE_LOG_INITIAL_HITS,
        PROBE_LOG_EVERY_N_HITS,
    )
    api_client = FuseAPIClient(
        args.backend_url,
        args.mode,
        mountpoint=args.mountpoint,
    )
    try:
        api_client.browse("/")  # Fail fast if backend is unreachable
    except FuseOSError as exc:
        log.error(
            "Cannot reach backend %s for mode=%s: %s",
            args.backend_url,
            args.mode,
            exc,
        )
        sys.exit(1)
    fuse = VODFuse(api_client, args.readahead_bytes, args.probe_read_bytes)
    if sys.platform.startswith("win"):
        # WinFsp/fusepy option support varies by version. Try stricter options first,
        # then fall back to minimal flags before giving up.
        win_attempts = [
            {"nothreads": args.single_thread, "foreground": args.foreground, "ro": True},
            {"nothreads": args.single_thread, "foreground": args.foreground},
            {"nothreads": True, "foreground": args.foreground},
            {"nothreads": True},
        ]
        seen_attempts = set()
        last_exc: Optional[Exception] = None
        for index, raw_options in enumerate(win_attempts, start=1):
            # Skip duplicates (for example when args.single_thread is already true).
            key = tuple(sorted(raw_options.items()))
            if key in seen_attempts:
                continue
            seen_attempts.add(key)

            log.info(
                "Attempting WinFsp mount attempt=%s mountpoint=%s options=%s",
                index,
                args.mountpoint,
                raw_options,
            )
            try:
                FUSE(
                    fuse,
                    args.mountpoint,
                    **raw_options,
                )
                return
            except Exception as exc:
                last_exc = exc
                log.error(
                    "WinFsp mount failed attempt=%s mountpoint=%s options=%s err=%s",
                    index,
                    args.mountpoint,
                    raw_options,
                    exc,
                )
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("WinFsp mount failed before any attempt executed")
    else:
        FUSE(
            fuse,
            args.mountpoint,
            nothreads=args.single_thread,
            foreground=args.foreground,
            ro=True,
            allow_other=True,
            big_writes=True,
            max_read=args.max_read,
            kernel_cache=(not args.disable_kernel_cache),
            auto_cache=(not args.disable_kernel_cache),
        )


if __name__ == "__main__":
    main()
