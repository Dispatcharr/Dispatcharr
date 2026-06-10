"""
HTTP Stream Reader - Thread-based HTTP stream reader that writes to a pipe.
This allows us to use the same fetch_chunk() path for both transcode and HTTP streams.
"""

import threading
import os
import requests
from requests.adapters import HTTPAdapter
from ..utils import get_logger

logger = get_logger()


class HTTPStreamReader:
    """Thread-based HTTP stream reader that writes to a pipe"""

    def __init__(self, url, user_agent=None, chunk_size=8192):
        self.url = url
        self.user_agent = user_agent
        self.chunk_size = chunk_size
        self.session = None
        self.response = None
        self.thread = None
        self.pipe_read = None
        self.pipe_write = None
        self.running = False

    def start(self):
        """Start the HTTP stream reader thread"""
        self.pipe_read, self.pipe_write = os.pipe()

        # Make the write end non-blocking so that os.write() raises BlockingIOError
        # instead of stalling the OS thread when the pipe buffer is full. Without
        # this, a full pipe blocks the entire gevent worker (all greenlets freeze)
        # because gevent does not patch os.write() on pipes.
        import fcntl
        flags = fcntl.fcntl(self.pipe_write, fcntl.F_GETFL)
        fcntl.fcntl(self.pipe_write, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self.running = True
        self.thread = threading.Thread(target=self._read_stream, daemon=True)
        self.thread.start()

        logger.info(f"Started HTTP stream reader thread for {self.url}")
        return self.pipe_read

    def _read_stream(self):
        """Thread worker that reads HTTP stream and writes to pipe"""
        try:
            # Build headers
            headers = {}
            if self.user_agent:
                headers['User-Agent'] = self.user_agent

            logger.info(f"HTTP reader connecting to {self.url}")

            # Create session
            self.session = requests.Session()

            # Disable retries for faster failure detection
            adapter = HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1)
            self.session.mount('http://', adapter)
            self.session.mount('https://', adapter)

            # Stream the URL
            self.response = self.session.get(
                self.url,
                headers=headers,
                stream=True,
                timeout=(5, 30)  # 5s connect, 30s read
            )

            if self.response.status_code != 200:
                logger.error(f"HTTP {self.response.status_code} from {self.url}")
                return

            logger.info(f"HTTP reader connected successfully, streaming data...")

            import select as _select

            # Stream chunks to pipe
            chunk_count = 0
            for chunk in self.response.iter_content(chunk_size=self.chunk_size):
                if not self.running:
                    break

                if chunk:
                    # Write the chunk in a non-blocking loop. The pipe write end is
                    # set O_NONBLOCK in start(), so os.write() raises BlockingIOError
                    # instead of stalling the OS thread. We use select.select on the
                    # write fd (gevent-patched - yields to hub) to wait for space,
                    # then retry. Partial writes are handled by advancing the offset.
                    offset = 0
                    write_error = False
                    while offset < len(chunk) and self.running:
                        try:
                            n = os.write(self.pipe_write, chunk[offset:])
                            offset += n
                        except BlockingIOError:
                            _, writable, _ = _select.select([], [self.pipe_write], [], 1.0)
                            if not writable and not self.running:
                                write_error = True
                                break
                        except OSError as e:
                            logger.error(f"Pipe write error: {e}")
                            write_error = True
                            break
                    if write_error:
                        break

                    chunk_count += 1
                    if chunk_count % 1000 == 0:
                        logger.debug(f"HTTP reader streamed {chunk_count} chunks")

            logger.info("HTTP stream ended")

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP reader request error: {e}")
        except Exception as e:
            logger.error(f"HTTP reader unexpected error: {e}", exc_info=True)
        finally:
            self.running = False
            # Close write end of pipe to signal EOF
            try:
                if self.pipe_write is not None:
                    os.close(self.pipe_write)
                    self.pipe_write = None
            except:
                pass

    def stop(self):
        """Stop the HTTP stream reader"""
        logger.info("Stopping HTTP stream reader")
        self.running = False

        # Close response
        if self.response:
            try:
                self.response.close()
            except:
                pass

        # Close session
        if self.session:
            try:
                self.session.close()
            except:
                pass

        # Close write end of pipe
        if self.pipe_write is not None:
            try:
                os.close(self.pipe_write)
                self.pipe_write = None
            except:
                pass

        # Wait for thread
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# MPEG-TS sync detection (used by the timeshift catch-up proxy)
# ---------------------------------------------------------------------------

_TS_PACKET_SIZE = 188
_TS_SYNC_BYTE = 0x47


def find_ts_sync(buf):
    """Offset of the first MPEG-TS sync chain in *buf*, or -1.

    A valid chain needs 0x47 at offsets i, i+188 and i+376 — three sync
    bytes one packet apart (the standard demuxer probe).  The timeshift
    proxy peeks at the first upstream bytes with this to reject HTTP-200
    PHP error pages and to strip any pre-sync preamble before the bytes
    reach a strict demuxer (ExoPlayer).
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
