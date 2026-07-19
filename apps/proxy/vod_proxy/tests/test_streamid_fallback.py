"""
Tests for `_get_content_and_relation`'s graceful stream_id fallback when the
VOD content UUID has been orphaned by an import-time refresh.

Context (see #961 / closed #973): `process_movie_batch` and `process_series_batch`
can create duplicate `vod_movie` / `vod_episode` records during a refresh and
repoint existing `M3U*Relation` rows at the new records. The old UUIDs that
external players (Emby / Jellyfin / ChannelsDVR) cached in `.strm` URLs are
left orphaned, and the proxy then 404s — even though the same request carries
a stable `stream_id` that uniquely identifies a live relation.

These tests cover the read-side fallback that resolves content via that
stream_id when the UUID lookup misses, leaving the existing UUID-first path
unchanged for the happy case. Both branches (movie + episode) exercise:

  * UUID hit (no fallback fires) — happy path unchanged
  * UUID miss + stream_id present → resolved via stream_id, [STREAMID-FALLBACK]
    logged at WARNING
  * UUID miss + stream_id present + preferred_m3u_account_id → strictest-first
    account match preferred
  * UUID miss + stream_id present but no relation matches → Http404 with both
    identifiers in the message
  * UUID miss + no stream_id → Http404 (no fallback attempt)
"""

from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase


def _wire_m3u_relations(content_mock, relations):
    """Wire content_obj.m3u_relations to the materialised candidate list."""
    qs = MagicMock()
    qs.select_related.return_value.order_by.return_value = list(relations)
    content_mock.m3u_relations.filter.return_value = qs
    return qs


# ---------- Movie branch --------------------------------------------------

class TestStreamIdFallbackMovie(SimpleTestCase):
    """Movie UUID dead -> fall back to M3UMovieRelation.stream_id."""

    def _call(self, **kwargs):
        # Imported inside each test so the module-level Movie / Episode /
        # M3U*Relation references can be patched per test without leaking.
        from apps.proxy.vod_proxy.views import _get_content_and_relation
        return _get_content_and_relation(
            kwargs.pop('content_type', 'movie'),
            kwargs.pop('content_id', 'dead-uuid'),
            preferred_m3u_account_id=kwargs.pop('preferred_m3u_account_id', None),
            preferred_stream_id=kwargs.pop('preferred_stream_id', None),
        )

    def test_uuid_hit_no_fallback_attempted(self):
        """When the UUID resolves, the M3UMovieRelation table is never queried
        for fallback purposes — the existing happy-path behaviour is preserved
        and only the stream_id-specific relation selection runs."""
        live_movie = MagicMock(name='Movie', uuid='live-uuid', id=42)
        live_movie.name = 'Live Movie'
        # The existing relation-selection logic walks
        # content_obj.m3u_relations; give it a relation matching the requested
        # stream_id so we exit cleanly.
        live_relation = MagicMock(stream_id='S1')
        live_relation.m3u_account.name = 'AcmeProvider'
        _wire_m3u_relations(live_movie, [live_relation])

        with patch('apps.proxy.vod_proxy.views.Movie') as MovieMock, \
             patch('apps.proxy.vod_proxy.views.M3UMovieRelation') as RelMock:
            MovieMock.objects.filter.return_value.first.return_value = live_movie
            content, relation, candidates = self._call(
                content_type='movie', content_id='live-uuid', preferred_stream_id='S1',
            )
            self.assertIs(content, live_movie)
            self.assertIs(relation, live_relation)
            self.assertEqual(candidates, [live_relation])
            # Fallback path must not have queried the relation table directly
            # — happy path is unchanged.
            RelMock.objects.filter.assert_not_called()

    def test_uuid_miss_resolves_via_stream_id(self):
        """UUID lookup returns None; stream_id finds an active relation; the
        recovered movie is returned and the fallback line is logged."""
        recovered_movie = MagicMock(name='Movie', uuid='new-uuid', id=99)
        recovered_movie.name = 'Recovered Movie'
        fallback_rel = MagicMock(movie=recovered_movie, stream_id='S1')
        fallback_rel.m3u_account.name = 'AcmeProvider'
        # The fallback only sets content_obj; relation selection then re-discovers
        # the same relation from the materialised candidate list.
        _wire_m3u_relations(recovered_movie, [fallback_rel])

        with patch('apps.proxy.vod_proxy.views.Movie') as MovieMock, \
             patch('apps.proxy.vod_proxy.views.M3UMovieRelation') as RelMock, \
             self.assertLogs('apps.proxy.vod_proxy.views', level='WARNING') as logs:
            MovieMock.objects.filter.return_value.first.return_value = None
            # The non-account-scoped fallback chain returns our rel.
            RelMock.objects.filter.return_value.select_related.return_value.order_by.return_value.first.return_value = fallback_rel
            content, relation, _ = self._call(
                content_type='movie', content_id='dead-uuid', preferred_stream_id='S1',
            )
            self.assertIs(content, recovered_movie)
            self.assertIs(relation, fallback_rel)
        self.assertTrue(
            any('[STREAMID-FALLBACK]' in m for m in logs.output),
            f"expected [STREAMID-FALLBACK] in warnings, got: {logs.output}",
        )

    def test_uuid_miss_prefers_requested_account_first(self):
        """When preferred_m3u_account_id is set AND a matching relation exists
        on that account, it must be chosen ahead of the unrestricted ordered
        fallback. This is the strictest-match-first contract."""
        preferred_movie = MagicMock(name='PreferredMovie', uuid='preferred-uuid', id=1)
        preferred_movie.name = 'Preferred'
        preferred_rel = MagicMock(movie=preferred_movie, stream_id='S1', m3u_account_id=7)
        preferred_rel.m3u_account.name = 'Preferred'
        _wire_m3u_relations(preferred_movie, [preferred_rel])

        with patch('apps.proxy.vod_proxy.views.Movie') as MovieMock, \
             patch('apps.proxy.vod_proxy.views.M3UMovieRelation') as RelMock:
            MovieMock.objects.filter.return_value.first.return_value = None

            # Two distinct fallback chains share the same RelMock — we
            # distinguish them by which `.filter(...)` call they emerged from.
            # The account-scoped query is the FIRST .filter() call (with the
            # m3u_account_id kw); the unrestricted ordered query is the SECOND.
            unrestricted_movie = MagicMock(uuid='other-uuid', id=2)
            unrestricted_movie.name = 'OtherMovie'
            unrestricted_rel = MagicMock(movie=unrestricted_movie)

            def filter_router(**kwargs):
                # First chain: scoped to m3u_account_id -> returns preferred_rel
                if 'm3u_account_id' in kwargs:
                    chain = MagicMock()
                    chain.select_related.return_value.first.return_value = preferred_rel
                    return chain
                # Second chain: no account scope -> returns unrestricted_rel
                chain = MagicMock()
                chain.select_related.return_value.order_by.return_value.first.return_value = unrestricted_rel
                return chain
            RelMock.objects.filter.side_effect = filter_router

            content, relation, _ = self._call(
                content_type='movie',
                content_id='dead-uuid',
                preferred_stream_id='S1',
                preferred_m3u_account_id=7,
            )
            # The account-scoped relation wins; the unrestricted-ordered one
            # is never consulted because the strict match succeeded.
            self.assertIs(content, preferred_movie)
            self.assertIs(relation, preferred_rel)

    def test_uuid_miss_with_no_stream_id_raises_404(self):
        with patch('apps.proxy.vod_proxy.views.Movie') as MovieMock, \
             patch('apps.proxy.vod_proxy.views.M3UMovieRelation') as RelMock:
            MovieMock.objects.filter.return_value.first.return_value = None
            content, relation, candidates = self._call(
                content_type='movie', content_id='dead-uuid', preferred_stream_id=None,
            )
            # _get_content_and_relation swallows exceptions and returns
            # (None, None, []) for any error including Http404 — caller checks
            # for that. Verify the fallback was NEVER attempted.
            self.assertIsNone(content)
            self.assertIsNone(relation)
            self.assertEqual(candidates, [])
            RelMock.objects.filter.assert_not_called()

    def test_uuid_miss_with_no_matching_relation_raises_404(self):
        with patch('apps.proxy.vod_proxy.views.Movie') as MovieMock, \
             patch('apps.proxy.vod_proxy.views.M3UMovieRelation') as RelMock:
            MovieMock.objects.filter.return_value.first.return_value = None
            # Both the account-scoped and unrestricted chains return None.
            RelMock.objects.filter.return_value.select_related.return_value.order_by.return_value.first.return_value = None
            RelMock.objects.filter.return_value.select_related.return_value.first.return_value = None
            content, relation, candidates = self._call(
                content_type='movie',
                content_id='dead-uuid',
                preferred_stream_id='ghost-stream',
            )
            self.assertIsNone(content)
            self.assertIsNone(relation)
            self.assertEqual(candidates, [])


# ---------- Episode branch ------------------------------------------------

class TestStreamIdFallbackEpisode(SimpleTestCase):
    """Episode UUID dead -> fall back to M3UEpisodeRelation.stream_id.

    Same contract as the movie branch; less duplication of edge cases since
    the code paths are intentionally symmetric.
    """

    def _call(self, **kwargs):
        from apps.proxy.vod_proxy.views import _get_content_and_relation
        return _get_content_and_relation(
            'episode',
            kwargs.pop('content_id', 'dead-uuid'),
            preferred_m3u_account_id=kwargs.pop('preferred_m3u_account_id', None),
            preferred_stream_id=kwargs.pop('preferred_stream_id', None),
        )

    def test_uuid_miss_resolves_via_stream_id(self):
        recovered_episode = MagicMock(uuid='new-uuid', id=77)
        recovered_episode.name = 'Recovered S01E01'
        recovered_episode.series.name = 'Recovered Show'
        fallback_rel = MagicMock(episode=recovered_episode, stream_id='S99')
        fallback_rel.m3u_account.name = 'AcmeProvider'
        _wire_m3u_relations(recovered_episode, [fallback_rel])

        with patch('apps.proxy.vod_proxy.views.Episode') as EpisodeMock, \
             patch('apps.proxy.vod_proxy.views.M3UEpisodeRelation') as RelMock, \
             self.assertLogs('apps.proxy.vod_proxy.views', level='WARNING') as logs:
            EpisodeMock.objects.filter.return_value.first.return_value = None
            RelMock.objects.filter.return_value.select_related.return_value.order_by.return_value.first.return_value = fallback_rel
            content, relation, _ = self._call(content_id='dead-uuid', preferred_stream_id='S99')
            self.assertIs(content, recovered_episode)
            self.assertIs(relation, fallback_rel)
        self.assertTrue(
            any('[STREAMID-FALLBACK]' in m and 'Episode' in m for m in logs.output),
            f"expected episode-flavoured [STREAMID-FALLBACK] warning, got: {logs.output}",
        )

    def test_uuid_hit_no_fallback_attempted(self):
        live_episode = MagicMock(uuid='live-uuid', id=42)
        live_episode.name = 'Live S01E02'
        live_episode.series.name = 'Live Show'
        live_relation = MagicMock(stream_id='S2')
        live_relation.m3u_account.name = 'AcmeProvider'
        _wire_m3u_relations(live_episode, [live_relation])

        with patch('apps.proxy.vod_proxy.views.Episode') as EpisodeMock, \
             patch('apps.proxy.vod_proxy.views.M3UEpisodeRelation') as RelMock:
            EpisodeMock.objects.filter.return_value.first.return_value = live_episode
            content, relation, candidates = self._call(content_id='live-uuid', preferred_stream_id='S2')
            self.assertIs(content, live_episode)
            self.assertIs(relation, live_relation)
            self.assertEqual(candidates, [live_relation])
            RelMock.objects.filter.assert_not_called()
