"""PluginActionSerializer's 'async' field (a Python keyword, added via
get_fields() rather than a class attribute) must round-trip correctly and
default to False for existing manifests that don't declare it."""

from django.test import SimpleTestCase

from apps.plugins.serializers import PluginActionSerializer


class PluginActionSerializerAsyncFieldTests(SimpleTestCase):
    def test_defaults_to_false_when_omitted(self):
        serializer = PluginActionSerializer(data={"id": "a", "label": "A"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["async"], False)

    def test_true_value_round_trips(self):
        serializer = PluginActionSerializer(data={"id": "a", "label": "A", "async": True})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["async"], True)

    def test_many_actions_each_keep_their_own_async_value(self):
        serializer = PluginActionSerializer(
            data=[
                {"id": "quick", "label": "Quick"},
                {"id": "slow", "label": "Slow", "async": True},
            ],
            many=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data[0]["async"], False)
        self.assertEqual(serializer.validated_data[1]["async"], True)
