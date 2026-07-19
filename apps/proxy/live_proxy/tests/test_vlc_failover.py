"""Tests for VLC input-failure detection used during stream failover."""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.live_proxy.input.manager import StreamManager
from apps.proxy.live_proxy.services.log_parsers import VLCLogParser


class VLCInputFailureParserTests(TestCase):
    def test_detects_unable_to_open_mrl(self):
        parser = VLCLogParser()
        line = (
            "main input error: VLC is unable to open the MRL "
            "'http://example.com/live/1/2/3.ts'. Check the log for details."
        )
        self.assertEqual(parser.can_parse(line), "vlc_input_failed")

    def test_ignores_unrelated_vlc_lines(self):
        parser = VLCLogParser()
        line = "vlcpulse audio output error: PulseAudio server connection failure"
        self.assertIsNone(parser.can_parse(line))


class VLCInputFailureHandlingTests(TestCase):
    def test_stderr_handler_closes_connection_on_input_failure(self):
        sm = StreamManager.__new__(StreamManager)
        sm.channel_id = "test-channel"
        sm.parser_type = "vlc"
        sm.ffmpeg_input_phase = True
        sm.bytes_processed = 0
        sm.connected = True
        sm.current_stream_id = 1

        with patch.object(sm, "_close_socket") as close_socket:
            sm._log_stderr_content(
                "main input error: VLC is unable to open the MRL 'http://x'. "
                "Check the log for details."
            )

        self.assertFalse(sm.connected)
        close_socket.assert_called_once()
