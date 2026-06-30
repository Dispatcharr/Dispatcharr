"""
Tests for VOD provider failover (PR: "Add VOD failover logic for M3U relations").

The VOD proxy previously selected a single highest-priority relation and
returned 503 if that account was at capacity, without trying other accounts
that carry the same title. `_get_all_relations_ordered()` is the helper that
enables failover by returning ALL active relations ordered by account
priority, with the already-selected preferred relation first.

These tests cover the helper's ordering, preferred-first placement,
de-duplication, content-type handling (movie / episode / series) and its
defensive fallbacks.
"""

from unittest.mock import MagicMock, patch
from django.test import TestCase


def _rel(rel_id, priority):
    """Build a fake relation with an account of the given priority."""
    rel = MagicMock()
    rel.id = rel_id
    rel.m3u_account = MagicMock()
    rel.m3u_account.priority = priority
    return rel


class FakeRelationQuerySet:
    """Minimal stand-in for the m3u_relations manager/queryset chain.

    Records the filter/order_by calls so tests can assert the helper only
    asks for active accounts, and returns a fixed, already-ordered list.
    """

    def __init__(self, relations):
        self._relations = relations
        self.filter_kwargs = None
        self.order_by_args = None

    def filter(self, **kwargs):
        self.filter_kwargs = kwargs
        return self

    def select_related(self, *args):
        return self

    def order_by(self, *args):
        self.order_by_args = args
        return self

    def __iter__(self):
        return iter(self._relations)

    def __list__(self):
        return list(self._relations)


def _import_helper():
    """Import the helper with heavy Django model deps stubbed out."""
    import sys
    for mod in ['apps.vod.models', 'apps.m3u.models', 'core.utils']:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
    from apps.proxy.vod_proxy.views import _get_all_relations_ordered
    return _get_all_relations_ordered


class TestGetAllRelationsOrdered(TestCase):
    def setUp(self):
        self.helper = _import_helper()

    def test_preferred_relation_is_placed_first(self):
        """The already-selected relation must come first even if not top priority."""
        preferred = _rel(rel_id=2, priority=0)
        all_rels = [_rel(rel_id=1, priority=5), preferred, _rel(rel_id=3, priority=2)]

        content = MagicMock()
        content.m3u_relations = FakeRelationQuerySet(all_rels)

        result = self.helper(content, 'movie', preferred_relation=preferred)

        self.assertEqual(result[0].id, 2, "Preferred relation must be first")
        # All relations are still present
        self.assertEqual({r.id for r in result}, {1, 2, 3})

    def test_preferred_relation_not_duplicated(self):
        """If the preferred relation is also in the queryset, it must appear once."""
        preferred = _rel(rel_id=2, priority=0)
        all_rels = [preferred, _rel(rel_id=1, priority=5)]

        content = MagicMock()
        content.m3u_relations = FakeRelationQuerySet(all_rels)

        result = self.helper(content, 'movie', preferred_relation=preferred)

        ids = [r.id for r in result]
        self.assertEqual(ids.count(2), 1, "Preferred relation must not be duplicated")
        self.assertEqual(len(result), 2)

    def test_only_active_accounts_requested(self):
        """Helper must filter on active accounts only."""
        all_rels = [_rel(rel_id=1, priority=0)]
        qs = FakeRelationQuerySet(all_rels)
        content = MagicMock()
        content.m3u_relations = qs

        self.helper(content, 'movie', preferred_relation=None)

        self.assertEqual(qs.filter_kwargs, {'m3u_account__is_active': True})

    def test_no_preferred_returns_all(self):
        """Without a preferred relation, all relations are returned."""
        all_rels = [_rel(rel_id=1, priority=0), _rel(rel_id=2, priority=5)]
        content = MagicMock()
        content.m3u_relations = FakeRelationQuerySet(all_rels)

        result = self.helper(content, 'movie', preferred_relation=None)

        self.assertEqual({r.id for r in result}, {1, 2})

    def test_series_uses_first_episode_relations(self):
        """For series, relations come from the first episode."""
        episode = MagicMock()
        episode.m3u_relations = FakeRelationQuerySet([_rel(rel_id=10, priority=0)])

        series = MagicMock()
        series.episodes.first.return_value = episode

        result = self.helper(series, 'series', preferred_relation=None)

        series.episodes.first.assert_called_once()
        self.assertEqual([r.id for r in result], [10])

    def test_missing_relations_attr_falls_back_to_preferred(self):
        """If the content object has no m3u_relations, return just the preferred."""
        preferred = _rel(rel_id=4, priority=0)

        class NoRelations:
            pass

        result = self.helper(NoRelations(), 'movie', preferred_relation=preferred)

        self.assertEqual(result, [preferred])

    def test_missing_relations_attr_and_no_preferred_returns_empty(self):
        """No relations and no preferred relation must yield an empty list, not raise."""
        class NoRelations:
            pass

        result = self.helper(NoRelations(), 'movie', preferred_relation=None)

        self.assertEqual(result, [])

    def test_db_error_falls_back_to_preferred(self):
        """Any error while collecting relations must not raise; return preferred."""
        preferred = _rel(rel_id=7, priority=0)

        content = MagicMock()
        # Accessing .filter raises to simulate a DB/ORM failure
        broken_qs = MagicMock()
        broken_qs.filter.side_effect = RuntimeError("DB down")
        content.m3u_relations = broken_qs

        result = self.helper(content, 'movie', preferred_relation=preferred)

        self.assertEqual(result, [preferred])
