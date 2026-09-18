"""XC get_vod_info artwork: relation-first with object fallback, cover_big/movie_image unified."""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_vod_info
from apps.vod.models import M3UMovieRelation, Movie, VODAccessPolicy, VODLogo
from apps.vod.profile_selection import build_vod_profile_selection

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
        return xc_get_vod_info(request, self.user, str(self.relation.id))

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
        # Keep the logo primary key distinct from the movie primary key used in
        # the relation-art proxy URL so the assertion below is unambiguous.
        VODLogo.objects.create(name='Unused', url='http://example.com/unused.png')
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

    def test_tmdb_id_uses_the_selected_provider_source_override(self):
        self.movie.tmdb_id = '100'
        self.movie.tmdb_match_id = '100'
        self.movie.save(update_fields=['tmdb_id', 'tmdb_match_id'])
        self.relation.tmdb_override_id = '200'
        self.relation.save(update_fields=['tmdb_override_id'])

        info = self._info()['info']

        self.assertEqual(info['tmdb_id'], '200')

    def test_curated_variants_keep_provider_name_but_not_provider_plot(self):
        policy = VODAccessPolicy.objects.create(
            name='Curated variants detail',
            export_mode=VODAccessPolicy.ExportMode.VARIANTS,
            metadata_source=VODAccessPolicy.MetadataSource.CANONICAL,
            naming_mode=VODAccessPolicy.NamingMode.PROVIDER,
            hard_constraints={'allow_unknown_metadata': True},
        )
        policy.users.add(self.user)
        self.movie.display_name = 'Clean Solo Movie'
        self.movie.tmdb_metadata = {
            'localized': {
                'en-US': {
                    'title': 'Clean Solo Movie',
                    'overview': 'Curated plot',
                }
            },
            'release_date': '2020-06-01',
            'rating': 7.4,
            'genres': [{'id': 1, 'name': 'Drama'}],
            'director': 'Curated Director',
            'actors': 'Curated Actor',
            'crew': 'Curated Producer (Producer)',
            'country': 'United States of America',
            'age_rating': 'PG-13',
            'youtube_trailer': 'curated-trailer',
        }
        self.movie.save(update_fields=['display_name', 'tmdb_metadata'])
        self.relation.custom_properties = {
            'detailed_fetched': True,
            'basic_data': {'name': 'PROVIDER - Solo Movie'},
            'detailed_info': {
                'name': 'Provider detail title',
                'plot': 'Provider plot',
                'rating': 2,
            },
        }
        self.relation.save(update_fields=['custom_properties'])
        build_vod_profile_selection(policy.id)

        info = self._info()['info']

        self.assertEqual(info['name'], 'PROVIDER - Solo Movie')
        self.assertEqual(info['plot'], 'Curated plot')
        self.assertEqual(info['genre'], 'Drama')
        self.assertEqual(info['rating'], 7.4)
        self.assertEqual(info['director'], 'Curated Director')
        self.assertEqual(info['actors'], 'Curated Actor')
        self.assertEqual(info['crew'], 'Curated Producer (Producer)')
        self.assertEqual(info['country'], 'United States of America')
        self.assertEqual(info['age'], 'PG-13')
        self.assertEqual(info['youtube_trailer'], 'curated-trailer')
