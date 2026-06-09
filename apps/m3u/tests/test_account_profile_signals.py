from django.db.models.signals import post_save
from django.test import TestCase

from apps.m3u.models import M3UAccount, M3UAccountProfile


class M3UAccountProfileSignalTests(TestCase):
    def test_account_max_streams_update_does_not_resave_default_profile(self):
        account = M3UAccount.objects.create(
            name="KPTV FAST",
            server_url="http://example.com/playlist.m3u",
            max_streams=1,
        )
        profile = account.profiles.get(is_default=True)
        self.assertEqual(profile.max_streams, 1)

        profile_post_save_events = []

        def capture_profile_save(sender, instance, created, **kwargs):
            profile_post_save_events.append((instance.pk, created))

        dispatch_uid = "test_account_max_streams_update_does_not_resave_default_profile"
        post_save.connect(
            capture_profile_save,
            sender=M3UAccountProfile,
            weak=False,
            dispatch_uid=dispatch_uid,
        )
        try:
            account.max_streams = 4
            account.save(update_fields=["max_streams"])
        finally:
            post_save.disconnect(
                sender=M3UAccountProfile,
                dispatch_uid=dispatch_uid,
            )

        profile.refresh_from_db()
        self.assertEqual(profile.max_streams, 4)
        self.assertEqual(profile_post_save_events, [])
