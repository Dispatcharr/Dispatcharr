"""Stream profile name/tvg_id tokens resolve the right values at transcode start."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelOverride, Stream
from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.input.manager import StreamManager
from core.models import StreamProfile

PROFILE_PARAMETERS = (
    "-i {streamUrl} -metadata title={channelName} -metadata tvg={tvgId}"
)


class TranscodeProfileTokenTests(TestCase):
    def setUp(self):
        self.profile = StreamProfile(
            name="Token Profile",
            command="ffmpeg",
            parameters=PROFILE_PARAMETERS,
            locked=False,
        )
        buffer = SimpleNamespace(
            channel_id="token-test", redis_client=Mock(), stopping=False,
        )
        # Reading proxy settings closes the DB connection, which would break
        # the test transaction when the manager is constructed.
        self.enterContext(
            patch.object(TSConfig, "get_proxy_settings", return_value={})
        )
        self.manager = StreamManager(
            buffer.channel_id,
            "http://example.com/stream.ts",
            buffer,
            user_agent="Mozilla/5.0",
            stream_id=1,
            worker_id="test-worker",
            channel_name="Token test",
        )
        self.enterContext(
            patch("apps.proxy.live_proxy.input.manager.close_old_connections")
        )
        # Stop after the command is built so no process is ever started.
        self.spawn = self.enterContext(
            patch("os.posix_spawn", side_effect=OSError("spawn blocked in test"))
        )

    def _spawned_argv(self):
        self.spawn.assert_called_once()
        return self.spawn.call_args.args[1]

    def _establish(self, stream_object):
        with patch(
            "apps.proxy.live_proxy.input.manager.get_stream_object",
            return_value=stream_object,
        ):
            return self.manager._establish_transcode_connection()

    def test_channel_override_name_and_tvg_id_are_used(self):
        channel = Channel.objects.create(
            channel_number=1.0,
            name="Provider Name",
            tvg_id="provider.tvg",
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=channel, name="Display Name", tvg_id="display.tvg"
        )
        # Fresh instance so the override is loaded lazily, as in production.
        fresh = Channel.objects.get(pk=channel.pk)

        with patch.object(Channel, "get_stream_profile", return_value=self.profile):
            self.assertFalse(self._establish(fresh))

        argv = self._spawned_argv()
        self.assertIn("title=Display Name", argv)
        self.assertIn("tvg=display.tvg", argv)
        self.assertNotIn("title=Provider Name", argv)
        self.assertNotIn("tvg=provider.tvg", argv)

    def test_channel_without_override_uses_channel_fields(self):
        channel = Channel.objects.create(
            channel_number=2.0, name="Plain Name", tvg_id="plain.tvg"
        )
        fresh = Channel.objects.get(pk=channel.pk)

        with patch.object(Channel, "get_stream_profile", return_value=self.profile):
            self.assertFalse(self._establish(fresh))

        argv = self._spawned_argv()
        self.assertIn("title=Plain Name", argv)
        self.assertIn("tvg=plain.tvg", argv)

    def test_channel_without_tvg_id_substitutes_empty_value(self):
        channel = Channel.objects.create(channel_number=3.0, name="No Tvg")
        fresh = Channel.objects.get(pk=channel.pk)

        with patch.object(Channel, "get_stream_profile", return_value=self.profile):
            self.assertFalse(self._establish(fresh))

        argv = self._spawned_argv()
        self.assertIn("title=No Tvg", argv)
        self.assertIn("tvg=", argv)

    def test_stream_preview_uses_stream_name_and_tvg_id(self):
        stream = Stream(name="Preview Stream", tvg_id="preview.tvg")

        with patch.object(Stream, "get_stream_profile", return_value=self.profile):
            self.assertFalse(self._establish(stream))

        argv = self._spawned_argv()
        self.assertIn("title=Preview Stream", argv)
        self.assertIn("tvg=preview.tvg", argv)
