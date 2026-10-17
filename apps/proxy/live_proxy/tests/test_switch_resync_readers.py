"""Readers move to the new source when the channel's stream switches."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.input.buffer import StreamBuffer
from apps.proxy.live_proxy.output.buffer import OutputStreamBuffer
from apps.proxy.live_proxy.output.fmp4.generator import FMP4StreamGenerator
from apps.proxy.live_proxy.output.fmp4.manager import FMP4RemuxManager
from apps.proxy.live_proxy.output.profile.manager import OutputProfileManager
from apps.proxy.live_proxy.output.ts.generator import StreamGenerator
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis, _pkt


CHANNEL_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PIPE_SELECT = "apps.proxy.live_proxy.output.pipe_write.select"  # encoder stdin waits live here
PROFILE = "apps.proxy.live_proxy.output.profile.manager"
FMP4 = "apps.proxy.live_proxy.output.fmp4.manager"
NEW = b"NEW"
MID_C1 = b"\x47" + bytes(1879)  # one chunk of ten 188-byte packets


class _Input:
    """A real input buffer on a fake Redis; a test adds chunks and switches while a reader runs."""

    def __init__(self):
        self.redis = _FakeRedis()
        self.buffer = StreamBuffer(CHANNEL_ID, redis_client=self.redis)
        self.now = [100.0]
        self.buffer.switch_marks._clock = lambda: self.now[0]

    def add(self, *chunks):
        for data in chunks:
            self.buffer.index += 1
            self.redis.kv[f"{self.buffer.buffer_prefix}{self.buffer.index}"] = data
        self.redis.kv[self.buffer.buffer_index_key] = str(self.buffer.index)

    def switch(self):
        """Mark the next chunk as the first of a new source, as update_url does."""
        mark = self.buffer.index + 1
        self.redis.zadd(self.buffer.discontinuities_key, {str(mark): float(mark)})
        self.now[0] += 1.0  # past any cached lookup


def _profile_writer(ts, output):
    mgr = OutputProfileManager.__new__(OutputProfileManager)
    mgr.profile_id = 3
    mgr.channel_id = CHANNEL_ID
    mgr.ts_buffer = ts
    mgr.running = True
    mgr._process = MagicMock()
    mgr._write_all = MagicMock()
    mgr.output_buffer = output
    return mgr


def _fmp4_writer(ts, output):
    mgr = FMP4RemuxManager.__new__(FMP4RemuxManager)
    mgr.channel_id = CHANNEL_ID
    mgr.ts_buffer = ts
    mgr.running = True
    mgr._process = MagicMock()
    mgr._write_all = MagicMock()
    mgr.fmp4_buffer = output
    return mgr


WRITERS = [
    (_profile_writer, PROFILE, "output_buffer"),
    (_fmp4_writer, FMP4, "fmp4_buffer"),
]


def _run_writer(factory, module, out_attr, inp, on_write=None, write=None):
    """Run a writer from index 0 until a read comes back empty.

    events lists the chunks written and each output mark ("mark") in order. on_write(n)
    runs after the nth stubbed write; write replaces the stdin stub to run the real
    write path.
    """
    events, reads = [], []
    output = MagicMock()
    output.record_output_discontinuity.side_effect = lambda: events.append("mark")
    mgr = factory(inp.buffer, output)
    if write is None:
        def stub(data, stop_check=None):
            events.append(bytes(data))
            if on_write:
                on_write(sum(1 for e in events if e != "mark"))

        mgr._write_all.side_effect = stub
    else:
        del mgr._write_all  # the real write path is under test
        mgr._process.stdin.write.side_effect = lambda view: write(view, mgr)

    real_read = inp.buffer.read_client_batch

    def read(local_index):
        reads.append(local_index)
        if len(reads) > 20:
            raise RuntimeError("read limit reached: the loop did not stop")
        batch = real_read(local_index)
        if not batch.chunks:
            mgr.running = False
        return batch

    inp.buffer.read_client_batch = read
    inp.buffer.find_chunk_index_by_time = MagicMock(return_value=0)
    with patch(module + ".logger") as log, patch(module + ".time.sleep"), patch(
        PIPE_SELECT
    ) as sel, patch(module + ".ConfigHelper.new_client_behind_seconds", return_value=5):
        sel.select.return_value = ([], [], [])
        mgr._writer_loop()
    return events, reads, log, getattr(mgr, out_attr)


def _logged(log, text):
    return any(text in str(c.args[0]) for c in log.info.call_args_list)


class WriterSwitchTests(SimpleTestCase):
    def test_writer_reads_from_the_mark_and_records_one_output_mark_before_it(self):
        for factory, module, out_attr in WRITERS:
            with self.subTest(writer=module):
                inp = _Input()
                inp.add(b"O1", b"O2")
                inp.switch()
                inp.add(b"N3", b"N4")
                events, reads, _, _ = _run_writer(factory, module, out_attr, inp)
                self.assertEqual(events, ["mark", b"N3", b"N4"])
                self.assertEqual(reads, [0, 4])

    def test_no_switch_records_no_output_mark(self):
        for factory, module, out_attr in WRITERS:
            with self.subTest(writer=module):
                inp = _Input()
                inp.add(b"O1", b"O2")
                events, _, log, _ = _run_writer(factory, module, out_attr, inp)
                self.assertEqual(events, [b"O1", b"O2"])
                self.assertFalse(_logged(log, "Source switch"))

    def test_switch_during_a_batch_drops_the_rest_of_it(self):
        for factory, module, out_attr in WRITERS:
            with self.subTest(writer=module):
                inp = _Input()
                inp.add(b"O1", b"O2", b"O3")

                def on_write(n):
                    if n == 1:
                        inp.switch()
                        inp.add(b"N4")

                events, reads, log, _ = _run_writer(factory, module, out_attr, inp, on_write)
                self.assertEqual(events, [b"O1", "mark", b"N4"])
                self.assertEqual(reads, [0, 3, 4])
                self.assertTrue(_logged(log, "resuming at index 3"))

    def test_mark_at_the_start_of_a_batch_does_not_cut_it(self):
        for factory, module, out_attr in WRITERS:
            with self.subTest(writer=module):
                inp = _Input()
                inp.switch()
                inp.add(b"N1", b"N2", b"N3")
                events, _, log, _ = _run_writer(factory, module, out_attr, inp)
                self.assertEqual(events, ["mark", b"N1", b"N2", b"N3"])
                self.assertFalse(_logged(log, "resuming"))


class MidChunkStopTests(SimpleTestCase):
    """A switch while a chunk is blocked on a full pipe stops the write at a packet
    boundary. The stdin stub takes the responses in order: an int is the bytes accepted,
    None means the pipe is full (on_block runs first), and once the list is used up
    every write is accepted whole."""

    def _run(self, factory, module, out_attr, responses, on_block):
        inp = _Input()
        inp.add(MID_C1)
        it = iter(responses)
        accepted = []

        def write(view, mgr):
            r = next(it, "ALL")
            if r is None:
                on_block(inp, mgr)
                return None
            n = len(view) if r == "ALL" else min(r, len(view))
            accepted.append(bytes(view[:n]))
            return n

        events, reads, log, out = _run_writer(factory, module, out_attr, inp, write=write)
        return b"".join(accepted), events, reads, log

    def test_writer_stops_at_a_packet_boundary_and_moves_to_the_new_source(self):
        def on_block(inp, mgr):
            inp.switch()
            inp.add(NEW)

        for factory, module, out_attr in WRITERS:
            with self.subTest(writer=module):
                accepted, events, reads, log = self._run(
                    factory, module, out_attr, [100, None, 88], on_block)
                # 100 bytes, then the pipe is full: the write finishes packet one (88 more
                # bytes) and stops there. The rest of chunk 1 is never sent.
                self.assertEqual(accepted, MID_C1[:188] + NEW)
                self.assertEqual(events, ["mark"])
                self.assertEqual(reads, [0, 1, 2])
                self.assertTrue(_logged(log, "resuming at index 1"))

    def test_a_full_pipe_without_a_switch_writes_the_whole_chunk(self):
        for factory, module, out_attr in WRITERS:
            with self.subTest(writer=module):
                accepted, events, _, _ = self._run(
                    factory, module, out_attr, [564, None], lambda inp, mgr: None)
                self.assertEqual(accepted, MID_C1)
                self.assertEqual(events, [])

    def test_shutdown_during_a_blocked_write_records_no_output_mark(self):
        for factory, module, out_attr in WRITERS:
            with self.subTest(writer=module):
                def on_block(inp, mgr):
                    inp.switch()
                    inp.add(NEW)
                    mgr.running = False

                accepted, events, _, _ = self._run(
                    factory, module, out_attr, [None], on_block)
                self.assertNotIn("mark", events)
                self.assertNotIn(NEW, accepted)


def _ts_generator(buffer, resources):
    gen = StreamGenerator.__new__(StreamGenerator)
    gen.client_id = "client-1"
    gen.channel_id = CHANNEL_ID
    gen.local_index = 0
    gen.buffer = buffer
    gen.last_yield_time = 0.0
    gen.empty_reads = 0
    gen.consecutive_empty = 0
    gen.stream_start_time = 0.0
    gen.bytes_sent = 0
    gen.chunks_sent = 0
    gen.last_stats_time = 0.0
    gen.last_stats_bytes = 0
    gen.current_rate = 0.0
    gen.last_stats_write = 0.0
    gen.stats_write_interval = 1.0
    gen.last_ttl_refresh = 0.0
    gen.ttl_refresh_interval = 3
    gen.proxy_server = MagicMock(redis_client=None)
    gen._check_resources = MagicMock(side_effect=resources)
    return gen


class TSClientSwitchTests(SimpleTestCase):
    def test_client_reads_from_the_mark(self):
        inp = _Input()
        inp.add(b"O1", b"O2")
        inp.switch()
        inp.add(b"N3")
        gen = _ts_generator(inp.buffer, [True, False])
        self.assertEqual(list(gen._stream_data_generator()), [b"N3"])
        self.assertEqual(gen.local_index, 3)

    def test_switch_during_a_batch_drops_the_rest_of_it(self):
        inp = _Input()
        inp.add(b"O1", b"O2", b"O3")
        gen = _ts_generator(inp.buffer, [True, True, False])
        yielded = []
        with patch("apps.proxy.live_proxy.output.ts.generator.logger") as log:
            for chunk in gen._stream_data_generator():
                yielded.append(chunk)
                if len(yielded) == 1:
                    inp.switch()
                    inp.add(b"N4")
        self.assertEqual(yielded, [b"O1", b"N4"])
        self.assertEqual(gen.local_index, 4)
        self.assertTrue(_logged(log, "resuming at index 3"))
        # Counters count only what was actually sent.
        self.assertEqual(gen.chunks_sent, 2)
        self.assertEqual(gen.bytes_sent, 4)

    def test_mark_at_the_start_of_a_batch_does_not_cut_it(self):
        inp = _Input()
        inp.switch()
        inp.add(b"N1", b"N2")
        gen = _ts_generator(inp.buffer, [True, False])
        self.assertEqual(list(gen._stream_data_generator()), [b"N1", b"N2"])


class FMP4ClientSwitchTests(SimpleTestCase):
    def test_switch_during_a_batch_drops_the_rest_of_it(self):
        redis = _FakeRedis()
        key = RedisKeys.output_discontinuities(CHANNEL_ID, "fmp4")
        buf = OutputStreamBuffer(CHANNEL_ID, redis_client=redis, fmt="fmp4", discontinuities_key=key)
        now = [100.0]
        buf.switch_marks._clock = lambda: now[0]

        def add(index, data):
            redis.kv[RedisKeys.output_buffer_chunk(CHANNEL_ID, "fmp4", index)] = data
            redis.kv[buf.buffer_index_key] = str(index)

        for i in (1, 2, 3):
            add(i, f"O{i}".encode())
        gen = FMP4StreamGenerator.__new__(FMP4StreamGenerator)
        gen.client_id = "client-1"
        gen.channel_id = CHANNEL_ID
        gen.fmt = "fmp4"
        gen.local_index = 0
        gen.fmp4_buffer = buf
        gen.proxy_server = MagicMock(redis_client=None)
        gen.bytes_sent = 0
        gen.chunks_sent = 0
        gen.consecutive_empty = 0
        gen.last_yield_time = 0.0
        gen._check_resources = MagicMock(side_effect=[True, True, False])
        gen._is_timeout = MagicMock(return_value=False)
        yielded = []
        for chunk in gen._stream_data_generator():
            yielded.append(chunk)
            if len(yielded) == 1:
                redis.zadd(key, {"4": 4.0})
                add(4, b"N4")
                now[0] += 1.0
        self.assertEqual(yielded, [b"O1", b"N4"])
        self.assertEqual(gen.local_index, 4)
        self.assertEqual(gen.chunks_sent, 2)


class ProfileOutputKeyTests(SimpleTestCase):
    def test_output_buffer_gets_switch_key(self):
        mgr = OutputProfileManager.__new__(OutputProfileManager)
        mgr.profile_id = 3
        mgr.channel_id = CHANNEL_ID
        with patch(
            "apps.proxy.live_proxy.output.profile.manager.RedisClient"
        ):
            buf = mgr._make_buffer()
        self.assertEqual(
            buf.discontinuities_key,
            RedisKeys.output_discontinuities(CHANNEL_ID, "mpegts:p3"),
        )


class ProfileCleanupTests(SimpleTestCase):
    def test_cleanup_deletes_output_discontinuities_key(self):
        mgr = OutputProfileManager.__new__(OutputProfileManager)
        mgr.profile_id = 3
        mgr.channel_id = CHANNEL_ID
        mgr._redis = MagicMock()
        with patch(
            "apps.proxy.live_proxy.output.profile.manager.RedisClient"
        ) as client_cls:
            client_cls.get_buffer.return_value.scan.return_value = (0, [])
            mgr._cleanup_redis()
        deleted = [c.args for c in mgr._redis.delete.call_args_list]
        self.assertIn(
            RedisKeys.output_discontinuities(CHANNEL_ID, "mpegts:p3"),
            deleted[0],
        )


class ReaderFlushTests(SimpleTestCase):
    def test_reader_publishes_aged_output_bytes_and_never_flushes_input(self):
        now = [0.0]
        redis = _FakeRedis()
        output = StreamBuffer(CHANNEL_ID, redis_client=redis)
        output._clock = lambda: now[0]
        ts_buffer = MagicMock()

        mgr = OutputProfileManager.__new__(OutputProfileManager)
        mgr.profile_id = 3
        mgr.channel_id = CHANNEL_ID
        mgr.ts_buffer = ts_buffer
        mgr.output_buffer = output
        mgr.running = True
        mgr._refresh_redis_ttls = MagicMock()
        mgr._process = MagicMock()
        mgr._process.poll.return_value = None
        mgr._process.stdout.read.side_effect = [bytes(_pkt(256, 0)), bytes(_pkt(256, 1))]

        # (select ready?, clock at this step): two small reads, then two timeouts.
        steps = iter([(True, 0.0), (True, 0.0), (False, 0.3), (False, 0.6)])
        snapshots = []

        def fake_select(_r, _w, _x, _timeout):
            snapshots.append(output.index)
            step = next(steps, None)
            if step is None:
                mgr.running = False
                return ([], [], [])
            ready, now[0] = step
            if ready:
                return ([mgr._process.stdout], [], [])
            return ([], [], [])

        with patch("apps.proxy.live_proxy.output.profile.manager.select.select", side_effect=fake_select):
            mgr._reader_loop()

        # Nothing is published before the age passes; the chunk lands on the 0.6 timeout.
        self.assertEqual(snapshots, [0, 0, 0, 0, 1])
        self.assertEqual(len(redis.kv[output.buffer_prefix + "1"]), 2 * TS_PACKET_SIZE)
        ts_buffer.flush_pending.assert_not_called()
        self.assertEqual(ts_buffer.method_calls, [])

    def test_reader_publishes_aged_output_bytes_on_a_busy_stream_without_timeouts(self):
        now = [0.0]
        redis = _FakeRedis()
        output = StreamBuffer(CHANNEL_ID, redis_client=redis)
        output._clock = lambda: now[0]

        mgr = OutputProfileManager.__new__(OutputProfileManager)
        mgr.profile_id = 3
        mgr.channel_id = CHANNEL_ID
        mgr.ts_buffer = MagicMock()
        mgr.output_buffer = output
        mgr.running = True
        mgr._refresh_redis_ttls = MagicMock()
        mgr._process = MagicMock()
        mgr._process.poll.return_value = None
        mgr._process.stdout.read.side_effect = [
            bytes(_pkt(256, 0)), bytes(_pkt(256, 1)), bytes(_pkt(256, 2)),
        ]

        # Every select is ready: the publish has to come from the flush after add_chunk.
        steps = iter([0.0, 0.0, 0.6])
        snapshots = []

        def fake_select(_r, _w, _x, _timeout):
            snapshots.append(output.index)
            step = next(steps, None)
            if step is None:
                mgr.running = False
                return ([], [], [])
            now[0] = step
            return ([mgr._process.stdout], [], [])

        with patch("apps.proxy.live_proxy.output.profile.manager.select.select", side_effect=fake_select):
            mgr._reader_loop()

        self.assertEqual(snapshots, [0, 0, 0, 1])
        self.assertEqual(len(redis.kv[output.buffer_prefix + "1"]), 3 * TS_PACKET_SIZE)


class WriteAllBoundaryTests(SimpleTestCase):
    """The pipe takes pieces of its own size (4096 here, not a multiple of 188). Once a
    stop is requested the write offers bytes only up to the next packet boundary, so it
    returns within one packet of the stop and never sends the rest of the chunk."""

    WRITERS = [
        (_profile_writer, "apps.proxy.live_proxy.output.profile.manager"),
        (_fmp4_writer, "apps.proxy.live_proxy.output.fmp4.manager"),
    ]

    def _write(self, factory, module, data, responses):
        mgr = factory(MagicMock(), MagicMock())
        mgr.__dict__.pop("_write_all", None)  # the real write path is under test
        it = iter(responses)
        accepted, calls, stops = [], [], []

        def write(view):
            calls.append(len(view))
            r = next(it)  # an exhausted script raises: a write beyond the expected ones
            if r is None:
                return None
            n = min(r, len(view))
            accepted.append(bytes(view[:n]))
            return n

        def stop_check():
            stops.append(True)
            return True

        mgr._process = MagicMock()
        mgr._process.stdin.write.side_effect = write
        with patch(PIPE_SELECT) as sel:
            sel.select.return_value = ([], [], [])
            mgr._write_all(data, stop_check)
        return b"".join(accepted), calls, stops, sel.select.call_count

    def test_unaligned_stop_finishes_the_packet_and_sends_nothing_more(self):
        data = bytes(10000)
        for factory, module in self.WRITERS:
            with self.subTest(writer=module):
                # 4096 accepted, pipe full (stop fires), then the write finishes packet 22.
                written, calls, stops, selects = self._write(
                    factory, module, data, responses=[4096, None, 4096, 4096])
                self.assertEqual(len(written), 22 * TS_PACKET_SIZE)  # 4136
                self.assertEqual(calls, [10000, 5904, 40])
                self.assertEqual(len(stops), 1)
                self.assertEqual(selects, 0)

    def test_stop_exactly_on_a_boundary_returns_without_waiting(self):
        data = bytes(10000)
        for factory, module in self.WRITERS:
            with self.subTest(writer=module):
                written, calls, stops, selects = self._write(
                    factory, module, data, responses=[2 * TS_PACKET_SIZE, None, 4096])
                self.assertEqual(len(written), 2 * TS_PACKET_SIZE)
                self.assertEqual(calls, [10000, 10000 - 2 * TS_PACKET_SIZE])
                self.assertEqual(len(stops), 1)
                self.assertEqual(selects, 0)

    def test_stop_with_nothing_accepted_returns_at_once(self):
        data = bytes(10000)
        for factory, module in self.WRITERS:
            with self.subTest(writer=module):
                written, calls, stops, selects = self._write(
                    factory, module, data, responses=[None, 4096])
                self.assertEqual(written, b"")
                self.assertEqual(calls, [10000])
                self.assertEqual(selects, 0)
