"""Default-profile max_streams sync via M3UAccount post_save.

Account form Max Streams is mirrored onto the default profile. Refresh
status/last_message saves must not rewrite the profile row, or they can
race with XC account-info refresh and clobber exp_date / custom_properties.
"""
from datetime import datetime, timezone
from unittest.mock import patch

from django.test import TestCase

from apps.m3u.models import M3UAccount, M3UAccountProfile


class DefaultProfileMaxStreamsSignalTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Signal Account",
            server_url="http://example.com/playlist.m3u",
            max_streams=3,
        )
        self.profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )

    def test_create_sets_default_profile_max_streams(self):
        self.assertEqual(self.profile.max_streams, 3)

    def test_full_save_syncs_changed_max_streams(self):
        self.account.max_streams = 7
        self.account.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.max_streams, 7)

    def test_update_fields_max_streams_syncs(self):
        self.account.max_streams = 9
        self.account.save(update_fields=["max_streams"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.max_streams, 9)

    def test_status_only_save_skips_profile_update(self):
        with patch.object(
            M3UAccountProfile.objects,
            "filter",
            wraps=M3UAccountProfile.objects.filter,
        ) as filter_mock:
            self.account.status = M3UAccount.Status.FETCHING
            self.account.last_message = "Starting download..."
            self.account.save(update_fields=["status", "last_message"])
            filter_mock.assert_not_called()

    def test_status_only_save_preserves_profile_expiration(self):
        exp = datetime(2026, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
        self.profile.custom_properties = {
            "user_info": {"exp_date": str(int(exp.timestamp()))}
        }
        self.profile.exp_date = exp
        self.profile.save(update_fields=["custom_properties", "exp_date"])

        self.account.status = M3UAccount.Status.SUCCESS
        self.account.last_message = "Done"
        self.account.save(update_fields=["status", "last_message"])

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.exp_date, exp)
        self.assertEqual(
            self.profile.custom_properties["user_info"]["exp_date"],
            str(int(exp.timestamp())),
        )

    def test_unchanged_max_streams_does_not_call_profile_save(self):
        with patch.object(M3UAccountProfile, "save") as save_mock:
            self.account.name = "Signal Account Renamed"
            self.account.save()
            save_mock.assert_not_called()

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.max_streams, 3)

    def test_full_save_unchanged_max_streams_does_not_clobber_exp_date(self):
        """Regression: old signal full-saved the default profile on every account
        save and could overwrite a concurrent XC account-info refresh."""
        newer = datetime(2028, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        M3UAccountProfile.objects.filter(pk=self.profile.pk).update(
            exp_date=newer,
            custom_properties={
                "user_info": {
                    "username": "u",
                    "exp_date": str(int(newer.timestamp())),
                }
            },
        )

        self.account.name = "Renamed During Refresh"
        self.account.last_message = "still refreshing"
        self.account.save()

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.exp_date, newer)
        self.assertEqual(
            self.profile.custom_properties["user_info"]["exp_date"],
            str(int(newer.timestamp())),
        )

    def test_sync_does_not_fire_profile_post_save(self):
        """QuerySet.update bypasses model save, so expiration-notification
        post_save must not run when only max_streams is mirrored."""
        with patch(
            "apps.m3u.signals.evaluate_profile_expiration_notification",
            create=True,
        ):
            with patch(
                "apps.m3u.tasks.evaluate_profile_expiration_notification"
            ) as notify_mock:
                self.account.max_streams = 11
                self.account.save(update_fields=["max_streams"])
                notify_mock.assert_not_called()

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.max_streams, 11)
