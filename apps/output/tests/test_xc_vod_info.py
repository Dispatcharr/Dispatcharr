"""XC get_vod_info artwork: relation-first with object fallback, cover_big/movie_image unified."""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_vod_info
from apps.vod.models import M3UMovieRelation, Movie, VODLogo

User = get_user_model()


class XCGetVodInfoArtworkTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='xcvoduser', password='testpass123')
        self.user.user_level = 10
        self.user.save()

        self.account = M3UAccount.objects.create(
            name='Provider A',
            server_url='http://a.example.com',
            username='a',
            password='a',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=1,
            custom_properties={'enable_vod': True},
        )
        self.movie = Movie.objects.create(name='Solo Movie', year=2020)
        self.relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            stream_id='m-1',
            last_advanced_refresh=timezone.now(),
            custom_properties={'detailed_fetched': True},
        )

    def _info(self):
        request = self.factory.get('/player_api.php')
        return xc_get_vod_info(request, self.user, str(self.movie.id))

    def test_cover_big_and_movie_image_are_identical(self):
        """Real XC servers return the same URL for both fields; clients may read either."""
        self.movie.custom_properties = {}
        self.movie.save(update_fields=['custom_properties'])
        self.relation.custom_properties = {
            'detailed_fetched': True,
            'detailed_info': {'movie_image': 'https://cdn.example.com/still.jpg'},
        }
        self.relation.save(update_fields=['custom_properties'])

        info = self._info()['info']

        self.assertEqual(info['cover_big'], info['movie_image'])
        self.assertEqual(info['cover'], info['movie_image'])
        self.assertIsNotNone(info['cover_big'])
        self.assertIn('kind=movie_image', info['cover_big'])

    def test_cover_falls_back_to_none_without_logo_or_relation_artwork(self):
        info = self._info()['info']
        self.assertIsNone(info['cover_big'])
        self.assertIsNone(info['movie_image'])

    def test_cover_prefers_relation_still_over_synced_logo(self):
        logo = VODLogo.objects.create(name='Synced', url='http://example.com/synced.png')
        self.movie.logo = logo
        self.movie.save(update_fields=['logo'])
        self.relation.custom_properties = {
            'detailed_fetched': True,
            'detailed_info': {'movie_image': 'https://cdn.example.com/still.jpg'},
        }
        self.relation.save(update_fields=['custom_properties'])

        info = self._info()['info']

        self.assertEqual(info['cover_big'], info['movie_image'])
        self.assertEqual(info['cover'], info['movie_image'])
        self.assertIn('kind=movie_image', info['cover_big'])
        self.assertNotIn(f'/{logo.id}/', info['cover_big'])

    def test_cover_falls_back_to_synced_logo_without_relation_art(self):
        logo = VODLogo.objects.create(name='Synced', url='http://example.com/synced.png')
        self.movie.logo = logo
        self.movie.save(update_fields=['logo'])

        info = self._info()['info']

        self.assertIn(f'/{logo.id}/', info['cover_big'])
        self.assertEqual(info['cover_big'], info['movie_image'])
        self.assertEqual(info['cover'], info['movie_image'])
