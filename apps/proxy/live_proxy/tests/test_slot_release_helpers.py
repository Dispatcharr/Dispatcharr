"""Unit tests for GETDEL fallback and claim/restore helpers."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from redis.exceptions import ResponseError

from apps.proxy.live_proxy import slot_release
from apps.proxy.live_proxy.constants import ChannelMetadataField


class RedisGetdelTests(SimpleTestCase):
    def setUp(self):
        slot_release._getdel_unsupported = False

    def tearDown(self):
        slot_release._getdel_unsupported = False

    def test_uses_getdel_when_available(self):
        client = MagicMock()
        client.getdel.return_value = b"1"

        self.assertEqual(slot_release.redis_getdel(client, "k"), b"1")
        client.getdel.assert_called_once_with("k")
        client.get.assert_not_called()

    def test_falls_back_once_when_getdel_is_unknown(self):
        client = MagicMock()
        client.getdel.side_effect = ResponseError("unknown command `GETDEL`")
        client.get.return_value = b"9"

        with self.assertLogs(slot_release.logger.name, level="ERROR") as logs:
            value = slot_release.redis_getdel(client, "k")

        self.assertEqual(value, b"9")
        client.delete.assert_called_once_with("k")
        self.assertTrue(slot_release._getdel_unsupported)
        self.assertTrue(any("GETDEL" in line for line in logs.output))

        client.getdel.reset_mock()
        client.get.return_value = b"8"
        self.assertEqual(slot_release.redis_getdel(client, "k2"), b"8")
        client.getdel.assert_not_called()

    def test_other_response_errors_propagate(self):
        client = MagicMock()
        client.getdel.side_effect = ResponseError("OOM command not allowed")

        with self.assertRaises(ResponseError):
            slot_release.redis_getdel(client, "k")
        self.assertFalse(slot_release._getdel_unsupported)


class ClaimAndReleaseTests(SimpleTestCase):
    def test_restores_token_when_release_raises(self):
        client = MagicMock()
        client.hdel.return_value = 1
        with patch.object(
            slot_release, "release_profile_slot", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                slot_release.claim_and_release_profile_slot(
                    client,
                    "meta",
                    "12",
                    12,
                    log_label="test",
                )

        client.hset.assert_called_once_with(
            "meta",
            mapping={ChannelMetadataField.M3U_PROFILE: "12"},
        )

    def test_restores_token_when_release_is_abandoned(self):
        client = MagicMock()
        client.hdel.return_value = 1
        with patch.object(slot_release, "release_profile_slot", return_value=False):
            with self.assertLogs(slot_release.logger.name, level="WARNING") as logs:
                released = slot_release.claim_and_release_profile_slot(
                    client,
                    "meta",
                    "12",
                    12,
                    log_label="test",
                )

        self.assertFalse(released)
        client.hset.assert_called_once_with(
            "meta",
            mapping={ChannelMetadataField.M3U_PROFILE: "12"},
        )
        self.assertTrue(any("m3u_profile restored" in line for line in logs.output))
        # STREAM_ID must stay so a later teardown can still find the session.
        stream_id_clears = [
            call
            for call in client.hdel.call_args_list
            if ChannelMetadataField.STREAM_ID in call.args
        ]
        self.assertEqual(stream_id_clears, [])

    def test_abandon_without_claim_does_not_claim_restore(self):
        client = MagicMock()
        with patch.object(slot_release, "release_profile_slot", return_value=False):
            with self.assertLogs(slot_release.logger.name, level="WARNING") as logs:
                released = slot_release.claim_and_release_profile_slot(
                    client,
                    None,
                    None,
                    12,
                    log_label="test",
                )

        self.assertFalse(released)
        client.hdel.assert_not_called()
        client.hset.assert_not_called()
        self.assertTrue(any("counters may be stale" in line for line in logs.output))
        self.assertFalse(any("m3u_profile restored" in line for line in logs.output))
