import os
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.m3u.models import M3UAccount
from apps.vod.api_views import (
    M3UVODCategoryRelationViewSet,
    VODMetadataViewSet,
    VODSourceRelationViewSet,
)
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODAccessPolicy,
    VODMovieProfileSelection,
    VODMetadataState,
    VODPlaybackSession,
    VODCategory,
)
from apps.vod.profile_selection import profile_ids_using_canonical_content
from apps.vod.tasks import (
    _merge_duplicate_tmdb_canonicals,
    enqueue_tmdb_enrichment,
    lookup_by_clean_title_year,
    refresh_canonical_clean_titles,
    reconcile_vod_metadata_queue,
)
from apps.vod.tmdb import (
    DEFAULT_TITLE_YEAR_RULES,
    Client,
    canonical_fields_from_metadata,
    clean_lookup_title,
    extract_year_from_title,
    normalize_details,
    normalize_group_title_cleanup,
    normalize_title_rules,
    normalize_year_rules,
    preferred_title,
)
from core.models import CoreSettings


class TMDBMetadataTests(SimpleTestCase):
    def test_canonical_list_fields_are_projected_from_tmdb_metadata(self):
        update = canonical_fields_from_metadata(
            {
                "localized": {
                    "de-DE": {
                        "title": "Deutscher Titel",
                        "overview": "Beschreibung",
                    }
                },
                "release_date": "2024-05-17",
                "rating": 7.25,
                "genres": [{"id": 1, "name": "Drama"}],
                "runtime_minutes": 95,
            },
            "de-DE",
            "movie",
        )

        self.assertEqual(update["display_name"], "Deutscher Titel")
        self.assertEqual(update["description"], "Beschreibung")
        self.assertEqual(update["year"], 2024)
        self.assertEqual(update["rating"], "7.25")
        self.assertEqual(update["genre"], "Drama")
        self.assertEqual(update["duration_secs"], 5700)

    def test_lookup_title_does_not_hide_provider_prefix_cleanup(self):
        self.assertEqual(
            clean_lookup_title("4K-AMZ - Bliss (2021)", year=2021),
            "4K-AMZ - Bliss",
        )

    def test_lookup_title_uses_the_canonical_display_name_verbatim(self):
        self.assertEqual(
            clean_lookup_title(
                "provider fallback",
                display_name="4K-AMZ - Bliss (2021)",
                year=2021,
            ),
            "4K-AMZ - Bliss",
        )

    def test_lookup_title_cleanup_applies_ordered_prefixes(self):
        self.assertEqual(
            clean_lookup_title(
                "WEB AMZ - Bliss [2021]",
                year=2021,
                rules=[
                    "WEB ",
                    "AMZ - ",
                ],
            ),
            "Bliss",
        )

    def test_lookup_title_cleanup_removes_whitespace_left_by_prefix(self):
        self.assertEqual(
            clean_lookup_title("NF - Title", rules=["NF -"]),
            "Title",
        )

    def test_literal_title_cleanup_does_not_interpret_regex_characters(self):
        rules = [
            {
                "match_type": "starts_with",
                "value": "4K-D+ -",
                "action": "remove",
            },
        ]
        self.assertEqual(
            clean_lookup_title(
                "4K-D+ - Bliss (2021)",
                year=2021,
                rules=rules,
            ),
            "Bliss",
        )

    def test_legacy_title_rule_is_migrated_to_a_literal_prefix(self):
        self.assertEqual(
            normalize_title_rules(
                [{"pattern": "AMZ - ", "replacement": ""}]
            ),
            [
                {
                    "match_type": "starts_with",
                    "value": "AMZ -",
                    "action": "remove",
                    "replacement": "",
                    "enabled": True,
                }
            ],
        )

    def test_legacy_year_patterns_are_configurable_defaults(self):
        rules = normalize_year_rules(DEFAULT_TITLE_YEAR_RULES)

        self.assertEqual(extract_year_from_title("Movie (2024)", rules), 2024)
        self.assertEqual(extract_year_from_title("Movie [2024]", rules), 2024)
        self.assertEqual(extract_year_from_title("Movie - 2023", rules), 2023)
        self.assertEqual(extract_year_from_title("Movie 2022", rules), 2022)

    def test_custom_year_format_extracts_and_cleans_the_release_year(self):
        rules = [{"value": "[YYYY]", "position": "end"}]

        self.assertEqual(extract_year_from_title("Movie [2024]", rules), 2024)
        self.assertEqual(
            clean_lookup_title("Movie [2024]", year=2024, year_rules=rules),
            "Movie",
        )

    def test_category_regex_runs_after_global_cleanup(self):
        self.assertEqual(
            clean_lookup_title(
                "(DE-) -10- Prisons 4K - 2024",
                year=2024,
                rules=["(DE-)"],
                year_rules=DEFAULT_TITLE_YEAR_RULES,
                group_rule={
                    "pattern": r"-\d+-\s*|\b4K\b",
                },
            ),
            "Prisons",
        )

    def test_category_regex_follows_global_year_cleanup(self):
        self.assertEqual(
            clean_lookup_title(
                "Provider Movie - 2024",
                year=2024,
                year_rules=DEFAULT_TITLE_YEAR_RULES,
                group_rule={"pattern": r"^Provider\s+"},
            ),
            "Movie",
        )

    def test_category_regex_cannot_damage_a_global_prefix_format(self):
        self.assertEqual(
            clean_lookup_title(
                "(DE-) -1- Movie - 2024",
                year=2024,
                rules=["(DE-)"],
                year_rules=DEFAULT_TITLE_YEAR_RULES,
                group_rule={"pattern": "-"},
            ),
            "1 Movie",
        )

    def test_category_regex_normalizes_to_removal_only(self):
        self.assertEqual(
            normalize_group_title_cleanup(
                {"pattern": r"\b4K\b", "case_sensitive": True}
            ),
            {"pattern": r"\b4K\b", "case_sensitive": True},
        )

    def test_search_outcome_distinguishes_no_match_and_ambiguous_match(self):
        client = Client("token")
        client.search_candidates = Mock(return_value=[])
        self.assertEqual(
            client.search_outcome("Bliss", 2021, "movie", "en-US"),
            ("", "not_found", 0),
        )
        client.search_candidates = Mock(
            return_value=[
                {"id": "1", "title": "Bliss", "year": 2021},
                {"id": "2", "title": "Bliss", "year": 2021},
            ]
        )
        self.assertEqual(
            client.search_outcome("Bliss", 2021, "movie", "en-US"),
            ("", "ambiguous", 2),
        )

    def test_normalizes_original_localized_and_watch_provider_data(self):
        metadata = normalize_details(
            {
                "id": 76600,
                "title": "Avatar: The Way of Water",
                "original_title": "Avatar: The Way of Water",
                "original_language": "en",
                "release_date": "2022-12-14",
                "genres": [{"id": 878, "name": "Science Fiction"}],
                "production_countries": [
                    {"iso_3166_1": "US", "name": "United States of America"}
                ],
                "credits": {
                    "cast": [{"name": "Sam Worthington"}, {"name": "Zoe Saldaña"}],
                    "crew": [
                        {"name": "James Cameron", "job": "Director"},
                        {"name": "Someone Else", "job": "Producer"},
                    ],
                },
                "videos": {
                    "results": [
                        {
                            "site": "YouTube",
                            "key": "trailer-key",
                            "type": "Trailer",
                            "official": True,
                            "size": 1080,
                        }
                    ]
                },
                "keywords": {
                    "keywords": [
                        {"id": 210024, "name": "anime"},
                        {"id": 9715, "name": "superhero"},
                    ]
                },
                "release_dates": {
                    "results": [
                        {
                            "iso_3166_1": "DE",
                            "release_dates": [
                                {"certification": "12", "type": 3}
                            ],
                        }
                    ]
                },
                "poster_path": "/poster.jpg",
                "backdrop_path": "/backdrop.jpg",
                "external_ids": {
                    "imdb_id": "tt1630029",
                    "wikidata_id": "Q27964338",
                },
                "translations": {
                    "translations": [
                        {
                            "iso_639_1": "de",
                            "iso_3166_1": "DE",
                            "data": {
                                "title": "Avatar: The Way of Water",
                                "overview": "Deutsche Beschreibung",
                            },
                        },
                        {
                            "iso_639_1": "en",
                            "iso_3166_1": "US",
                            "data": {
                                # TMDB sometimes leaves a translated title
                                # blank even though the overview is localized.
                                "title": "",
                                "overview": "English overview",
                            },
                        },
                    ]
                },
                "watch/providers": {
                    "results": {
                        "DE": {
                            "link": "https://www.themoviedb.org/movie/76600/watch",
                            "flatrate": [
                                {
                                    "provider_id": 337,
                                    "provider_name": "Disney Plus",
                                    "logo_path": "/logo.jpg",
                                    "display_priority": 1,
                                }
                            ],
                        }
                    }
                },
            },
            "movie",
            ["de-DE", "en-US"],
            match_method="provider_tmdb_id",
        )

        self.assertNotIn("original_title", metadata)
        self.assertEqual(
            metadata["localized"]["de-DE"]["overview"],
            "Deutsche Beschreibung",
        )
        self.assertEqual(
            metadata["watch_providers"]["DE"]["flatrate"][0]["name"],
            "Disney Plus",
        )
        self.assertEqual(preferred_title(metadata, "en-US"), "Avatar: The Way of Water")
        self.assertEqual(
            metadata["poster_url"],
            "https://image.tmdb.org/t/p/w500/poster.jpg",
        )
        self.assertEqual(
            metadata["backdrop_url"],
            "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
        )
        self.assertEqual(metadata["external_ids"]["imdb_id"], "tt1630029")
        self.assertEqual(metadata["director"], "James Cameron")
        self.assertEqual(metadata["actors"], "Sam Worthington, Zoe Saldaña")
        self.assertEqual(metadata["crew"], "Someone Else (Producer)")
        self.assertEqual(metadata["country"], "United States of America")
        self.assertEqual(metadata["youtube_trailer"], "trailer-key")
        self.assertEqual(metadata["age_rating"], "12")
        self.assertEqual(
            metadata["keywords"],
            [
                {"id": 210024, "name": "anime"},
                {"id": 9715, "name": "superhero"},
            ],
        )
        self.assertTrue(metadata["is_anime"])

    def test_detail_request_includes_richer_movie_metadata(self):
        response = Mock(status_code=200, headers={})
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": 613911, "title": "Bliss"}
        session = Mock()
        session.get.return_value = response

        Client("v3-api-key", session=session, min_interval=0).details(
            "613911", "movie", ["de-DE", "en-US"], match_method="manual"
        )

        params = session.get.call_args.kwargs["params"]
        appended = set(params["append_to_response"].split(","))
        self.assertTrue(
            {
                "translations",
                "external_ids",
                "watch/providers",
                "credits",
                "videos",
                "keywords",
                "release_dates",
            }.issubset(appended)
        )

    def test_manual_overrides_keep_the_tmdb_identity(self):
        from apps.vod.tmdb import apply_manual_overrides

        metadata = apply_manual_overrides(
            {"id": "613911", "rating": 5.5},
            {"id": "", "rating": "7.0"},
        )

        self.assertEqual(metadata["id"], "613911")
        self.assertEqual(metadata["rating"], "7.0")
        self.assertEqual(metadata["_manual_overrides"], {"rating": "7.0"})

    def test_search_accepts_only_one_exact_title_and_year_match(self):
        response = Mock(status_code=200, headers={})
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [
                {
                    "id": 1,
                    "title": "Avatar",
                    "original_title": "Avatar",
                    "release_date": "2009-12-10",
                },
                {
                    "id": 2,
                    "title": "Avatar 2",
                    "original_title": "Avatar 2",
                    "release_date": "2022-12-14",
                },
            ]
        }
        session = Mock()
        session.get.return_value = response
        client = Client("v3-api-key", session=session, min_interval=0)

        self.assertEqual(client.search("Avatar", 2009, "movie", "de-DE"), "1")

    def test_search_rejects_ambiguous_exact_matches(self):
        response = Mock(status_code=200, headers={})
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [
                {"id": 1, "name": "The Office", "first_air_date": "2005-03-24"},
                {"id": 2, "name": "The Office", "first_air_date": "2005-01-01"},
            ]
        }
        session = Mock()
        session.get.return_value = response
        client = Client("v3-api-key", session=session, min_interval=0)

        self.assertEqual(client.search("The Office", 2005, "tv", "en-US"), "")


class VODTitleYearMatchingTests(TestCase):
    def test_matches_primary_secondary_clean_and_provider_titles(self):
        movie = Movie.objects.create(
            name="Provider title",
            display_name="Primärtitel",
            clean_title="Clean title",
            year=2024,
            tmdb_metadata={
                "localized": {"en-US": {"title": "Secondary title"}}
            },
        )

        for title in (
            "Primärtitel", "Secondary title", "Clean title", "Provider title"
        ):
            self.assertEqual(
                lookup_by_clean_title_year(Movie, [(title, 2024)]).get(
                    (title.casefold(), 2024)
                ),
                movie,
            )

    def test_does_not_match_without_a_year(self):
        Movie.objects.create(name="Same title", clean_title="Same title")

        self.assertEqual(
            lookup_by_clean_title_year(Movie, [("Same title", None)]),
            {},
        )

    def test_ambiguous_title_and_year_does_not_match(self):
        Movie.objects.create(
            name="Provider one", display_name="Shared title", year=2024
        )
        Movie.objects.create(
            name="Provider two",
            display_name="Shared title",
            year=2024,
            tmdb_id="900001",
        )

        self.assertEqual(
            lookup_by_clean_title_year(Movie, [("Shared title", 2024)]),
            {},
        )

    def test_primary_title_wins_before_a_different_canonical_clean_title(self):
        primary = Movie.objects.create(
            name="Provider primary",
            display_name="Preferred title",
            year=2024,
            tmdb_id="900010",
        )
        Movie.objects.create(
            name="Different provider title",
            clean_title="Preferred title",
            year=2024,
        )

        self.assertEqual(
            lookup_by_clean_title_year(
                Movie, [("Preferred title", 2024)]
            ).get(("preferred title", 2024)),
            primary,
        )

    def test_secondary_title_wins_before_a_different_canonical_clean_title(self):
        secondary = Movie.objects.create(
            name="Provider secondary",
            display_name="Primärtitel",
            tmdb_metadata={
                "localized": {"en-US": {"title": "Secondary title"}}
            },
            year=2024,
            tmdb_id="900011",
        )
        Movie.objects.create(
            name="Another provider title",
            clean_title="Secondary title",
            year=2024,
        )

        self.assertEqual(
            lookup_by_clean_title_year(
                Movie, [("Secondary title", 2024)]
            ).get(("secondary title", 2024)),
            secondary,
        )

    def test_category_regex_follows_global_cleanup_for_the_canonical(self):
        account = M3UAccount.objects.create(
            name="Category cleanup provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        category = VODCategory.objects.create(
            name="Ranked 4K",
            category_type="movie",
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=account,
            category=category,
            enabled=True,
            custom_properties={
                "title_cleanup": {
                    "pattern": r"-\d+-\s*|\b4K\b",
                }
            },
        )
        movie = Movie.objects.create(
            name="(DE-) -10- Prisons 4K - 2024",
            year=2024,
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            category=category,
            stream_id="ranked-movie",
            custom_properties={
                "basic_data": {"name": "(DE-) -10- Prisons 4K - 2024"}
            },
        )
        CoreSettings.set_vod_metadata_settings(
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
            title_rules=["(DE-)"],
            year_rules=DEFAULT_TITLE_YEAR_RULES,
        )

        refresh_canonical_clean_titles(movie_ids=[movie.id])

        movie.refresh_from_db()
        self.assertEqual(movie.clean_title, "Prisons")


class VODMetadataAPITests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="tmdb-admin",
            password="test-password",
            user_level=10,
        )
        self.factory = APIRequestFactory()

    def test_category_title_cleanup_endpoint_validates_and_persists_regex(self):
        account = M3UAccount.objects.create(
            name="Category cleanup API provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        category = VODCategory.objects.create(
            name="Ranked movies",
            category_type="movie",
        )
        relation = M3UVODCategoryRelation.objects.create(
            m3u_account=account,
            category=category,
            enabled=True,
        )
        request = self.factory.patch(
            f"/api/vod/category-relations/{relation.id}/title-cleanup/",
            {
                "title_cleanup": {
                    "pattern": r"^-\d+-\s*",
                    "case_sensitive": True,
                }
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = M3UVODCategoryRelationViewSet.as_view(
            {"patch": "title_cleanup"}
        )(request, pk=relation.id)

        self.assertEqual(response.status_code, 200, response.data)
        relation.refresh_from_db()
        self.assertEqual(
            relation.custom_properties["title_cleanup"],
            {
                "pattern": r"^-\d+-\s*",
                "case_sensitive": True,
            },
        )

        invalid_request = self.factory.patch(
            f"/api/vod/category-relations/{relation.id}/title-cleanup/",
            {"title_cleanup": {"pattern": "("}},
            format="json",
        )
        force_authenticate(invalid_request, user=self.admin)
        invalid_response = M3UVODCategoryRelationViewSet.as_view(
            {"patch": "title_cleanup"}
        )(invalid_request, pk=relation.id)
        self.assertEqual(invalid_response.status_code, 400)
        relation.refresh_from_db()
        self.assertEqual(
            relation.custom_properties["title_cleanup"],
            {
                "pattern": r"^-\d+-\s*",
                "case_sensitive": True,
            },
        )

    def test_category_title_cleanup_preview_uses_provider_titles_in_relation(self):
        account = M3UAccount.objects.create(
            name="Category preview provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        other_account = M3UAccount.objects.create(
            name="Other preview provider",
            server_url="http://other.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        category = VODCategory.objects.create(
            name="Ranked preview movies",
            category_type="movie",
        )
        category_relation = M3UVODCategoryRelation.objects.create(
            m3u_account=account,
            category=category,
            enabled=True,
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=other_account,
            category=category,
            enabled=True,
        )
        matching_movie = Movie.objects.create(name="Ranked provider movie")
        plain_movie = Movie.objects.create(name="Plain provider movie")
        other_movie = Movie.objects.create(name="Other account movie")
        matching_relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=matching_movie,
            category=category,
            stream_id="ranked-1",
            custom_properties={
                "basic_data": {"name": "(DE-) -1- Prisons 4K - 2024"}
            },
        )
        plain_relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=plain_movie,
            category=category,
            stream_id="plain-1",
            custom_properties={"basic_data": {"name": "Ordinary Movie"}},
        )
        M3UMovieRelation.objects.create(
            m3u_account=other_account,
            movie=other_movie,
            category=category,
            stream_id="other-1",
            custom_properties={
                "basic_data": {"name": "(DE-) -2- Another 4K - 2024"}
            },
        )
        CoreSettings.set_vod_metadata_settings(
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
            title_rules=["(DE-)"],
            year_rules=DEFAULT_TITLE_YEAR_RULES,
        )

        request = self.factory.post(
            f"/api/vod/category-relations/{category_relation.id}/title-cleanup-preview/",
            {
                "title_cleanup": {
                    "pattern": r"-\d+-\s*|\b4K\b",
                    "case_sensitive": False,
                },
                "page": 1,
                "page_size": 25,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = M3UVODCategoryRelationViewSet.as_view(
            {"post": "title_cleanup_preview"}
        )(request, pk=category_relation.id)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_in_category"], 2)
        self.assertEqual(response.data["page_match_count"], 1)
        self.assertEqual(
            response.data["results"],
            [
                {
                    "relation_id": matching_relation.id,
                    "content_type": "movie",
                    "before": "(DE-) -1- Prisons 4K - 2024",
                    "after": "Prisons",
                    "year": 2024,
                    "matched": True,
                    "changed": True,
                },
                {
                    "relation_id": plain_relation.id,
                    "content_type": "movie",
                    "before": "Ordinary Movie",
                    "after": "Ordinary Movie",
                    "year": None,
                    "matched": False,
                    "changed": False,
                },
            ],
        )

        initial_request = self.factory.post(
            f"/api/vod/category-relations/{category_relation.id}/title-cleanup-preview/",
            {"title_cleanup": {}, "page": 1, "page_size": 25},
            format="json",
        )
        force_authenticate(initial_request, user=self.admin)
        initial_response = M3UVODCategoryRelationViewSet.as_view(
            {"post": "title_cleanup_preview"}
        )(initial_request, pk=category_relation.id)

        self.assertEqual(initial_response.status_code, 200, initial_response.data)
        self.assertEqual(initial_response.data["total_in_category"], 2)
        self.assertEqual(initial_response.data["page_match_count"], 0)
        self.assertEqual(
            initial_response.data["results"][0],
            {
                "relation_id": matching_relation.id,
                "content_type": "movie",
                "before": "(DE-) -1- Prisons 4K - 2024",
                "after": "-1- Prisons 4K",
                "year": 2024,
                "matched": False,
                "changed": True,
            },
        )

        invalid_request = self.factory.post(
            f"/api/vod/category-relations/{category_relation.id}/title-cleanup-preview/",
            {"title_cleanup": {"pattern": "("}},
            format="json",
        )
        force_authenticate(invalid_request, user=self.admin)
        invalid_response = M3UVODCategoryRelationViewSet.as_view(
            {"post": "title_cleanup_preview"}
        )(invalid_request, pk=category_relation.id)
        self.assertEqual(invalid_response.status_code, 200)
        self.assertTrue(invalid_response.data["error"])

    def test_canonical_changes_only_mark_profiles_that_embed_the_title(self):
        account = M3UAccount.objects.create(
            name="Canonical profile scope",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        movie = Movie.objects.create(name="Bliss")
        relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="movie-1",
        )
        compact = VODAccessPolicy.objects.create(
            name="Compact canonical",
            export_mode=VODAccessPolicy.ExportMode.COMPACT,
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            active_selection_generation="compact-generation",
        )
        provider_variants = VODAccessPolicy.objects.create(
            name="Provider variants",
            export_mode=VODAccessPolicy.ExportMode.VARIANTS,
            metadata_source=VODAccessPolicy.MetadataSource.PROVIDER,
            naming_mode=VODAccessPolicy.NamingMode.MODE_DEFAULT,
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            active_selection_generation="provider-generation",
        )
        canonical_variants = VODAccessPolicy.objects.create(
            name="Canonical variants",
            export_mode=VODAccessPolicy.ExportMode.VARIANTS,
            metadata_source=VODAccessPolicy.MetadataSource.CANONICAL,
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            active_selection_generation="canonical-generation",
        )
        excluded_compact = VODAccessPolicy.objects.create(
            name="Excluded compact",
            export_mode=VODAccessPolicy.ExportMode.COMPACT,
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            active_selection_generation="excluded-generation",
        )
        for policy in (compact, provider_variants, canonical_variants):
            VODMovieProfileSelection.objects.create(
                policy=policy,
                generation=policy.active_selection_generation,
                movie=movie,
                relation=relation,
            )

        policy_ids = profile_ids_using_canonical_content(movie_ids=[movie.id])

        self.assertEqual(
            policy_ids,
            sorted([compact.id, canonical_variants.id]),
        )
        self.assertNotIn(provider_variants.id, policy_ids)
        self.assertNotIn(excluded_compact.id, policy_ids)

    def test_unlock_allows_an_unchanged_failed_title_to_run_again(self):
        movie = Movie.objects.create(
            name="Unmatched title",
            tmdb_status="not_found",
            tmdb_enrichment_signature="current-signature",
        )
        request = self.factory.post(
            "/api/vod/metadata/unlock/",
            {
                "selections": [
                    {"id": movie.id, "content_type": "movie"}
                ],
                "toggle": True,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "unlock"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        movie.refresh_from_db()
        self.assertEqual(movie.tmdb_enrichment_signature, "")
        self.assertEqual(response.data["unlocked"], 1)

    def test_lock_toggle_locks_then_unlocks_an_unchanged_title(self):
        movie = Movie.objects.create(
            name="Manual title",
            clean_title="Manual title",
        )
        request = self.factory.post(
            "/api/vod/metadata/lock/",
            {
                "selections": [
                    {"id": movie.id, "content_type": "movie"}
                ],
                "toggle": True,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "lock"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        movie.refresh_from_db()
        self.assertTrue(movie.tmdb_enrichment_signature)
        self.assertEqual(response.data["locked"], 1)
        original_signature = movie.tmdb_enrichment_signature

        second_request = self.factory.post(
            "/api/vod/metadata/lock/",
            {
                "selections": [
                    {"id": movie.id, "content_type": "movie"}
                ],
                "toggle": True,
            },
            format="json",
        )
        force_authenticate(second_request, user=self.admin)
        second_response = VODMetadataViewSet.as_view({"post": "lock"})(
            second_request
        )

        self.assertEqual(second_response.status_code, 200, second_response.data)
        self.assertEqual(second_response.data["action"], "unlocked")
        self.assertEqual(second_response.data["unlocked"], 1)
        movie.refresh_from_db()
        self.assertNotEqual(movie.tmdb_enrichment_signature, original_signature)
        self.assertEqual(movie.tmdb_enrichment_signature, "")

    def test_duplicate_tmdb_canonicals_are_merged_into_the_main_title(self):
        account = M3UAccount.objects.create(
            name="TMDB duplicate provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        target = Movie.objects.create(
            name="Crank 2 - High Voltage",
            tmdb_match_id="15092",
            tmdb_status="matched",
        )
        duplicate = Movie.objects.create(
            name="NF - Crank: High Voltage",
            tmdb_match_id="15092",
            tmdb_status="matched",
        )
        target_relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=target,
            stream_id="target-1",
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=target,
            stream_id="target-2",
        )
        duplicate_relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=duplicate,
            stream_id="duplicate-1",
        )
        policy = VODAccessPolicy.objects.create(name="Duplicate merge profile")
        selection = VODMovieProfileSelection.objects.create(
            policy=policy,
            generation="ready",
            movie=duplicate,
            relation=duplicate_relation,
        )
        history = VODPlaybackSession.objects.create(
            session_id="duplicate-history",
            content_type="movie",
            canonical_id=duplicate.id,
            relation_id=duplicate_relation.id,
            mode=VODPlaybackSession.Mode.PLAYER,
        )

        merged, targets = _merge_duplicate_tmdb_canonicals(Movie)

        self.assertEqual(merged, 1)
        self.assertEqual(targets, {target.id})
        self.assertFalse(Movie.objects.filter(pk=duplicate.id).exists())
        duplicate_relation.refresh_from_db()
        selection.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(duplicate_relation.movie_id, target.id)
        self.assertEqual(selection.movie_id, target.id)
        self.assertEqual(history.canonical_id, target.id)
        self.assertEqual(target.m3u_relations.count(), 3)
        self.assertEqual(target_relation.movie_id, target.id)

    @patch.dict(
        os.environ,
        {"TMDB_API_READ_ACCESS_TOKEN": "", "TMDB_API_KEY": ""},
    )
    def test_status_reports_configuration_without_exposing_token(self):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["de-DE", "en-US"],
            auto_enrich=True,
            match_missing=False,
        )
        request = self.factory.get("/api/vod/metadata/")
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["settings"]["token_configured"])
        self.assertEqual(response.data["settings"]["token_source"], "stored")
        self.assertNotIn("api_token", response.data["settings"])

    def test_settings_normalizes_at_most_two_locales(self):
        request = self.factory.put(
            "/api/vod/metadata/settings/",
            {
                "languages": ["de-de", "en-us"],
                "auto_enrich": True,
                "match_missing": True,
                "api_token": "stored-secret",
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"put": "update_settings"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["settings"]["languages"], ["de-DE", "en-US"])
        self.assertTrue(CoreSettings.get_tmdb_match_missing())

    @patch("apps.vod.tmdb.Client.search_candidates")
    def test_tmdb_lookup_returns_candidates_without_writing_content(self, search):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        search.return_value = [
            {
                "id": "613911",
                "title": "Bliss",
                "year": 2021,
                "overview": "Search preview",
            }
        ]
        request = self.factory.post(
            "/api/vod/metadata/tmdb-lookup/",
            {"content_type": "movie", "query": "Bliss", "year": 2021},
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "tmdb_lookup"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["id"], "613911")
        search.assert_called_once_with("Bliss", 2021, "movie", "en-US")

    def test_canonical_metadata_editor_persists_keywords_and_manual_values(self):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["de-DE", "en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        movie = Movie.objects.create(
            name="Provider Bliss",
            tmdb_metadata={"id": "613911", "status": "matched"},
            tmdb_status="matched",
        )
        request = self.factory.patch(
            "/api/vod/metadata/content/",
            {
                "content_type": "movie",
                "id": movie.id,
                "values": {
                    "title": "Bliss",
                    "secondary_title": "Bliss",
                    "description": "Deutsche Beschreibung",
                    "secondary_description": "English overview",
                    "year": "2021",
                    "release_date": "2021-02-05",
                    "duration_minutes": "103",
                    "rating": "6.5",
                    "genre": "Science Fiction, Drama",
                    "age_rating": "12",
                    "director": "Mike Cahill",
                    "actors": "Owen Wilson, Salma Hayek",
                    "crew": "Crew Member",
                    "country": "United States",
                    "youtube_trailer": "trailer-key",
                    "poster_url": "https://image.example/poster.jpg",
                    "backdrop_url": "https://image.example/backdrop.jpg",
                    "tmdb_id": "613911",
                    "imdb_id": "tt10333426",
                    "tvdb_id": "",
                    "wikidata_id": "Q123",
                    "keywords": ["anime", "virtual reality"],
                    "is_anime": True,
                    "adult": False,
                },
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        with patch(
            "apps.vod.profile_selection.mark_profile_selections_outdated"
        ) as mark_outdated:
            response = VODMetadataViewSet.as_view({"patch": "update_content"})(
                request
            )

        self.assertEqual(response.status_code, 200, response.data)
        movie.refresh_from_db()
        self.assertEqual(movie.display_name, "Bliss")
        self.assertEqual(movie.duration_secs, 103 * 60)
        self.assertEqual(movie.tmdb_match_id, "613911")
        self.assertTrue(movie.tmdb_enrichment_signature)
        self.assertEqual(movie.tmdb_metadata["external_ids"]["imdb_id"], "tt10333426")
        self.assertEqual(
            [row["name"] for row in movie.tmdb_metadata["keywords"]],
            ["anime", "virtual reality"],
        )
        self.assertTrue(movie.tmdb_metadata["is_anime"])
        self.assertEqual(
            movie.custom_properties["_manual_metadata"]["display_name"],
            "Bliss",
        )
        mark_outdated.assert_called_once_with(
            trigger_reason="Canonical VOD metadata was edited manually",
            policy_ids=[],
        )

    def test_canonical_metadata_editor_merges_an_existing_tmdb_title(self):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["de-DE", "en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        account = M3UAccount.objects.create(
            name="Manual TMDB merge provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        target = Movie.objects.create(
            name="Crank",
            display_name="Crank",
            tmdb_match_id="1948",
            tmdb_status="matched",
            custom_properties={"target_marker": True},
        )
        duplicate = Movie.objects.create(name="NF - Crank")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=target,
            stream_id="existing-crank",
        )
        moved_relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=duplicate,
            stream_id="new-crank",
        )
        request = self.factory.patch(
            "/api/vod/metadata/content/",
            {
                "content_type": "movie",
                "id": duplicate.id,
                "values": {
                    "title": "Crank",
                    "secondary_title": "Crank",
                    "description": "German overview",
                    "secondary_description": "English overview",
                    "year": "2006",
                    "tmdb_id": "1948",
                    "imdb_id": "tt0479884",
                },
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        with patch(
            "apps.vod.profile_selection.mark_profile_selections_outdated"
        ) as mark_outdated:
            response = VODMetadataViewSet.as_view({"patch": "update_content"})(
                request
            )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Movie.objects.filter(pk=duplicate.id).exists())
        target.refresh_from_db()
        moved_relation.refresh_from_db()
        self.assertEqual(moved_relation.movie_id, target.id)
        self.assertEqual(moved_relation.tmdb_override_id, "1948")
        self.assertEqual(target.m3u_relations.count(), 2)
        self.assertEqual(target.display_name, "Crank")
        self.assertEqual(target.tmdb_match_id, "1948")
        self.assertEqual(target.tmdb_imdb_id, "tt0479884")
        self.assertTrue(target.tmdb_enrichment_signature)
        self.assertTrue(target.custom_properties["target_marker"])
        self.assertEqual(
            target.custom_properties["_manual_metadata"]["display_name"],
            "Crank",
        )
        self.assertTrue(response.data["merged"])
        self.assertEqual(response.data["target"]["id"], target.id)
        self.assertEqual(
            response.data["target"]["relation_id"], moved_relation.id
        )
        mark_outdated.assert_called_once_with(
            trigger_reason="Canonical VOD metadata was edited manually",
            policy_ids=[],
        )

    def test_manual_enrichment_requires_an_explicit_selection(self):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        request = self.factory.post(
            "/api/vod/metadata/refresh/",
            {"selections": []},
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "refresh"})(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("selections", response.data)

    @patch("apps.vod.tasks.enqueue_tmdb_enrichment")
    def test_manual_enrichment_forces_explicit_unlocked_selection(self, enqueue):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        enqueue.return_value = {
            "queued": True,
            "task_id": "task",
            "status": "queued",
        }
        request = self.factory.post(
            "/api/vod/metadata/refresh/",
            {
                "select_all": True,
                "selections": [],
                "exclude_selections": [
                    {"id": 9, "content_type": "movie"}
                ],
                "filters": {
                    "type": "movies",
                    "search": "Bliss",
                    "metadata_status": "missing_metadata",
                },
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "refresh"})(request)

        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once_with(
            trigger_reason="Manual TMDB metadata refresh",
            force=True,
            search_missing=True,
            movie_ids=None,
            series_ids=None,
            selection_filters={
                "type": "movies",
                "search": "Bliss",
                "metadata_status": "missing_metadata",
            },
            exclude_movie_ids=[9],
            exclude_series_ids=[],
        )

    @patch("apps.vod.tasks.enqueue_tmdb_enrichment")
    def test_manual_enrichment_rejects_a_locked_title(self, enqueue):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        movie = Movie.objects.create(
            name="Protected title",
            tmdb_enrichment_signature="locked",
        )
        request = self.factory.post(
            "/api/vod/metadata/refresh/",
            {
                "selections": [
                    {"id": movie.id, "content_type": "movie"}
                ]
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "refresh"})(request)

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("1 selected title is locked", response.data["detail"])
        enqueue.assert_not_called()

    def test_api_key_only_update_preserves_library_metadata_preferences(self):
        CoreSettings.set_vod_metadata_settings(
            api_token="old-secret",
            languages=["de-DE", "en-US"],
            auto_enrich=False,
            match_missing=True,
            prefer_artwork=False,
            title_rules=[
                {"pattern": "AMZ - ", "replacement": ""}
            ],
        )
        request = self.factory.put(
            "/api/vod/metadata/settings/",
            {"api_token": "new-secret", "auto_enrich": True},
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"put": "update_settings"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CoreSettings.get_tmdb_languages(), ["de-DE", "en-US"])
        self.assertTrue(CoreSettings.get_tmdb_match_missing())
        self.assertFalse(CoreSettings.get_tmdb_prefer_artwork())
        self.assertTrue(CoreSettings.get_tmdb_auto_enrich())
        self.assertEqual(
            CoreSettings.get_tmdb_title_rules(),
            [
                {
                    "match_type": "starts_with",
                    "value": "AMZ -",
                    "action": "remove",
                    "replacement": "",
                    "enabled": True,
                }
            ],
        )

    def test_title_preview_uses_the_requested_visible_canonical_rows(self):
        movie = Movie.objects.create(
            name="DE - Bliss (2021)",
            display_name="DE - Bliss (2021)",
            year=2021,
        )
        series = Series.objects.create(
            name="AMZ - The Office [2005]",
            display_name="AMZ - The Office [2005]",
            year=2005,
            tmdb_status="ambiguous",
            tmdb_metadata={"status": "ambiguous", "candidate_count": 2},
            tmdb_enrichment_signature="reviewed",
        )
        request = self.factory.post(
            "/api/vod/metadata/title-preview/",
            {
                "title_rules": [
                    {
                        "value": "AMZ - ",
                    },
                    {
                        "value": "DE - ",
                    },
                    {"value": "The "},
                ],
                "items": [
                    {"id": series.id, "content_type": "series"},
                    {"id": movie.id, "content_type": "movie"},
                ],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "title_preview"})(
            request
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                (row["content_type"], row["id"], row["before"], row["after"])
                for row in response.data["results"]
            ],
            [
                (
                    "series",
                    series.id,
                    "AMZ - The Office [2005]",
                    "Office",
                ),
                ("movie", movie.id, "DE - Bliss (2021)", "Bliss"),
            ],
        )
        self.assertEqual(response.data["results"][0]["tmdb_status"], "ambiguous")
        self.assertEqual(response.data["results"][0]["candidate_count"], 2)
        self.assertEqual(response.data["results"][0]["tmdb_id"], "")
        self.assertTrue(
            response.data["results"][0]["metadata_auto_locked"]
        )
        self.assertFalse(
            response.data["results"][1]["metadata_auto_locked"]
        )
        self.assertEqual(response.data["locked_count"], 1)

    def test_title_preview_paginates_all_titles_without_tmdb_id(self):
        account = M3UAccount.objects.create(
            name="Preview provider",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        movies = [Movie.objects.create(name=f"Movie {index}") for index in range(3)]
        for index, movie in enumerate(movies):
            M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=movie,
                stream_id=f"movie-{index}",
            )
        Movie.objects.filter(pk=movies[0].pk).update(
            tmdb_enrichment_signature="reviewed"
        )
        matched = Movie.objects.create(name="Matched", tmdb_match_id="123")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=matched,
            stream_id="matched",
        )
        request = self.factory.post(
            "/api/vod/metadata/title-preview/",
            {
                "title_rules": [],
                "missing_tmdb_only": True,
                "page": 2,
                "page_size": 2,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "title_preview"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], 3)
        self.assertEqual(response.data["page"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertNotEqual(response.data["results"][0]["before"], "Matched")
        self.assertEqual(response.data["locked_count"], 1)

    def test_title_preview_search_requires_text(self):
        request = self.factory.post(
            "/api/vod/metadata/title-preview/",
            {"title_rules": []},
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "title_preview"})(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["search"], "Enter a title to search.")

    @patch("apps.vod.profile_selection.mark_profile_selections_outdated")
    def test_title_cleanup_persists_clean_title_without_lookup_exclusion(
        self, mark_outdated
    ):
        movie = Movie.objects.create(
            name="4K-AMZ - Bliss (2021)",
            display_name="4K-AMZ - Bliss (2021)",
            year=2021,
        )
        request = self.factory.post(
            "/api/vod/metadata/apply-title-cleanup/",
            {
                "title_rules": [
                    {
                        "match_type": "starts_with",
                        "value": "4K-AMZ - ",
                        "action": "remove",
                    }
                ],
                "selections": [{"id": movie.id, "content_type": "movie"}],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view(
            {"post": "apply_title_cleanup"}
        )(request)

        self.assertEqual(response.status_code, 200)
        movie.refresh_from_db()
        self.assertEqual(movie.clean_title, "Bliss")
        self.assertFalse(movie.tmdb_lookup_excluded)
        self.assertEqual(movie.tmdb_enrichment_signature, "locked")
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(response.data["processed"], 1)

    def test_title_cleanup_rejects_a_locked_canonical(self):
        movie = Movie.objects.create(
            name="NF - Locked Movie",
            clean_title="Previously reviewed",
            tmdb_enrichment_signature="processed",
        )
        request = self.factory.post(
            "/api/vod/metadata/apply-title-cleanup/",
            {
                "title_rules": ["NF -"],
                "selections": [{"id": movie.id, "content_type": "movie"}],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view(
            {"post": "apply_title_cleanup"}
        )(request)

        self.assertEqual(response.status_code, 400)
        movie.refresh_from_db()
        self.assertEqual(movie.clean_title, "Previously reviewed")
        self.assertEqual(movie.tmdb_enrichment_signature, "processed")
        self.assertIn("1 selected title is locked", response.data["detail"])

    def test_provider_cleanup_locks_only_unprocessed_canonicals(self):
        CoreSettings.set_vod_metadata_settings(
            languages=["de-DE", "en-US"],
            auto_enrich=False,
            match_missing=False,
            title_rules=["NF -"],
        )
        locked = Movie.objects.create(
            name="NF - Locked Movie",
            clean_title="Keep reviewed title",
            tmdb_enrichment_signature="processed",
        )
        unlocked = Movie.objects.create(name="NF - New Movie")

        updated = refresh_canonical_clean_titles(
            [locked.id, unlocked.id],
            lock_processed=True,
        )

        locked.refresh_from_db()
        unlocked.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(locked.clean_title, "Keep reviewed title")
        self.assertEqual(locked.tmdb_enrichment_signature, "processed")
        self.assertEqual(unlocked.clean_title, "New Movie")
        self.assertEqual(unlocked.tmdb_enrichment_signature, "locked")

    @patch("apps.vod.tasks.enqueue_tmdb_enrichment")
    def test_tmdb_reset_clears_only_curated_snapshot_then_reloads_selection(
        self, enqueue
    ):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        movie = Movie.objects.create(
            name="Provider title",
            display_name="TMDB title",
            tmdb_id="123",
            description="Provider description",
            tmdb_match_id="123",
            tmdb_imdb_id="tt123",
            tmdb_metadata={"id": "123", "status": "matched"},
            tmdb_status="matched",
            tmdb_enriched_at=timezone.now(),
            tmdb_enrichment_signature="",
        )
        enqueue.return_value = {"queued": True, "task_id": "task", "status": "queued"}
        request = self.factory.post(
            "/api/vod/metadata/reset/",
            {
                "mode": "tmdb",
                "selections": [{"id": movie.id, "content_type": "movie"}],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "reset"})(request)

        self.assertEqual(response.status_code, 202)
        movie.refresh_from_db()
        self.assertEqual(movie.name, "Provider title")
        self.assertEqual(movie.description, "Provider description")
        self.assertEqual(movie.tmdb_id, "123")
        self.assertEqual(movie.display_name, "")
        self.assertEqual(movie.tmdb_metadata, {})
        self.assertEqual(movie.tmdb_status, "")
        self.assertEqual(movie.tmdb_match_id, "123")
        self.assertEqual(movie.tmdb_imdb_id, "tt123")
        enqueue.assert_called_once_with(
            trigger_reason="Selected VOD metadata was reset",
            force=True,
            movie_ids=[movie.id],
            series_ids=[],
        )

    @patch("apps.vod.tasks.enqueue_tmdb_enrichment")
    def test_reset_rejects_a_locked_title(self, enqueue):
        CoreSettings.set_vod_metadata_settings(
            api_token="stored-secret",
            languages=["en-US"],
            auto_enrich=False,
            match_missing=False,
        )
        movie = Movie.objects.create(
            name="Protected provider title",
            display_name="Protected custom title",
            tmdb_enrichment_signature="locked",
        )
        request = self.factory.post(
            "/api/vod/metadata/reset/",
            {
                "mode": "provider",
                "selections": [
                    {"id": movie.id, "content_type": "movie"}
                ],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "reset"})(request)

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("1 selected title is locked", response.data["detail"])
        movie.refresh_from_db()
        self.assertEqual(movie.display_name, "Protected custom title")
        self.assertEqual(movie.tmdb_enrichment_signature, "locked")
        enqueue.assert_not_called()

    def test_provider_reset_rebuilds_canonical_fields_from_stored_sources(self):
        account = M3UAccount.objects.create(
            name="Provider metadata",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        movie = Movie.objects.create(
            name="Provider title",
            display_name="TMDB title",
            description="Stale description",
            year=2021,
            rating="9.9",
            genre="Stale genre",
            duration_secs=9999,
            custom_properties={
                "_manual_metadata": {
                    "description": "Manual description",
                    "youtube_trailer": "manual-trailer",
                }
            },
            tmdb_metadata={"id": "123", "status": "matched"},
            tmdb_match_id="123",
            tmdb_status="matched",
            tmdb_enriched_at=timezone.now(),
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="movie-1",
            custom_properties={
                "detailed_info": {
                    "name": "Fresh provider title",
                    "plot": "Fresh provider description",
                    "trailer": "provider-trailer",
                }
            },
        )
        request = self.factory.post(
            "/api/vod/metadata/reset/",
            {
                "mode": "provider",
                "selections": [{"id": movie.id, "content_type": "movie"}],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        response = VODMetadataViewSet.as_view({"post": "reset"})(request)

        self.assertEqual(response.status_code, 200)
        movie.refresh_from_db()
        self.assertEqual(movie.description, "Fresh provider description")
        self.assertEqual(movie.display_name, "Fresh provider title")
        self.assertEqual(movie.clean_title, "Fresh provider title")
        self.assertEqual(movie.tmdb_metadata, {})
        self.assertEqual(movie.tmdb_status, "")
        self.assertEqual(movie.tmdb_match_id, "")
        self.assertIsNone(movie.year)
        self.assertEqual(movie.rating, "")
        self.assertEqual(movie.genre, "")
        self.assertIsNone(movie.duration_secs)
        self.assertEqual(
            movie.custom_properties["youtube_trailer"], "provider-trailer"
        )
        self.assertNotIn("_manual_metadata", movie.custom_properties)

    def test_manual_tmdb_match_moves_only_the_selected_provider_source(self):
        account = M3UAccount.objects.create(
            name="TMDB test",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        movie = Movie.objects.create(
            name="Wrong provider match",
            tmdb_id="111",
            tmdb_match_id="111",
            tmdb_metadata={"id": "111", "status": "matched"},
            tmdb_status="matched",
            tmdb_enriched_at=timezone.now(),
        )
        target = Movie.objects.create(
            name="Correct title",
            tmdb_id="76600",
            tmdb_match_id="76600",
            tmdb_metadata={"id": "76600", "status": "matched"},
            tmdb_status="matched",
        )
        relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="movie-1",
        )
        request = self.factory.patch(
            "/api/vod/source-relations/relation-tmdb-match/",
            {
                "tmdb_id": "76600",
                "selections": [
                    {"content_type": "movie", "relation_id": relation.id}
                ],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        view = VODSourceRelationViewSet.as_view({"patch": "relation_tmdb_match"})
        response = view(request)

        self.assertEqual(response.status_code, 409)

        confirmed_request = self.factory.patch(
            "/api/vod/source-relations/relation-tmdb-match/",
            {
                "tmdb_id": "76600",
                "confirmed": True,
                "selections": [
                    {"content_type": "movie", "relation_id": relation.id}
                ],
            },
            format="json",
        )
        force_authenticate(confirmed_request, user=self.admin)
        with (
            patch(
                "apps.vod.profile_selection.mark_profile_selections_outdated"
            ),
            patch("apps.vod.catalog_cache.bump_catalog_generation") as bump_catalog,
        ):
            response = view(confirmed_request)

        movie.refresh_from_db()
        relation.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(movie.tmdb_id, "111")
        self.assertEqual(relation.movie_id, target.id)
        self.assertEqual(relation.tmdb_override_id, "76600")
        self.assertEqual(response.data["moved_sources"], 1)
        bump_catalog.assert_called_once_with(invalidate_selections=False)

    def test_canonical_target_search_finds_existing_library_title(self):
        account = M3UAccount.objects.create(
            name="Canonical search",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        target = Movie.objects.create(
            name="Daredevil Born Again",
            display_name="Daredevil: Born Again",
            clean_title="Daredevil Born Again",
            year=2025,
            tmdb_match_id="202555",
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=target,
            stream_id="canonical-search",
        )
        request = self.factory.get(
            "/api/vod/source-relations/canonical-targets/",
            {
                "content_type": "movie",
                "search": "Daredevil",
                "year": "2025",
            },
        )
        force_authenticate(request, user=self.admin)

        response = VODSourceRelationViewSet.as_view(
            {"get": "canonical_targets"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["id"], target.id)
        self.assertEqual(response.data["results"][0]["tmdb_id"], "202555")
        self.assertEqual(response.data["results"][0]["source_count"], 1)

    def test_source_can_move_to_existing_canonical_without_tmdb(self):
        account = M3UAccount.objects.create(
            name="Canonical move",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        original = Movie.objects.create(name="Wrong title", year=2024)
        target = Movie.objects.create(
            name="Correct title",
            display_name="Correct title",
            clean_title="Correct title",
            year=2024,
        )
        relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=original,
            stream_id="move-existing",
        )
        request = self.factory.patch(
            "/api/vod/source-relations/relation-tmdb-match/",
            {
                "target_id": target.id,
                "selections": [
                    {"content_type": "movie", "relation_id": relation.id}
                ],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        with (
            patch("apps.vod.catalog_cache.bump_catalog_generation"),
            patch("apps.vod.profile_selection.mark_profile_selections_outdated"),
        ):
            response = VODSourceRelationViewSet.as_view(
                {"patch": "relation_tmdb_match"}
            )(request)

        relation.refresh_from_db()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(relation.movie_id, target.id)
        self.assertEqual(relation.tmdb_override_id, "")
        self.assertEqual(response.data["target"]["id"], target.id)

    def test_source_can_create_and_move_to_provider_backed_canonical_title(self):
        account = M3UAccount.objects.create(
            name="Canonical create",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        original = Movie.objects.create(name="Previously grouped title")
        relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=original,
            stream_id="move-new",
            custom_properties={
                "basic_data": {
                    "name": "D+ - Provider title (2026)",
                    "year": "2026",
                    "plot": "Provider description",
                }
            },
        )
        request = self.factory.patch(
            "/api/vod/source-relations/relation-tmdb-match/",
            {
                "create_from_provider": True,
                "selections": [
                    {"content_type": "movie", "relation_id": relation.id}
                ],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        with (
            patch("apps.vod.catalog_cache.bump_catalog_generation"),
            patch("apps.vod.profile_selection.mark_profile_selections_outdated"),
        ):
            response = VODSourceRelationViewSet.as_view(
                {"patch": "relation_tmdb_match"}
            )(request)

        relation.refresh_from_db()
        created = Movie.objects.get(pk=relation.movie_id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(created.name, "D+ - Provider title (2026)")
        self.assertEqual(created.display_name, "D+ - Provider title (2026)")
        self.assertEqual(created.clean_title, "D+ - Provider title")
        self.assertEqual(created.description, "Provider description")
        self.assertEqual(created.year, 2026)
        self.assertNotIn("_manual_metadata", created.custom_properties or {})
        self.assertEqual(response.data["target"]["id"], created.id)
        self.assertEqual(response.data["target"]["relation_id"], relation.id)

    def test_manual_series_match_moves_its_episode_sources(self):
        account = M3UAccount.objects.create(
            name="TMDB series test",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        original = Series.objects.create(
            name="Wrong series",
            tmdb_id="111",
            tmdb_match_id="111",
        )
        target = Series.objects.create(
            name="Correct series",
            tmdb_id="1399",
            tmdb_match_id="1399",
            tmdb_metadata={"id": "1399", "status": "matched"},
            tmdb_status="matched",
        )
        relation = M3USeriesRelation.objects.create(
            m3u_account=account,
            series=original,
            external_series_id="series-1",
        )
        episode = Episode.objects.create(
            series=original,
            name="Provider episode",
            season_number=1,
            episode_number=2,
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            m3u_account=account,
            series_relation=relation,
            episode=episode,
            stream_id="episode-1",
        )
        request = self.factory.patch(
            "/api/vod/source-relations/relation-tmdb-match/",
            {
                "tmdb_id": "1399",
                "confirmed": True,
                "selections": [
                    {"content_type": "series", "relation_id": relation.id}
                ],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)

        with (
            patch(
                "apps.vod.profile_selection.mark_profile_selections_outdated"
            ),
            patch("apps.vod.catalog_cache.bump_catalog_generation") as bump_catalog,
        ):
            response = VODSourceRelationViewSet.as_view(
                {"patch": "relation_tmdb_match"}
            )(request)

        relation.refresh_from_db()
        episode_relation.refresh_from_db()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(relation.series_id, target.id)
        self.assertEqual(episode_relation.episode.series_id, target.id)
        self.assertEqual(episode_relation.episode.season_number, 1)
        self.assertEqual(episode_relation.episode.episode_number, 2)
        bump_catalog.assert_called_once_with(invalidate_selections=False)

    def test_watchdog_ends_a_lost_running_status(self):
        state = VODMetadataState.objects.create(
            status=VODMetadataState.Status.RUNNING,
            task_id="lost-task",
            progress={"phase": "Fetching TMDB metadata", "percent": 12},
        )
        VODMetadataState.objects.filter(pk=state.pk).update(
            updated_at=timezone.now() - timedelta(minutes=20)
        )

        with (
            patch("celery.result.AsyncResult") as async_result,
            patch("apps.vod.tasks.is_task_lock_held", return_value=False),
        ):
            async_result.return_value.state = "PENDING"
            result = reconcile_vod_metadata_queue.run()

        state.refresh_from_db()
        self.assertTrue(result["repaired"])
        self.assertEqual(state.status, VODMetadataState.Status.FAILED)

    def test_active_enrichment_records_one_follow_up_pass(self):
        state = VODMetadataState.objects.create(
            status=VODMetadataState.Status.RUNNING,
            task_id="active-task",
        )

        result = enqueue_tmdb_enrichment(
            trigger_reason="A manual match changed during the active pass",
        )

        state.refresh_from_db()
        self.assertFalse(result["queued"])
        self.assertTrue(state.rerun_requested)
