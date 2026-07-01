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

from unittest.mock import MagicMock
from django.test import TestCase

from apps.proxy.vod_proxy.views import _order_candidates


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
