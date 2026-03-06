from django.test import TestCase
from django.utils import timezone
from apps.epg.models import EPGData, EPGSource, ProgramData
from apps.epg.serializers import ProgramDataSerializer


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
