"""
Simple read-only FUSE client for Dispatcharr VOD.

Usage:
  python fuse_client.py --mode movies --backend-url http://localhost:9191 --mountpoint /mnt/vod_movies
  python fuse_client.py --mode tv --backend-url http://localhost:9191 --mountpoint /mnt/vod_tv

Requires: fusepy (Linux/macOS) or WinFsp with fusepy on Windows.
"""
import argparse
import errno
import logging
import os
import subprocess
import stat
import time
from typing import Dict, Optional
from urllib.parse import urljoin

import requests
from fuse import FUSE, FuseOSError, LoggingMixIn, Operations, fuse_get_context

log = logging.getLogger("dispatcharr_fuse")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Use a generous fake size when we cannot learn the real length so players keep requesting data.
DEFAULT_FAKE_SIZE = 5 * 1024 * 1024 * 1024  # 5 GiB
# Keep sessions warm so we don't rebuild upstream sessions between reads.
SESSION_IDLE_TTL = 300  # seconds
# Ignore tiny first reads (Finder/thumbnail probes) to avoid creating upstream sessions.
DEFAULT_PROBE_READ_BYTES = 512 * 1024  # 512 KiB


class FuseAPIClient:
    """HTTP bridge to the backend FUSE API."""

    def __init__(self, backend_url: str, mode: str):
        self.base = backend_url.rstrip("/")
        self.mode = mode
        self.session = requests.Session()

    def browse(self, path: str) -> Dict:
        resp = self.session.get(
            f"{self.base}/api/fuse/browse/{self.mode}/", params={"path": path}
        )
        resp.raise_for_status()
        return resp.json()

    def stream_url(self, content_type: str, content_id: str) -> str:
        resp = self.session.get(
            f"{self.base}/api/fuse/stream/{content_type}/{content_id}/"
        )
        resp.raise_for_status()
        return resp.json().get("stream_url")

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
            resp = session.get(next_url, headers=headers, stream=True, timeout=30, allow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                # The proxy returns relative redirects; urljoin keeps the original host/scheme.
                next_url = urljoin(next_url, resp.headers["Location"])
                continue
            if resp.status_code not in (200, 206):
                raise FuseOSError(errno.EIO)
            total_size = None
            # Parse Content-Range: bytes start-end/total
            cr = resp.headers.get("Content-Range")
            if cr and "/" in cr:
                try:
                    total_size = int(cr.split("/")[-1])
                except Exception:
                    total_size = None
            # Return both content and the final URL we ended up at (sessionized path) and optional total size
            return resp.content, next_url, total_size
        raise FuseOSError(errno.EIO)


class VODFuse(LoggingMixIn, Operations):
    """Read-only filesystem exposing VOD Movies or TV."""

    def __init__(self, api_client: FuseAPIClient, readahead_bytes: int, probe_read_bytes: int):
        self.api = api_client
        self.readahead_bytes = readahead_bytes
        self.probe_read_bytes = probe_read_bytes
        self.dir_cache: Dict[str, Dict] = {}
        self.path_index: Dict[str, Dict] = {}
        # shared session pool across opens of the same path to avoid repeated upstream sessions
        # path -> {"session", "session_url", "size", "refcount", "last_used"}
        self.session_pool: Dict[str, Dict] = {}
        self.proc_name_cache: Dict[int, str] = {}
        self.access_log_once: set = set()

    def _process_name(self, pid: int) -> str:
        if pid in self.proc_name_cache:
            return self.proc_name_cache[pid]
        name = ""
        try:
            import psutil  # type: ignore

            name = psutil.Process(pid).name()
        except Exception:
            try:
                out = subprocess.check_output(["ps", "-p", str(pid), "-o", "comm="], text=True)
                name = out.strip()
            except Exception:
                name = ""
        self.proc_name_cache[pid] = name
        return name

    def _log_access(self, event: str, path: str, detail: str = ""):
        try:
            uid, gid, pid = fuse_get_context()
        except Exception:
            uid = gid = pid = -1
        name = self._process_name(pid) if pid and pid > 1 else ""
        key = (event, path, pid)
        if key in self.access_log_once:
            return
        self.access_log_once.add(key)
        log.info("FUSE %s pid=%s proc=%s uid=%s path=%s %s", event, pid, name, uid, path, detail)

    def _is_background_process(self) -> bool:
        """
        Detect Spotlight/QuickLook/mdworker probes so we can serve zeros without opening upstream.
        """
        try:
            uid, gid, pid = fuse_get_context()
        except Exception:
            return False
        if not pid or pid < 2:
            return False
        name = self._process_name(pid)
        return name.lower() in {
            "mds", "mdworker", "mdworker_shared", "spotlight", "quicklookd", "qlmanage",
            "photolibraryd", "photoanalysisd",
        }

    # Helpers
    def _get_entries(self, path: str):
        if path in self.dir_cache:
            return self.dir_cache[path]
        data = self.api.browse(path)
        self.dir_cache[path] = data
        # index children
        for entry in data.get("entries", []):
            self.path_index[entry["path"]] = entry
        return data

    def _find_entry(self, path: str) -> Optional[Dict]:
        if path == "/":
            return {"is_dir": True}
        if path in self.path_index:
            return self.path_index[path]
        # Attempt to refresh parent directory
        parent = "/" + "/".join([p for p in path.strip("/").split("/")[:-1]])
        if parent == "":
            parent = "/"
        self._get_entries(parent)
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
                entry["size"] = DEFAULT_FAKE_SIZE
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
            entry["size"] = DEFAULT_FAKE_SIZE

    def _get_handle(self, path: str, entry: Dict):
        """
        Ensure we have per-path session state without touching the upstream.
        """
        now = time.time()
        # Evict stale idle sessions
        for stale_path, state in list(self.session_pool.items()):
            if state.get("refcount", 0) <= 0 and (now - state.get("last_used", now)) > SESSION_IDLE_TTL:
                sess = state.get("session")
                if sess:
                    try:
                        sess.close()
                    except Exception:
                        pass
                self.session_pool.pop(stale_path, None)

        if path in self.session_pool:
            state = self.session_pool[path]
            state["refcount"] = state.get("refcount", 0) + 1
            state["last_used"] = now
            return state

        sess = requests.Session()
        # propagate auth header
        sess.headers.update(self.api.session.headers)

        stream_url = entry.get("stream_url")
        if not stream_url and entry.get("uuid"):
            stream_url = self.api.stream_url(entry["content_type"], entry["uuid"])
            entry["stream_url"] = stream_url
        if not stream_url:
            raise FuseOSError(errno.EIO)

        state = {
            "session": sess,
            "session_url": entry.get("session_url"),
            "size": entry.get("size") or DEFAULT_FAKE_SIZE,
            "refcount": 1,
            "last_used": now,
            "activated": False,   # becomes True after we decide to hit upstream
            "served_fake": False, # we served a fake stub read already
            "buffer_offset": None,
            "buffer_data": b"",
        }
        self.session_pool[path] = state
        return state

    # FUSE operations
    def getattr(self, path, fh=None):
        self._log_access("getattr", path)
        entry = self._find_entry(path)
        if not entry:
            raise FuseOSError(errno.ENOENT)

        # getattr is called frequently by Finder; avoid network HEAD here.
        self._ensure_file_metadata(entry, allow_head=False)

        now = time.time()
        if entry.get("is_dir"):
            return dict(
                st_mode=(stat.S_IFDIR | 0o755),
                st_nlink=2,
                st_ctime=now,
                st_mtime=now,
                st_atime=now,
            )

        size = entry.get("size") or 0
        return dict(
            st_mode=(stat.S_IFREG | 0o444),
            st_nlink=1,
            st_size=size,
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
        )

    def readdir(self, path, fh):
        self._log_access("readdir", path)
        data = self._get_entries(path)
        entries = [".", ".."] + [e["name"] for e in data.get("entries", [])]
        for entry in entries:
            yield entry

    def open(self, path, flags):
        self._log_access("open", path)
        entry = self._find_entry(path)
        if not entry or entry.get("is_dir"):
            raise FuseOSError(errno.EISDIR if entry else errno.ENOENT)
        return 0

    def read(self, path, size, offset, fh):
        self._log_access("read", path, detail=f"size={size} offset={offset}")
        entry = self._find_entry(path)
        if not entry:
            raise FuseOSError(errno.ENOENT)
        # Acquire or create per-path handle with session + session_url
        handle = self._get_handle(path, entry)
        handle["last_used"] = time.time()

        # Treat Spotlight/QuickLook/md* processes as probes and avoid triggering upstream.
        is_probe_read = self._is_background_process()
        # Only issue HEAD when we believe this is a real playback request.
        self._ensure_file_metadata(entry, allow_head=not is_probe_read)

        # If this is a background probe, serve zeros and stay idle upstream.
        if is_probe_read:
            handle["served_fake"] = True
            return b"\0" * size

        handle["activated"] = True

        url = handle.get("session_url") or entry.get("session_url") or entry.get("stream_url")
        # Serve from buffer when possible
        buf_offset = handle.get("buffer_offset")
        buf_data = handle.get("buffer_data") or b""
        if buf_offset is not None and buf_data:
            buf_end = buf_offset + len(buf_data)
            if offset >= buf_offset and (offset + size) <= buf_end:
                start = offset - buf_offset
                end = start + size
                return buf_data[start:end]

        # Align fetch to readahead boundary to maximize sequential throughput.
        fetch_offset = max(0, offset - (offset % self.readahead_bytes))
        fetch_size = max(size, self.readahead_bytes)
        # If we know the size, avoid requesting past EOF.
        total_size = handle.get("size")
        if total_size and total_size > 0:
            fetch_size = min(fetch_size, max(0, total_size - fetch_offset))
        # Never issue a zero-length range.
        fetch_size = max(1, fetch_size)

        try:
            content, final_url, total_size = self.api.ranged_get(handle["session"], url, fetch_offset, fetch_size)
            # Cache sessionized URL for future reads so we don't create new sessions each time.
            handle["session_url"] = final_url
            # If we learned the real size from Content-Range, update caches so seeking uses accurate length.
            if total_size:
                handle["size"] = total_size
                entry["size"] = total_size
            handle["buffer_offset"] = fetch_offset
            handle["buffer_data"] = content
            start = offset - fetch_offset
            end = start + size
            return content[start:end]
        except requests.RequestException as exc:  # pragma: no cover
            log.error("Stream error for %s: %s", path, exc)
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
        state = self.session_pool.get(path)
        if not state:
            return 0
        state["refcount"] -= 1
        if state["refcount"] <= 0:
            state["refcount"] = 0
            state["last_used"] = time.time()
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
        default=1 * 1024 * 1024,
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
    return parser.parse_args()


def main():
    args = parse_args()
    api_client = FuseAPIClient(args.backend_url, args.mode)
    fuse = VODFuse(api_client, args.readahead_bytes, args.probe_read_bytes)
    FUSE(
        fuse,
        args.mountpoint,
        nothreads=True,
        foreground=args.foreground,
        ro=True,
        allow_other=True,
        big_writes=True,
        max_read=args.max_read,
    )


if __name__ == "__main__":
    main()
