"""StreamManager side of channel init: promote-on-chunk, latch, polling, reconnect."""

from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.init_buffer import InitBufferStatus
from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.services.channel_service import ChannelService
from apps.proxy.live_proxy.tests.test_buffer_discontinuity import _FakeRedis
from apps.proxy.live_proxy.tests.test_pipe_nonblocking_reads import (
    CHUNK_TIMEOUT,
    MANAGER_CONFIG,
    _make_manager as _make_fetch_manager,
)

CHANNEL_ID = "init-gate-channel"
READINESS = "apps.proxy.live_proxy.init_buffer.channel_init_buffer_ready"
TIMER = "apps.proxy.live_proxy.input.manager.threading.Timer"


def _status(ready, *, experimental=True):
    return InitBufferStatus(
        ready=ready,
        experimental=experimental,
        buffer_index=3,
        media_depth=6.0 if ready else 1.0,
        behind_seconds=6.0,
        min_seconds=2.0,
        max_wait_seconds=3.0,
    )


def _make_manager(redis, *, experimental=True, promoted=False):
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL_ID
    sm.running = True
    sm.stopping = False
    sm.experimental_ingest_buffer = experimental
    sm._init_buffer_promoted = promoted
    sm._buffer_check_timers = []
    sm.buffer = MagicMock(channel_id=CHANNEL_ID, redis_client=redis)
    return sm


class EvaluateInitBufferTests(SimpleTestCase):
    def setUp(self):
        self.redis = _FakeRedis()
        self.redis.hset(
            RedisKeys.channel_metadata(CHANNEL_ID),
            ChannelMetadataField.STATE,
            ChannelState.CONNECTING,
        )
        self.timer_cls = self.enterContext(patch(TIMER))
        self.promote = self.enterContext(
            patch.object(
                ChannelService,
                "promote_channel_when_buffer_ready",
                return_value=ChannelState.ACTIVE,
            )
        )
        self.sm = _make_manager(self.redis)

    def _evaluate(self, ready, *, schedule_retry):
        status = _status(ready)
        with patch(READINESS, return_value=(ready, status)) as readiness:
            result = self.sm._evaluate_init_buffer(schedule_retry=schedule_retry)
        return result, status, readiness

    def test_ready_promotes_latches_and_cancels_timers(self):
        pending = Mock()
        pending.is_alive.return_value = True
        self.sm._buffer_check_timers = [pending]

        result, status, _ = self._evaluate(True, schedule_retry=True)

        self.assertTrue(result)
        self.promote.assert_called_once_with(CHANNEL_ID, init_status=status)
        self.assertTrue(self.sm._init_buffer_promoted)
        pending.cancel.assert_called_once_with()
        self.assertEqual(self.sm._buffer_check_timers, [])
        self.timer_cls.assert_not_called()

    def test_not_ready_while_polling_schedules_a_tracked_retry(self):
        result, _status_, _ = self._evaluate(False, schedule_retry=True)

        self.assertFalse(result)
        self.promote.assert_not_called()
        self.assertFalse(self.sm._init_buffer_promoted)
        self.timer_cls.assert_called_once_with(0.5, self.sm._check_buffer_and_set_state)
        timer = self.timer_cls.return_value
        timer.start.assert_called_once_with()
        self.assertEqual(self.sm._buffer_check_timers, [timer])

    def test_not_ready_on_chunk_publish_does_not_stack_timers(self):
        result, _status_, _ = self._evaluate(False, schedule_retry=False)

        self.assertFalse(result)
        self.timer_cls.assert_not_called()
        self.assertEqual(self.sm._buffer_check_timers, [])

    def test_retry_is_not_scheduled_once_stopping(self):
        self.sm.stopping = True

        result = self.sm._evaluate_init_buffer(schedule_retry=True)

        self.assertFalse(result)
        self.timer_cls.assert_not_called()

    def test_ready_with_nothing_to_promote_retries_while_still_connecting(self):
        """Transient promote miss (Redis blip, race) must not stick forever in connecting."""
        self.promote.return_value = None

        result, _status_, _ = self._evaluate(True, schedule_retry=True)

        self.assertFalse(result)
        self.assertFalse(self.sm._init_buffer_promoted)
        self.timer_cls.assert_called_once_with(0.5, self.sm._check_buffer_and_set_state)
        self.assertEqual(self.sm._buffer_check_timers, [self.timer_cls.return_value])

    def test_ready_with_nothing_to_promote_latches_once_past_connecting(self):
        """Peer already left init: latch so chunk publishes stop checking."""
        self.promote.return_value = None
        # Entry pending check sees connecting; after promote None the finish
        # helper re-reads and sees waiting_for_clients.
        states = iter(
            [
                ChannelState.CONNECTING.encode(),
                ChannelState.WAITING_FOR_CLIENTS.encode(),
            ]
        )
        self.redis.hget = lambda key, field: next(states)

        result, _status_, _ = self._evaluate(True, schedule_retry=True)

        self.assertTrue(result)
        self.assertTrue(self.sm._init_buffer_promoted)
        self.timer_cls.assert_not_called()

    def test_chunk_publish_ready_miss_does_not_stack_timers(self):
        """schedule_retry=False must not arm a poll; the quiet poll still covers it."""
        self.promote.return_value = None

        result, _status_, _ = self._evaluate(True, schedule_retry=False)

        self.assertFalse(result)
        self.assertFalse(self.sm._init_buffer_promoted)
        self.timer_cls.assert_not_called()

    def test_state_past_init_latches_without_a_readiness_check(self):
        for state in (
            ChannelState.WAITING_FOR_CLIENTS,
            ChannelState.ACTIVE,
            ChannelState.BUFFERING,
        ):
            with self.subTest(state=state):
                self.sm._init_buffer_promoted = False
                self.redis.hset(
                    RedisKeys.channel_metadata(CHANNEL_ID),
                    ChannelMetadataField.STATE,
                    state,
                )
                with patch(READINESS) as readiness:
                    result = self.sm._evaluate_init_buffer(schedule_retry=False)

                self.assertTrue(result)
                self.assertTrue(self.sm._init_buffer_promoted)
                readiness.assert_not_called()
                self.promote.assert_not_called()

    def test_initializing_and_missing_state_still_check_readiness(self):
        for state in (ChannelState.INITIALIZING, ChannelState.CONNECTING, None):
            with self.subTest(state=state):
                metadata = RedisKeys.channel_metadata(CHANNEL_ID)
                if state is None:
                    self.redis.hdel(metadata, ChannelMetadataField.STATE)
                else:
                    self.redis.hset(metadata, ChannelMetadataField.STATE, state)

                _result, _status_, readiness = self._evaluate(
                    False, schedule_retry=False
                )

                readiness.assert_called_once()

    def test_already_promoted_does_no_work(self):
        self.sm._init_buffer_promoted = True
        self.sm.buffer = MagicMock()

        with patch(READINESS) as readiness:
            result = self.sm._evaluate_init_buffer(schedule_retry=True)

        self.assertTrue(result)
        readiness.assert_not_called()
        self.sm.buffer.redis_client.hget.assert_not_called()

    def test_not_running_does_no_work(self):
        self.sm.running = False

        with patch(READINESS) as readiness:
            result = self.sm._evaluate_init_buffer(schedule_retry=True)

        self.assertFalse(result)
        readiness.assert_not_called()
        self.timer_cls.assert_not_called()

    def test_check_buffer_and_set_state_swallows_errors(self):
        with patch.object(
            self.sm, "_evaluate_init_buffer", side_effect=RuntimeError("redis down")
        ):
            self.assertFalse(self.sm._check_buffer_and_set_state())


class SetWaitingForClientsInitGateTests(SimpleTestCase):
    """The first-connect path shares the latch and the tracked retry timer."""

    def setUp(self):
        self.redis = MagicMock()
        self.timer_cls = self.enterContext(patch(TIMER))
        self.promote = self.enterContext(
            patch.object(
                ChannelService,
                "promote_channel_when_buffer_ready",
                return_value=ChannelState.WAITING_FOR_CLIENTS,
            )
        )
        self.sm = _make_manager(self.redis)

    def _set_state(self, state):
        self.redis.hgetall.return_value = {ChannelMetadataField.STATE: state}

    def test_ready_promotes_with_status_and_latches(self):
        self._set_state(ChannelState.INITIALIZING)
        pending = Mock()
        pending.is_alive.return_value = True
        self.sm._buffer_check_timers = [pending]
        status = _status(True)

        with patch(READINESS, return_value=(True, status)):
            self.sm._set_waiting_for_clients()

        self.promote.assert_called_once_with(CHANNEL_ID, init_status=status)
        self.assertTrue(self.sm._init_buffer_promoted)
        pending.cancel.assert_called_once_with()

    def test_nothing_promoted_while_connecting_schedules_a_retry(self):
        self._set_state(ChannelState.CONNECTING)
        self.promote.return_value = None
        # Finish helper re-checks state via hget; stay in connecting.
        self.redis.hget.return_value = ChannelState.CONNECTING.encode()

        with patch(READINESS, return_value=(True, _status(True))):
            result = self.sm._set_waiting_for_clients()

        self.assertFalse(result)
        self.assertFalse(self.sm._init_buffer_promoted)
        self.timer_cls.assert_called_once_with(0.5, self.sm._check_buffer_and_set_state)

    def test_nothing_promoted_after_peer_moved_on_latches(self):
        """Promote misses because state left connecting between check and promote."""
        self._set_state(ChannelState.CONNECTING)
        self.promote.return_value = None
        # After promote, gate check sees waiting_for_clients.
        self.redis.hget.return_value = ChannelState.WAITING_FOR_CLIENTS.encode()

        with patch(READINESS, return_value=(True, _status(True))):
            result = self.sm._set_waiting_for_clients()

        self.assertTrue(result)
        self.assertTrue(self.sm._init_buffer_promoted)
        self.timer_cls.assert_not_called()

    def test_not_ready_marks_connecting_and_tracks_the_retry_timer(self):
        self._set_state(ChannelState.INITIALIZING)

        with patch(READINESS, return_value=(False, _status(False))):
            result = self.sm._set_waiting_for_clients()

        self.assertFalse(result)
        mapping = self.redis.hset.call_args.kwargs["mapping"]
        self.assertEqual(mapping[ChannelMetadataField.STATE], ChannelState.CONNECTING)
        self.timer_cls.assert_called_once_with(0.5, self.sm._check_buffer_and_set_state)
        self.assertEqual(self.sm._buffer_check_timers, [self.timer_cls.return_value])
        self.promote.assert_not_called()

    def test_state_past_connecting_latches_without_readiness(self):
        self._set_state(ChannelState.ACTIVE)

        with patch(READINESS) as readiness:
            self.sm._set_waiting_for_clients()

        readiness.assert_not_called()
        self.promote.assert_not_called()
        self.redis.hset.assert_not_called()
        self.assertTrue(self.sm._init_buffer_promoted)


class FetchChunkInitPromotionTests(SimpleTestCase):
    """Promote on the read that publishes a Redis chunk, for experimental init only."""

    class _Buffer:
        redis_client = None
        channel_id = CHANNEL_ID

        def __init__(self, *, advance=True, success=True):
            self.index = 0
            self._advance = advance
            self._success = success

        def add_chunk(self, _chunk):
            if self._advance:
                self.index += 1
            return self._success

    def _fetch(self, *, experimental=True, promoted=False, **buffer_kwargs):
        sock = MagicMock()
        sock.recv.return_value = b"x" * 188
        sock.gettimeout.return_value = 1.0
        sm = _make_fetch_manager(
            socket=sock,
            buffer=self._Buffer(**buffer_kwargs),
            experimental_ingest_buffer=experimental,
            _init_buffer_promoted=promoted,
        )
        evaluate = Mock()
        sm._evaluate_init_buffer = evaluate
        with patch(CHUNK_TIMEOUT, return_value=1.0), patch(MANAGER_CONFIG) as cfg:
            cfg.CHUNK_SIZE = 8192
            result = sm.fetch_chunk()
        return result, evaluate, sm

    def test_publishing_a_chunk_checks_init_without_stacking_timers(self):
        result, evaluate, _sm = self._fetch()

        self.assertTrue(result)
        evaluate.assert_called_once_with(schedule_retry=False)

    def test_no_new_chunk_means_no_check(self):
        result, evaluate, _sm = self._fetch(advance=False)

        self.assertTrue(result)
        evaluate.assert_not_called()

    def test_already_promoted_means_no_check(self):
        result, evaluate, _sm = self._fetch(promoted=True)

        self.assertTrue(result)
        evaluate.assert_not_called()

    def test_failed_write_means_no_check(self):
        _result, evaluate, _sm = self._fetch(success=False)

        evaluate.assert_not_called()

    def test_chunk_count_gate_keeps_polling_only(self):
        """Non-experimental behavior is unchanged: no check on chunk publish."""
        result, evaluate, _sm = self._fetch(experimental=False)

        self.assertTrue(result)
        evaluate.assert_not_called()

    def test_check_failure_does_not_drop_the_read(self):
        sock = MagicMock()
        sock.recv.return_value = b"x" * 188
        sock.gettimeout.return_value = 1.0
        sm = _make_fetch_manager(
            socket=sock,
            buffer=self._Buffer(),
            experimental_ingest_buffer=True,
            _init_buffer_promoted=False,
        )
        sm._evaluate_init_buffer = Mock(side_effect=RuntimeError("boom"))
        with patch(CHUNK_TIMEOUT, return_value=1.0), patch(MANAGER_CONFIG) as cfg:
            cfg.CHUNK_SIZE = 8192
            self.assertTrue(sm.fetch_chunk())


class ReconnectResetsInitGateTests(SimpleTestCase):
    def test_new_connection_reopens_the_gate_and_drops_the_shared_clock(self):
        redis = _FakeRedis()
        metadata = RedisKeys.channel_metadata(CHANNEL_ID)
        redis.hset(metadata, ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT, "50.0")
        sm = _make_manager(redis, promoted=True)

        sm._arm_startup_no_data_clock()

        self.assertFalse(sm._init_buffer_promoted)
        self.assertIsNone(
            redis.hget(metadata, ChannelMetadataField.INIT_MIN_BUFFER_REACHED_AT)
        )

    def test_clock_clear_failure_is_not_fatal(self):
        redis = MagicMock()
        redis.hdel.side_effect = RuntimeError("redis down")
        sm = _make_manager(redis, promoted=True)

        sm._arm_startup_no_data_clock()

        self.assertFalse(sm._init_buffer_promoted)
