"""XC episode lookup retains clean 404s and public selection constraints."""

from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.views import stream_xc_episode
from apps.vod.models import Episode, M3UEpisodeRelation, Series
from apps.vod.references import output_reference


class TestStreamXcEpisodeMissingRelation(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="synthetic-user", user_level=10)
        self.account = M3UAccount.objects.create(name="Synthetic provider")
        self.series = Series.objects.create(name="Synthetic series")
        self.episode = Episode.objects.create(series=self.series, name="Episode")

    def call(self, stream_id):
        request = self.factory.get(f"/series/synthetic-user/test/{stream_id}.mp4")
        with patch(
            "apps.proxy.vod_proxy.views.authorize_xc_client",
            return_value=(self.user, None),
        ):
            return stream_xc_episode(
                request, "synthetic-user", "test", str(stream_id), "mp4"
            )

    def test_missing_relation_returns_clean_404_not_500(self):
        self.assertEqual(self.call(self.episode.pk).status_code, 404)
        self.assertEqual(self.call("stale-id").status_code, 404)

    def test_valid_relation_still_streams(self):
        M3UEpisodeRelation.objects.create(
            episode=self.episode,
            m3u_account=self.account,
            stream_id="provider-id",
        )
        with patch(
            "apps.proxy.vod_proxy.views.stream_vod",
            return_value=HttpResponse("STREAMED"),
        ) as stream:
            response = self.call(self.episode.pk)
        self.assertEqual(stream.call_args.args[2], self.episode.uuid)
        self.assertFalse(stream.call_args.kwargs["check_network"])
        self.assertEqual(response.content, b"STREAMED")

    def test_selected_public_id_retains_its_requirements(self):
        M3UEpisodeRelation.objects.create(
            episode=self.episode,
            m3u_account=self.account,
            stream_id="provider-id",
        )
        reference = output_reference(
            "episode", self.episode.pk, {"audio_languages": ["ger"]}
        )
        with patch(
            "apps.proxy.vod_proxy.views.stream_vod",
            return_value=HttpResponse("STREAMED"),
        ) as stream:
            self.call(reference.legacy_id)
        self.assertEqual(stream.call_args.args[2], reference.legacy_uuid)
