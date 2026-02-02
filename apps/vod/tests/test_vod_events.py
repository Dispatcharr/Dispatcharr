"""
Tests for VOD lifecycle events (Movie, Series, Episode).
"""
from unittest.mock import patch

from django.test import TestCase

from apps.vod.models import Movie, Series, Episode


class MovieLifecycleEventTests(TestCase):
    """Tests for movie lifecycle events via signals."""

    @patch('core.events.emit')
    def test_movie_added_event(self, mock_emit):
        """Test that vod.movie_added is emitted when a movie is created."""
        movie = Movie.objects.create(
            name='Test Movie',
            year=2024,
        )

        added_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.movie_added'
        ]
        self.assertEqual(len(added_calls), 1)
        self.assertEqual(added_calls[0][0][1], movie)

    @patch('core.events.emit')
    def test_movie_removed_event(self, mock_emit):
        """Test that vod.movie_removed is emitted when a movie is deleted."""
        movie = Movie.objects.create(
            name='Test Movie',
            year=2024,
        )
        mock_emit.reset_mock()

        movie.delete()

        removed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.movie_removed'
        ]
        self.assertEqual(len(removed_calls), 1)


class SeriesLifecycleEventTests(TestCase):
    """Tests for series lifecycle events via signals."""

    @patch('core.events.emit')
    def test_series_added_event(self, mock_emit):
        """Test that vod.series_added is emitted when a series is created."""
        series = Series.objects.create(
            name='Test Series',
            year=2024,
        )

        added_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.series_added'
        ]
        self.assertEqual(len(added_calls), 1)
        self.assertEqual(added_calls[0][0][1], series)

    @patch('core.events.emit')
    def test_series_removed_event(self, mock_emit):
        """Test that vod.series_removed is emitted when a series is deleted."""
        series = Series.objects.create(
            name='Test Series',
            year=2024,
        )
        mock_emit.reset_mock()

        series.delete()

        removed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.series_removed'
        ]
        self.assertEqual(len(removed_calls), 1)


class EpisodeLifecycleEventTests(TestCase):
    """Tests for episode lifecycle events via signals."""

    def setUp(self):
        self.series = Series.objects.create(
            name='Test Series',
            year=2024,
        )

    @patch('core.events.emit')
    def test_episode_added_event(self, mock_emit):
        """Test that vod.episode_added is emitted when an episode is created."""
        episode = Episode.objects.create(
            name='Test Episode',
            series=self.series,
            season_number=1,
            episode_number=1,
        )

        added_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.episode_added'
        ]
        self.assertEqual(len(added_calls), 1)
        self.assertEqual(added_calls[0][0][1], episode)

    @patch('core.events.emit')
    def test_episode_removed_event(self, mock_emit):
        """Test that vod.episode_removed is emitted when an episode is deleted."""
        episode = Episode.objects.create(
            name='Test Episode',
            series=self.series,
            season_number=1,
            episode_number=1,
        )
        mock_emit.reset_mock()

        episode.delete()

        removed_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.episode_removed'
        ]
        self.assertEqual(len(removed_calls), 1)
