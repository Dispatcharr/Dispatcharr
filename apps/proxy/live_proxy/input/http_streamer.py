"""
HTTP Stream Reader - Thread-based HTTP stream reader that writes to a pipe.
This allows us to use the same fetch_chunk() path for both transcode and HTTP
streams (live TV) and for timeshift/catch-up archives.

When *response* is supplied the reader skips connection setup and streams the
already-open ``requests.Response`` directly.  This is used by the timeshift
view which needs to cascade through multiple candidate URLs before handing
the winning response to the reader.

When *strip_ts_preamble* is True the first bytes written to the pipe are
aligned to the first MPEG-TS sync chain (0x47 at 188-byte intervals).  Some
XC servers emit PHP warnings or HTML error text before the binary stream;
strict demuxers (ExoPlayer / TiviMate) raise ``UnrecognizedInputFormat`` on
those bytes.  The live path typically receives clean TS so the flag defaults
to False, but the timeshift path enables it.
"""

import fcntl
import os
import select as _select
import threading

import requests
from requests.adapters import HTTPAdapter

from ..utils import get_logger

logger = get_logger()

# MPEG-TS sync constants (shared with timeshift views)
_TS_PACKET_SIZE = 188
_TS_SYNC_BYTE = 0x47
_TS_SYNC_SEARCH_LIMIT = 65536

# Linux fcntl constant — increase pipe buffer beyond the 64 KB default.
_F_SETPIPE_SZ = 1031
_PIPE_TARGET_SIZE = 1 << 20  # 1 MB


def find_ts_sync(buf):
    """Offset of the first MPEG-TS sync chain in *buf*, or -1.

    A valid chain needs 0x47 at offsets i, i+188 and i+376 — three sync
    bytes one packet apart (the standard demuxer probe).
    """
    end = len(buf) - 2 * _TS_PACKET_SIZE
    for i in range(0, end):
        if (
            buf[i] == _TS_SYNC_BYTE
            and buf[i + _TS_PACKET_SIZE] == _TS_SYNC_BYTE
            and buf[i + 2 * _TS_PACKET_SIZE] == _TS_SYNC_BYTE
        ):
            return i
    return -1


class HTTPStreamReader:
    """Thread-based HTTP stream reader that writes to an OS pipe.

    Parameters
    ----------
    url : str
        Provider URL (used when *response* is None to open a new connection).
    user_agent : str, optional
        User-Agent header for the upstream request.
    chunk_size : int
        Chunk size for ``iter_content`` and ``pipe_reader.read``.
    response : requests.Response, optional
        An already-open streaming response.  When provided the reader skips
        connection setup and streams this response directly.  The caller is
        responsible for having opened it with ``stream=True``.
    extra_headers : dict, optional
        Additional HTTP headers (e.g. Range) forwarded to the provider when
        *response* is None.
    strip_ts_preamble : bool
        Strip non-MPEG-TS bytes before the first 0x47 sync chain.
    """

    def __init__(
        self,
        url,
        user_agent=None,
        chunk_size=8192,
        *,
        response=None,
        extra_headers=None,
        strip_ts_preamble=False,
    ):
        self.url = url
        self.user_agent = user_agent
        self.chunk_size = chunk_size
        self._provided_response = response
        self._extra_headers = extra_headers or {}
        self._strip_ts_preamble = strip_ts_preamble
        self.session = None
        self.response = response  # may be pre-set
        self.thread = None
        self.pipe_read = None
        self.pipe_write = None
        self.running = False

    def start(self):
        """Start the HTTP stream reader thread."""
        self.pipe_read, self.pipe_write = os.pipe()

        # Grow the kernel pipe buffer from 64 KB to 1 MB so the producer
        # thread is not blocked while the consumer yields to uWSGI.  This
        # is the single biggest throughput improvement for the timeshift
        # path: it turns the producer/consumer from ping-pong alternation
        # into genuinely parallel operation.
        try:
            fcntl.fcntl(self.pipe_write, _F_SETPIPE_SZ, _PIPE_TARGET_SIZE)
        except (OSError, ValueError):
            pass  # non-Linux or unprivileged — keep 64 KB default

        # Make the write end non-blocking so that os.write() raises
        # BlockingIOError instead of stalling the OS thread when the pipe
        # buffer is full.  Without this, a full pipe blocks the entire gevent
        # worker (all greenlets freeze) because gevent does not patch
        # os.write() on pipes.
        # Skip for pre-opened responses (timeshift path) — those run in a
        # real OS thread where blocking writes are fine and the 1 MB pipe
        # buffer provides sufficient decoupling.
        if self._provided_response is None:
            flags = fcntl.fcntl(self.pipe_write, fcntl.F_GETFL)
            fcntl.fcntl(self.pipe_write, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self.running = True
        self.thread = threading.Thread(target=self._read_stream, daemon=True)
        self.thread.start()

        logger.info("Started HTTP stream reader thread for %s", self.url)
        return self.pipe_read

    # ------------------------------------------------------------------
    # Non-blocking pipe write helper
    # ------------------------------------------------------------------

    def _pipe_write_all(self, data):
        """Write *data* to the pipe, handling O_NONBLOCK + partial writes.

        Uses select() on the write fd (gevent-patched — yields to hub) to
        wait for space when the pipe is full, instead of blocking the OS
        thread.
        """
        offset = 0
        while offset < len(data) and self.running:
            try:
                n = os.write(self.pipe_write, data[offset:])
                offset += n
            except BlockingIOError:
                _, writable, _ = _select.select([], [self.pipe_write], [], 1.0)
                if not writable and not self.running:
                    return False
            except (BrokenPipeError, OSError):
                return False
        return True

    # ------------------------------------------------------------------
    # Producer thread
    # ------------------------------------------------------------------

    def _read_stream(self):
        """Thread worker: read HTTP stream → write to pipe."""
        try:
            if self._provided_response is not None:
                # Re-use the already-open response (timeshift cascade path).
                self.response = self._provided_response
            else:
                # Open a fresh connection (live TV path).
                headers = dict(self._extra_headers)
                if self.user_agent:
                    headers["User-Agent"] = self.user_agent

                logger.info("HTTP reader connecting to %s", self.url)

                self.session = requests.Session()
                adapter = HTTPAdapter(
                    max_retries=0, pool_connections=1, pool_maxsize=1,
                )
                self.session.mount("http://", adapter)
                self.session.mount("https://", adapter)

                self.response = self.session.get(
                    self.url,
                    headers=headers,
                    stream=True,
                    timeout=(5, 30),
                )

                if self.response.status_code not in (200, 206):
                    logger.error(
                        "HTTP %d from %s", self.response.status_code, self.url,
                    )
                    return

            logger.info("HTTP reader connected, streaming data…")

            # Optional TS preamble stripping — find the first MPEG-TS sync
            # chain and discard everything before it.
            synced = not self._strip_ts_preamble
            sync_buf = bytearray() if not synced else None

            chunk_count = 0
            for chunk in self.response.iter_content(chunk_size=self.chunk_size):
                if not self.running:
                    break
                if not chunk:
                    continue

                # ---- TS preamble strip logic ----
                if not synced:
                    sync_buf.extend(chunk)
                    if len(sync_buf) < 2 * _TS_PACKET_SIZE + 1:
                        continue
                    offset = find_ts_sync(sync_buf)
                    if offset >= 0:
                        chunk = bytes(sync_buf[offset:])
                        synced = True
                        sync_buf = None
                    elif len(sync_buf) >= _TS_SYNC_SEARCH_LIMIT:
                        logger.warning(
                            "Upstream produced %d bytes without TS sync "
                            "chain; passing through unmodified",
                            len(sync_buf),
                        )
                        chunk = bytes(sync_buf)
                        synced = True
                        sync_buf = None
                    else:
                        continue

                # ---- Non-blocking write to pipe ----
                if not self._pipe_write_all(chunk):
                    break

                chunk_count += 1
                if chunk_count % 1000 == 0:
                    logger.debug("HTTP reader streamed %d chunks", chunk_count)

            # Flush any remaining sync_buf that never found a chain.
            if not synced and sync_buf:
                self._pipe_write_all(bytes(sync_buf))

            logger.info("HTTP stream ended")

        except requests.exceptions.RequestException as exc:
            logger.error("HTTP reader request error: %s", exc)
        except Exception as exc:
            logger.error("HTTP reader unexpected error: %s", exc, exc_info=True)
        finally:
            self.running = False
            try:
                if self.pipe_write is not None:
                    os.close(self.pipe_write)
                    self.pipe_write = None
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def stop(self):
        """Stop the HTTP stream reader."""
        logger.info("Stopping HTTP stream reader")
        self.running = False

        if self.response:
            try:
                self.response.close()
            except Exception:
                pass

        if self.session:
            try:
                self.session.close()
            except Exception:
                pass

        if self.pipe_write is not None:
            try:
                os.close(self.pipe_write)
                self.pipe_write = None
            except OSError:
                pass

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
