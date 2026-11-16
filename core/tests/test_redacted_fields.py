"""Provider credentials are masked in stored status messages and system events."""
from importlib import import_module

from django.apps import apps as django_apps
from django.db import connection
from django.test import TestCase

from apps.epg.models import EPGSource
from apps.m3u.models import M3UAccount
from core.models import SystemEvent
from core.utils import log_system_event

XC_ERROR = (
    "HTTPConnectionPool(host='provider.test', port=8080): Max retries exceeded with url: "
    "/player_api.php?username=u1-secret&password=p1-secret (Caused by ConnectTimeoutError)"
)
LIVE_URL = "http://provider.test:8080/live/u1-secret/p1-secret/123.ts"


def _raw(table, column, row_id):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {table} WHERE id = %s", [row_id])
        return cursor.fetchone()[0]


def _set_raw(table, column, row_id, value):
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET {column} = %s WHERE id = %s", [value, row_id])


class RedactedStatusMessageTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Redact XC", server_url="http://provider.test:8080", account_type="XC"
        )

    def assertMasked(self, stored):
        self.assertNotIn("u1-secret", stored)
        self.assertNotIn("p1-secret", stored)

    def test_queryset_update_masks_last_message(self):
        M3UAccount.objects.filter(pk=self.account.pk).update(last_message=XC_ERROR)
        stored = _raw("m3u_m3uaccount", "last_message", self.account.pk)
        self.assertMasked(stored)
        self.assertIn("Max retries exceeded", stored)

    def test_save_masks_last_message(self):
        self.account.last_message = f"Failed to fetch {LIVE_URL}"
        self.account.save()
        self.assertMasked(_raw("m3u_m3uaccount", "last_message", self.account.pk))

    def test_plain_message_is_unchanged(self):
        M3UAccount.objects.filter(pk=self.account.pk).update(last_message="Processed 120 streams")
        self.assertEqual(
            _raw("m3u_m3uaccount", "last_message", self.account.pk), "Processed 120 streams"
        )

    def test_epg_last_message_masked(self):
        source = EPGSource.objects.create(name="Redact EPG", source_type="xmltv")
        EPGSource.objects.filter(pk=source.pk).update(
            last_message="Download failed: http://provider.test/xmltv.php?username=u1-secret&password=p1-secret"
        )
        self.assertMasked(_raw("epg_epgsource", "last_message", source.pk))


class RedactedSystemEventTests(TestCase):
    def test_log_system_event_masks_nested_details(self):
        log_system_event(
            "m3u_error",
            account_name="Redact XC",
            message=XC_ERROR,
            attempts=[{"url": LIVE_URL}, 3],
        )
        event = SystemEvent.objects.get(event_type="m3u_error")
        stored = str(_raw("core_systemevent", "details", event.pk))
        self.assertNotIn("u1-secret", stored)
        self.assertNotIn("p1-secret", stored)
        self.assertEqual(event.details["account_name"], "Redact XC")
        self.assertEqual(event.details["attempts"][1], 3)


class RedactExistingMigrationTests(TestCase):
    def test_existing_rows_are_masked(self):
        account = M3UAccount.objects.create(
            name="Legacy msg", server_url="http://provider.test:8080", account_type="XC"
        )
        _set_raw("m3u_m3uaccount", "last_message", account.pk, XC_ERROR)
        event = SystemEvent.objects.create(event_type="m3u_error", details={})
        _set_raw("core_systemevent", "details", event.pk, '{"message": "%s"}' % XC_ERROR)

        import_module("apps.m3u.migrations.0020_redact_last_message").redact_existing(django_apps, None)
        import_module("core.migrations.0035_redact_system_event_details").redact_existing(django_apps, None)

        for stored in (
            _raw("m3u_m3uaccount", "last_message", account.pk),
            str(_raw("core_systemevent", "details", event.pk)),
        ):
            self.assertNotIn("p1-secret", stored)
            self.assertNotIn("u1-secret", stored)
