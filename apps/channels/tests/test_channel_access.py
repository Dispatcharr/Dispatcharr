"""Shared channel visibility rules and the surfaces that rely on them."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import TestCase
from django.utils import timezone

from apps.channels.access import (
    channels_queryset_for_user,
    get_channel_for_user,
    scope_by_channel_access,
    user_can_access_channel,
    user_may_use_profile,
)
from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelProfile,
    ChannelProfileMembership,
    Recording,
)
from apps.output.views import xc_get_live_categories
from apps.proxy.live_proxy.views import _resolve_xc_live_channel

User = get_user_model()


def _make_user(username, level, **custom_properties):
    user = User.objects.create_user(username=username, password="x")
    user.user_level = level
    user.custom_properties = custom_properties
    user.save()
    return user


class ChannelsQuerysetForUserTests(TestCase):
    def setUp(self):
        self.allowed = Channel.objects.create(
            channel_number=1, name="Allowed", user_level=0
        )
        self.profile_hidden = Channel.objects.create(
            channel_number=2, name="Other profile", user_level=0
        )
        self.adult = Channel.objects.create(
            channel_number=3, name="Adult", user_level=0, is_adult=True
        )
        self.high_level = Channel.objects.create(
            channel_number=4, name="High", user_level=5
        )
        self.over_admin_level = Channel.objects.create(
            channel_number=5, name="Over admin", user_level=11
        )

        self.profile = ChannelProfile.objects.create(name="Access profile")
        ChannelProfileMembership.objects.filter(
            channel_profile=self.profile, channel=self.profile_hidden
        ).update(enabled=False)

        self.standard = _make_user("access-standard", 1)
        self.standard.channel_profiles.add(self.profile)
        self.admin = _make_user("access-admin", 10)

    def _ids(self, user, **kwargs):
        return set(
            channels_queryset_for_user(
                Channel.objects.all(), user, **kwargs
            ).values_list("id", flat=True)
        )

    def test_standard_user_is_limited_to_assigned_profiles(self):
        ids = self._ids(self.standard)
        self.assertIn(self.allowed.id, ids)
        self.assertNotIn(self.profile_hidden.id, ids)

    def test_user_without_profiles_sees_every_channel_within_level(self):
        unrestricted = _make_user("access-unrestricted", 1)
        ids = self._ids(unrestricted)
        self.assertEqual(
            ids, {self.allowed.id, self.profile_hidden.id, self.adult.id}
        )

    def test_user_level_filters_higher_channels(self):
        ids = self._ids(self.standard, profiles=False)
        self.assertNotIn(self.high_level.id, ids)
        self.assertNotIn(self.over_admin_level.id, ids)

    def test_adult_preference_hides_adult_channels(self):
        self.standard.custom_properties = {"hide_adult_content": True}
        self.standard.save(update_fields=["custom_properties"])
        self.assertNotIn(self.adult.id, self._ids(self.standard, profiles=False))

    def test_adult_channels_are_visible_without_the_preference(self):
        self.assertIn(self.adult.id, self._ids(self.standard, profiles=False))

    def test_profiles_false_keeps_out_of_profile_channel(self):
        self.assertIn(
            self.profile_hidden.id, self._ids(self.standard, profiles=False)
        )

    def test_admin_sees_every_channel_by_default(self):
        self.assertEqual(
            self._ids(self.admin),
            {
                self.allowed.id,
                self.profile_hidden.id,
                self.adult.id,
                self.high_level.id,
                self.over_admin_level.id,
            },
        )

    def test_level_cap_admins_hides_channels_above_admin_level(self):
        capped = self._ids(self.admin, level_cap_admins=True)
        self.assertNotIn(self.over_admin_level.id, capped)
        self.assertIn(self.high_level.id, capped)

    def test_unauthenticated_user_sees_nothing(self):
        self.assertEqual(self._ids(None), set())

    def test_user_can_access_channel_matches_queryset(self):
        self.assertTrue(user_can_access_channel(self.standard, self.allowed))
        self.assertFalse(user_can_access_channel(self.standard, self.profile_hidden))
        self.assertFalse(user_can_access_channel(self.standard, self.high_level))

    def test_get_channel_for_user_is_one_query(self):
        # Profile membership is folded into Exists subqueries so a single
        # channel lookup does not need a separate channel_profiles.exists().
        with self.assertNumQueries(1):
            self.assertEqual(
                get_channel_for_user(self.standard, id=self.allowed.id),
                self.allowed,
            )
        with self.assertNumQueries(1):
            self.assertIsNone(
                get_channel_for_user(self.standard, id=self.profile_hidden.id)
            )

    def test_admin_can_access_any_channel(self):
        self.assertTrue(user_can_access_channel(self.admin, self.over_admin_level))

    def test_user_may_use_profile(self):
        other = ChannelProfile.objects.create(name="Not assigned")
        self.assertTrue(user_may_use_profile(self.admin, other.id))
        self.assertTrue(user_may_use_profile(self.standard, self.profile.id))
        self.assertFalse(user_may_use_profile(self.standard, other.id))
        unrestricted = _make_user("access-free", 1)
        self.assertTrue(user_may_use_profile(unrestricted, other.id))

    def test_scope_by_channel_access_limits_rows_owned_by_a_channel(self):
        now = timezone.now()
        make = lambda channel: Recording.objects.create(
            channel=channel,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )
        visible = make(self.allowed)
        hidden = make(self.profile_hidden)
        scoped = set(
            scope_by_channel_access(Recording.objects.all(), self.standard).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(scoped, {visible.id})
        everything = set(
            scope_by_channel_access(Recording.objects.all(), self.admin).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(everything, {visible.id, hidden.id})


class ChannelAccessSurfaceTests(TestCase):
    """The XC and catch-up paths look channels up by a guessable integer id."""

    def setUp(self):
        self.adult_group = ChannelGroup.objects.create(name="AdultOnly")
        self.mixed_group = ChannelGroup.objects.create(name="Mixed")
        self.outside_group = ChannelGroup.objects.create(name="OutsideProfile")

        self.adult = Channel.objects.create(
            channel_number=1,
            name="Adult",
            user_level=0,
            is_adult=True,
            channel_group=self.adult_group,
        )
        self.safe = Channel.objects.create(
            channel_number=2, name="Safe", user_level=0, channel_group=self.mixed_group
        )
        self.mixed_adult = Channel.objects.create(
            channel_number=3,
            name="MixedAdult",
            user_level=0,
            is_adult=True,
            channel_group=self.mixed_group,
        )
        self.outside = Channel.objects.create(
            channel_number=4,
            name="Outside",
            user_level=0,
            channel_group=self.outside_group,
        )

        self.profile = ChannelProfile.objects.create(name="Surface profile")
        ChannelProfileMembership.objects.filter(
            channel_profile=self.profile, channel=self.outside
        ).update(enabled=False)

        self.user = _make_user("surface-user", 1, hide_adult_content=True)
        self.user.channel_profiles.add(self.profile)
        self.admin = _make_user("surface-admin", 10)

    def _category_names(self, user):
        return {row["category_name"] for row in xc_get_live_categories(user)}

    def test_categories_omit_a_group_whose_only_channels_are_adult(self):
        names = self._category_names(self.user)
        self.assertIn("Mixed", names)
        self.assertNotIn("AdultOnly", names)

    def test_categories_omit_a_group_whose_only_channels_are_outside_the_profile(self):
        self.assertNotIn("OutsideProfile", self._category_names(self.user))

    def test_categories_include_adult_group_without_the_preference(self):
        self.user.custom_properties = {}
        self.user.save(update_fields=["custom_properties"])
        self.assertIn("AdultOnly", self._category_names(self.user))

    def test_xc_live_resolve_hides_adult_channel(self):
        channel, error = _resolve_xc_live_channel(self.user, self.adult.id)
        self.assertIsNone(channel)
        self.assertEqual(error.status_code, 404)

    def test_xc_live_resolve_hides_channel_outside_profile(self):
        channel, error = _resolve_xc_live_channel(self.user, self.outside.id)
        self.assertIsNone(channel)
        self.assertEqual(error.status_code, 404)

    def test_xc_live_resolve_returns_accessible_channel(self):
        channel, error = _resolve_xc_live_channel(self.user, self.safe.id)
        self.assertEqual(channel.id, self.safe.id)
        self.assertIsNone(error)

    def test_xc_live_resolve_admin_unknown_channel_is_not_found(self):
        with self.assertRaises(Http404):
            _resolve_xc_live_channel(self.admin, 999999)

    def test_catchup_access_denies_adult_and_outside_profile_channels(self):
        self.assertIsNone(get_channel_for_user(self.user, id=self.adult.id))
        self.assertIsNone(get_channel_for_user(self.user, id=self.outside.id))
        self.assertEqual(get_channel_for_user(self.user, id=self.safe.id), self.safe)
        self.assertEqual(get_channel_for_user(self.admin, id=self.adult.id), self.adult)
