"""Tests for failover stream rotation order."""
from django.test import TestCase

from apps.proxy.live_proxy.url_utils import order_alternates_from_current


class AlternateStreamOrderTests(TestCase):
    def test_rotates_from_current_stream(self):
        alternates = [
            {'stream_id': 1, 'profile_id': 10},
            {'stream_id': 3, 'profile_id': 30},
            {'stream_id': 4, 'profile_id': 40},
        ]
        ordered_ids = [1, 2, 3, 4]

        result = order_alternates_from_current(alternates, ordered_ids, current_stream_id=2)

        self.assertEqual([s['stream_id'] for s in result], [3, 4, 1])

    def test_first_failover_from_primary(self):
        alternates = [
            {'stream_id': 2, 'profile_id': 20},
            {'stream_id': 3, 'profile_id': 30},
            {'stream_id': 4, 'profile_id': 40},
        ]
        ordered_ids = [1, 2, 3, 4]

        result = order_alternates_from_current(alternates, ordered_ids, current_stream_id=1)

        self.assertEqual([s['stream_id'] for s in result], [2, 3, 4])

    def test_wraps_from_last_stream(self):
        alternates = [
            {'stream_id': 1, 'profile_id': 10},
            {'stream_id': 2, 'profile_id': 20},
            {'stream_id': 3, 'profile_id': 30},
        ]
        ordered_ids = [1, 2, 3, 4]

        result = order_alternates_from_current(alternates, ordered_ids, current_stream_id=4)

        self.assertEqual([s['stream_id'] for s in result], [1, 2, 3])

    def test_skips_unavailable_streams_in_rotation(self):
        alternates = [
            {'stream_id': 4, 'profile_id': 40},
            {'stream_id': 1, 'profile_id': 10},
        ]
        ordered_ids = [1, 2, 3, 4]

        result = order_alternates_from_current(alternates, ordered_ids, current_stream_id=2)

        self.assertEqual([s['stream_id'] for s in result], [4, 1])
