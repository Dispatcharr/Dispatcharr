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

        # Both ends must be nonblocking under gevent. os.read/os.write are not
        # monkey-patched: a blocking call freezes the whole worker. Write-end
        # backpressure is handled with select in _read_stream. The read end is
        # consumed by StreamManager.fetch_chunk via select then os.read; without
        # O_NONBLOCK, a concurrent stop that closes this fd while another channel
        # reuses the number can make that os.read block forever on an empty pipe
        # whose writer greenlet can never run.
        os.set_blocking(self.pipe_write, False)
        os.set_blocking(self.pipe_read, False)

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
