"""Movie.is_adult migration backfill from relation basic_data."""

import importlib.util
from pathlib import Path

from django.db import connection
from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UMovieRelation, Movie


def _load_backfill():
    path = Path(__file__).resolve().parents[1] / "migrations" / "0005_movie_is_adult.py"
    spec = importlib.util.spec_from_file_location("vod_movie_is_adult_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.backfill_movie_is_adult


class MovieIsAdultBackfillTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Backfill XC",
            server_url="http://example.com",
            is_active=True,
        )

    def test_backfill_sets_adult_from_string_and_int_basic_data(self):
        adult_str = Movie.objects.create(name="Adult String", is_adult=False)
        adult_int = Movie.objects.create(name="Adult Int", is_adult=False)
        safe = Movie.objects.create(name="Safe Movie", is_adult=False)
        invalid = Movie.objects.create(name="Invalid Flag", is_adult=False)

        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=adult_str,
            stream_id="a1",
            custom_properties={"basic_data": {"is_adult": "1"}},
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=adult_int,
            stream_id="a2",
            custom_properties={"basic_data": {"is_adult": 1}},
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=safe,
            stream_id="s1",
            custom_properties={"basic_data": {"is_adult": 0}},
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=invalid,
            stream_id="i1",
            custom_properties={"basic_data": {"is_adult": "None"}},
        )

        class _SchemaEditor:
            connection = connection

        _load_backfill()(apps=None, schema_editor=_SchemaEditor())

        adult_str.refresh_from_db()
        adult_int.refresh_from_db()
        safe.refresh_from_db()
        invalid.refresh_from_db()

        self.assertTrue(adult_str.is_adult)
        self.assertTrue(adult_int.is_adult)
        self.assertFalse(safe.is_adult)
        self.assertFalse(invalid.is_adult)
