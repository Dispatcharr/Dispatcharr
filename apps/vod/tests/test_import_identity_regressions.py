"""List enrichment preserves public selections and rejects contradictory IDs."""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
    VODContentAlias,
)
from apps.vod.references import output_reference
from apps.vod.selection import resolve_content
from apps.vod.tasks import (
    cleanup_orphaned_vod_content,
    process_movie_batch,
    process_series_batch,
)


class ListIdentityRegressionTests(TestCase):
    def setUp(self):
        self.fixtures = {}
        for kind, model, source_model, import_batch, provider_field in (
            ("movie", Movie, M3UMovieRelation, process_movie_batch, "stream_id"),
            ("series", Series, M3USeriesRelation, process_series_batch, "series_id"),
        ):
            account = M3UAccount.objects.create(
                name=f"Synthetic {kind}", account_type="XC"
            )
            category = VODCategory.objects.create(
                name=f"Synthetic {kind}", category_type=kind
            )
            defaults = M3UVODCategoryRelation.objects.create(
                m3u_account=account,
                category=category,
                enabled=True,
                metadata_defaults={"audio_languages": ["ger"], "resolution": "1080p"},
            )
            self.fixtures[kind] = {
                "model": model,
                "source_model": source_model,
                "import": import_batch,
                "provider_field": provider_field,
                "account": account,
                "category": category,
                "defaults": defaults,
            }

    def import_rows(self, kind, rows):
        fixture = self.fixtures[kind]
        return fixture["import"](
            fixture["account"],
            [
                {
                    fixture["provider_field"]: stream_id,
                    "category_id": "1",
                    "name": f"Synthetic {kind}",
                    **properties,
                }
                for stream_id, properties in rows
            ],
            {"1": fixture["category"]},
            {fixture["category"].pk: fixture["defaults"]},
        )

    def source(self, kind):
        fixture = self.fixtures[kind]
        return fixture["source_model"].objects.get(m3u_account=fixture["account"])

    def assert_resolves(self, kind, identifier, target, *, by_uuid=False):
        resolved, _ = resolve_content(kind, identifier, by_uuid=by_uuid)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.pk, target.pk)

    def test_later_external_ids_keep_canonical_ids_sources_and_published_selections(
        self,
    ):
        for kind in self.fixtures:
            with self.subTest(kind=kind):
                self.import_rows(kind, [(1, {})])
                source = self.source(kind)
                original = getattr(source, kind)
                public = output_reference(
                    kind, original.pk, {"audio_languages": ["ger"]}
                )
                source.manual_metadata = {"video_features": ["hdr", "custom:imax"]}
                source.observed_metadata = {"subtitle_languages": ["eng"]}
                source.locked_fields = ["video_features"]
                source.last_observed_at = timezone.now()
                source.save()
                source_id, observed_at = source.pk, source.last_observed_at
                for _ in range(2):
                    self.import_rows(
                        kind, [(1, {"tmdb_id": "123", "imdb_id": "tt123"})]
                    )
                    source.refresh_from_db()
                    target = getattr(source, kind)
                    self.assertEqual(target.pk, original.pk)
                    self.assertEqual(target.uuid, original.uuid)
                    self.assertEqual(source.pk, source_id)
                    self.assertEqual(
                        source.manual_metadata,
                        {"video_features": ["hdr", "custom:imax"]},
                    )
                    self.assertEqual(
                        source.observed_metadata, {"subtitle_languages": ["eng"]}
                    )
                    self.assertEqual(source.locked_fields, ["video_features"])
                    self.assertEqual(source.last_observed_at, observed_at)
                    self.assertEqual((target.tmdb_id, target.imdb_id), ("123", "tt123"))
                    for identifier, by_uuid in (
                        (original.pk, False),
                        (original.uuid, True),
                        (public.legacy_id, False),
                        (public.legacy_uuid, True),
                    ):
                        self.assert_resolves(kind, identifier, target, by_uuid=by_uuid)
                cleanup_orphaned_vod_content(
                    stale_days=1, account_id=source.m3u_account_id
                )
                self.assert_resolves(kind, public.legacy_id, target)

    def test_later_identity_merges_an_existing_title_and_preserves_both_public_ids(
        self,
    ):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                self.import_rows(kind, [(1, {})])
                source = self.source(kind)
                original = getattr(source, kind)
                donor = fixture["model"].objects.create(
                    name="Known title", tmdb_id="456", imdb_id="tt456"
                )
                donor_uuid = donor.uuid
                donor_public = output_reference(
                    kind, donor.pk, {"audio_languages": ["ger"]}
                )
                account = M3UAccount.objects.create(
                    name=f"Other {kind}", account_type="XC"
                )
                provider_key = "stream_id" if kind == "movie" else "external_series_id"
                other = fixture["source_model"].objects.create(
                    **{
                        kind: donor,
                        "m3u_account": account,
                        provider_key: "other",
                        "manual_metadata": {"audio_languages": ["ger"]},
                    }
                )
                self.import_rows(kind, [(1, {"tmdb_id": "456", "imdb_id": "tt456"})])
                source.refresh_from_db()
                other.refresh_from_db()
                self.assertEqual(getattr(source, f"{kind}_id"), original.pk)
                self.assertEqual(getattr(other, f"{kind}_id"), original.pk)
                self.assertFalse(fixture["model"].objects.filter(pk=donor.pk).exists())
                self.assertEqual(other.manual_metadata, {"audio_languages": ["ger"]})
                for identifier, by_uuid in (
                    (donor.pk, False),
                    (donor_uuid, True),
                    (donor_public.legacy_id, False),
                    (donor_public.legacy_uuid, True),
                ):
                    self.assert_resolves(kind, identifier, original, by_uuid=by_uuid)

    def test_series_enrichment_preserves_episode_sources_and_old_episode_urls(self):
        self.import_rows("series", [(1, {})])
        source = self.source("series")
        original = source.series
        donor = Series.objects.create(name="Known show", tmdb_id="789")
        current_episode = Episode.objects.create(
            series=original, name="E1", season_number=1, episode_number=1
        )
        old_episode = Episode.objects.create(
            series=donor, name="E1", season_number=1, episode_number=1
        )
        old_id, old_uuid = old_episode.pk, old_episode.uuid
        public = output_reference("episode", old_id, {"audio_languages": ["ger"]})
        other_account = M3UAccount.objects.create(
            name="Other episodes", account_type="XC"
        )
        donor_source = M3USeriesRelation.objects.create(
            series=donor, m3u_account=other_account, external_series_id="other"
        )
        episode_source = M3UEpisodeRelation.objects.create(
            episode=old_episode,
            m3u_account=other_account,
            series_relation=donor_source,
            stream_id="ep1",
            manual_metadata={"audio_languages": ["ger"]},
        )
        self.import_rows("series", [(1, {"tmdb_id": "789"})])
        episode_source.refresh_from_db()
        self.assertEqual(episode_source.episode_id, current_episode.pk)
        self.assertEqual(episode_source.manual_metadata, {"audio_languages": ["ger"]})
        for identifier, by_uuid in (
            (old_id, False),
            (old_uuid, True),
            (public.legacy_id, False),
            (public.legacy_uuid, True),
        ):
            self.assert_resolves(
                "episode", identifier, current_episode, by_uuid=by_uuid
            )

    def test_same_batch_merges_known_sources_without_reusing_retired_cached_rows(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                self.import_rows(
                    kind, [(1, {"name": "Unknown A"}), (2, {"name": "Unknown B"})]
                )
                sources = list(fixture["source_model"].objects.order_by("pk"))
                originals = [getattr(source, kind) for source in sources]
                references = [
                    output_reference(kind, row.pk, {"audio_languages": ["ger"]})
                    for row in originals
                ]
                self.import_rows(
                    kind,
                    [
                        (1, {"tmdb_id": "777"}),
                        (2, {"tmdb_id": "777", "imdb_id": "tt777"}),
                    ],
                )
                self.assertEqual(fixture["model"].objects.count(), 1)
                target = fixture["model"].objects.get(tmdb_id="777")
                for source, original, reference in zip(sources, originals, references):
                    source.refresh_from_db()
                    self.assertEqual(getattr(source, f"{kind}_id"), target.pk)
                    self.assert_resolves(kind, original.pk, target)
                    self.assert_resolves(kind, original.uuid, target, by_uuid=True)
                    self.assert_resolves(kind, reference.legacy_id, target)

    def test_same_batch_rejects_conflicting_identifiers_in_either_order(self):
        for kind, fixture in self.fixtures.items():
            for rows in (
                [
                    (1, {"tmdb_id": "10", "imdb_id": "ttA"}),
                    (2, {"tmdb_id": "10", "imdb_id": "ttB"}),
                ],
                [
                    (2, {"tmdb_id": "10", "imdb_id": "ttB"}),
                    (1, {"tmdb_id": "10", "imdb_id": "ttA"}),
                ],
            ):
                with self.subTest(kind=kind, first=rows[0][0]):
                    with self.assertRaises(ValueError):
                        self.import_rows(kind, rows)
                    self.assertFalse(fixture["model"].objects.exists())
                    self.assertFalse(fixture["source_model"].objects.exists())

    def test_later_conflict_rolls_back_an_earlier_enrichment_and_alias_merge(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                self.import_rows(kind, [(1, {})])
                source = self.source(kind)
                original = getattr(source, kind)
                donor = fixture["model"].objects.create(
                    name="Known title", tmdb_id="10", imdb_id="ttA"
                )
                aliases_before = VODContentAlias.objects.count()
                with self.assertRaises(ValueError):
                    self.import_rows(
                        kind,
                        [
                            (1, {"tmdb_id": "10"}),
                            (2, {"tmdb_id": "20", "imdb_id": "ttA"}),
                        ],
                    )
                source.refresh_from_db()
                original.refresh_from_db()
                self.assertEqual(getattr(source, f"{kind}_id"), original.pk)
                self.assertIsNone(original.tmdb_id)
                self.assertTrue(fixture["model"].objects.filter(pk=donor.pk).exists())
                self.assertEqual(VODContentAlias.objects.count(), aliases_before)

    def test_caught_bulk_failure_also_rolls_back_identity_enrichment(self):
        for kind, fixture in self.fixtures.items():
            with self.subTest(kind=kind):
                self.import_rows(kind, [(1, {})])
                source = self.source(kind)
                original = getattr(source, kind)
                with patch.object(
                    fixture["source_model"].objects,
                    "bulk_update",
                    side_effect=RuntimeError("Synthetic bulk failure"),
                ):
                    result = self.import_rows(kind, [(1, {"tmdb_id": "999"})])
                self.assertIn("failed", result)
                original.refresh_from_db()
                self.assertIsNone(original.tmdb_id)
