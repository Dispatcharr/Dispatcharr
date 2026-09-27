"""Tests for stream attribution in Connect/plugin event payloads.

Live-proxy runtime events (buffering, failover, reconnect, error, stream
switch) must identify the stream that caused them so per-stream reliability
can be derived from persisted events and webhook/plugin payloads. See #1564.
"""

import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


CHANNEL_UUID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _stream(stream_id, name):
    stream = MagicMock()
    stream.id = stream_id
    stream.name = name
    stream.url = f"http://provider.example/{stream_id}.ts"
    stream.m3u_account.name = "Provider"
    return stream


class DispatchEventSystemAttributionTests(SimpleTestCase):
    def _dispatch(self, event_type, redis_stream_id=None, channel_missing=False, **details):
        channel = MagicMock()
        channel.id = 42
        channel.name = "BBC News"

        streams = {1234: _stream(1234, "Feed A"), 5678: _stream(5678, "Feed B")}

        def get_stream(id):
            if id not in streams:
                raise LookupError(id)
            return streams[id]

        redis = MagicMock()
        redis.get.side_effect = lambda key: (
            str(redis_stream_id).encode() if key == "channel_stream:42" and redis_stream_id else None
        )

        with patch("apps.channels.models.Channel.objects") as channel_objects, patch(
            "apps.channels.models.Stream.objects"
        ) as stream_objects, patch(
            "core.utils.RedisClient.get_client", return_value=redis
        ), patch(
            "apps.connect.utils.trigger_event"
        ) as trigger, patch(
            "django.db.close_old_connections"
        ):
            if channel_missing:
                channel_objects.get.side_effect = LookupError("no channel")
            else:
                channel_objects.get.return_value = channel
            stream_objects.get.side_effect = get_stream
            self.stream_objects = stream_objects

            from core.utils import dispatch_event_system

            dispatch_event_system(
                event_type, channel_id=CHANNEL_UUID, channel_name="Fallback Name", **details
            )

        trigger.assert_called_once()
        name, payload = trigger.call_args[0]
        self.assertEqual(name, event_type)
        return payload

    def test_stream_switch_payload_identifies_both_streams_and_reason(self):
        payload = self._dispatch(
            "stream_switch",
            previous_stream_id=1234,
            stream_id=5678,
            reason="buffering_timeout",
        )

        self.assertEqual(payload["channel_id"], str(CHANNEL_UUID))
        self.assertEqual(payload["channel_name"], "BBC News")
        self.assertEqual(payload["previous_stream_id"], 1234)
        self.assertEqual(payload["stream_id"], 5678)
        self.assertEqual(payload["stream_name"], "Feed B")
        self.assertEqual(payload["reason"], "buffering_timeout")

    def test_stream_id_falls_back_to_active_stream_and_is_included(self):
        payload = self._dispatch("channel_buffering", redis_stream_id=5678, speed=0.5)

        self.assertEqual(payload["channel_id"], str(CHANNEL_UUID))
        self.assertEqual(payload["stream_id"], 5678)
        self.assertEqual(payload["stream_name"], "Feed B")
        self.assertEqual(payload["speed"], 0.5)
        self.assertNotIn("previous_stream_id", payload)

    def test_explicit_stream_id_wins_over_active_stream(self):
        payload = self._dispatch(
            "channel_error", redis_stream_id=5678, stream_id=1234, error_type="connection_failed"
        )

        self.assertEqual(payload["stream_id"], 1234)
        self.assertEqual(payload["stream_name"], "Feed A")

    def test_zero_speed_survives_empty_key_cleanup(self):
        payload = self._dispatch("channel_buffering", stream_id=5678, speed=0.0, reason=None, note="")

        self.assertIn("speed", payload)
        self.assertEqual(payload["speed"], 0.0)
        self.assertNotIn("reason", payload)
        self.assertNotIn("note", payload)

    def test_previous_stream_details_pass_through_without_lookup(self):
        payload = self._dispatch(
            "channel_failover",
            previous_stream_id=1234,
            previous_stream_name="Feed A",
            previous_provider_name="Old Provider",
            stream_id=5678,
            reason="buffering_timeout",
        )

        self.assertEqual(payload["previous_stream_id"], 1234)
        self.assertEqual(payload["previous_stream_name"], "Feed A")
        self.assertEqual(payload["previous_provider_name"], "Old Provider")
        # Only the new stream is resolved; the previous one arrives in the details.
        self.stream_objects.get.assert_called_once_with(id=5678)

    def test_channel_id_reported_when_channel_row_is_missing(self):
        payload = self._dispatch("channel_stop", channel_missing=True)

        self.assertEqual(payload["channel_id"], str(CHANNEL_UUID))
        self.assertEqual(payload["channel_name"], "Fallback Name")
