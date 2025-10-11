#!/usr/bin/env python3
import os
import stat
import logging
import requests
from fuse import FUSE, Operations, LoggingMixIn
from collections import OrderedDict
import time
from urllib.parse import urlparse
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# -------------------------
# Tunables for performance
# -------------------------
READ_CHUNK_BYTES   = 1024 * 256   # 256 KiB chunks pulled from upstream per read iteration
BUFFER_MAX_BYTES   = 1024 * 1024 * 8  # 8 MiB sliding window per open handle
DOWNLOAD_SLEEP_SEC = 0.0          # small pause per chunk to ease throttling (e.g., 0.01)
READ_WAIT_TIMEOUT  = 15.0         # max seconds a read waits for needed bytes to arrive
HTTP_TIMEOUT_SEC   = 20           # connect/read timeout for requests
USER_UID           = 1000         # tweak to your environment if needed
USER_GID           = 1000

class VideoStreamFS(LoggingMixIn, Operations):
    def __init__(self, source_dir):
        self.source_dir = source_dir
        self.fd_counter = 0
        self.open_files = {}
        self._global_lock = threading.Lock()
        self.cache = OrderedDict()  # (fh, offset, size) -> (data, timestamp)
        self.cache_max_items = 10
        self.cache_ttl = 5  # seconds
        self.cache_files = {}
        logging.info(f"Initialized VideoStreamFS with source_dir={source_dir}")

    # ---------- helpers ----------
    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        return os.path.join(self.source_dir, partial)

    def _head_follow(self, url):
        """
        HEAD (preferred) to follow redirects and get final URL + size.
        Fallback to GET(stream=True) if Content-Length missing.
        """
        s = requests.Session()
        r = s.head(url, allow_redirects=True, timeout=HTTP_TIMEOUT_SEC)
        r.raise_for_status()

        url_parts = urlparse(r.url)
        final_url = f'{url_parts.scheme}://{url_parts.netloc}{r.headers.get('X-Session-URL')}'

        size = r.headers.get("Content-Length")

        if size is None:
            # Fallback to GET (no Range) to fetch headers only
            gr = s.get(final_url, stream=True, allow_redirects=True, timeout=HTTP_TIMEOUT_SEC)
            try:
                gr.raise_for_status()
                size = gr.headers.get("Content-Length")
            finally:
                gr.close()

        total_size = int(size) if size is not None and size.isdigit() else 0
        return s, final_url, total_size

    def _cache_get(self, fh, offset, size):
        key = (fh, offset, size)
        entry = self.cache.get(key)
        if entry:
            data, ts = entry
            if time.time() - ts < self.cache_ttl:
                logging.info(f"Cache HIT for fh={fh} offset={offset} size={size}")
                return data
            else:
                logging.info(f"Cache EXPIRED for fh={fh} offset={offset} size={size}")
                del self.cache[key]
        return None

    def _cache_set(self, fh, offset, size, data):
        key = (fh, offset, size)
        if len(self.cache) >= self.cache_max_items:
            self.cache.popitem(last=False)  # remove oldest
        self.cache[key] = (data, time.time())
        logging.info(f"Cache SET for fh={fh} offset={offset} size={size}")

    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]  # strip leading slash
        return os.path.join(self.source_dir, partial)

    def getattr(self, path, fh=None):
        logging.info(f"GETATTR {path}")
        full_path = self._full_path(path)

        if os.path.isdir(full_path):
            st = os.lstat(full_path)
            return {
                "st_mode": stat.S_IFDIR | 0o755,
                "st_nlink": 2,
                "st_size": 0,
                "st_uid": 1000,
                "st_gid": 1000,
                "st_ctime": st.st_ctime,
                "st_mtime": st.st_mtime,
                "st_atime": st.st_atime,
            }

        if not os.path.exists(full_path):
            raise FileNotFoundError

        # For regular files, do HEAD request to get size of the redirected resource
        st = os.lstat(full_path)
        mode = stat.S_IFREG | 0o444  # read-only file

        try:
            with open(full_path, "r") as f:
                original_url = f.read().strip()

            session, final_url, size = self._head_follow(original_url)

            self.cache_files[path] = {
                "original_url": original_url,
                "url": final_url,
                "size": size,
                "session": session,
            }
        except Exception as e:
            logging.warning(f"Failed HEAD request for {path}: {e}")
            size = st.st_size

        return {
            "st_mode": mode,
            "st_nlink": 1,
            "st_size": size,
            "st_uid": 1000,
            "st_gid": 1000,
            "st_ctime": st.st_ctime,
            "st_mtime": st.st_mtime,
            "st_atime": st.st_atime,
        }

    def readdir(self, path, fh):
        logging.info(f"READDIR {path}")
        full_path = self._full_path(path)
        dirents = [".", ".."] + os.listdir(full_path)
        for r in dirents:
            yield r

    def open(self, path, flags):
        full_path = self._full_path(path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")

        # Resolve unique redirected URL & size using HEAD
        session = self.cache_files[path]["session"]
        stream_url = self.cache_files[path]["url"]
        total_size = self.cache_files[path]["size"]
        original_url = self.cache_files[path]["original_url"]

        # Allocate fh
        with self._global_lock:
            self.fd_counter += 1
            fh = self.fd_counter

        # Per-handle state
        state = {
            "session": session,            # requests.Session
            "original_url": original_url,  # stable URL from source file
            "stream_url": stream_url,      # unique redirected URL (this session only)
            "size": total_size,            # may be 0 if unknown
            "resp": None,                  # active requests.Response (stream)
            "resp_lock": threading.Lock(),

            # Sliding buffer state
            "buffer": bytearray(),
            "buf_start": 0,   # absolute offset of first byte in buffer
            "buf_end": 0,     # absolute offset *after* last byte in buffer
            "desired_offset": 0,  # where downloader should be streaming from

            "stop_event": threading.Event(),
            "have_data": threading.Condition(),  # notify readers when new bytes arrive
            "downloader": None,
        }

        # Start downloader; initial position is offset 0 (will adapt on first read)
        t = threading.Thread(target=self._downloader_loop, args=(fh,), name=f"dl-{fh}", daemon=True)
        state["downloader"] = t
        self.open_files[fh] = state
        t.start()

        logging.debug(f"OPEN {path} fh={fh} original={original_url} stream={stream_url} size={total_size}")
        return fh

    def read(self, path, size, offset, fh):
        st = self.open_files.get(fh)
        if not st:
            logging.error(f"READ on unknown fh={fh}")
            return b""

        # If requested range is outside current window, ask downloader to restart at offset
        with st["have_data"]:
            if not (st["buf_start"] <= offset < st["buf_end"] or (offset == st["buf_end"] and size == 0)):
                # Request a (re)positioning of upstream stream
                st["desired_offset"] = offset
                # Clear buffer because we'll restart at new offset
                with st["resp_lock"]:
                    st["buffer"].clear()
                    st["buf_start"] = offset
                    st["buf_end"] = offset
                st["have_data"].notify_all()

            deadline = time.time() + READ_WAIT_TIMEOUT
            # Wait until we have enough bytes or stream stopped
            while True:
                available = st["buf_end"] - offset
                if available >= size or st["stop_event"].is_set():
                    break
                # If upstream known size and offset beyond EOF, return empty
                if st["size"] and offset >= st["size"]:
                    break
                remaining = deadline - time.time()
                if remaining <= 0:
                    logging.warning(f"READ timeout fh={fh} off={offset} size={size} avail={available}")
                    break
                st["have_data"].wait(timeout=min(0.2, remaining))

            # Serve available bytes (may be partial near EOF/timeout)
            start = max(offset, st["buf_start"])
            end = min(offset + size, st["buf_end"])
            if end <= start:
                return b""

            rel_start = start - st["buf_start"]
            rel_end = end - st["buf_start"]
            out = bytes(st["buffer"][rel_start:rel_end])
            logging.debug(f"READ fh={fh} off={offset} size={size} -> returned={len(out)} "
                          f"(buf [{st['buf_start']},{st['buf_end']}) len={len(st['buffer'])})")
            return out

    def release(self, path, fh):
        st = self.open_files.pop(fh, None)
        if not st:
            return 0
        logging.debug(f"RELEASE fh={fh} stream_url discarded")
        st["stop_event"].set()
        with st["have_data"]:
            st["have_data"].notify_all()
        # Close response and session
        with st["resp_lock"]:
            try:
                if st["resp"] is not None:
                    st["resp"].close()
            except Exception:
                pass
            try:
                st["session"].close()
            except Exception:
                pass

        del self.cache_files[path]
        # Let the downloader thread exit
        return 0

    # ---------- downloader logic ----------
    def _open_stream(self, st, start_offset):
        """
        (Re)open the upstream HTTP stream at a specific offset using Range.
        """
        # Close any existing response
        with st["resp_lock"]:
            if st["resp"] is not None:
                try:
                    st["resp"].close()
                except Exception:
                    pass
                st["resp"] = None

        headers = {"Range": f"bytes={start_offset}-"}
        logging.debug(f"HTTP OPEN stream from {start_offset} url={st['stream_url']}")
        r = st["session"].get(
            st["stream_url"],
            headers=headers,
            stream=True,
            allow_redirects=False,  # IMPORTANT: keep the resolved URL (no new redirect)
            timeout=HTTP_TIMEOUT_SEC,
        )
        # Accept 206 (preferred). Some servers may return 200 (no ranges) — we can handle if start_offset==0
        if r.status_code not in (200, 206):
            try:
                r.raise_for_status()
            finally:
                r.close()

        # Parse/refresh size from Content-Range if present
        cr = r.headers.get("Content-Range")
        if cr and "/" in cr:
            try:
                total = int(cr.split("/")[-1])
                st["size"] = total
            except Exception:
                pass
        elif st["size"] == 0:
            # Try Content-Length as a fallback (represents remaining bytes from start_offset)
            try:
                rem = int(r.headers.get("Content-Length", "0"))
                if rem > 0:
                    st["size"] = start_offset + rem
            except Exception:
                pass

        with st["resp_lock"]:
            st["resp"] = r

    def _downloader_loop(self, fh):
        st = self.open_files.get(fh)
        if not st:
            return

        current_offset = 0
        # Start at desired_offset (initially 0; read() may change it)
        with st["have_data"]:
            current_offset = st["desired_offset"]

        try:
            self._open_stream(st, current_offset)
        except Exception as e:
            logging.error(f"Downloader failed to open initial stream fh={fh}: {e}")
            st["stop_event"].set()
            with st["have_data"]:
                st["have_data"].notify_all()
            return

        while not st["stop_event"].is_set():
            # Check for seek request (desired_offset changed outside current window)
            with st["have_data"]:
                desired = st["desired_offset"]
                # If desired is not the next byte to fetch, we need to restart stream at desired
                if desired != st["buf_end"]:
                    current_offset = desired
                    # Reset buffer window to new start
                    with st["resp_lock"]:
                        st["buffer"].clear()
                        st["buf_start"] = desired
                        st["buf_end"] = desired
                    try:
                        self._open_stream(st, current_offset)
                    except Exception as e:
                        logging.error(f"Downloader reopen failed fh={fh} off={desired}: {e}")
                        st["stop_event"].set()
                        st["have_data"].notify_all()
                        break

            # Pull next chunk
            try:
                with st["resp_lock"]:
                    r = st["resp"]
                if r is None:
                    # Stream closed unexpectedly; try to reopen at buf_end
                    current = st["buf_end"]
                    try:
                        self._open_stream(st, current)
                        with st["resp_lock"]:
                            r = st["resp"]
                    except Exception as e:
                        logging.error(f"Downloader reopen-after-null failed fh={fh}: {e}")
                        st["stop_event"].set()
                        with st["have_data"]:
                            st["have_data"].notify_all()
                        break

                chunk = r.raw.read(READ_CHUNK_BYTES)
                if not chunk:
                    # EOF
                    logging.debug(f"Downloader EOF fh={fh}")
                    st["stop_event"].set()
                    with st["have_data"]:
                        st["have_data"].notify_all()
                    break

                # Append chunk; enforce sliding window
                with st["have_data"]:
                    st["buffer"].extend(chunk)
                    st["buf_end"] += len(chunk)

                    if len(st["buffer"]) > BUFFER_MAX_BYTES:
                        # Evict from front
                        evict = len(st["buffer"]) - BUFFER_MAX_BYTES
                        del st["buffer"][:evict]
                        st["buf_start"] += evict

                    st["have_data"].notify_all()

                if DOWNLOAD_SLEEP_SEC > 0:
                    time.sleep(DOWNLOAD_SLEEP_SEC)

            except requests.exceptions.RequestException as e:
                logging.warning(f"Downloader network error fh={fh}: {e}; retrying shortly")
                time.sleep(0.5)
                # Try to reopen at current buf_end
                try:
                    self._open_stream(st, st["buf_end"])
                except Exception as e2:
                    logging.error(f"Downloader reopen after error failed fh={fh}: {e2}")
                    st["stop_event"].set()
                    with st["have_data"]:
                        st["have_data"].notify_all()
                    break
            except Exception as e:
                logging.error(f"Downloader unexpected error fh={fh}: {e}")
                st["stop_event"].set()
                with st["have_data"]:
                    st["have_data"].notify_all()
                break

def main(source_dir, mount_dir):
    FUSE(VideoStreamFS(source_dir), mount_dir, nothreads=True, foreground=True, ro=True, allow_other=True)

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <source_dir> <mount_dir>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
