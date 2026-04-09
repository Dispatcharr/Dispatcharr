from unittest.mock import patch, MagicMock

from django.test import TestCase

from core.models import CoreSettings, DVR_SETTINGS_KEY, EPG_SETTINGS_KEY


class GetDvrSeriesRulesTest(TestCase):
    """Verify get_dvr_series_rules handles corrupted stored data."""

    def _set_series_rules_raw(self, raw_value):
        """Write a raw series_rules value into the DB, bypassing set_dvr_series_rules."""
        obj, _ = CoreSettings.objects.get_or_create(
            key=DVR_SETTINGS_KEY,
            defaults={"name": "DVR Settings", "value": {}},
        )
        current = obj.value if isinstance(obj.value, dict) else {}
        current["series_rules"] = raw_value
        obj.value = current
        obj.save()

    def test_valid_rules_returned_as_is(self):
        rules = [{"tvg_id": "abc", "mode": "all", "title": "Show"}]
        self._set_series_rules_raw(rules)
        result = CoreSettings.get_dvr_series_rules()
        self.assertEqual(result, rules)

    def test_non_dict_elements_filtered(self):
        """Strings in the list cause 'str' has no attribute 'get'."""
        self._set_series_rules_raw(["bad_string", {"tvg_id": "abc", "mode": "all", "title": ""}])
        result = CoreSettings.get_dvr_series_rules()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tvg_id"], "abc")

    def test_non_list_value_returns_empty(self):
        """If series_rules is a JSON string instead of a list, return empty."""
        self._set_series_rules_raw("[]")
        result = CoreSettings.get_dvr_series_rules()
        self.assertEqual(result, [])

    def test_none_value_returns_empty(self):
        self._set_series_rules_raw(None)
        result = CoreSettings.get_dvr_series_rules()
        self.assertEqual(result, [])

    def test_mixed_corrupt_elements(self):
        self._set_series_rules_raw([42, None, True, {"tvg_id": "x", "mode": "new", "title": "T"}])
        result = CoreSettings.get_dvr_series_rules()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tvg_id"], "x")


class SetDvrSeriesRulesTest(TestCase):
    """Verify set_dvr_series_rules sanitizes input before persisting."""

    def test_valid_rules_persisted(self):
        rules = [{"tvg_id": "abc", "mode": "all", "title": "Show"}]
        result = CoreSettings.set_dvr_series_rules(rules)
        self.assertEqual(result, rules)
        self.assertEqual(CoreSettings.get_dvr_series_rules(), rules)

    def test_non_dict_elements_stripped_on_write(self):
        dirty = ["bad", 42, {"tvg_id": "abc", "mode": "all", "title": ""}]
        result = CoreSettings.set_dvr_series_rules(dirty)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tvg_id"], "abc")
        self.assertEqual(CoreSettings.get_dvr_series_rules(), result)

    def test_non_list_input_stores_empty(self):
        result = CoreSettings.set_dvr_series_rules("not a list")
        self.assertEqual(result, [])
        self.assertEqual(CoreSettings.get_dvr_series_rules(), [])


class CoreSettingsSerializerDvrTest(TestCase):
    """Verify the generic settings API sanitizes series_rules on save."""

    def test_serializer_strips_corrupt_series_rules(self):
        """Settings page round-trip must not persist corrupt series_rules."""
        from core.serializers import CoreSettingsSerializer

        obj, _ = CoreSettings.objects.get_or_create(
            key=DVR_SETTINGS_KEY,
            defaults={"name": "DVR Settings", "value": {"series_rules": []}},
        )
        dirty_value = {
            **obj.value,
            "series_rules": ["bad", {"tvg_id": "ok", "mode": "all", "title": ""}],
        }
        serializer = CoreSettingsSerializer(obj, data={"value": dirty_value}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        obj.refresh_from_db()
        rules = obj.value.get("series_rules", [])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["tvg_id"], "ok")

    def test_serializer_handles_non_list_series_rules(self):
        from core.serializers import CoreSettingsSerializer

        obj, _ = CoreSettings.objects.get_or_create(
            key=DVR_SETTINGS_KEY,
            defaults={"name": "DVR Settings", "value": {"series_rules": []}},
        )
        dirty_value = {**obj.value, "series_rules": "not a list"}
        serializer = CoreSettingsSerializer(obj, data={"value": dirty_value}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        obj.refresh_from_db()
        self.assertEqual(obj.value.get("series_rules"), [])


class EpgIgnoreListsTest(TestCase):
    """Verify EPG ignore list getters handle corrupted stored data."""

    def _set_epg_field_raw(self, field, raw_value):
        obj, _ = CoreSettings.objects.get_or_create(
            key=EPG_SETTINGS_KEY,
            defaults={"name": "EPG Settings", "value": {}},
        )
        current = obj.value if isinstance(obj.value, dict) else {}
        current[field] = raw_value
        obj.value = current
        obj.save()

    def test_valid_string_lists_returned(self):
        for field, getter in [
            ("epg_match_ignore_prefixes", CoreSettings.get_epg_match_ignore_prefixes),
            ("epg_match_ignore_suffixes", CoreSettings.get_epg_match_ignore_suffixes),
            ("epg_match_ignore_custom", CoreSettings.get_epg_match_ignore_custom),
        ]:
            self._set_epg_field_raw(field, ["HD", "SD"])
            self.assertEqual(getter(), ["HD", "SD"])

    def test_non_string_elements_filtered(self):
        for field, getter in [
            ("epg_match_ignore_prefixes", CoreSettings.get_epg_match_ignore_prefixes),
            ("epg_match_ignore_suffixes", CoreSettings.get_epg_match_ignore_suffixes),
            ("epg_match_ignore_custom", CoreSettings.get_epg_match_ignore_custom),
        ]:
            self._set_epg_field_raw(field, [42, None, "HD", True, "SD"])
            result = getter()
            self.assertEqual(result, ["HD", "SD"])

    def test_non_list_value_returns_empty(self):
        for field, getter in [
            ("epg_match_ignore_prefixes", CoreSettings.get_epg_match_ignore_prefixes),
            ("epg_match_ignore_suffixes", CoreSettings.get_epg_match_ignore_suffixes),
            ("epg_match_ignore_custom", CoreSettings.get_epg_match_ignore_custom),
        ]:
            self._set_epg_field_raw(field, "not a list")
            self.assertEqual(getter(), [])


class DropDBCommandTlsTest(TestCase):
    """Verify dropdb management command passes TLS parameters to psycopg2."""
    databases = []

    _DB_WITH_TLS = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'testdb',
            'USER': 'testuser',
            'PASSWORD': 'testpass',
            'HOST': 'localhost',
            'PORT': 5432,
            'OPTIONS': {
                'sslmode': 'verify-full',
                'sslrootcert': '/certs/ca.crt',
                'sslcert': '/certs/client.crt',
                'sslkey': '/certs/client.key',
            },
        }
    }

    _DB_NO_TLS = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'testdb',
            'USER': 'testuser',
            'PASSWORD': 'testpass',
            'HOST': 'localhost',
            'PORT': 5432,
        }
    }

    @patch('core.management.commands.dropdb.psycopg2.connect')
    @patch('core.management.commands.dropdb.connection')
    @patch('builtins.input', return_value='yes')
    def test_dropdb_passes_ssl_kwargs_when_tls_enabled(self, _inp, _conn, mock_connect):
        mock_pg = MagicMock()
        mock_connect.return_value = mock_pg
        mock_pg.cursor.return_value = MagicMock()

        with self.settings(DATABASES=self._DB_WITH_TLS):
            from django.core.management import call_command
            call_command('dropdb')

        mock_connect.assert_called_once_with(
            dbname='postgres', user='testuser', password='testpass',
            host='localhost', port=5432,
            sslmode='verify-full',
            sslrootcert='/certs/ca.crt',
            sslcert='/certs/client.crt',
            sslkey='/certs/client.key',
        )

    @patch('core.management.commands.dropdb.psycopg2.connect')
    @patch('core.management.commands.dropdb.connection')
    @patch('builtins.input', return_value='yes')
    def test_dropdb_no_ssl_kwargs_when_tls_disabled(self, _inp, _conn, mock_connect):
        mock_pg = MagicMock()
        mock_connect.return_value = mock_pg
        mock_pg.cursor.return_value = MagicMock()

        with self.settings(DATABASES=self._DB_NO_TLS):
            from django.core.management import call_command
            call_command('dropdb')

        mock_connect.assert_called_once_with(
            dbname='postgres', user='testuser', password='testpass',
            host='localhost', port=5432,
        )
