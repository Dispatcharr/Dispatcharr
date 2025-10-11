#!/usr/bin/env python3
import errno
import os
import stat
import time
import argparse
import threading
from typing import Dict, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from fuse import FUSE, Operations, FuseOSError

# Notes:
# - Requires: pip install fusepy requests
# - Linux: install FUSE (e.g., sudo apt-get install fuse3) and ensure user can mount
# - Mount with: sudo python3 url_stream_fs.py --source /path/to/url-files --mount /mnt/streamfs -o allow_other
#
# Behavior:
# - Mirrors the directory structure under --source.
# - Each regular file is treated as a "URL file": first non-empty, non-comment line is the media URL.
# - getattr:
#     - For files, returns a read-only regular file with size derived from HEAD Content-Length.
#     - Size is cached with TTL to avoid excessive HEADs.
# - open:
#     - Performs HEAD against the file's URL, reads Content-Length and X-Session-URL (if present).
#     - Stores a per-open handle with "session_url" for subsequent reads.
# - read:
#     - Issues GET with Range: bytes=offset-end to the per-handle session_url (or original URL if no session header).
#     - Returns exactly the bytes requested by FUSE (or fewer near EOF).
# - release:
#     - Closes the per-open requests.Session and discards handle state.


DEFAULT_TTL_SECONDS = 60  # cache TTL for HEAD-derived file size (getattr)
DEFAULT_TIMEOUT = (5, 30)  # (connect, read) timeouts for requests
USER_AGENT = "URLStreamFS/1.1 (+https://github.com/)"

# Read-only stat size strategy to avoid prematurely creating sessions:
# - "zero": always report 0 (never HEAD on getattr)
# - "cached": report last-known size if we've opened before (no HEAD on getattr)
# - "head": perform HEAD on getattr (may create a session early)
DEFAULT_STAT_MODE = "cached"

# If a GET returns one of these, we will refresh the session and retry once
SESSION_RETRY_STATUS = {401, 403, 404, 410, 412, 429, 500, 502, 503, 504}


def is_probably_url(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def read_url_from_file(local_path: str) -> str:
    # Reads first non-empty, non-comment line (comments start with '#')
    with open(local_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not is_probably_url(line):
                raise FuseOSError(errno.EINVAL)
            return line
    raise FuseOSError(errno.EINVAL)


class URLStreamFS(Operations):
    def __init__(
        self,
        source_root: str,
        extra_headers: Optional[Dict[str, str]] = None,
        stat_ttl: int = DEFAULT_TTL_SECONDS,
        timeout: Tuple[int, int] = DEFAULT_TIMEOUT,
        only_ext: Optional[Tuple[str, ...]] = None,
        stat_mode: str = DEFAULT_STAT_MODE,
    ):
        self.source_root = os.path.abspath(source_root)
        self.extra_headers = extra_headers or {}
        self.stat_ttl = stat_ttl
        self.timeout = timeout
        self.only_ext = tuple(e.lower() for e in only_ext) if only_ext else None
        self.stat_mode = stat_mode  # zero|cached|head

        # Cache for HEAD-derived sizes keyed by absolute path
        self._size_cache: Dict[str, Dict] = {}
        self._size_lock = threading.RLock()

        # Handle table for per-open sessions
        self._fh_lock = threading.RLock()
        self._next_fh = 3  # arbitrary start
        self._handles: Dict[int, Dict] = {}

    # Helpers

    def _full_path(self, path: str) -> str:
        assert path.startswith("/")
        return os.path.join(self.source_root, path.lstrip("/"))

    def _is_supported_file(self, full: str) -> bool:
        if not os.path.isfile(full):
            return False
        if self.only_ext:
            _, ext = os.path.splitext(full)
            return ext.lower() in self.only_ext
        return True

    def _requests_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Connection": "keep-alive",
                **self.extra_headers,
            }
        )
        # A small connection pool helps concurrent readers
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        return s

    def _head(self, session: requests.Session, url: str) -> requests.Response:
        # Allow redirects; server returns Content-Length and possibly X-Session-URL
        resp = session.head(url, allow_redirects=True, timeout=self.timeout)
        if resp.status_code >= 400:
            raise FuseOSError(errno.EIO)
        return resp

    def _update_size_cache(self, full: str, size: Optional[int]) -> None:
        with self._size_lock:
            self._size_cache[full] = {
                "ts": time.time(),
                "local_mtime": os.path.getmtime(full),
                "size": size,
            }

    def _get_size_cached(self, full: str, url: str) -> Optional[int]:
        # Returns size from cache or refreshes via HEAD (using a short-lived session not tied to 'open')
        now = time.time()
        local_mtime = os.path.getmtime(full)
        with self._size_lock:
            entry = self._size_cache.get(full)
            if (
                entry
                and entry["local_mtime"] == local_mtime
                and (now - entry["ts"]) <= self.stat_ttl
                and entry.get("size") is not None
            ):
                return entry["size"]

        # Avoid creating server-side viewing sessions during getattr unless explicitly requested
        if self.stat_mode != "head":
            return None

        # Refresh with HEAD (may create/advance a session server-side)
        sess = self._requests_session()
        try:
            resp = self._head(sess, url)
            size = None
            cl = resp.headers.get("Content-Length")
            if cl is not None:
                try:
                    size = int(cl)
                except ValueError:
                    size = None
        finally:
            sess.close()

        with self._size_lock:
            self._size_cache[full] = {
                "ts": now,
                "local_mtime": local_mtime,
                "size": size,
            }
        return size

    def _ensure_session(self, handle: Dict) -> None:
        # Lazily start or refresh a session for this open handle
        if handle.get("session_url"):
            return
        sess: requests.Session = handle["sess"]
        orig_url: str = handle["orig_url"]

        head = self._head(sess, orig_url)
        session_url = head.headers.get("X-Session-URL") or orig_url

        size = None
        cl = head.headers.get("Content-Length")
        if cl is not None:
            try:
                size = int(cl)
            except ValueError:
                size = None

        handle["session_url"] = session_url
        handle["size"] = size
        # Save for getattr(stat_mode=cached)
        self._update_size_cache(handle["full"], size)

    def access(self, path, mode):
        full = self._full_path(path)
        if not os.path.exists(full):
            raise FuseOSError(errno.ENOENT)
        # Read-only FS
        if mode & (os.W_OK | os.X_OK):
            # Allow execute traversal on directories, deny writes
            if os.path.isdir(full):
                return 0
            if mode & os.W_OK:
                raise FuseOSError(errno.EROFS)
        return 0

    def getattr(self, path, fh=None):
        full = self._full_path(path)
        if not os.path.exists(full):
            raise FuseOSError(errno.ENOENT)

        st = os.lstat(full)

        # Directory: mirror local attrs
        if stat.S_ISDIR(st.st_mode):
            return dict(
                st_mode=(stat.S_IFDIR | 0o555),  # read+execute
                st_nlink=2,
                st_size=0,
                st_ctime=st.st_ctime,
                st_mtime=st.st_mtime,
                st_atime=st.st_atime,
            )

        # Files: expose as read-only regular files and override size from remote (per stat_mode)
        if self._is_supported_file(full):
            mode = stat.S_IFREG | 0o444
            try:
                url = read_url_from_file(full)
            except FuseOSError:
                url = None

            size = 0
            if url:
                if self.stat_mode == "zero":
                    size = 0
                elif self.stat_mode == "cached":
                    cached = self._get_size_cached(full, url)  # will not network-call in cached mode
                    size = cached if cached is not None else 0
                else:  # head
                    probed = self._get_size_cached(full, url)  # performs HEAD when stale
                    size = probed if probed is not None else 0

            return dict(
                st_mode=mode,
                st_nlink=1,
                st_size=size,
                st_ctime=st.st_ctime,
                st_mtime=st.st_mtime,
                st_atime=st.st_atime,
            )

        # Non-supported regular files: show as 0444 with local size
        return dict(
            st_mode=(stat.S_IFREG | 0o444),
            st_nlink=1,
            st_size=st.st_size,
            st_ctime=st.st_ctime,
            st_mtime=st.st_mtime,
            st_atime=st.st_atime,
        )

    def readdir(self, path, fh):
        full = self._full_path(path)
        if not os.path.isdir(full):
            raise FuseOSError(errno.ENOTDIR)

        entries = [".", ".."]
        try:
            for name in os.listdir(full):
                entries.append(name)
        except PermissionError:
            raise FuseOSError(errno.EACCES)

        for e in entries:
            yield e

     # Open returns a new file handle; session is created lazily on first read
    def open(self, path, flags):
        full = self._full_path(path)
        if not os.path.exists(full):
            raise FuseOSError(errno.ENOENT)
        if not self._is_supported_file(full):
            if flags & (os.O_WRONLY | os.O_RDWR):
                raise FuseOSError(errno.EROFS)
            raise FuseOSError(errno.EPERM)

        if flags & (os.O_WRONLY | os.O_RDWR):
            raise FuseOSError(errno.EROFS)

        url = read_url_from_file(full)

        sess = self._requests_session()

        with self._fh_lock:
            fh = self._next_fh
            self._next_fh += 1
            self._handles[fh] = {
                "path": path,
                "full": full,
                "orig_url": url,
                "session_url": None,  # defer creating session until first read
                "size": None,
                "sess": sess,
                "lock": threading.RLock(),
            }
        return fh

    def _perform_range_get(self, sess: requests.Session, url: str, start: int, size: int) -> requests.Response:
        end = start + size - 1 if size > 0 else None
        headers = {}
        if size > 0:
            headers["Range"] = f"bytes={start}-{end}"
        return sess.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=self.timeout,
        )

    def read(self, path, size, offset, fh):
        with self._fh_lock:
            handle = self._handles.get(fh)
        if handle is None:
            raise FuseOSError(errno.EBADF)

        sess: requests.Session = handle["sess"]

        # Lazily create or refresh session before first read
        try:
            with handle["lock"]:
                if not handle.get("session_url"):
                    self._ensure_session(handle)
                session_url = handle["session_url"]
        except Exception:
            raise

        # Attempt GET; if it indicates session is invalid, refresh once and retry
        def fetch_once(target_url: str):
            return self._perform_range_get(sess, target_url, max(0, offset), size)

        try:
            with handle["lock"]:
                resp = fetch_once(session_url)

                # If server sends a new X-Session-URL on GET, update our handle
                new_session_url = resp.headers.get("X-Session-URL")
                if new_session_url and new_session_url != session_url:
                    handle["session_url"] = new_session_url
                    session_url = new_session_url

                if resp.status_code in SESSION_RETRY_STATUS:
                    # Refresh session and retry once
                    self._ensure_session(handle)
                    session_url = handle["session_url"]
                    resp.close()
                    resp = fetch_once(session_url)

            if resp.status_code not in (200, 206):
                if resp.status_code == 416:
                    return b""
                raise FuseOSError(errno.EIO)

            data = b""
            start = max(0, offset)

            if resp.status_code == 200 and start > 0:
                # Fallback: server ignored range; skip then slice
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        break
                    if start >= len(chunk):
                        start -= len(chunk)
                        continue
                    take = min(len(chunk) - start, size - len(data))
                    data += chunk[start : start + take]
                    start = 0
                    if len(data) >= size:
                        break
            else:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        break
                    need = size - len(data)
                    if need <= 0:
                        break
                    if len(chunk) > need:
                        data += chunk[:need]
                        break
                    data += chunk

            return data
        except requests.Timeout:
            raise FuseOSError(errno.ETIMEDOUT)
        except requests.RequestException:
            raise FuseOSError(errno.EIO)

    def release(self, path, fh):
        with self._fh_lock:
            handle = self._handles.pop(fh, None)
        if handle:
            try:
                handle["sess"].close()
            except Exception:
                pass
        return 0

    # Read-only FS
    def unlink(self, path):
        raise FuseOSError(errno.EROFS)

    def rename(self, old, new):
        raise FuseOSError(errno.EROFS)

    def mkdir(self, path, mode):
        raise FuseOSError(errno.EROFS)

    def rmdir(self, path):
        raise FuseOSError(errno.EROFS)

    def chmod(self, path, mode):
        raise FuseOSError(errno.EROFS)

    def chown(self, path, uid, gid):
        raise FuseOSError(errno.EROFS)

    def truncate(self, path, length, fh=None):
        raise FuseOSError(errno.EROFS)

    def utimens(self, path, times=None):
        # Ignore updates
        return 0

    def statfs(self, path):
        # Provide some sane defaults; not critical for media servers
        block_size = 4096
        total = 1 << 30  # 1 GiB virtual
        free = total // 2
        return dict(
            f_bsize=block_size,
            f_frsize=block_size,
            f_blocks=total // block_size,
            f_bfree=free // block_size,
            f_bavail=free // block_size,
            f_files=1000000,
            f_ffree=999999,
            f_namemax=255,
        )


def parse_headers(header_list: Optional[list]) -> Dict[str, str]:
    headers = {}
    if not header_list:
        return headers
    for h in header_list:
        if ":" not in h:
            continue
        k, v = h.split(":", 1)
        headers[k.strip()] = v.strip()
    return headers


def main():
    parser = argparse.ArgumentParser(description="Mount URL-streaming FUSE filesystem")
    parser.add_argument("--source", required=True, help="Local directory with URL files")
    parser.add_argument("--mount", required=True, help="Mount point")
    parser.add_argument(
        "--ext",
        action="append",
        help="Only treat files with this extension as URL files (e.g., --ext .url). Repeatable.",
    )
    parser.add_argument(
        "--header",
        action="append",
        help="Extra HTTP header to send to the API (e.g., --header 'Authorization: Bearer ...'). Repeatable.",
    )
    parser.add_argument("--stat-ttl", type=int, default=DEFAULT_TTL_SECONDS, help="Seconds to cache remote size")
    parser.add_argument(
        "--stat-mode",
        choices=["zero", "cached", "head"],
        default=DEFAULT_STAT_MODE,
        help="How getattr reports size: zero (no HEAD), cached (no HEAD until opened), or head (HEAD on getattr).",
    )
    parser.add_argument("--fg", action="store_true", help="Run in foreground")
    parser.add_argument("-o", dest="fuseopts", default="", help="Additional FUSE options (e.g., allow_other)")
    args = parser.parse_args()

    if not os.path.isdir(args.source):
        raise SystemExit(f"Source directory not found: {args.source}")
    if not os.path.isdir(args.mount):
        raise SystemExit(f"Mount point must exist and be a directory: {args.mount}")

    headers = parse_headers(args.header)
    only_ext = tuple(args.ext) if args.ext else None

    fs = URLStreamFS(
        source_root=args.source,
        extra_headers=headers,
        stat_ttl=args.stat_ttl,
        only_ext=only_ext,
        stat_mode=args.stat_mode,
    )

    # Prepare FUSE options
    fuse_kwargs = {
        "foreground": args.fg,
        "nothreads": False,
        "allow_other": "allow_other" in (args.fuseopts or ""),
    }

    # fusepy uses options via -o; we pass the raw string if provided
    FUSE(fs, args.mount, nothreads=fuse_kwargs["nothreads"], foreground=fuse_kwargs["foreground"], fsname="urlstreamfs", ro=True, debug=args.fg)


if __name__ == "__main__":
    main()
