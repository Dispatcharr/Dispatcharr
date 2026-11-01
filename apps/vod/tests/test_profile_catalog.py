from unittest.mock import patch

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.output.views import (
    xc_get_vod_categories,
    xc_get_vod_info,
    xc_get_vod_streams,
)
from apps.vod import profile_catalog
from apps.vod.models import (
    M3UMovieRelation,
    M3UVODCategoryRelation,
    Movie,
    VODCategory,
    VODProfile,
    VODProfileAssignment,
    VODProfileCategoryRule,
    VODProfileEntry,
)
from apps.vod.profiles import output_name


class OutputNameTests(SimpleTestCase):
    metadata = {"audio_languages": ["ger", "eng"], "resolution": "2160p"}

    template = VODProfile._meta.get_field("name_template").default

    def test_default_format_matches_the_live_title_suffix(self):
        self.assertEqual(
            output_name(self.template, "Film", self.metadata),
            "Film [GER/ENG · 2160p]",
        )
        self.assertEqual(output_name(self.template, "Film", {}), "Film")
        self.assertEqual(
            output_name(self.template, "|USA| Film -", self.metadata),
            "|USA| Film - [GER/ENG · 2160p]",
        )
        self.assertEqual(
            output_name(self.template, "Film", {"video_features": ["hdr"]}),
            "Film [HDR]",
        )

    def test_placeholders_and_edition(self):
        self.assertEqual(
            output_name(
                "{title} ({year}) - {dub} {format}",
                "Film",
                self.metadata,
                year=2020,
                extension="mkv",
            ),
            "Film (2020) - GER/ENG MKV",
        )
        self.assertEqual(output_name("{title} ({year})", "Film", {}), "Film")
        self.assertEqual(
            output_name("{title} ({sub} | {provider})", "Film", {}, provider="A"),
            "Film (A)",
        )
        self.assertEqual(
            output_name(self.template, "Film", self.metadata, edition="4K"),
            "Film 4K [GER/ENG · 2160p]",
        )
        self.assertEqual(
            output_name("{title} | {edition}", "Film", {}, edition="4K"), "Film | 4K"
        )


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class ProfileCatalogTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/player_api.php")
        self.user = User.objects.create_user(
            username="catalog-user", password="test", user_level=1
        )
        self.high = M3UAccount.objects.create(
            name="High", account_type="XC", priority=10, is_active=True
        )
        self.low = M3UAccount.objects.create(
            name="Low", account_type="XC", priority=1, is_active=True
        )
        self.german = VODCategory.objects.create(
            name="DE | Movies", category_type="movie"
        )
        self.english = VODCategory.objects.create(
            name="EN | Movies", category_type="movie"
        )
        for account in (self.high, self.low):
            for category in (self.german, self.english):
                M3UVODCategoryRelation.objects.create(
                    m3u_account=account, category=category, enabled=True
                )
        self.film = Movie.objects.create(name="Film", year=2020)
        self.film_en = self.source(self.high, self.film, self.english, ["eng"], "1080p")
        self.film_de = self.source(self.low, self.film, self.german, ["ger"], "1080p")
        self.film_4k = self.source(self.low, self.film, self.german, ["ger"], "2160p")
        self.other = Movie.objects.create(name="Other", year=2021)
        self.other_en = self.source(
            self.high, self.other, self.english, ["eng"], "720p"
        )
        self.default = VODProfile.objects.get(is_default=True)

    def source(self, account, movie, category, languages, resolution):
        return M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            category=category,
            stream_id=f"{account.pk}-{movie.pk}-{resolution}-{languages[0]}",
            container_extension="mkv",
            declared_metadata={
                "audio_languages": languages,
                "resolution": resolution,
            },
        )

    def streams(self, user=None):
        return {
            row["name"]: row["stream_id"]
            for row in xc_get_vod_streams(self.request, user or self.user)
        }

    def profile(self, rules=((".*", "enable"),), **fields):
        profile = VODProfile.objects.create(name="Custom", **fields)
        VODProfileAssignment.objects.create(user=self.user, profile=profile)
        for order, (pattern, action, *case_sensitive) in enumerate(rules):
            VODProfileCategoryRule.objects.create(
                profile=profile,
                scope="movie",
                regex_pattern=pattern,
                action=action,
                case_sensitive=bool(case_sensitive),
                order=order,
            )
        return profile

    def build(self, profile):
        counts = profile_catalog.build_catalog(profile)
        profile.refresh_from_db()
        return counts

    def test_default_catalogue_reproduces_live_output(self):
        live = xc_get_vod_streams(self.request, self.user)
        live_german = xc_get_vod_streams(
            self.request, self.user, category_id=self.german.pk
        )
        live_categories = xc_get_vod_categories(self.user)
        self.assertEqual(
            [row["name"] for row in live], ["Film [ENG · 1080p]", "Other [ENG · 720p]"]
        )
        self.assertEqual([row["name"] for row in live_german], ["Film [GER · 1080p]"])
        counts = self.build(self.default)
        self.assertEqual(self.default.catalog_status, VODProfile.CatalogStatus.READY)
        # Film's best German source is kept for category requests only.
        self.assertEqual(counts["movie"], {"titles": 2, "entries": 2})
        self.assertEqual(VODProfileEntry.objects.count(), 3)
        self.assertEqual(xc_get_vod_streams(self.request, self.user), live)
        self.assertEqual(
            xc_get_vod_streams(self.request, self.user, category_id=self.german.pk),
            live_german,
        )
        self.assertEqual(xc_get_vod_categories(self.user), live_categories)
        self.assertEqual(len(live_categories), 2)

    def test_unbuilt_custom_profile_offers_nothing(self):
        self.profile()
        self.assertEqual(self.streams(), {})
        with self.assertRaises(Http404):
            xc_get_vod_info(self.request, self.user, self.film.pk)

    def test_filters_and_ranking_choose_the_source(self):
        self.build(
            self.profile(
                content_filters={"audio_languages": ["ger"]},
                ranking=["resolution_desc", "provider"],
            )
        )
        self.assertEqual(list(self.streams()), ["Film [GER · 2160p]"])
        entry = VODProfileEntry.objects.get(profile__name="Custom")
        self.assertEqual(entry.relation_id, self.film_4k.pk)
        self.assertEqual(entry.source_ids, [self.film_4k.pk])
        with self.assertRaises(Http404):
            xc_get_vod_info(self.request, self.user, self.other.pk)

    def test_excluded_titles_are_left_out(self):
        self.build(
            self.profile(
                excluded_titles=[{"content_type": "movie", "id": self.film.pk}]
            )
        )
        self.assertEqual(list(self.streams()), ["Other [ENG · 720p]"])
        with self.assertRaises(Http404):
            xc_get_vod_info(self.request, self.user, self.film.pk)

    def test_import_rules_first_match_decides_and_unmatched_is_disabled(self):
        profile = self.profile(
            rules=[("^EN", "disable"), ("^DE", "enable", True)]
        )
        self.build(profile)
        self.assertEqual(list(self.streams()), ["Film [GER · 1080p]"])
        self.assertEqual(
            [row["category_name"] for row in xc_get_vod_categories(self.user)],
            ["DE | Movies"],
        )
        profile.category_rules.update(regex_pattern="^de")
        self.build(profile)
        self.assertEqual(self.streams(), {})

    def test_manual_choices_win_over_import_rules(self):
        low_german, high_english = (
            M3UVODCategoryRelation.objects.get(m3u_account=account, category=category)
            for account, category in (
                (self.low, self.german),
                (self.high, self.english),
            )
        )
        profile = self.profile(
            rules=[("^DE", "disable")],
            category_choices=[{"relation": low_german.pk, "enabled": True}],
        )
        self.build(profile)
        self.assertEqual(list(self.streams()), ["Film [GER · 1080p]"])
        profile.category_choices = [
            {"relation": low_german.pk, "enabled": False},
            {"relation": high_english.pk, "enabled": True},
        ]
        profile.save()
        self.build(profile)
        self.assertEqual(
            sorted(self.streams()), ["Film [ENG · 1080p]", "Other [ENG · 720p]"]
        )

    def test_editions_get_their_own_entry_and_public_id(self):
        self.build(
            self.profile(
                content_filters={"audio_languages": ["ger"]},
                edition_rules=[
                    {
                        "id": "uhd",
                        "name": "4K",
                        "title_suffix": "4K",
                        "min_resolution": 2160,
                        "max_resolution": 0,
                        "required_audio_languages": [],
                        "required_subtitle_languages": [],
                        "required_video_features": [],
                    }
                ],
            )
        )
        streams = self.streams()
        self.assertEqual(set(streams), {"Film [GER · 1080p]", "Film 4K [GER · 2160p]"})
        self.assertNotEqual(
            streams["Film [GER · 1080p]"], streams["Film 4K [GER · 2160p]"]
        )

    def test_sources_entries_list_every_provider_source(self):
        from apps.proxy.vod_proxy.views import _get_content_and_relation
        from apps.vod.models import VODContentAlias

        # The same German 1080p copy from a second account stays separate.
        copy = self.source(self.high, self.film, self.german, ["ger"], "1080p")
        counts = self.build(self.profile(output_mode="variants"))
        self.assertEqual(counts["movie"], {"titles": 2, "entries": 5})
        rows = xc_get_vod_streams(self.request, self.user)
        self.assertEqual(
            sorted(row["name"] for row in rows),
            [
                "Film [ENG · 1080p]",
                "Film [GER · 1080p]",
                "Film [GER · 1080p]",
                "Film [GER · 2160p]",
                "Other [ENG · 720p]",
            ],
        )
        self.assertEqual(len({row["stream_id"] for row in rows}), 5)
        entries = dict(
            VODProfileEntry.objects.filter(profile__name="Custom").values_list(
                "relation_id", "source_ids"
            )
        )
        # Each entry plays only its own source, so there is no failover.
        self.assertEqual(entries[copy.pk], [copy.pk])
        self.assertEqual(entries[self.film_de.pk], [self.film_de.pk])
        for relation in (copy, self.film_de):
            entry = VODProfileEntry.objects.get(
                profile__name="Custom", relation_id=relation.pk
            )
            alias = VODContentAlias.objects.get(legacy_id=entry.public_id)
            _content, selected, candidates = _get_content_and_relation(
                "movie", str(alias.legacy_uuid), user=self.user
            )
            self.assertEqual((selected, candidates), (relation, [relation]))
            info = xc_get_vod_info(self.request, self.user, entry.public_id)
            self.assertEqual(info["movie_data"]["stream_id"], entry.public_id)

    def test_titles_without_tmdb_id_can_be_left_out_or_listed(self):
        Movie.objects.filter(pk=self.film.pk).update(tmdb_match_id="15916")
        Movie.objects.filter(pk=self.other.pk).update(tmdb_id="")
        profile = self.profile(content_filters={"missing_tmdb_mode": "exclude"})
        self.build(profile)
        self.assertEqual(list(self.streams()), ["Film [ENG · 1080p]"])
        profile.content_filters = {"missing_tmdb_mode": "only"}
        profile.save()
        self.build(profile)
        self.assertEqual(list(self.streams()), ["Other [ENG · 720p]"])

    def test_enriched_metadata_sends_the_library_ids(self):
        Movie.objects.filter(pk=self.film.pk).update(
            tmdb_match_id="15916", tmdb_imdb_id="tt0208502", tmdb_id="", imdb_id=""
        )
        self.build(self.default)

        def film():
            rows = xc_get_vod_streams(self.request, self.user)
            return next(row for row in rows if row["name"].startswith("Film"))

        self.assertEqual((film()["tmdb_id"], film()["imdb_id"]), ("", ""))
        self.default.metadata_source = "enriched"
        self.default.save()
        self.assertEqual(
            (film()["tmdb_id"], film()["imdb_id"]), ("15916", "tt0208502")
        )
        info = xc_get_vod_info(self.request, self.user, film()["stream_id"])
        self.assertEqual(info["info"]["tmdb_id"], "15916")

    def test_sources_entries_ignore_editions(self):
        self.build(
            self.profile(
                output_mode="variants",
                edition_rules=[
                    {
                        "id": "uhd",
                        "name": "4K",
                        "title_suffix": "4K",
                        "min_resolution": 2160,
                        "max_resolution": 0,
                        "required_audio_languages": [],
                        "required_subtitle_languages": [],
                        "required_video_features": [],
                    }
                ],
            )
        )
        self.assertIn("Film [GER · 2160p]", self.streams())

    def test_grouped_output_offers_one_category_per_type(self):
        from apps.vod.profiles import GROUP_CATEGORY_IDS

        self.build(self.profile(output_groups="movie_series"))
        group = GROUP_CATEGORY_IDS["movie"]
        self.assertEqual(
            xc_get_vod_categories(self.user),
            [{"category_id": str(group), "category_name": "Movies", "parent_id": 0}],
        )
        rows = xc_get_vod_streams(self.request, self.user)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["category_id"] for row in rows}, {str(group)})
        self.assertEqual(
            xc_get_vod_streams(self.request, self.user, category_id=str(group)), rows
        )
        self.assertEqual(
            xc_get_vod_streams(self.request, self.user, category_id=self.german.pk),
            [],
        )
        info = xc_get_vod_info(self.request, self.user, rows[0]["stream_id"])
        self.assertEqual(info["movie_data"]["category_id"], str(group))

    def test_clean_titles_use_the_library_cleanup_only(self):
        Movie.objects.filter(pk=self.film.pk).update(
            clean_title="Clean Film",
            tmdb_metadata={"localized": {"en-US": {"title": "Translated"}}},
        )
        self.build(self.profile(title_source="clean"))
        self.assertIn("Clean Film [ENG · 1080p]", self.streams())

    def test_public_ids_are_shared_between_profiles(self):
        live = self.streams()
        self.build(self.profile())
        self.assertEqual(self.streams(), live)

    def test_rebuild_switches_generation_and_keeps_old_on_failure(self):
        self.build(self.default)
        first = self.default.catalog_generation
        self.build(self.default)
        self.assertNotEqual(self.default.catalog_generation, first)
        self.assertFalse(VODProfileEntry.objects.filter(generation=first).exists())
        current = self.default.catalog_generation
        with patch.object(
            profile_catalog, "_write", side_effect=RuntimeError("disk full")
        ):
            with self.assertRaises(RuntimeError):
                profile_catalog.build_catalog(self.default)
        self.default.refresh_from_db()
        self.assertEqual(self.default.catalog_status, VODProfile.CatalogStatus.FAILED)
        self.assertEqual(self.default.catalog_generation, current)
        self.assertEqual(self.default.catalog_error, "disk full")
        self.assertEqual(len(self.streams()), 2)

    def test_settings_saved_during_a_build_stay_pending(self):
        original = profile_catalog._build_content

        def change_settings(profile, generation, content_type):
            VODProfile.objects.filter(pk=profile.pk).update(ranking=["resolution_asc"])
            return original(profile, generation, content_type)

        with patch.object(profile_catalog, "_build_content", change_settings):
            self.build(self.default)
        self.assertEqual(self.default.catalog_status, VODProfile.CatalogStatus.PENDING)

    def test_playback_follows_profile_sources(self):
        from apps.proxy.vod_proxy.views import _get_content_and_relation
        from apps.vod.models import VODContentAlias

        self.build(
            self.profile(
                content_filters={"audio_languages": ["ger"]},
                ranking=["resolution_asc"],
            )
        )
        entry = VODProfileEntry.objects.get(profile__name="Custom")
        alias = VODContentAlias.objects.get(legacy_id=entry.public_id)
        for identifier in (alias.legacy_uuid, self.film.uuid):
            _content, relation, candidates = _get_content_and_relation(
                "movie", str(identifier), user=self.user
            )
            self.assertEqual(relation, self.film_de)
            self.assertEqual(candidates, [self.film_de])
        _content, relation, _candidates = _get_content_and_relation(
            "movie", str(self.other.uuid), user=self.user
        )
        self.assertIsNone(relation)
        _content, relation, _candidates = _get_content_and_relation(
            "movie", str(self.film.uuid)
        )
        self.assertEqual(relation, self.film_en)

    @patch("apps.vod.profile_catalog.request_catalog_build")
    def test_saving_relevant_settings_queues_a_build(self, request_build):
        admin = User.objects.create_user(
            username="catalog-admin", password="test", user_level=10
        )
        client = APIClient()
        client.force_authenticate(admin)
        url = reverse("api:vod:profile-detail", args=[self.default.pk])
        self.build(self.default)
        response = client.patch(url, {"name_template": "{title}"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["catalog_status"], "ready")
        request_build.assert_not_called()
        response = client.patch(url, {"ranking": ["resolution_desc"]}, format="json")
        self.assertEqual(response.data["catalog_status"], "pending")
        request_build.assert_called_once_with([self.default.pk], countdown=5)

    def test_title_and_metadata_sources(self):
        from apps.vod import library

        settings = {**library.library_settings(), "languages": ["en-US", "de-DE"]}
        patcher = patch("apps.vod.library.library_settings", return_value=settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        Movie.objects.filter(pk=self.film.pk).update(
            description="Provider plot",
            genre="Provider genre",
            tmdb_metadata={
                "genres": [{"name": "Drama"}, {"name": "Fantasy"}],
                "rating": 7.5,
                "release_date": "2010-09-27",
                "director": "Colin Levy",
                "localized": {
                    "en-US": {"title": "The Film", "overview": "English plot"},
                    "de-DE": {"title": "Der Film", "overview": "Deutscher Text"},
                },
            },
        )
        self.build(self.default)

        def film(rows):
            return next(row for row in rows if "Film" in row["name"])

        # Provider titles and metadata, as clients get them today.
        row = film(xc_get_vod_streams(self.request, self.user))
        self.assertEqual(row["name"], "Film [ENG · 1080p]")
        self.assertEqual(
            (row["plot"], row["genre"]), ("Provider plot", "Provider genre")
        )
        # The title source changes only the title.
        self.default.title_source = "de-DE"
        self.default.save()
        row = film(xc_get_vod_streams(self.request, self.user))
        self.assertEqual(row["name"], "Der Film [ENG · 1080p]")
        self.assertEqual(row["plot"], "Provider plot")
        # Library metadata follows the title language.
        self.default.metadata_source = "enriched"
        self.default.save()
        row = film(xc_get_vod_streams(self.request, self.user))
        self.assertEqual(
            (row["plot"], row["genre"], row["rating"], row["year"]),
            ("Deutscher Text", "Drama, Fantasy", "7.5", 2010),
        )
        info = xc_get_vod_info(self.request, self.user, row["stream_id"])["info"]
        self.assertEqual(
            (info["plot"], info["genre"], info["director"], info["release_date"]),
            ("Deutscher Text", "Drama, Fantasy", "Colin Levy", "2010-09-27"),
        )
        # Provider titles with Library metadata use the first Library language.
        self.default.title_source = "provider"
        self.default.save()
        row = film(xc_get_vod_streams(self.request, self.user))
        self.assertEqual(
            (row["name"], row["plot"]), ("Film [ENG · 1080p]", "English plot")
        )

@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class ProfileEditorApiTests(TestCase):
    setUp = ProfileCatalogTests.setUp
    source = ProfileCatalogTests.source

    def admin_client(self):
        admin, _ = User.objects.get_or_create(
            username="editor-admin", defaults={"user_level": 10}
        )
        client = APIClient()
        client.force_authenticate(admin)
        return client

    def test_options_list_users_accounts_and_categories(self):
        response = self.admin_client().get(reverse("api:vod:profile-options"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(
            {"id": self.user.pk, "name": "catalog-user"}, response.data["users"]
        )
        self.assertEqual(
            [row["name"] for row in response.data["accounts"]], ["High", "Low"]
        )
        self.assertEqual(len(response.data["categories"]), 4)
        self.assertEqual(
            set(response.data["categories"][0]),
            {
                "id",
                "name",
                "category",
                "category_type",
                "account",
                "enabled",
                "custom_properties",
            },
        )
        self.assertIn("2160p", response.data["resolutions"])
        self.assertIn("metadata_languages", response.data)

    def preview(self, profile, **query):
        return self.admin_client().post(
            reverse("api:vod:profile-preview"),
            {
                "profile": profile,
                "profile_id": self.default.pk,
                "content_type": "movie",
                **query,
            },
            format="json",
        )

    def test_preview_lists_the_offered_titles_of_unsaved_settings(self):
        response = self.preview(
            {
                "name": "Default",
                "name_template": "{title} ({year}) {dub}",
                "content_filters": {"audio_languages": ["ger"]},
                "ranking": ["resolution_desc"],
            }
        )
        self.assertEqual(response.status_code, 200, response.data)
        # "Other" has no German source, so it is not part of the preview.
        self.assertEqual(response.data["count"], 1)
        (film,) = response.data["results"]
        self.assertEqual(film["entries"][0]["name"], "Film (2020) GER")
        self.assertEqual(film["entries"][0]["metadata"]["resolution"], "2160p")
        self.assertEqual(film["entries"][0]["provider"], "Low")
        self.assertEqual(film["entries"][0]["category"], "DE | Movies")
        self.assertFalse(VODProfileEntry.objects.exists())
        response = self.preview({"ranking": ["popularity"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("ranking", response.data["profile"])

    def test_preview_explains_each_source(self):
        response = self.preview(
            {
                "content_filters": {"audio_languages": ["ger"]},
                "ranking": ["resolution_asc"],
            },
            search="film",
        )
        sources = {
            row["id"]: (row["state"], row["reason"])
            for row in response.data["results"][0]["sources"]
        }
        self.assertEqual(
            sources,
            {
                self.film_de.pk: ("selected", ""),
                # Allowed, but it cannot stand in for the 1080p entry.
                self.film_4k.pk: ("unused", ""),
                self.film_en.pk: ("skipped", "Does not match the content filters."),
            },
        )

    def test_preview_pages_offered_titles_and_lists_excluded_ones(self):
        response = self.preview({}, page_size=1, page=2)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            [row["title"] for row in response.data["results"]], ["Other"]
        )
        response = self.preview({}, account=self.low.pk)
        self.assertEqual([row["title"] for row in response.data["results"]], ["Film"])
        # The filter narrows the titles; the entry still uses the best source.
        self.assertEqual(
            response.data["results"][0]["entries"][0]["source_id"], self.film_en.pk
        )
        response = self.preview({}, category=self.english.pk)
        self.assertEqual(response.data["count"], 2)
        excluded = {"excluded_titles": [{"content_type": "movie", "id": self.film.pk}]}
        response = self.preview(excluded)
        self.assertEqual([row["title"] for row in response.data["results"]], ["Other"])
        response = self.preview(excluded, excluded=True)
        self.assertEqual(response.data["count"], 1)
        self.assertTrue(response.data["results"][0]["excluded"])
        self.assertEqual(
            response.data["results"][0]["reason"], "Excluded from this profile."
        )

    def test_preview_leaves_out_titles_the_filters_drop(self):
        disabled = M3UVODCategoryRelation.objects.get(
            m3u_account=self.high, category=self.english
        )
        profile = {"category_choices": [{"relation": disabled.pk, "enabled": False}]}
        self.assertEqual(self.preview(profile, search="oth").data["count"], 0)
        film = self.preview(profile, search="film").data["results"][0]
        reasons = {source["id"]: source["reason"] for source in film["sources"]}
        self.assertEqual(reasons[self.film_en.pk], "Category disabled in this profile.")
        Movie.objects.filter(pk=self.other.pk).update(genre="Horror")
        response = self.preview(
            {"content_filters": {"excluded_genres": ["horror"]}}, search="Other"
        )
        self.assertEqual(response.data["count"], 0)

    @patch("apps.vod.profile_catalog.request_catalog_build")
    def test_rebuild_queues_an_immediate_build(self, request_build):
        response = self.admin_client().post(
            reverse("api:vod:profile-rebuild", args=[self.default.pk])
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["catalog_status"], "pending")
        request_build.assert_called_once_with([self.default.pk], countdown=0)
