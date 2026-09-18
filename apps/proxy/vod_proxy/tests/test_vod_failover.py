"""
Tests for VOD provider failover (PR: "Add VOD failover logic for M3U relations").

The VOD proxy previously selected a single highest-priority relation and
returned 503 if that account was at capacity, without trying other accounts
that carry the same title.

`_get_content_and_relation()` now materialises the active, priority-ordered
relations once (single DB query) and returns that list. `_order_candidates()`
is a pure in-memory helper that moves the preferred relation to the front and
removes duplicates, so the initial connection path hits the database exactly
once. stream_vod()/head_vod() then walk the ordered list and use the first
account with spare capacity.

These tests cover the in-memory ordering helper: preferred-first placement,
de-duplication, empty-input fallbacks, and the guarantee that it performs no
database access.
"""

from unittest.mock import MagicMock, patch
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.http import HttpResponse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODAccessPolicy,
    VODCategory,
    M3UVODCategoryRelation,
)

from apps.proxy.vod_proxy.multi_worker_connection_manager import (
    MultiWorkerVODConnectionManager,
)

from apps.proxy.vod_proxy.views import (
    _build_vod_source_metadata_best_effort,
    _category_scoped_candidates,
    _order_candidates,
    _select_vod_stream,
    _session_pinned_source_key,
    stream_vod,
    stream_xc_episode,
    stream_xc_movie,
    switch_vod_source,
)


def _rel(rel_id, priority):
    rel = MagicMock()
    rel.id = rel_id
    rel.m3u_account = MagicMock()
    rel.m3u_account.priority = priority
    return rel


class TestOrderCandidates(TestCase):
    def test_preferred_relation_is_placed_first(self):
        preferred = _rel(rel_id=2, priority=0)
        candidates = [_rel(rel_id=1, priority=5), _rel(rel_id=3, priority=2), preferred]

        result = _order_candidates(candidates, preferred_relation=preferred)

        self.assertEqual(result[0].id, 2, "Preferred relation must be first")
        self.assertEqual({r.id for r in result}, {1, 2, 3})

    def test_preferred_relation_not_duplicated(self):
        preferred = _rel(rel_id=2, priority=0)
        candidates = [preferred, _rel(rel_id=1, priority=5)]

        result = _order_candidates(candidates, preferred_relation=preferred)

        ids = [r.id for r in result]
        self.assertEqual(ids.count(2), 1, "Preferred relation must not be duplicated")
        self.assertEqual(len(result), 2)

    def test_no_preferred_keeps_order(self):
        candidates = [_rel(rel_id=1, priority=0), _rel(rel_id=2, priority=5)]

        result = _order_candidates(candidates, preferred_relation=None)

        self.assertEqual([r.id for r in result], [1, 2])

    def test_empty_with_preferred_returns_preferred(self):
        preferred = _rel(rel_id=7, priority=0)

        result = _order_candidates([], preferred_relation=preferred)

        self.assertEqual(result, [preferred])

    def test_empty_without_preferred_returns_empty(self):
        result = _order_candidates([], preferred_relation=None)

        self.assertEqual(result, [])

    def test_no_database_access(self):
        """The helper must be pure in-memory: it must never touch the ORM."""
        class Boom:
            def __init__(self, rel_id, priority):
                self.id = rel_id
                self.m3u_account = MagicMock()
                self.m3u_account.priority = priority

            def __getattr__(self, name):
                if name in ('filter', 'objects', 'all', 'select_related', 'order_by'):
                    raise AssertionError(f"ORM access attempted via .{name}()")
                raise AttributeError(name)

        candidates = [Boom(1, 0), Boom(2, 5)]

        result = _order_candidates(candidates, preferred_relation=None)

        self.assertEqual([r.id for r in result], [1, 2])


class TestPlaybackMetadataIsolation(SimpleTestCase):
    @patch(
        'apps.proxy.vod_proxy.views._build_vod_source_metadata',
        side_effect=RuntimeError('optional metadata failed'),
    )
    def test_optional_metadata_failure_does_not_abort_selection(self, _metadata):
        relation = MagicMock()
        relation.id = 7
        relation.m3u_account_id = 3
        relation.stream_id = '42'
        relation.m3u_account.name = 'Provider'
        relation.category.id = 9
        relation.category.name = 'Movies'

        result = _build_vod_source_metadata_best_effort(
            'movie', MagicMock(), relation
        )

        self.assertEqual(result['relation_id'], 7)
        self.assertEqual(result['label'], 'Provider — Movies')
        self.assertEqual(result['technical_metadata'], {})


class TestLogicalSessionSourcePinning(SimpleTestCase):
    @patch('apps.proxy.vod_proxy.views._build_vod_source_metadata_best_effort')
    @patch('apps.proxy.vod_proxy.views._build_vod_stream_url')
    @patch('apps.proxy.vod_proxy.views._get_m3u_profile')
    @patch('apps.proxy.vod_proxy.views._session_pinned_source_key')
    @patch('apps.proxy.vod_proxy.views._get_content_and_relation')
    @patch('apps.vod.policies.policy_for_user')
    @patch('apps.vod.policies.ordered_candidates')
    def test_reconnect_cannot_switch_to_another_source(
        self,
        ordered_candidates,
        policy_for_user,
        get_content_and_relation,
        pinned_source_key,
        get_profile,
        build_stream_url,
        build_metadata,
    ):
        preferred = MagicMock(id=1, m3u_account_id=10, stream_id='preferred')
        preferred.m3u_account.name = 'Preferred'
        preferred.category_id = 100
        preferred.category.name = 'Preferred category'
        pinned = MagicMock(id=2, m3u_account_id=20, stream_id='pinned')
        pinned.m3u_account.name = 'Pinned'
        pinned.category_id = 200
        pinned.category.name = 'Pinned category'
        content = MagicMock()
        get_content_and_relation.return_value = (
            content,
            preferred,
            [preferred, pinned],
        )
        policy_for_user.return_value = MagicMock()
        ordered_candidates.return_value = [preferred, pinned]
        pinned_source_key.return_value = 'movie:20:pinned'
        profile = MagicMock()
        get_profile.return_value = (profile, 1)
        build_stream_url.return_value = 'https://provider/movie.mkv'
        build_metadata.return_value = {'key': 'movie:20:pinned'}

        selected = _select_vod_stream(
            'movie',
            'content-id',
            session_id='logical-session',
        )

        self.assertIs(selected['relation'], pinned)
        build_stream_url.assert_called_once_with(pinned, profile, 'movie')


class TestManualVODSourceSwitch(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = get_user_model().objects.create_user(
            username='source-switch-admin',
            user_level=10,
        )
        self.movie = Movie.objects.create(name='Switchable Movie')
        self.category = VODCategory.objects.create(
            name='Hindi Movies', category_type='movie'
        )
        self.account_a = M3UAccount.objects.create(
            name='Provider A',
            account_type=M3UAccount.Types.XC,
            server_url='https://a.example',
            username='a',
            password='secret',
        )
        self.account_b = M3UAccount.objects.create(
            name='Provider B',
            account_type=M3UAccount.Types.XC,
            server_url='https://b.example',
            username='b',
            password='secret',
        )
        self.category_relation_a = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_a,
            category=self.category,
            enabled=True,
            metadata_defaults={'audio_languages': ['hin']},
        )
        self.category_relation_b = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_b,
            category=self.category,
            enabled=True,
            metadata_defaults={'audio_languages': ['hin']},
        )
        self.current = M3UMovieRelation.objects.create(
            m3u_account=self.account_a,
            movie=self.movie,
            category=self.category,
            stream_id='current',
        )
        self.target = M3UMovieRelation.objects.create(
            m3u_account=self.account_b,
            movie=self.movie,
            category=self.category,
            stream_id='target',
        )
        self.policy = VODAccessPolicy.objects.create(
            name='Hindi compact',
            export_mode=VODAccessPolicy.ExportMode.COMPACT,
            hard_constraints={
                'required_audio_languages': ['hin'],
                'allow_unknown_metadata': False,
            },
        )

    @patch(
        'apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager.get_instance'
    )
    def test_switch_now_validates_and_queues_exact_source(self, get_manager):
        redis_client = MagicMock()
        redis_client.hgetall.return_value = {
            'content_obj_type': 'movie',
            'content_uuid': str(self.movie.uuid),
            'source_key': f'movie:{self.account_a.id}:current',
            'source_metadata': (
                '{"access_policy_id": %d, "access_policy_export_mode": "compact", '
                '"relation_id": %d}'
                % (self.policy.id, self.current.id)
            ),
            'user_id': str(self.admin.id),
        }
        manager = MagicMock(redis_client=redis_client)
        get_manager.return_value = manager
        request = self.factory.post(
            '/proxy/vod/switch_source/',
            {
                'client_id': 'logical-session',
                'relation_id': self.target.id,
                'mode': 'now',
            },
            format='json',
        )
        force_authenticate(request, user=self.admin)

        response = switch_vod_source(request)

        self.assertEqual(response.status_code, 200)
        redis_client.setex.assert_called_once()
        key, ttl, raw_payload = redis_client.setex.call_args.args
        self.assertEqual(key, 'vod_proxy:source_switch:logical-session')
        self.assertEqual(ttl, 600)
        self.assertIn(f'"relation_id":{self.target.id}', raw_payload)
        self.assertIn(
            f'"source_key":"movie:{self.account_b.id}:target"', raw_payload
        )
        manager.stop_logical_session.assert_called_once_with(
            'logical-session', reason='manual_source_switch'
        )
        manager._trigger_vod_stats_update.assert_called_once()

    @patch(
        'apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager.get_instance'
    )
    def test_switch_is_rejected_outside_compact_mode(self, get_manager):
        self.policy.export_mode = VODAccessPolicy.ExportMode.VARIANTS
        self.policy.save(update_fields=['export_mode'])
        redis_client = MagicMock()
        redis_client.hgetall.return_value = {
            'content_obj_type': 'movie',
            'content_uuid': str(self.movie.uuid),
            'source_key': f'movie:{self.account_a.id}:current',
            'source_metadata': (
                '{"access_policy_id": %d, "relation_id": %d}'
                % (self.policy.id, self.current.id)
            ),
            'user_id': str(self.admin.id),
        }
        manager = MagicMock(redis_client=redis_client)
        get_manager.return_value = manager
        request = self.factory.post(
            '/proxy/vod/switch_source/',
            {
                'client_id': 'logical-session',
                'relation_id': self.target.id,
                'mode': 'next_request',
            },
            format='json',
        )
        force_authenticate(request, user=self.admin)

        response = switch_vod_source(request)

        self.assertEqual(response.status_code, 409)
        redis_client.setex.assert_not_called()
        manager.stop_logical_session.assert_not_called()


class TestCategoryScopedCandidates(TestCase):
    def test_movie_failover_cannot_leave_selected_category(self):
        selected = _rel(rel_id=1, priority=1)
        selected.category_id = 10
        same_category = _rel(rel_id=2, priority=5)
        same_category.category_id = 10
        other_category = _rel(rel_id=3, priority=10)
        other_category.category_id = 20

        result = _category_scoped_candidates(
            'movie',
            [other_category, same_category, selected],
            selected,
        )

        self.assertEqual([relation.id for relation in result], [2, 1])

    def test_episode_failover_uses_parent_series_category(self):
        selected = _rel(rel_id=1, priority=1)
        selected.series_relation.category_id = 10
        same_category = _rel(rel_id=2, priority=5)
        same_category.series_relation.category_id = 10
        other_category = _rel(rel_id=3, priority=10)
        other_category.series_relation.category_id = 20

        result = _category_scoped_candidates(
            'episode',
            [other_category, same_category, selected],
            selected,
        )

        self.assertEqual([relation.id for relation in result], [2, 1])


class TestSourceScopedIdleSessions(SimpleTestCase):
    def setUp(self):
        self.redis = MagicMock()
        self.redis.scan.return_value = (
            0,
            ['vod_persistent_connection:existing'],
        )
        self.redis.hgetall.return_value = {
            'content_obj_type': 'movie',
            'content_uuid': 'shared-movie',
            'source_key': 'movie:1:netflix-stream',
            'client_ip': '127.0.0.1',
            'client_user_agent': 'UHF',
            'last_activity': '100',
        }
        self.redis.hget.return_value = '0'
        self.manager = MultiWorkerVODConnectionManager.__new__(
            MultiWorkerVODConnectionManager
        )
        self.manager.redis_client = self.redis

    def _find(self, source_key):
        return self.manager.find_matching_idle_session(
            content_type='movie',
            content_uuid='shared-movie',
            client_ip='127.0.0.1',
            client_user_agent='UHF',
            source_key=source_key,
        )

    def test_reuses_same_source(self):
        self.assertEqual(
            self._find('movie:1:netflix-stream'),
            'existing',
        )

    def test_rejects_other_category_source(self):
        self.assertIsNone(self._find('movie:1:nickelodeon-stream'))

    def test_reuses_matching_source_while_previous_range_is_active(self):
        self.redis.hgetall.return_value = {
            **self.redis.hgetall.return_value,
            'active_streams': '1',
        }

        self.assertEqual(self._find('movie:1:netflix-stream'), 'existing')

    @patch('core.utils.RedisClient.get_client')
    def test_session_source_key_decodes_redis_bytes(self, get_client):
        get_client.return_value.hget.return_value = b'movie:1:netflix-stream'

        self.assertEqual(
            _session_pinned_source_key('existing'),
            'movie:1:netflix-stream',
        )


class TestXCRelationPlayback(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = get_user_model().objects.create_user(
            username='xc-variant-user',
            custom_properties={'xc_password': 'secret'},
        )
        self.account = M3UAccount.objects.create(
            name='Variant Provider',
            server_url='http://example.com',
            username='provider-user',
            password='provider-pass',
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={'enable_vod': True},
        )

    @patch('apps.proxy.vod_proxy.views.stream_vod')
    @patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True)
    def test_movie_relation_id_resolves_exact_upstream_source(
        self, _mock_access, mock_stream_vod
    ):
        movie = Movie.objects.create(name='Shared Movie')
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            stream_id='upstream-movie-42',
            container_extension='mkv',
        )
        mock_stream_vod.return_value = HttpResponse(status=204)

        response = stream_xc_movie(
            self.factory.get('/movie/xc-variant-user/secret/1.mkv'),
            username=self.user.username,
            password='secret',
            stream_id=str(relation.id),
            extension='mkv',
        )

        self.assertEqual(response.status_code, 204)
        request, content_type, content_uuid = mock_stream_vod.call_args.args[:3]
        self.assertEqual(content_type, 'movie')
        self.assertEqual(content_uuid, movie.uuid)
        self.assertEqual(request.GET['m3u_account_id'], str(self.account.id))
        self.assertEqual(request.GET['stream_id'], 'upstream-movie-42')

    @patch('apps.proxy.vod_proxy.views.stream_vod')
    @patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True)
    def test_episode_relation_id_resolves_exact_upstream_source(
        self, _mock_access, mock_stream_vod
    ):
        series = Series.objects.create(name='Shared Series')
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=series,
            external_series_id='upstream-series-9',
        )
        episode = Episode.objects.create(
            series=series,
            name='Episode 1',
            season_number=1,
            episode_number=1,
        )
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=episode,
            series_relation=series_relation,
            stream_id='upstream-episode-99',
            container_extension='mkv',
        )
        mock_stream_vod.return_value = HttpResponse(status=204)

        response = stream_xc_episode(
            self.factory.get('/series/xc-variant-user/secret/1.mkv'),
            username=self.user.username,
            password='secret',
            stream_id=str(relation.id),
            extension='mkv',
        )

        self.assertEqual(response.status_code, 204)
        request, content_type, content_uuid = mock_stream_vod.call_args.args[:3]
        self.assertEqual(content_type, 'episode')
        self.assertEqual(content_uuid, episode.uuid)
        self.assertEqual(request.GET['m3u_account_id'], str(self.account.id))
        self.assertEqual(request.GET['stream_id'], 'upstream-episode-99')

    @patch('apps.proxy.vod_proxy.views.head_vod')
    @patch('apps.proxy.vod_proxy.views.network_access_allowed', return_value=True)
    def test_movie_relation_supports_external_player_head_request(
        self, _mock_access, mock_head_vod
    ):
        movie = Movie.objects.create(name='HEAD Movie')
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            stream_id='upstream-head-42',
            container_extension='mkv',
        )
        mock_head_vod.return_value = HttpResponse(status=204)

        response = stream_xc_movie(
            self.factory.head('/movie/xc-variant-user/secret/1.mkv'),
            username=self.user.username,
            password='secret',
            stream_id=str(relation.id),
            extension='mkv',
        )

        self.assertEqual(response.status_code, 204)
        request, content_type, content_uuid = mock_head_vod.call_args.args[:3]
        self.assertEqual(content_type, 'movie')
        self.assertEqual(content_uuid, movie.uuid)
        self.assertEqual(request.GET['stream_id'], 'upstream-head-42')


class TestDirectProxyHeadPlayback(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    @patch('apps.proxy.vod_proxy.views.head_vod')
    def test_direct_proxy_url_delegates_head_without_losing_source_query(
        self, mock_head_vod
    ):
        mock_head_vod.return_value = HttpResponse(status=204)
        request = self.factory.head(
            '/proxy/vod/movie/content-uuid'
            '?stream_id=607419&m3u_account_id=50'
        )

        response = stream_vod(
            request,
            content_type='movie',
            content_id='content-uuid',
        )

        self.assertEqual(response.status_code, 204)
        raw_request, content_type, content_id = mock_head_vod.call_args.args[:3]
        self.assertEqual(content_type, 'movie')
        self.assertEqual(content_id, 'content-uuid')
        self.assertEqual(raw_request.GET['stream_id'], '607419')
        self.assertEqual(raw_request.GET['m3u_account_id'], '50')
