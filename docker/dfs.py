#!/usr/bin/env python3
"""
StreamFS — a Python FUSE virtual filesystem that exposes video-on-demand URLs
(from mapping files) as regular read-only files with full byte-range support.

Design highlights
-----------------
- Mapping directory (default: /mnt/mappings) contains *text files*. Each file's
  content is a single URL (source URL). The filename becomes the exposed file.
- When a client opens a file, StreamFS issues a HEAD request to the source URL.
  The server returns a *unique* session URL in the `X-Session-URL` header. That
  session URL is used for **all subsequent GETs** for that file handle.
- File size is taken from `Content-Length` (returned by HEAD).
- `read()` uses HTTP Range requests against the session URL so that scrubbing
  (random seeks) works seamlessly.
- Read-only filesystem. Multiple simultaneous clients are supported; each open
  gets its own session URL and connection pool.

Requirements
------------
- Linux with FUSE (libfuse) installed.
- Python 3.8+
- `fusepy` and `requests` packages.

    pip install fusepy requests

Mount example
-------------
    sudo ./streamfs.py /mnt/streamfs --maps /mnt/mappings -f -d

Unmount
-------
    sudo umount /mnt/streamfs

Notes
-----
- The mapping directory is reloaded automatically on directory listing calls,
  so adding/removing mapping files becomes visible to clients.
- Optional small read-ahead cache per open handle is included for sequential
  reads; it is conservative and safe to disable with `--no-readahead`.
- TLS verification can be disabled (e.g., for lab networks) via `--insecure`.

"""
import errno
import logging
import os
import stat
import sys
import time
import threading
import argparse
from typing import Dict, Tuple, Optional

import requests
from fuse import FUSE, Operations, LoggingMixIn

# -------------------------- Helpers & Data Classes -------------------------- #

class HTTPError(IOError):
    pass


def clamp(n: int, low: int, high: int) -> int:
    return max(low, min(high, n))


class OpenHandle:
    """Tracks state for one open() file handle."""

    def __init__(self, logical_path: str, source_url: str, session: requests.Session,
                 session_url: str, size: int, readahead: bool, verify_tls: bool):
        self.path = logical_path
        self.source_url = source_url
        self.session = session
        self.session_url = session_url
        self.size = size
        self.verify_tls = verify_tls

        # Simple read-ahead cache: maps (start,end) -> bytes
        self.readahead = readahead
        self.cache_lock = threading.Lock()
        self.cache: Dict[Tuple[int, int], bytes] = {}
        self.max_cache_bytes = 4 * 1024 * 1024  # 4 MiB per handle cap
        self.cache_bytes = 0

    def _add_cache(self, start: int, data: bytes):
        if not self.readahead:
            return
        with self.cache_lock:
            end = start + len(data)
            key = (start, end)
            # If adding exceeds cap, clear cache (simple strategy).
            if self.cache_bytes + len(data) > self.max_cache_bytes:
                self.cache.clear()
                self.cache_bytes = 0
            self.cache[key] = data
            self.cache_bytes += len(data)

    def _get_from_cache(self, start: int, size: int) -> Optional[bytes]:
        if not self.readahead or size <= 0:
            return None
        with self.cache_lock:
            for (s, e), blob in list(self.cache.items()):
                if start >= s and (start + size) <= e:
                    off = start - s
                    return blob[off:off + size]
        return None

    def ranged_get(self, start: int, size: int) -> bytes:
        if size <= 0:
            return b""
        # Clamp against EOF
        end_inclusive = clamp(start + size - 1, 0, self.size - 1)
        if end_inclusive < start:
            return b""

        # Cache lookup
        cached = self._get_from_cache(start, end_inclusive - start + 1)
        if cached is not None:
            return cached

        headers = {"Range": f"bytes={start}-{end_inclusive}"}
        resp = self.session.get(self.session_url, headers=headers, stream=False,
                                timeout=(5, 30), verify=self.verify_tls)
        if resp.status_code not in (200, 206):
            raise HTTPError(f"Unexpected GET status {resp.status_code} for {self.path}")
        data = resp.content
        # Cache the full returned chunk
        self._add_cache(start, data)
        return data

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


# ------------------------------ Filesystem Core ----------------------------- #

class StreamFS(LoggingMixIn, Operations):
    def __init__(self, mappings_dir: str, verify_tls: bool = True, readahead: bool = True):
        super().__init__()
        self.mappings_dir = os.path.abspath(mappings_dir)
        self.verify_tls = verify_tls
        self.readahead = readahead

        self._log = logging.getLogger("StreamFS")
        self._log.info("Using mappings dir: %s", self.mappings_dir)

        # name -> source URL string (loaded from files)
        self.mappings: Dict[str, str] = {}
        self._mappings_mtime = 0.0
        self._mappings_lock = threading.Lock()

        # name -> (size, etag/last-modified)
        self.meta_cache: Dict[str, Tuple[int, Optional[str]]] = {}
        self._meta_lock = threading.Lock()

        # fh -> OpenHandle
        self._fh_lock = threading.Lock()
        self._next_fh = 3
        self._open_handles: Dict[int, OpenHandle] = {}

        if not os.path.isdir(self.mappings_dir):
            raise RuntimeError(f"Mappings directory does not exist: {self.mappings_dir}")
        self._reload_mappings(force=True)

    # --------------------------- Mapping management -------------------------- #

    def _reload_mappings(self, force: bool = False):
        try:
            mtime = os.stat(self.mappings_dir).st_mtime
        except FileNotFoundError:
            mtime = time.time()
        if not force and mtime <= self._mappings_mtime:
            return

        with self._mappings_lock:
            new_map: Dict[str, str] = {}
            for entry in os.listdir(self.mappings_dir):
                full = os.path.join(self.mappings_dir, entry)
                if not os.path.isfile(full):
                    continue
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        url = f.read().strip()
                        if url:
                            new_map[entry] = url
                except Exception as e:
                    self._log.warning("Skipping mapping %s: %s", entry, e)
            self.mappings = new_map
            self._mappings_mtime = mtime
            self._log.info("Loaded %d mappings", len(self.mappings))

    # ------------------------------- Utilities ------------------------------- #

    def _source_for_path(self, path: str) -> Optional[str]:
        name = path.lstrip("/")
        return self.mappings.get(name)

    def _head_fetch_meta(self, source_url: str) -> Tuple[int, Optional[str], str]:
        """Return (size, etag_or_lastmod, session_url) from HEAD.
        Expects server to include X-Session-URL header.
        """
        s = requests.Session()
        resp = s.get(source_url, allow_redirects=True, timeout=(5, 15), verify=self.verify_tls)
        if resp.status_code >= 400:
            s.close()
            raise HTTPError(f"HEAD failed {resp.status_code} for {source_url}")
        size_hdr = resp.headers.get("Content-Length")
        if not size_hdr:
            s.close()
            raise HTTPError("No Content-Length on HEAD")
        try:
            size = int(size_hdr)
        except ValueError:
            s.close()
            raise HTTPError("Invalid Content-Length")

        session_url = resp.headers.get("X-Session-URL")
        if not session_url:
            # Fallback: use final URL if header not present
            session_url = str(resp.url)
        etag = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
        # Keep this session for the handle that will use it.
        return size, etag, session_url, s

    # ------------------------------- FUSE ops -------------------------------- #

    def getattr(self, path, fh=None):
        self._reload_mappings()
        if path == "/":
            mode = stat.S_IFDIR | 0o555
            now = int(time.time())
            return {
                "st_mode": mode,
                "st_nlink": 2,
                "st_ctime": now,
                "st_mtime": now,
                "st_atime": now,
            }

        src = self._source_for_path(path)
        if not src:
            raise OSError(errno.ENOENT, "No such file", path)

        # Find or refresh meta
        name = path.lstrip("/")
        size: Optional[int] = None
        with self._meta_lock:
            meta = self.meta_cache.get(name)
            if meta:
                size = meta[0]

        if size is None:
            try:
                size, etag, _session_url, sess = self._head_fetch_meta(src)
                sess.close()
                with self._meta_lock:
                    self.meta_cache[name] = (size, etag)
            except Exception as e:
                self._log.error("HEAD meta fetch failed for %s: %s", name, e)
                raise OSError(errno.EIO, str(e))

        mode = stat.S_IFREG | 0o444
        now = int(time.time())
        return {
            "st_mode": mode,
            "st_nlink": 1,
            "st_size": size,
            "st_ctime": now,
            "st_mtime": now,
            "st_atime": now,
        }

    def readdir(self, path, fh):
        self._reload_mappings()
        if path != "/":
            raise OSError(errno.ENOENT, "No such directory", path)
        yield from [".", "..", *sorted(self.mappings.keys())]

    def open(self, path, flags):
        # Read-only enforcement
        if flags & (os.O_WRONLY | os.O_RDWR):
            raise OSError(errno.EACCES, "Read-only filesystem")

        src = self._source_for_path(path)
        if not src:
            raise OSError(errno.ENOENT, "No such file", path)

        # HEAD to obtain size and session URL
        try:
            size, etag, session_url, session = self._head_fetch_meta(src)
        except Exception as e:
            self._log.error("open() HEAD failed for %s: %s", path, e)
            raise OSError(errno.EIO, str(e))

        # Update meta cache
        with self._meta_lock:
            self.meta_cache[path.lstrip("/")] = (size, etag)

        with self._fh_lock:
            fh = self._next_fh
            self._next_fh += 1
            self._open_handles[fh] = OpenHandle(
                logical_path=path,
                source_url=src,
                session=session,
                session_url=session_url,
                size=size,
                readahead=self.readahead,
                verify_tls=self.verify_tls,
            )
            self._log.debug("Opened %s (fh=%d) session_url=%s size=%d", path, fh, session_url, size)
            return fh

    def read(self, path, size, offset, fh):
        with self._fh_lock:
            handle = self._open_handles.get(fh)
        if not handle:
            raise OSError(errno.EBADF, "Invalid file handle")
        try:
            return handle.ranged_get(offset, size)
        except HTTPError as e:
            self._log.error("HTTP read error for %s: %s", path, e)
            raise OSError(errno.EIO, str(e))
        except requests.RequestException as e:
            self._log.error("Network error for %s: %s", path, e)
            raise OSError(errno.EIO, str(e))

    # VFS is read-only; deny write ops explicitly
    def write(self, path, data, offset, fh):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def truncate(self, path, length, fh=None):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def unlink(self, path):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def rename(self, old, new):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def mkdir(self, path, mode):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def rmdir(self, path):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def chmod(self, path, mode):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def chown(self, path, uid, gid):
        raise OSError(errno.EROFS, "Read-only filesystem")

    def utimens(self, path, times=None):
        # Ignore timestamp changes to avoid errors in some clients
        return 0

    def release(self, path, fh):
        with self._fh_lock:
            handle = self._open_handles.pop(fh, None)
        if handle:
            handle.close()
        return 0

    def flush(self, path, fh):
        # No writeback
        return 0


# ---------------------------------- Main ----------------------------------- #

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="VOD virtual filesystem over HTTP with Range support")
    p.add_argument("mountpoint", help="Mount point for the FUSE filesystem")
    p.add_argument("--maps", dest="maps", default="/mnt/mappings",
                   help="Directory of mapping files (default: /mnt/mappings)")
    p.add_argument("-f", "--foreground", action="store_true", help="Run in foreground")
    p.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--insecure", action="store_true", help="Disable TLS verification")
    p.add_argument("--no-readahead", action="store_true", help="Disable read-ahead cache")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format="[%(levelname)s] %(name)s: %(message)s")

    fs = StreamFS(
        mappings_dir=args.maps,
        verify_tls=not args.insecure,
        readahead=not args.no_readahead,
    )

    # Mount options: allow other users to read, default_permissions for kernel checks
    fuse_opts = {
        "foreground": args.foreground,
        "allow_other": True,
        "ro": True,
        "default_permissions": True,
    }

    # Convert dict to FUSE option list
    mount_opts = []
    for k, v in fuse_opts.items():
        if isinstance(v, bool):
            if v:
                mount_opts.append(k)
        else:
            mount_opts.append(f"{k}={v}")

    FUSE(fs, args.mountpoint, nothreads=True, **{opt: True for opt in mount_opts})


if __name__ == "__main__":
    main()
