from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.vod.models import Episode, M3UEpisodeRelation, Series


class XCEpisodeSelectionTests(TestCase):
    def test_relation_id_selects_and_forwards_the_exact_upstream_stream(self):
        from apps.proxy.vod_proxy.views import stream_vod as actual_stream_vod

        user = User.objects.create_user(
            username="xc-viewer",
            password="unused",
            custom_properties={"xc_password": "xc-secret"},
        )
        account = M3UAccount.objects.create(
            name="Shared provider",
            server_url="http://example.com",
            is_active=True,
        )
        series = Series.objects.create(name="Avatar")
        episode = Episode.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            name="Der Junge im Eisberg",
        )
        selected_relation = M3UEpisodeRelation.objects.create(
            m3u_account=account,
            episode=episode,
            stream_id="german-episode-1",
            container_extension="mkv",
        )
        url = reverse(
            "stream_xc_episode",
            kwargs={
                "username": user.username,
                "password": "xc-secret",
                "stream_id": str(selected_relation.id),
                "extension": "mkv",
            },
        )

        with (
            patch(
                "apps.proxy.vod_proxy.views.network_access_allowed",
                return_value=True,
            ),
            patch("core.utils.RedisClient.get_client", return_value=None),
            patch(
                "apps.proxy.vod_proxy.views.stream_vod",
                wraps=actual_stream_vod,
            ) as stream_vod,
        ):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 301)
        stream_vod.assert_called_once()
        args, kwargs = stream_vod.call_args
        self.assertEqual(args[1], "episode")
        self.assertEqual(args[2], episode.uuid)
        self.assertEqual(kwargs["preferred_m3u_account_id"], account.id)
        self.assertEqual(kwargs["preferred_stream_id"], "german-episode-1")
        self.assertIn(f"m3u_account_id={account.id}", response["Location"])
        self.assertIn("stream_id=german-episode-1", response["Location"])
