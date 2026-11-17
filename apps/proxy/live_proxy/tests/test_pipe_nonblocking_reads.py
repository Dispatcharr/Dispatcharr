"""Regression tests for gevent-safe pipe reads in the live proxy.

os.read and FileIO.read are not monkey-patched. A blocking read on a pipe whose
write end is held in the same worker freezes every greenlet. Concurrent channel
stop/start can also reuse an fd number after select has already decided that
number is ready, so readers must confirm their file object is still open after
select, and treat "no data" from a nonblocking pipe as a retry, not a disconnect
or an EOF.
"""
import os
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.input.http_streamer import HTTPStreamReader
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.output.fmp4.manager import FMP4RemuxManager
from apps.proxy.live_proxy.output.pipe_restart import ProcessSlot
from apps.proxy.live_proxy.output.profile.manager import OutputProfileManager
from apps.proxy.live_proxy.utils import posix_spawn_proc

CHUNK_TIMEOUT = "apps.proxy.live_proxy.config_helper.ConfigHelper.chunk_timeout"
MANAGER_CONFIG = "apps.proxy.live_proxy.input.manager.Config"


def _is_nonblocking(fd):
    return not os.get_blocking(fd)


class NonblockingPipeSemanticsTests(SimpleTestCase):
    """The stdlib behavior the readers below depend on."""

    def test_os_read_raises_on_an_empty_nonblocking_pipe(self):
        """The deadlock signature: empty pipe, write end held open, read must not block."""
        r, w = os.pipe()
        os.set_blocking(r, False)
        try:
            with self.assertRaises(BlockingIOError):
                os.read(r, 4096)
        finally:
            os.close(r)
            os.close(w)

    def test_fileio_read_returns_none_on_an_empty_nonblocking_pipe(self):
        """FileIO.read returns None instead of raising, and b"" is the real EOF."""
        r, w = os.pipe()
        os.set_blocking(r, False)
        f = os.fdopen(r, "rb", buffering=0)
        try:
            self.assertIsNone(f.read(4096))
        finally:
            f.close()
            os.close(w)


class HTTPStreamReaderPipeFlagsTests(SimpleTestCase):
    @patch.object(HTTPStreamReader, "_read_stream", lambda self: None)
    def test_both_pipe_ends_are_nonblocking(self):
        reader = HTTPStreamReader("http://example.com/stream.ts")
        pipe_read = reader.start()
        try:
            self.assertTrue(_is_nonblocking(pipe_read))
            self.assertTrue(_is_nonblocking(reader.pipe_write))
        finally:
            reader.running = False
            if reader.pipe_write is not None:
                os.close(reader.pipe_write)
                reader.pipe_write = None
            os.close(pipe_read)


class PosixSpawnProcPipeFlagsTests(SimpleTestCase):
    def test_parent_pipe_ends_are_nonblocking(self):
        proc = posix_spawn_proc(["/bin/sleep", "30"])
        try:
            self.assertTrue(_is_nonblocking(proc.stdin.fileno()))
            self.assertTrue(_is_nonblocking(proc.stdout.fileno()))
            self.assertTrue(_is_nonblocking(proc.stderr.fileno()))
        finally:
            proc.kill()
            proc.wait(timeout=2)
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()


class _Buffer:
    def __init__(self):
        self.chunks = []
        self.redis_client = None
        self.channel_id = "test-channel"

    def add_chunk(self, chunk):
        self.chunks.append(chunk)
        return True


def _make_manager(**overrides):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = "test-channel"
    sm.running = True
    sm.connected = True
    sm.stop_requested = False
    sm.needs_stream_switch = False
    sm.last_data_time = 0.0
    sm.bytes_processed = 0
    sm.last_bytes_update = 0.0
    sm.bytes_update_interval = 60
    sm._buffer_check_timers = []
    sm.buffer = _Buffer()
    sm.socket = None
    sm._startup_switch_enabled = lambda: False
    sm._upstream_may_continue = lambda: True
    for key, value in overrides.items():
        setattr(sm, key, value)
    return sm


class FetchChunkPipeSafetyTests(SimpleTestCase):
    def _fetch(self, sm):
        with patch(CHUNK_TIMEOUT, return_value=1.0), patch(MANAGER_CONFIG) as cfg:
            cfg.CHUNK_SIZE = 8192
            return sm.fetch_chunk()

    def test_returns_false_when_socket_replaced_during_select(self):
        """A reconnect swapped self.socket while we waited, so the ready fd is not ours.

        The old FileIO is left open here, so only the identity check can reject it.
        """
        r, w = os.pipe()
        os.set_blocking(r, False)
        sock = os.fdopen(r, "rb", buffering=0)
        sm = _make_manager(socket=sock)
        replacement = MagicMock()

        def replace_during_select(rlist, _w, _x, _timeout):
            sm.socket = replacement
            return rlist, [], []

        try:
            with patch("select.select", side_effect=replace_during_select), \
                 patch("os.read") as mock_read:
                result = self._fetch(sm)

            self.assertFalse(result)
            mock_read.assert_not_called()
            self.assertIs(sm.socket, replacement)
            self.assertTrue(sm.connected)
        finally:
            sock.close()
            os.close(w)

    def test_returns_false_when_socket_closed_during_select(self):
        """_close_socket closes the FileIO before it clears self.socket."""
        r, w = os.pipe()
        os.set_blocking(r, False)
        sock = os.fdopen(r, "rb", buffering=0)
        sm = _make_manager(socket=sock)

        def close_during_select(rlist, _w, _x, _timeout):
            sock.close()
            return rlist, [], []

        try:
            with patch("select.select", side_effect=close_during_select), \
                 patch("os.read") as mock_read:
                result = self._fetch(sm)

            self.assertFalse(result)
            mock_read.assert_not_called()
        finally:
            os.close(w)

    def test_blocking_io_error_is_no_data_not_disconnect(self):
        r, w = os.pipe()
        os.set_blocking(r, False)
        sock = os.fdopen(r, "rb", buffering=0)
        sm = _make_manager(socket=sock)

        try:
            with patch("select.select", return_value=([r], [], [])), \
                 patch("os.read", side_effect=BlockingIOError):
                result = self._fetch(sm)

            self.assertFalse(result)
            self.assertTrue(sm.connected)
        finally:
            sock.close()
            os.close(w)

    def test_reads_chunk_when_socket_still_valid(self):
        r, w = os.pipe()
        os.set_blocking(r, False)
        os.set_blocking(w, False)
        sock = os.fdopen(r, "rb", buffering=0)
        sm = _make_manager(socket=sock)
        payload = b"x" * 188
        os.write(w, payload)

        try:
            result = self._fetch(sm)

            self.assertTrue(result)
            self.assertEqual(sm.buffer.chunks, [payload])
        finally:
            sock.close()
            os.close(w)


class InputStderrReaderTests(SimpleTestCase):
    def test_does_not_read_after_stderr_closed_during_select(self):
        """The cached fd number may belong to another channel's pipe by now."""
        r, w = os.pipe()
        os.set_blocking(r, False)
        stderr = os.fdopen(r, "rb", buffering=0)
        sm = _make_manager()
        sm.transcode_process = MagicMock(stderr=stderr)
        sm.stderr_reader_thread = None

        def close_during_select(rlist, _w, _x, _timeout):
            stderr.close()
            return rlist, [], []

        try:
            with patch("select.select", side_effect=close_during_select), \
                 patch("os.read") as mock_read, \
                 patch("apps.proxy.live_proxy.input.manager.close_old_connections"):
                sm._read_stderr()

            mock_read.assert_not_called()
        finally:
            os.close(w)


class StdoutNoDataIsNotEofTests(SimpleTestCase):
    """A stale select must not look like the transcoder exiting."""

    class _Proc:
        def __init__(self, reads):
            self._reads = iter(reads)
            self.stdout = self

        def poll(self):
            return None

        def read(self, _size):
            return next(self._reads)

    def test_profile_reader_keeps_going_after_none(self):
        mgr = OutputProfileManager.__new__(OutputProfileManager)
        mgr.running = True
        mgr.channel_id = "abcdefgh"
        mgr.profile_id = 1
        mgr._refresh_redis_ttls = lambda: None
        seen = []

        class Buf:
            def add_chunk(self, data):
                seen.append(data)

            def stop(self):
                seen.append(b"STOP")

        mgr.output_buffer = Buf()
        proc = self._Proc([None, b"pkt", b""])

        with patch("select.select", return_value=([proc.stdout], [], [])):
            mgr._reader_loop(ProcessSlot(proc))

        self.assertEqual(seen, [b"pkt", b"STOP"])

    def test_fmp4_reader_keeps_going_after_none(self):
        mgr = FMP4RemuxManager.__new__(FMP4RemuxManager)
        mgr.running = True
        mgr.channel_id = "abcdefgh"
        mgr._refresh_redis_ttls = lambda: None
        proc = self._Proc([None, b"", b""])

        with patch("select.select", return_value=([proc.stdout], [], [])):
            mgr._reader_loop(ProcessSlot(proc))

        # None did not end the loop. The b"" that followed it did, after both
        # reads were consumed.
        self.assertEqual(list(proc._reads), [b""])
