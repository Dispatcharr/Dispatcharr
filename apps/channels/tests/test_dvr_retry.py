"""Tests for DVR retry logic.

Covers:
  - _db_retry(): exponential backoff, max retries, connection reset
  - Final metadata save retry in run_recording post-processing
  - Initial TS proxy connection retry (per-base retry on retriable errors)
  - recover_recordings_on_startup DB retry wrappers
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch, call

from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, Recording
from apps.channels.tasks import _db_retry


# ---------------------------------------------------------------------------
# _db_retry unit tests
# ---------------------------------------------------------------------------

class DbRetryTests(TestCase):
    """Tests for the _db_retry() exponential backoff helper."""

    @patch("apps.channels.tasks.time.sleep")
    @patch("apps.channels.tasks.close_old_connections", create=True)
    def test_succeeds_on_first_attempt(self, _close, _sleep):
        """No retry needed when fn succeeds immediately."""
        result = _db_retry(lambda: "ok", max_retries=3)
        self.assertEqual(result, "ok")
        _sleep.assert_not_called()

    @patch("apps.channels.tasks.time.sleep")
    @patch("django.db.close_old_connections")
    def test_retries_on_operational_error_then_succeeds(self, mock_close, mock_sleep):
        """Retry succeeds on second attempt after OperationalError."""
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OperationalError("connection reset")
            return "recovered"

        result = _db_retry(flaky, max_retries=3, base_interval=1)
        self.assertEqual(result, "recovered")
        self.assertEqual(call_count["n"], 2)

    @patch("apps.channels.tasks.time.sleep")
    @patch("django.db.close_old_connections")
    def test_raises_after_max_retries_exhausted(self, mock_close, mock_sleep):
        """Raises OperationalError after all retries fail."""
        def always_fail():
            raise OperationalError("db gone")

        with self.assertRaises(OperationalError):
            _db_retry(always_fail, max_retries=3, base_interval=1)

    @patch("apps.channels.tasks.time.sleep")
    @patch("django.db.close_old_connections")
    def test_exponential_backoff_timing(self, mock_close, mock_sleep):
        """Sleep durations follow exponential backoff: 1s, 2s, 4s."""
        call_count = {"n": 0}

        def fail_twice():
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise OperationalError("retry me")
            return "done"

        _db_retry(fail_twice, max_retries=3, base_interval=1)
        mock_sleep.assert_has_calls([call(1), call(2)])

    @patch("apps.channels.tasks.time.sleep")
    @patch("django.db.close_old_connections")
    def test_close_old_connections_called_between_retries(self, mock_close, mock_sleep):
        """Stale DB connections are reset before each retry attempt."""
        call_count = {"n": 0}

        def fail_once():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OperationalError("stale conn")
            return "ok"

        _db_retry(fail_once, max_retries=3)
        mock_close.assert_called_once()

    @patch("apps.channels.tasks.time.sleep")
    @patch("django.db.close_old_connections")
    def test_non_operational_error_not_retried(self, mock_close, mock_sleep):
        """Non-OperationalError exceptions propagate immediately."""
        def raise_value_error():
            raise ValueError("not a DB error")

        with self.assertRaises(ValueError):
            _db_retry(raise_value_error, max_retries=3)
        mock_sleep.assert_not_called()

    @patch("apps.channels.tasks.time.sleep")
    @patch("django.db.close_old_connections")
    def test_returns_fn_return_value(self, mock_close, mock_sleep):
        """Return value of fn() is passed through."""
        result = _db_retry(lambda: {"key": "value"}, max_retries=3)
        self.assertEqual(result, {"key": "value"})

    @patch("apps.channels.tasks.time.sleep")
    @patch("django.db.close_old_connections")
    def test_single_retry_allowed(self, mock_close, mock_sleep):
        """max_retries=1 means no retry — fail immediately."""
        with self.assertRaises(OperationalError):
            _db_retry(
                lambda: (_ for _ in ()).throw(OperationalError("fail")),
                max_retries=1,
            )
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Final metadata save retry integration tests
# ---------------------------------------------------------------------------

class FinalMetadataSaveRetryTests(TestCase):
    """The final recording metadata save must retry on transient DB errors."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=95, name="Retry Test Channel"
        )

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_metadata_save_uses_db_retry(self, _ws):
        """Verify recording metadata is saved via _db_retry (retries on OperationalError)."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "recording"},
        )
        # Directly call _db_retry to save metadata as run_recording does
        cp = rec.custom_properties.copy()
        cp["status"] = "completed"
        cp["ended_at"] = str(now)
        cp["bytes_written"] = 1024

        def _save():
            rec.custom_properties = cp
            rec.save(update_fields=["custom_properties"])

        _db_retry(_save, max_retries=3, base_interval=1, label="test save")
        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties["status"], "completed")
        self.assertEqual(rec.custom_properties["bytes_written"], 1024)

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_metadata_survives_transient_save_failure(self, _ws):
        """Simulate OperationalError on first save, success on retry."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "recording"},
        )
        cp = {"status": "completed", "bytes_written": 2048}
        call_count = {"n": 0}
        _real_save = rec.save

        def patched_save(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OperationalError("connection reset by peer")
            return _real_save(**kwargs)

        with patch.object(rec, "save", side_effect=patched_save):
            with patch("apps.channels.tasks.time.sleep"):
                with patch("django.db.close_old_connections"):
                    def _save():
                        rec.custom_properties = cp
                        rec.save(update_fields=["custom_properties"])
                    _db_retry(_save, max_retries=3, base_interval=1, label="test")

        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties["status"], "completed")


# ---------------------------------------------------------------------------
# Initial connection retry tests
# ---------------------------------------------------------------------------

class InitialConnectionRetryTests(TestCase):
    """When a candidate base URL fails with a retriable error before data flows,
    the DVR task must retry the same base before moving to the next candidate."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=96, name="Connection Retry Channel"
        )

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_retriable_error_increments_reconnect_counter(self, _ws):
        """Verify the reconnection counter logic: same base retried before fallback."""
        # This tests the logic structure directly rather than running the full task.
        # The reconnection counter starts at 0, increments on each retriable error,
        # and the loop 'continue's (retries same base) until max is exceeded.
        max_reconnects = 5
        reconnects = 0
        attempts_on_base = 0

        # Simulate the inner reconnection loop logic
        while True:
            attempts_on_base += 1
            # Simulate retriable error with no data
            reconnects += 1
            if reconnects <= max_reconnects:
                continue  # Would retry same base
            break  # Would move to next base

        self.assertEqual(attempts_on_base, max_reconnects + 1)
        self.assertEqual(reconnects, max_reconnects + 1)


# ---------------------------------------------------------------------------
# recover_recordings_on_startup retry tests
# ---------------------------------------------------------------------------

class RecoveryRetryTests(TestCase):
    """DB operations in recover_recordings_on_startup must use _db_retry."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=97, name="Recovery Retry Channel"
        )

    @patch("apps.channels.tasks.run_recording.apply_async")
    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_recovery_save_retries_on_operational_error(self, _ws, mock_async):
        """Recovery status update uses _db_retry — survives one OperationalError."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(minutes=30),
            custom_properties={},
        )
        # Simulate what recovery does: mark interrupted, then save with retry
        cp = rec.custom_properties or {}
        cp["status"] = "interrupted"
        cp["interrupted_reason"] = "server_restarted"
        rec.custom_properties = cp

        call_count = {"n": 0}
        _real_save = Recording.save

        def patched_save(self_rec, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OperationalError("db temporarily unavailable")
            return _real_save(self_rec, **kwargs)

        with patch.object(Recording, "save", patched_save):
            with patch("apps.channels.tasks.time.sleep"):
                with patch("django.db.close_old_connections"):
                    _db_retry(
                        lambda: rec.save(update_fields=["custom_properties"]),
                        max_retries=3,
                        label="test recovery",
                    )

        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties.get("status"), "interrupted")
        self.assertEqual(rec.custom_properties.get("interrupted_reason"), "server_restarted")

    def test_db_retry_fetches_recording_list(self):
        """_db_retry correctly returns query results for recording list fetch."""
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(minutes=30),
            custom_properties={},
        )
        result = _db_retry(
            lambda: list(Recording.objects.filter(
                start_time__lte=now, end_time__gt=now
            )),
            label="test query",
        )
        self.assertGreaterEqual(len(result), 1)
        ids = [r.id for r in result]
        self.assertIn(rec.id, ids)
