"""Library account choices follow stored VOD sources and viewing permissions."""

from django.test import TestCase, override_settings

from apps.m3u.models import M3UAccount
from apps.vod import library
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
)

from . import test_library as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryAccountOptionTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint

    def options(self, **filters):
        response = self.client.get(self.endpoint("filter-options"), filters)
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"] for row in response.json()["accounts"]}

    def test_active_accounts_without_vod_sources_are_not_offered(self):
        empty = M3UAccount.objects.create(name="test-m3u", is_active=True)
        custom = M3UAccount.get_custom_account()
        custom.is_active = True
        custom.save()
        self.assertEqual(self.options(), {self.account.pk})
        self.assertNotIn(empty.pk, self.options())
        self.assertNotIn(custom.pk, self.options())

    def test_choices_follow_movie_series_and_disabled_content_types(self):
        account = M3UAccount.objects.create(name="Series only", is_active=True)
        series = Series.objects.create(name="Series")
        M3USeriesRelation.objects.create(
            m3u_account=account, series=series, external_series_id="1"
        )
        self.assertEqual(self.options(), {self.account.pk, account.pk})
        self.assertEqual(self.options(type="movie"), {self.account.pk})
        self.assertEqual(self.options(type="series"), {account.pk})
        self.user.custom_properties = {"vod_movies_enabled": False}
        self.user.save()
        self.client.force_authenticate(self.user)
        self.assertEqual(self.options(), {account.pk})
        self.assertEqual(self.options(type="movie"), set())

    def test_source_existence_not_account_name_or_type_decides(self):
        account = M3UAccount.objects.create(
            name="Standard with stored VOD",
            account_type=M3UAccount.Types.STADNARD,
            is_active=True,
        )
        M3UMovieRelation.objects.create(
            movie=self.movie, m3u_account=account, stream_id="1"
        )
        self.assertEqual(self.options(), {self.account.pk, account.pk})
        account.is_active = False
        account.save()
        self.assertEqual(self.options(), {self.account.pk})

    def test_hidden_adult_only_accounts_are_not_leaked(self):
        account = M3UAccount.objects.create(name="Adult only", is_active=True)
        movie = Movie.objects.create(name="Adult", is_adult=True)
        M3UMovieRelation.objects.create(movie=movie, m3u_account=account, stream_id="1")
        self.assertIn(account.pk, self.options())
        self.user.custom_properties = {"hide_adult_content": True}
        self.user.save()
        self.client.force_authenticate(self.user)
        self.assertEqual(self.options(), {self.account.pk})

    def test_current_account_filter_does_not_remove_other_choices(self):
        account = M3UAccount.objects.create(name="Second provider", is_active=True)
        M3UMovieRelation.objects.create(
            movie=self.movie, m3u_account=account, stream_id="1"
        )
        self.assertEqual(
            self.options(account=self.account.pk), {self.account.pk, account.pk}
        )

    def test_totals_count_visible_titles_independent_of_filters(self):
        series = Series.objects.create(name="Series")
        M3USeriesRelation.objects.create(
            m3u_account=self.account, series=series, external_series_id="1"
        )
        blocked = Movie.objects.create(name="Blocked", library_blocked=True)
        M3UMovieRelation.objects.create(
            movie=blocked, m3u_account=self.account, stream_id="2"
        )
        response = self.client.get(
            self.endpoint("filter-options"), {"type": "movie", "account": self.account.pk}
        )
        self.assertEqual(response.json()["totals"], {"movie": 2, "series": 1})
        self.client.force_authenticate(self.user)
        response = self.client.get(self.endpoint("filter-options"))
        self.assertEqual(response.json()["totals"], {"movie": 1, "series": 1})

    def test_available_accounts_use_one_database_query(self):
        with self.assertNumQueries(1):
            rows = library.available_accounts({}, ["movie", "series"])
        self.assertEqual([row["id"] for row in rows], [self.account.pk])


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibrarySeriesResolutionTests(TestCase):
    """Provider episode resolutions follow the source metadata precedence."""

    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint

    def add_series(self, name, *, height=None, manual=None):
        category, _ = VODCategory.objects.get_or_create(
            name="Series", category_type="series"
        )
        M3UVODCategoryRelation.objects.get_or_create(
            m3u_account=self.account,
            category=category,
            defaults={"enabled": True, "metadata_defaults": {"resolution": "1080p"}},
        )
        series = Series.objects.create(name=name)
        relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=series,
            category=category,
            external_series_id=name,
            manual_metadata={"resolution": manual} if manual else {},
        )
        if height:
            episode = Episode.objects.create(
                series=series, name=f"{name} S01E01", season_number=1, episode_number=1
            )
            M3UEpisodeRelation.objects.create(
                m3u_account=self.account,
                episode=episode,
                series_relation=relation,
                stream_id=f"{name}-1",
                custom_properties={"info": {"video": {"height": height}}},
            )
        return series

    def rows(self, **filters):
        response = self.client.get(self.endpoint(), {"type": "series", **filters})
        self.assertEqual(response.status_code, 200, response.data)
        return {row["name"]: row for row in response.json()["results"]}

    def test_episode_resolution_replaces_only_an_inherited_category_value(self):
        self.add_series("Episodes", height=720)
        self.add_series("Manual", height=720, manual="2160p")
        self.add_series("Category only")
        rows = self.rows()
        self.assertEqual(rows["Episodes"]["metadata_summary"]["resolution"], ["720p"])
        self.assertEqual(
            rows["Episodes"]["metadata_origins"]["resolution"], {"720p": "provider"}
        )
        self.assertEqual(
            rows["Manual"]["metadata_origins"]["resolution"], {"2160p": "manual"}
        )
        self.assertEqual(
            rows["Category only"]["metadata_origins"]["resolution"],
            {"1080p": "category"},
        )
        self.assertEqual(
            rows["Category only"]["metadata_origins"]["audio_languages"], {}
        )

    def test_resolution_filter_and_options_use_the_same_precedence(self):
        self.add_series("Episodes", height=720)
        self.add_series("Manual", height=720, manual="2160p")
        self.add_series("Category only")
        self.assertEqual(set(self.rows(resolution="720p")), {"Episodes"})
        self.assertEqual(set(self.rows(resolution="2160p")), {"Manual"})
        self.assertEqual(set(self.rows(resolution="1080p")), {"Category only"})
        response = self.client.get(self.endpoint("filter-options"), {"type": "series"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()["resolution"], ["1080p", "2160p", "720p"])

    def test_several_genre_terms_match_any_part_of_a_genre(self):
        drama = self.add_series("Drama")
        comedy = self.add_series("Comedy")
        self.add_series("Horror")
        for series, genre in ((drama, "Drama"), (comedy, "Comedy, Family")):
            series.genre = genre
            series.save()
        self.assertEqual(set(self.rows(genre="dram,Comed")), {"Drama", "Comedy"})
