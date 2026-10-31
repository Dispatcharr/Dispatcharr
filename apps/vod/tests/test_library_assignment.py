"""Local canonical assignment must be relation-exact and survive provider imports."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.vod.models import Episode, M3UEpisodeRelation, VODContentAlias

from . import test_library_completion as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryAssignmentTests(TestCase):
    setUp = fixtures.LibraryCompletionTests.setUp
    endpoint = fixtures.LibraryCompletionTests.endpoint
    import_rows = fixtures.LibraryCompletionTests.import_rows

    def assign(self, kind, sources, **values):
        return self.client.patch(
            self.endpoint("source-metadata"),
            {
                "items": [{"content_type": kind, "id": row.pk} for row in sources],
                **values,
            },
            format="json",
        )

    def test_local_lookup_is_read_only_and_never_requires_tmdb(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                source = self.import_rows(kind, [{"name": "2012", "year": 2009}]).get()
                title = getattr(source, kind)
                title.display_name = "2012"
                title.tmdb_id = "14161"
                title.save()
                before = list(fixture[0].objects.values())
                with patch("apps.vod.library.tmdb_client") as client:
                    response = self.client.get(
                        self.endpoint("canonical-targets"),
                        {"content_type": kind, "query": "2012", "year": 2009},
                    )
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.json()["results"][0]["id"], title.pk)
                    exact = self.client.get(
                        self.endpoint("canonical-targets"),
                        {"content_type": kind, "tmdb_id": "14161"},
                    )
                    self.assertEqual(exact.json()["results"][0]["source_count"], 1)
                    client.assert_not_called()
                self.assertEqual(before, list(fixture[0].objects.values()))

    def test_lookup_requires_admin_and_never_crosses_content_types(self):
        self.import_rows("movie", [{"name": "Only movie"}])
        response = self.client.get(
            self.endpoint("canonical-targets"),
            {"content_type": "series", "query": "Only movie"},
        )
        self.assertEqual(response.json()["results"], [])
        user = self.client.handler._force_user
        user.user_level = 1
        self.client.force_authenticate(user)
        response = self.client.get(
            self.endpoint("canonical-targets"),
            {"content_type": "movie", "query": "Only movie"},
        )
        self.assertEqual(response.status_code, 403)

    def test_manual_local_assignment_survives_conflicting_provider_ids_for_both_types(
        self,
    ):
        for kind, fixture in self.fixtures.items():
            for external_id in (None, "456"):
                with self.subTest(kind=kind, external_id=external_id):
                    fixture[1].objects.all().delete()
                    fixture[0].objects.all().delete()
                    source = self.import_rows(
                        kind, [{"name": "Wrong (2020)", "tmdb_id": "123"}]
                    ).get()
                    target = fixture[0].objects.create(
                        name="Correct",
                        year=2019,
                        tmdb_id=external_id,
                        tmdb_lookup_excluded=True,
                    )
                    raw = source.custom_properties
                    response = self.assign(
                        kind,
                        [source],
                        target_id=target.pk,
                        manual_metadata={"audio_languages": ["eng"]},
                    )
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.json()["metadata"]["id"], target.pk)
                    source.refresh_from_db()
                    self.assertEqual(
                        source.custom_properties["basic_data"], raw["basic_data"]
                    )
                    self.import_rows(
                        kind,
                        [
                            {
                                "name": "Other (2021)",
                                "tmdb_id": "999",
                                "imdb_id": "tt999",
                            }
                        ],
                    )
                    source.refresh_from_db()
                    target.refresh_from_db()
                    self.assertEqual(getattr(source, f"{kind}_id"), target.pk)
                    self.assertEqual(
                        (target.name, target.year, target.tmdb_id, target.imdb_id),
                        ("Correct", 2019, external_id, None),
                    )
                    self.assertEqual(
                        source.manual_metadata, {"audio_languages": ["eng"]}
                    )
                    self.assertTrue(
                        source.custom_properties["_library_manual_assignment"]
                    )

    def test_move_keeps_other_sources_and_target_protection(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                sources = list(
                    self.import_rows(
                        kind, [{"name": "Old (2020)"}, {"name": "Old (2020)"}]
                    )
                )
                old_id = getattr(sources[0], f"{kind}_id")
                target = fixture[0].objects.create(
                    name="Target", description="Curated", tmdb_lookup_excluded=True
                )
                response = self.assign(kind, [sources[0]], target_id=target.pk)
                self.assertEqual(response.status_code, 200, response.data)
                sources[1].refresh_from_db()
                self.assertEqual(getattr(sources[1], f"{kind}_id"), old_id)
                target.refresh_from_db()
                self.assertEqual(target.description, "Curated")
                self.assertTrue(target.tmdb_lookup_excluded)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_advanced_provider_refresh_cannot_replace_a_local_manual_assignment(self):
        from apps.vod.tasks import refresh_movie_advanced_data

        source = self.import_rows("movie", [{"name": "Old"}]).get()
        target = self.fixtures["movie"][0].objects.create(
            name="Target", tmdb_lookup_excluded=True
        )
        self.assertEqual(
            self.assign("movie", [source], target_id=target.pk).status_code, 200
        )
        with (
            patch("core.xtream_codes.Client") as client,
            patch("apps.vod.tasks.handle_movie_id_conflicts") as merge,
        ):
            client.return_value.__enter__.return_value.get_vod_info.return_value = {
                "info": {
                    "tmdb_id": "999",
                    "imdb_id": "tt999",
                    "plot": "Provider description",
                }
            }
            self.assertEqual(
                refresh_movie_advanced_data(source.pk, force_refresh=True),
                "Advanced data refreshed.",
            )
            merge.assert_not_called()
        source.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(source.movie_id, target.pk)
        self.assertIsNone(target.tmdb_id)
        self.assertTrue(source.custom_properties["_library_manual_assignment"])

    def test_create_from_provider_preserves_provider_data_and_old_public_id(self):
        for kind in self.fixtures:
            with self.subTest(kind=kind):
                source = self.import_rows(
                    kind, [{"name": "Provider title (2020)", "tmdb_id": "123"}]
                ).get()
                old = getattr(source, kind)
                raw = source.custom_properties["basic_data"]
                response = self.assign(kind, [source], create_from_provider=True)
                self.assertEqual(response.status_code, 200, response.data)
                source.refresh_from_db()
                self.assertNotEqual(getattr(source, f"{kind}_id"), old.pk)
                target = getattr(source, kind)
                self.assertEqual(target.name, "Provider title (2020)")
                self.assertIsNone(target.tmdb_id)
                self.assertEqual(source.custom_properties["basic_data"], raw)
                self.assertTrue(
                    VODContentAlias.objects.filter(legacy_uuid=old.uuid).exists()
                )

    def test_create_accepts_a_curated_name_and_year_without_rewriting_the_source(self):
        for kind in self.fixtures:
            with self.subTest(kind=kind):
                source = self.import_rows(
                    kind, [{"name": "Provider [4K]", "year": 2020}]
                ).get()
                raw = source.custom_properties
                response = self.assign(
                    kind,
                    [source],
                    create_from_provider=True,
                    title_name="Curated title",
                    title_year=2019,
                )
                self.assertEqual(response.status_code, 200, response.data)
                source.refresh_from_db()
                target = getattr(source, kind)
                self.assertEqual((target.name, target.year), ("Curated title", 2019))
                self.assertEqual(response.json()["metadata"]["name"], "Curated title")
                self.assertTrue(target.tmdb_lookup_excluded)
                self.assertEqual(
                    source.custom_properties["basic_data"], raw["basic_data"]
                )
                for invalid in ({"title_name": ""}, {"title_year": 1200}):
                    self.assertEqual(
                        self.assign(
                            kind, [source], create_from_provider=True, **invalid
                        ).status_code,
                        400,
                    )

    def test_create_reuses_an_existing_title_without_overwriting_its_curated_values(
        self,
    ):
        source = self.import_rows("movie", [{"name": "Provider"}]).get()
        target = self.fixtures["movie"][0].objects.create(
            name="Target",
            year=2019,
            display_name="Curated display",
            tmdb_lookup_excluded=True,
        )
        response = self.assign(
            "movie",
            [source],
            create_from_provider=True,
            title_name="Target",
            title_year=2019,
        )
        self.assertEqual(response.status_code, 200, response.data)
        source.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(source.movie_id, target.pk)
        self.assertEqual(target.display_name, "Curated display")
        self.assertTrue(target.tmdb_lookup_excluded)

    def test_series_move_splits_only_exact_provider_episodes(self):
        fixture = self.fixtures["series"]
        sources = list(self.import_rows("series", [{"name": "Old"}, {"name": "Old"}]))
        old = sources[0].series
        target = fixture[0].objects.create(name="Target")
        episode = Episode.objects.create(
            series=old, season_number=1, episode_number=1, name="Episode"
        )
        rows = [
            M3UEpisodeRelation.objects.create(
                m3u_account=self.account,
                episode=episode,
                series_relation=source,
                stream_id=str(100 + i),
            )
            for i, source in enumerate(sources)
        ]
        response = self.assign("series", [sources[0]], target_id=target.pk)
        self.assertEqual(response.status_code, 200, response.data)
        for row, series_id in zip(rows, (target.pk, old.pk)):
            row.refresh_from_db()
            self.assertEqual(row.episode.series_id, series_id)

    def test_invalid_or_failed_moves_roll_back_assignment_and_metadata(self):
        source = self.import_rows("movie", [{"name": "Old"}]).get()
        target = self.fixtures["movie"][0].objects.create(name="Target")
        for values in (
            {"target_id": 999999},
            {"target_id": target.pk, "tmdb_id": "123"},
            {"target_id": target.pk, "create_from_provider": True},
        ):
            response = self.assign("movie", [source], **values)
            self.assertIn(response.status_code, (400, 404))
        with patch(
            "apps.vod.library._relocate_source",
            side_effect=ValueError("Conflicting episode identities"),
        ):
            response = self.assign(
                "movie",
                [source],
                target_id=target.pk,
                manual_metadata={"resolution": "1080p"},
            )
        self.assertEqual(response.status_code, 400)
        source.refresh_from_db()
        self.assertNotEqual(source.movie_id, target.pk)
        self.assertEqual(source.manual_metadata, {})
        self.assertNotIn("_library_manual_assignment", source.custom_properties)

    def test_bulk_create_and_mixed_kind_targets_are_rejected(self):
        sources = list(self.import_rows("movie", [{"name": "One"}, {"name": "Two"}]))
        self.assertEqual(
            self.assign("movie", sources, create_from_provider=True).status_code, 400
        )
        self.assertEqual(self.assign("movie", sources, target_id=1).status_code, 400)
        series = self.import_rows("series", [{"name": "Series"}]).get()
        response = self.client.patch(
            self.endpoint("source-metadata"),
            {
                "items": [
                    {"content_type": "movie", "id": sources[0].pk},
                    {"content_type": "series", "id": series.pk},
                ],
                "target_id": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def tearDown(self):
        cache.clear()
