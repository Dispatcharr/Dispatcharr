"""XC episode details override inherited defaults without losing source edits."""

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.metadata import provider_source_metadata
from apps.vod.models import Episode, M3UEpisodeRelation, M3USeriesRelation, Series
from apps.vod.tasks import batch_process_episodes


class EpisodeSourceMetadataTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Synthetic episode provider", account_type="XC"
        )
        self.series = Series.objects.create(name="Synthetic series")
        self.parent = M3USeriesRelation.objects.create(
            series=self.series,
            m3u_account=self.account,
            external_series_id="show",
            declared_metadata={"audio_languages": ["ger"], "resolution": "720p"},
        )
        self.facts = {
            "audio_languages": ["en"],
            "subtitle_languages": ["fr"],
            "resolution": "2160p",
            "video_features": ["dv", "custom:imax"],
        }
        self.normalized = {
            **self.facts,
            "audio_languages": ["eng"],
            "subtitle_languages": ["fre"],
        }

    def import_episode(self, info):
        batch_process_episodes(
            self.account,
            self.series,
            {
                "1": [
                    {
                        "id": "ep1",
                        "title": "Synthetic episode",
                        "episode_num": 1,
                        "info": info,
                    }
                ]
            },
            series_relation=self.parent,
        )
        return M3UEpisodeRelation.objects.get(stream_id="ep1")

    def test_nested_episode_facts_are_normalized_and_override_series_defaults(self):
        source = self.import_episode(self.facts)
        self.assertEqual(source.declared_metadata, self.normalized)
        self.assertEqual(source.effective_metadata()["values"], self.normalized)
        self.assertEqual(
            source.effective_metadata()["provenance"],
            {key: "provider" for key in self.normalized},
        )

    def test_retained_episode_payload_is_read_correctly_without_a_refresh(self):
        episode = Episode.objects.create(
            series=self.series,
            name="Existing episode",
            season_number=1,
            episode_number=1,
        )
        source = M3UEpisodeRelation.objects.create(
            episode=episode,
            m3u_account=self.account,
            series_relation=self.parent,
            stream_id="legacy",
            custom_properties={"info": {"id": "legacy", "info": self.facts}},
        )
        self.assertEqual(source.declared_metadata, {})
        self.assertEqual(source.effective_metadata()["values"], self.normalized)

    def test_partial_refresh_retains_other_facts_manual_overrides_and_locks(self):
        source = self.import_episode(self.facts)
        original_id = source.pk
        source.manual_metadata = {"audio_languages": ["ger"]}
        source.locked_fields = ["audio_languages"]
        source.save()
        source = self.import_episode({"subtitle_languages": ["en"]})
        self.assertEqual(source.pk, original_id)
        self.assertEqual(
            source.declared_metadata, {**self.normalized, "subtitle_languages": ["eng"]}
        )
        self.assertEqual(source.manual_metadata, {"audio_languages": ["ger"]})
        self.assertEqual(source.locked_fields, ["audio_languages"])
        self.assertEqual(
            source.effective_metadata()["values"]["audio_languages"], ["ger"]
        )

    def test_invalid_nested_field_does_not_erase_valid_flat_facts(self):
        self.assertEqual(
            provider_source_metadata(
                {
                    "audio_languages": ["de"],
                    "resolution": "720p",
                    "info": {"audio_languages": ["invalid"], "quality": "4K"},
                }
            ),
            {"audio_languages": ["ger"], "resolution": "2160p"},
        )
        self.assertEqual(
            provider_source_metadata({"audio_languages": ["de"], "info": []}),
            {"audio_languages": ["ger"]},
        )
