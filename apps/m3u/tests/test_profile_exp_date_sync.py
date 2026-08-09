"""M3UAccountProfile.save() exp_date sync from custom_properties.

XC accounts keep provider exp_date as the source of truth. Standard accounts
set exp_date manually and must not be overwritten by leftover XC user_info
(e.g. after converting an account from XC to Standard).
"""
from datetime import datetime, timezone

from django.test import TestCase

from apps.m3u.models import M3UAccount, M3UAccountProfile


class ProfileExpDateSyncTests(TestCase):
    def _make_account(self, account_type, name="Exp Sync Account"):
        return M3UAccount.objects.create(
            name=name,
            server_url="http://example.com/playlist.m3u",
            account_type=account_type,
        )

    def test_std_account_manual_exp_date_not_overwritten_by_stale_xc_props(self):
        account = self._make_account(M3UAccount.Types.STADNARD)
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)

        stale = datetime(2026, 7, 17, 21, 28, 6, tzinfo=timezone.utc)
        manual = datetime(2027, 7, 17, 21, 28, 0, tzinfo=timezone.utc)
        profile.custom_properties = {
            "user_info": {"exp_date": str(int(stale.timestamp()))},
        }
        profile.exp_date = manual
        profile.save(update_fields=["custom_properties", "exp_date"])

        profile.refresh_from_db()
        self.assertEqual(profile.exp_date, manual)

    def test_xc_account_still_syncs_exp_date_from_custom_properties(self):
        account = self._make_account(M3UAccount.Types.XC, name="XC Exp Sync")
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)

        provider = datetime(2028, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        profile.custom_properties = {
            "user_info": {"exp_date": str(int(provider.timestamp()))},
        }
        profile.exp_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        profile.save(update_fields=["custom_properties", "exp_date"])

        profile.refresh_from_db()
        self.assertEqual(profile.exp_date, provider)
