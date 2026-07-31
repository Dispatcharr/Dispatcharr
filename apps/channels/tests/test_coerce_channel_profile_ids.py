from django.test import SimpleTestCase

from apps.channels.utils import coerce_channel_profile_ids


class CoerceChannelProfileIdsTests(SimpleTestCase):
    def test_coerces_strings_to_ints(self):
        result = coerce_channel_profile_ids({"channel_profile_ids": ["1", 2]})
        self.assertEqual(result["channel_profile_ids"], [1, 2])

    def test_leaves_other_keys_alone(self):
        result = coerce_channel_profile_ids({"channel_numbering_mode": "fixed"})
        self.assertEqual(result, {"channel_numbering_mode": "fixed"})

    def test_handles_legacy_json_encoded_string_without_raising(self):
        # Historical rows (TextField era / bad writes) can store
        # custom_properties as a JSON-encoded string instead of an object.
        result = coerce_channel_profile_ids('{"channel_profile_ids": [1, 2]}')
        self.assertEqual(result["channel_profile_ids"], [1, 2])

    def test_handles_non_json_string_without_raising(self):
        result = coerce_channel_profile_ids("not json")
        self.assertEqual(result, {})

    def test_handles_none(self):
        self.assertEqual(coerce_channel_profile_ids(None), {})

    def test_drops_unparseable_entries_but_keeps_valid_ones(self):
        result = coerce_channel_profile_ids(
            {"channel_profile_ids": [1, "abc", None, "3"]}
        )
        self.assertEqual(result["channel_profile_ids"], [1, 3])

    def test_wraps_lone_scalar_id(self):
        result = coerce_channel_profile_ids({"channel_profile_ids": "5"})
        self.assertEqual(result["channel_profile_ids"], [5])
