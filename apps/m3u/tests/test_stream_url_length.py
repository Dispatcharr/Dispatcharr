"""Stream URL length limits for M3U import and model storage."""
from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import ChannelGroup, Stream
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import process_m3u_batch_direct


class StreamURLLengthTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Long URL Provider",
            server_url="http://example.com/list.m3u",
        )
        self.group = ChannelGroup.objects.create(name="News")
        self.groups = {"News": self.group.id}

    def test_model_max_length_is_8192(self):
        self.assertEqual(Stream._meta.get_field("url").max_length, 8192)

    def test_import_persists_url_above_previous_4096_limit(self):
        long_url = "https://example.com/stitch/hls/channel?" + ("j" * 4100)
        self.assertGreater(len(long_url), 4096)
        self.assertLessEqual(len(long_url), 8192)

        batch = [{
            "name": "Long JWT Stream",
            "url": long_url,
            "attributes": {"group-title": "News"},
            "vlc_opts": {},
        }]
        # process_m3u_batch_direct closes all DB connections for thread workers;
        # patch that away so the TestCase connection stays usable.
        with patch("django.db.connections"):
            process_m3u_batch_direct(
                self.account.id,
                batch,
                self.groups,
                ["name", "url"],
                compiled_filters=[],
            )

        stream = Stream.objects.get(m3u_account=self.account, name="Long JWT Stream")
        self.assertEqual(stream.url, long_url)
