from django.test import TestCase
from django.utils import timezone
from apps.epg.models import EPGData, EPGSource, ProgramData
from apps.epg.serializers import ProgramDataSerializer, ProgramDetailSerializer
from apps.epg.utils import extract_season_episode, extract_season_episode_from_description


class ProgramDataSerializerTests(TestCase):
    """Tests for ProgramDataSerializer season/episode extraction from custom_properties."""

    def setUp(self):
        self.epg_source = EPGSource.objects.create(
            name="Test Source", source_type="xmltv"
        )
        self.epg = EPGData.objects.create(
            tvg_id="test-tvg", name="Test EPG", epg_source=self.epg_source
        )
        self.now = timezone.now()

    def _create_program(self, **kwargs):
        defaults = {
            "epg": self.epg,
            "start_time": self.now,
            "end_time": self.now + timezone.timedelta(hours=1),
            "title": "Test Program",
        }
        defaults.update(kwargs)
        return ProgramData.objects.create(**defaults)

    def test_season_and_episode_from_custom_properties(self):
        """Season and episode should be extracted from custom_properties."""
        program = self._create_program(
            custom_properties={"season": 3, "episode": 5}
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 3)
        self.assertEqual(data["episode"], 5)

    def test_season_only_from_custom_properties(self):
        """Season should be returned even when episode is absent."""
        program = self._create_program(custom_properties={"season": 2})
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 2)
        self.assertIsNone(data["episode"])

    def test_episode_only_from_custom_properties(self):
        """Episode should be returned even when season is absent."""
        program = self._create_program(custom_properties={"episode": 10})
        data = ProgramDataSerializer(program).data
        self.assertIsNone(data["season"])
        self.assertEqual(data["episode"], 10)

    def test_season_episode_null_when_custom_properties_is_none(self):
        """Both should be None when custom_properties is None."""
        program = self._create_program(custom_properties=None)
        data = ProgramDataSerializer(program).data
        self.assertIsNone(data["season"])
        self.assertIsNone(data["episode"])

    def test_season_episode_null_when_custom_properties_is_empty(self):
        """Both should be None when custom_properties is an empty dict."""
        program = self._create_program(custom_properties={})
        data = ProgramDataSerializer(program).data
        self.assertIsNone(data["season"])
        self.assertIsNone(data["episode"])

    def test_season_episode_null_when_keys_absent(self):
        """Both should be None when custom_properties has other keys but no season/episode."""
        program = self._create_program(
            custom_properties={"categories": ["Drama"], "rating": "TV-14"}
        )
        data = ProgramDataSerializer(program).data
        self.assertIsNone(data["season"])
        self.assertIsNone(data["episode"])

    def test_sub_title_included_in_serialized_data(self):
        """sub_title field should be present in serialized output."""
        program = self._create_program(sub_title="The Pilot")
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["sub_title"], "The Pilot")

    def test_sub_title_null_when_not_set(self):
        """sub_title should be None when not set."""
        program = self._create_program()
        data = ProgramDataSerializer(program).data
        self.assertIsNone(data["sub_title"])

    def test_all_expected_fields_present(self):
        """Serialized output should contain all expected fields."""
        program = self._create_program(
            sub_title="Episode Title",
            custom_properties={"season": 1, "episode": 1},
        )
        data = ProgramDataSerializer(program).data
        expected_fields = {
            "id", "start_time", "end_time", "title", "sub_title",
            "description", "tvg_id", "season", "episode",
            "is_new", "is_live", "is_premiere", "is_finale",
        }
        self.assertEqual(set(data.keys()), expected_fields)

    def test_season_episode_from_onscreen_episode(self):
        """Season and episode should be parsed from onscreen_episode string."""
        program = self._create_program(
            custom_properties={"onscreen_episode": "S12 E6"}
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 12)
        self.assertEqual(data["episode"], 6)

    def test_onscreen_episode_no_space(self):
        """Should parse onscreen_episode without space between S and E."""
        program = self._create_program(
            custom_properties={"onscreen_episode": "S3E21"}
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 3)
        self.assertEqual(data["episode"], 21)

    def test_onscreen_episode_with_part(self):
        """Should parse season/episode even when part info follows."""
        program = self._create_program(
            custom_properties={"onscreen_episode": "S8 E8 P2/2"}
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 8)
        self.assertEqual(data["episode"], 8)

    def test_direct_season_episode_takes_priority_over_onscreen(self):
        """Direct season/episode keys should take priority over onscreen parsing."""
        program = self._create_program(
            custom_properties={
                "season": 1, "episode": 2,
                "onscreen_episode": "S99 E99",
            }
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 1)
        self.assertEqual(data["episode"], 2)

    def test_onscreen_episode_invalid_format(self):
        """Should return None for onscreen_episode that doesn't match S/E pattern."""
        program = self._create_program(
            custom_properties={"onscreen_episode": "Episode 5"}
        )
        data = ProgramDataSerializer(program).data
        self.assertIsNone(data["season"])
        self.assertIsNone(data["episode"])

    def test_bulk_serialization_with_mixed_data(self):
        """Serializer should handle a mix of programs with and without metadata."""
        p1 = self._create_program(
            title="Show A",
            sub_title="Ep 1",
            custom_properties={"season": 1, "episode": 1},
        )
        p2 = self._create_program(
            title="Movie B",
            custom_properties=None,
        )
        p3 = self._create_program(
            title="Show C",
            custom_properties={},
        )
        data = ProgramDataSerializer([p1, p2, p3], many=True).data
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["season"], 1)
        self.assertEqual(data[0]["episode"], 1)
        self.assertIsNone(data[1]["season"])
        self.assertIsNone(data[1]["episode"])
        self.assertIsNone(data[2]["season"])
        self.assertIsNone(data[2]["episode"])

    def test_is_new_true_when_flag_set(self):
        """is_new should be True when custom_properties has 'new' flag."""
        program = self._create_program(custom_properties={"new": True})
        data = ProgramDataSerializer(program).data
        self.assertTrue(data["is_new"])

    def test_is_live_true_when_flag_set(self):
        """is_live should be True when custom_properties has 'live' flag."""
        program = self._create_program(custom_properties={"live": True})
        data = ProgramDataSerializer(program).data
        self.assertTrue(data["is_live"])

    def test_is_premiere_true_when_flag_set(self):
        """is_premiere should be True when custom_properties has 'premiere' flag."""
        program = self._create_program(custom_properties={"premiere": True})
        data = ProgramDataSerializer(program).data
        self.assertTrue(data["is_premiere"])

    def test_flags_false_when_not_set(self):
        """All boolean flags should be False when not in custom_properties."""
        program = self._create_program(custom_properties={"season": 1})
        data = ProgramDataSerializer(program).data
        self.assertFalse(data["is_new"])
        self.assertFalse(data["is_live"])
        self.assertFalse(data["is_premiere"])

    def test_flags_false_when_custom_properties_none(self):
        """All boolean flags should be False when custom_properties is None."""
        program = self._create_program(custom_properties=None)
        data = ProgramDataSerializer(program).data
        self.assertFalse(data["is_new"])
        self.assertFalse(data["is_live"])
        self.assertFalse(data["is_premiere"])

    def test_flags_false_when_custom_properties_empty(self):
        """All boolean flags should be False when custom_properties is empty."""
        program = self._create_program(custom_properties={})
        data = ProgramDataSerializer(program).data
        self.assertFalse(data["is_new"])
        self.assertFalse(data["is_live"])
        self.assertFalse(data["is_premiere"])

    def test_multiple_flags_set(self):
        """Multiple flags can be true simultaneously."""
        program = self._create_program(
            custom_properties={"new": True, "live": True, "premiere": True}
        )
        data = ProgramDataSerializer(program).data
        self.assertTrue(data["is_new"])
        self.assertTrue(data["is_live"])
        self.assertTrue(data["is_premiere"])

    def test_flags_with_season_episode(self):
        """Flags should work alongside season/episode data."""
        program = self._create_program(
            custom_properties={"season": 5, "episode": 1, "new": True, "premiere": True}
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 5)
        self.assertEqual(data["episode"], 1)
        self.assertTrue(data["is_new"])
        self.assertFalse(data["is_live"])
        self.assertTrue(data["is_premiere"])

    def test_is_finale_from_premiere_text_season_finale(self):
        """is_finale should be True when premiere_text contains 'Season Finale'."""
        program = self._create_program(
            custom_properties={"premiere": True, "premiere_text": "Season Finale"}
        )
        data = ProgramDataSerializer(program).data
        self.assertTrue(data["is_finale"])

    def test_is_finale_from_premiere_text_series_finale(self):
        """is_finale should be True when premiere_text contains 'Series Finale'."""
        program = self._create_program(
            custom_properties={"premiere": True, "premiere_text": "Series Finale"}
        )
        data = ProgramDataSerializer(program).data
        self.assertTrue(data["is_finale"])

    def test_is_finale_case_insensitive(self):
        """is_finale detection should be case-insensitive."""
        program = self._create_program(
            custom_properties={"premiere": True, "premiere_text": "SEASON FINALE"}
        )
        data = ProgramDataSerializer(program).data
        self.assertTrue(data["is_finale"])

    def test_is_finale_false_for_premiere_text(self):
        """is_finale should be False when premiere_text is 'Season Premiere'."""
        program = self._create_program(
            custom_properties={"premiere": True, "premiere_text": "Season Premiere"}
        )
        data = ProgramDataSerializer(program).data
        self.assertFalse(data["is_finale"])

    def test_is_finale_false_when_no_premiere_text(self):
        """is_finale should be False when premiere_text is absent."""
        program = self._create_program(
            custom_properties={"premiere": True}
        )
        data = ProgramDataSerializer(program).data
        self.assertFalse(data["is_finale"])

    def test_is_finale_false_when_custom_properties_none(self):
        """is_finale should be False when custom_properties is None."""
        program = self._create_program(custom_properties=None)
        data = ProgramDataSerializer(program).data
        self.assertFalse(data["is_finale"])


class ExtractSeasonEpisodeHelperTests(TestCase):
    """Tests for the shared extract_season_episode helper function."""

    def test_both_present(self):
        season, episode = extract_season_episode({"season": 3, "episode": 5})
        self.assertEqual(season, 3)
        self.assertEqual(episode, 5)

    def test_fallback_to_onscreen(self):
        season, episode = extract_season_episode({"onscreen_episode": "S12 E6"})
        self.assertEqual(season, 12)
        self.assertEqual(episode, 6)

    def test_direct_values_override_onscreen(self):
        season, episode = extract_season_episode({
            "season": 1, "episode": 2, "onscreen_episode": "S99 E99"
        })
        self.assertEqual(season, 1)
        self.assertEqual(episode, 2)

    def test_empty_dict(self):
        season, episode = extract_season_episode({})
        self.assertIsNone(season)
        self.assertIsNone(episode)

    def test_partial_with_onscreen_fill(self):
        """Direct season + onscreen episode fills the gap."""
        season, episode = extract_season_episode({
            "season": 5, "onscreen_episode": "S5E10"
        })
        self.assertEqual(season, 5)
        self.assertEqual(episode, 10)

    def test_description_fallback_s_e_format(self):
        """S01E01 in description should be used as third-tier fallback."""
        season, episode = extract_season_episode({}, description="S2 E31 The Episode Title")
        self.assertEqual(season, 2)
        self.assertEqual(episode, 31)

    def test_description_fallback_season_episode_format(self):
        season, episode = extract_season_episode({}, description="Season 3 Episode 12 Some Title")
        self.assertEqual(season, 3)
        self.assertEqual(episode, 12)

    def test_description_fallback_nxnn_format(self):
        season, episode = extract_season_episode({}, description="5x03 Episode Name")
        self.assertEqual(season, 5)
        self.assertEqual(episode, 3)

    def test_description_not_used_when_cp_has_both(self):
        """Description fallback should not override existing custom_properties values."""
        season, episode = extract_season_episode(
            {"season": 1, "episode": 2}, description="S99 E99 Fake"
        )
        self.assertEqual(season, 1)
        self.assertEqual(episode, 2)

    def test_description_not_used_when_onscreen_provides_both(self):
        season, episode = extract_season_episode(
            {"onscreen_episode": "S3E5"}, description="S99 E99 Fake"
        )
        self.assertEqual(season, 3)
        self.assertEqual(episode, 5)

    def test_description_fills_gap_after_partial_onscreen(self):
        """If onscreen provides only season, description can fill episode."""
        # onscreen_episode "S5" doesn't match the S/E pattern, so no values from onscreen
        # description provides both
        season, episode = extract_season_episode(
            {"season": 5}, description="S5 E10 Title"
        )
        self.assertEqual(season, 5)
        self.assertEqual(episode, 10)

    def test_description_none_is_safe(self):
        season, episode = extract_season_episode({}, description=None)
        self.assertIsNone(season)
        self.assertIsNone(episode)

    def test_description_empty_string_is_safe(self):
        season, episode = extract_season_episode({}, description="")
        self.assertIsNone(season)
        self.assertIsNone(episode)


class ExtractSeasonEpisodeFromDescriptionTests(TestCase):
    """Tests for extract_season_episode_from_description() in tasks.py."""

    def test_s_e_compact(self):
        s, e, cleaned = extract_season_episode_from_description("S2E31 The Kevin Episode")
        self.assertEqual(s, 2)
        self.assertEqual(e, 31)
        self.assertEqual(cleaned, "The Kevin Episode")

    def test_s_e_with_space(self):
        s, e, cleaned = extract_season_episode_from_description("S2 E31 The Kevin Episode")
        self.assertEqual(s, 2)
        self.assertEqual(e, 31)
        self.assertEqual(cleaned, "The Kevin Episode")

    def test_season_episode_words(self):
        s, e, cleaned = extract_season_episode_from_description("Season 3 Episode 12 Title Here")
        self.assertEqual(s, 3)
        self.assertEqual(e, 12)
        self.assertEqual(cleaned, "Title Here")

    def test_nxnn_format(self):
        s, e, cleaned = extract_season_episode_from_description("5x03 Episode Name")
        self.assertEqual(s, 5)
        self.assertEqual(e, 3)
        self.assertEqual(cleaned, "Episode Name")

    def test_leading_dash(self):
        s, e, cleaned = extract_season_episode_from_description("- S1E5 Title")
        self.assertEqual(s, 1)
        self.assertEqual(e, 5)
        self.assertEqual(cleaned, "Title")

    def test_case_insensitive(self):
        s, e, cleaned = extract_season_episode_from_description("s10e20 Lower Case")
        self.assertEqual(s, 10)
        self.assertEqual(e, 20)
        self.assertEqual(cleaned, "Lower Case")

    def test_no_match_returns_original(self):
        s, e, cleaned = extract_season_episode_from_description("Just a normal description")
        self.assertIsNone(s)
        self.assertIsNone(e)
        self.assertEqual(cleaned, "Just a normal description")

    def test_none_input(self):
        s, e, cleaned = extract_season_episode_from_description(None)
        self.assertIsNone(s)
        self.assertIsNone(e)
        self.assertIsNone(cleaned)

    def test_empty_string(self):
        s, e, cleaned = extract_season_episode_from_description("")
        self.assertIsNone(s)
        self.assertIsNone(e)
        self.assertEqual(cleaned, "")

    def test_mid_string_s_e_not_matched(self):
        """S/E in middle of description should NOT be matched (anchored to start)."""
        s, e, cleaned = extract_season_episode_from_description("Some intro text S1E5 title")
        self.assertIsNone(s)
        self.assertIsNone(e)
        self.assertEqual(cleaned, "Some intro text S1E5 title")


class ProgramDataSerializerDescriptionFallbackTests(TestCase):
    """Integration tests: serializer uses description fallback for S/E."""

    def setUp(self):
        self.epg_source = EPGSource.objects.create(
            name="Test Source", source_type="xmltv"
        )
        self.epg = EPGData.objects.create(
            tvg_id="test-tvg", name="Test EPG", epg_source=self.epg_source
        )
        self.now = timezone.now()

    def _create_program(self, **kwargs):
        defaults = {
            "epg": self.epg,
            "start_time": self.now,
            "end_time": self.now + timezone.timedelta(hours=1),
            "title": "Test Program",
        }
        defaults.update(kwargs)
        return ProgramData.objects.create(**defaults)

    def test_se_from_description_when_no_cp(self):
        program = self._create_program(
            custom_properties={},
            description="S2 E5 The Episode Title",
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 2)
        self.assertEqual(data["episode"], 5)

    def test_se_from_description_not_used_when_cp_has_values(self):
        program = self._create_program(
            custom_properties={"season": 1, "episode": 1},
            description="S99 E99 Fake",
        )
        data = ProgramDataSerializer(program).data
        self.assertEqual(data["season"], 1)
        self.assertEqual(data["episode"], 1)


class ProgramDetailSerializerTests(TestCase):
    """Tests for ProgramDetailSerializer — rich field extraction from custom_properties."""

    def setUp(self):
        self.epg_source = EPGSource.objects.create(
            name="Test Source", source_type="xmltv"
        )
        self.epg = EPGData.objects.create(
            tvg_id="test-tvg", name="Test EPG", epg_source=self.epg_source
        )
        self.now = timezone.now()

    def _create_program(self, **kwargs):
        defaults = {
            "epg": self.epg,
            "start_time": self.now,
            "end_time": self.now + timezone.timedelta(hours=1),
            "title": "Test Program",
        }
        defaults.update(kwargs)
        return ProgramData.objects.create(**defaults)

    def test_all_detail_fields_present(self):
        """Detail serializer should include all expected fields."""
        program = self._create_program(custom_properties={"season": 1, "episode": 1})
        data = ProgramDetailSerializer(program).data
        expected_fields = {
            "id", "start_time", "end_time", "title", "sub_title", "description", "tvg_id",
            "season", "episode", "is_new", "is_live", "is_premiere", "is_finale",
            "categories", "rating", "rating_system", "star_ratings",
            "credits", "video_quality", "aspect_ratio", "stereo", "is_previously_shown",
            "country", "language", "production_date", "original_air_date",
            "imdb_id", "tmdb_id", "tvdb_id", "icon", "images",
        }
        self.assertEqual(set(data.keys()), expected_fields)

    def test_categories_extraction(self):
        program = self._create_program(
            custom_properties={"categories": ["Drama", "Thriller"]}
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["categories"], ["Drama", "Thriller"])

    def test_categories_empty_when_absent(self):
        program = self._create_program(custom_properties={})
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["categories"], [])

    def test_rating_extraction(self):
        program = self._create_program(
            custom_properties={"rating": "TV-14", "rating_system": "VCHIP"}
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["rating"], "TV-14")
        self.assertEqual(data["rating_system"], "VCHIP")

    def test_star_ratings_extraction(self):
        program = self._create_program(
            custom_properties={"star_ratings": [{"value": "8.5/10", "system": "IMDB"}]}
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(len(data["star_ratings"]), 1)
        self.assertEqual(data["star_ratings"][0]["value"], "8.5/10")

    def test_credits_extraction(self):
        program = self._create_program(
            custom_properties={
                "credits": {
                    "actor": [{"name": "Bryan Cranston", "role": "Walter White"}],
                    "director": ["Rian Johnson"],
                    "writer": ["Moira Walley-Beckett"],
                }
            }
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(len(data["credits"]["actors"]), 1)
        self.assertEqual(data["credits"]["actors"][0]["name"], "Bryan Cranston")
        self.assertEqual(data["credits"]["directors"], ["Rian Johnson"])
        self.assertEqual(data["credits"]["writers"], ["Moira Walley-Beckett"])

    def test_credits_empty_when_absent(self):
        program = self._create_program(custom_properties={})
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["credits"]["actors"], [])
        self.assertEqual(data["credits"]["directors"], [])

    def test_video_quality_extraction(self):
        program = self._create_program(
            custom_properties={"video": {"quality": "HDTV", "aspect": "16:9"}}
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["video_quality"], "HDTV")
        self.assertEqual(data["aspect_ratio"], "16:9")

    def test_audio_extraction(self):
        program = self._create_program(
            custom_properties={"audio": {"stereo": "Dolby Digital"}}
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["stereo"], "Dolby Digital")

    def test_geographic_fields(self):
        program = self._create_program(
            custom_properties={"country": "US", "language": "en"}
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["country"], "US")
        self.assertEqual(data["language"], "en")

    def test_original_air_date(self):
        program = self._create_program(
            custom_properties={
                "previously_shown_details": {"start": "2013-09-15"}
            }
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["original_air_date"], "2013-09-15")

    def test_external_ids(self):
        program = self._create_program(
            custom_properties={
                "imdb.com_id": "tt0903747",
                "themoviedb.org_id": "1396",
                "thetvdb.com_id": "81189",
            }
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["imdb_id"], "tt0903747")
        self.assertEqual(data["tmdb_id"], "1396")
        self.assertEqual(data["tvdb_id"], "81189")

    def test_images_extraction(self):
        program = self._create_program(
            custom_properties={
                "icon": "https://example.com/icon.png",
                "images": [{"url": "https://example.com/poster.jpg", "type": "poster"}],
            }
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["icon"], "https://example.com/icon.png")
        self.assertEqual(len(data["images"]), 1)

    def test_null_custom_properties_returns_safe_defaults(self):
        """All enriched fields should be null/empty when custom_properties is None."""
        program = self._create_program(custom_properties=None)
        data = ProgramDetailSerializer(program).data
        self.assertIsNone(data["season"])
        self.assertIsNone(data["episode"])
        self.assertEqual(data["categories"], [])
        self.assertIsNone(data["rating"])
        self.assertEqual(data["star_ratings"], [])
        self.assertEqual(data["credits"]["actors"], [])
        self.assertIsNone(data["video_quality"])
        self.assertIsNone(data["country"])
        self.assertIsNone(data["imdb_id"])
        self.assertEqual(data["images"], [])

    def test_season_episode_uses_shared_helper(self):
        """Detail serializer should use the same onscreen_episode fallback."""
        program = self._create_program(
            custom_properties={"onscreen_episode": "S5E14"}
        )
        data = ProgramDetailSerializer(program).data
        self.assertEqual(data["season"], 5)
        self.assertEqual(data["episode"], 14)

    def test_status_flags_match_slim_serializer(self):
        """Status flags should produce identical results as ProgramDataSerializer."""
        program = self._create_program(
            custom_properties={
                "new": True, "live": True, "premiere": True,
                "premiere_text": "Season Finale",
            }
        )
        slim = ProgramDataSerializer(program).data
        detail = ProgramDetailSerializer(program).data
        self.assertEqual(slim["is_new"], detail["is_new"])
        self.assertEqual(slim["is_live"], detail["is_live"])
        self.assertEqual(slim["is_premiere"], detail["is_premiere"])
        self.assertEqual(slim["is_finale"], detail["is_finale"])
