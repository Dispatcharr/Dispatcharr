from django.test import SimpleTestCase

from apps.plugins.loader import PluginManager
from apps.plugins.serializers import PluginFieldSerializer


class PluginFieldRowsTests(SimpleTestCase):
    def test_rows_survive_normalization(self):
        field = {"id": "notes", "type": "text", "rows": 8}
        self.assertEqual(PluginManager()._normalize_fields([field])[0]["rows"], 8)

    def test_rows_must_be_positive(self):
        serializer = PluginFieldSerializer(data={"id": "notes", "type": "text", "rows": 0})
        self.assertFalse(serializer.is_valid())
