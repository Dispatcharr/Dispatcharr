import uuid

from django.test import SimpleTestCase, TestCase

from core.utils import custom_properties_as_dict, ensure_custom_properties_dict
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.channels.models import ChannelGroupM3UAccount, ChannelGroup


class CustomPropertiesAsDictTests(SimpleTestCase):
    def test_dict_passthrough(self):
        value = {"enable_vod": True}
        self.assertIs(custom_properties_as_dict(value), value)

    def test_json_string_parsed(self):
        self.assertEqual(
            custom_properties_as_dict('{"enable_vod": true}'),
            {"enable_vod": True},
        )

    def test_non_json_string_returns_empty_dict(self):
        self.assertEqual(custom_properties_as_dict("not-json"), {})

    def test_json_array_returns_empty_dict(self):
        self.assertEqual(custom_properties_as_dict("[1, 2]"), {})

    def test_none_returns_empty_dict(self):
        self.assertEqual(custom_properties_as_dict(None), {})


class EnsureCustomPropertiesDictTests(SimpleTestCase):
    def test_dict_passthrough_without_reparse(self):
        value = {"enable_vod": True}
        self.assertIs(ensure_custom_properties_dict(value), value)

    def test_none_returns_empty_dict(self):
        self.assertEqual(ensure_custom_properties_dict(None), {})


class CustomPropertiesSaveNormalizationTests(TestCase):
    def test_m3u_account_save_rewrites_string_custom_properties(self):
        account = M3UAccount.objects.create(
            name=f"Test Account {uuid.uuid4().hex[:8]}",
            custom_properties='{"enable_vod": true}',
        )
        account.refresh_from_db()
        self.assertEqual(account.custom_properties, {"enable_vod": True})

    def test_profile_save_rewrites_string_custom_properties(self):
        account = M3UAccount.objects.create(
            name=f"Test Account {uuid.uuid4().hex[:8]}"
        )
        profile = M3UAccountProfile.objects.get(
            m3u_account=account, is_default=True
        )
        profile.custom_properties = '{"notes": "hello"}'
        profile.save(update_fields=["custom_properties"])
        profile.refresh_from_db()
        self.assertEqual(profile.custom_properties, {"notes": "hello"})

    def test_group_relation_save_rewrites_string_custom_properties(self):
        account = M3UAccount.objects.create(
            name=f"Test Account {uuid.uuid4().hex[:8]}"
        )
        group = ChannelGroup.objects.create(
            name=f"Sports {uuid.uuid4().hex[:8]}"
        )
        rel = ChannelGroupM3UAccount.objects.create(
            m3u_account=account,
            channel_group=group,
            custom_properties='{"force_dummy_epg": true}',
        )
        rel.refresh_from_db()
        self.assertEqual(rel.custom_properties, {"force_dummy_epg": True})
