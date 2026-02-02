"""
Tests for VOD lifecycle events (Movie, Series, Episode).
"""
from unittest.mock import patch

from django.test import TestCase

from apps.vod.models import Movie, Series, Episode


class MovieLifecycleEventTests(TestCase):
    """Tests for movie lifecycle events via signals."""

    @patch('core.events.emit')
    def test_movie_created_event(self, mock_emit):
        """Test that vod.movie_created is emitted when a movie is created."""
        movie = Movie.objects.create(
            name='Test Movie',
            year=2024,
        )

        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.movie_created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], movie)

    @patch('core.events.emit')
    def test_movie_deleted_event(self, mock_emit):
        """Test that vod.movie_deleted is emitted when a movie is deleted."""
        movie = Movie.objects.create(
            name='Test Movie',
            year=2024,
        )
        mock_emit.reset_mock()

        movie.delete()

        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.movie_deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)


class SeriesLifecycleEventTests(TestCase):
    """Tests for series lifecycle events via signals."""

    @patch('core.events.emit')
    def test_series_created_event(self, mock_emit):
        """Test that vod.series_created is emitted when a series is created."""
        series = Series.objects.create(
            name='Test Series',
            year=2024,
        )

        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.series_created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], series)

    @patch('core.events.emit')
    def test_series_deleted_event(self, mock_emit):
        """Test that vod.series_deleted is emitted when a series is deleted."""
        series = Series.objects.create(
            name='Test Series',
            year=2024,
        )
        mock_emit.reset_mock()

        series.delete()

        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.series_deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)


class EpisodeLifecycleEventTests(TestCase):
    """Tests for episode lifecycle events via signals."""

    def setUp(self):
        self.series = Series.objects.create(
            name='Test Series',
            year=2024,
        )

    @patch('core.events.emit')
    def test_episode_created_event(self, mock_emit):
        """Test that vod.episode_created is emitted when an episode is created."""
        episode = Episode.objects.create(
            name='Test Episode',
            series=self.series,
            season_number=1,
            episode_number=1,
        )

        created_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.episode_created'
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0][0][1], episode)

    @patch('core.events.emit')
    def test_episode_deleted_event(self, mock_emit):
        """Test that vod.episode_deleted is emitted when an episode is deleted."""
        episode = Episode.objects.create(
            name='Test Episode',
            series=self.series,
            season_number=1,
            episode_number=1,
        )
        mock_emit.reset_mock()

        episode.delete()

        deleted_calls = [
            call for call in mock_emit.call_args_list
            if call[0][0] == 'vod.episode_deleted'
        ]
        self.assertEqual(len(deleted_calls), 1)
