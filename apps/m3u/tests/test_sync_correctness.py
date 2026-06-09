"""
Correctness reproductions and fixes for sync_auto_channels.

Each test documents a specific bug in the unpatched code: reproduces the bug
first (fails on HEAD prior to the Tier 2 patch), then is flipped to assert
the correct post-fix behavior. Comments call out the failure mode and the
fix location.
"""
from unittest import skipUnless

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelGroupM3UAccount,
    ChannelStream,
    Stream,
)
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import sync_auto_channels


def _make_account(name="Test Provider", custom_properties=None):
    return M3UAccount.objects.create(
        name=name,
        server_url="http://example.com/test.m3u",
        custom_properties=custom_properties,
    )


def _make_group(name="Sports"):
    return ChannelGroup.objects.create(name=name)


def _attach_group_to_account(account, group, custom_properties=None):
    return ChannelGroupM3UAccount.objects.create(
        m3u_account=account,
        channel_group=group,
        enabled=True,
        auto_channel_sync=True,
        auto_sync_channel_start=100,
        custom_properties=custom_properties,
    )


def _make_stream(account, group, name="ESPN", tvg_id="espn", stream_chno=None):
    return Stream.objects.create(
        name=name,
        url=f"http://example.com/{name.lower()}.m3u8",
        m3u_account=account,
        channel_group=group,
        tvg_id=tvg_id,
        stream_chno=stream_chno,
        last_seen=timezone.now(),
    )


def _sync(account):
    # Use a scan_start_time prior to the freshly-created streams so
    # `last_seen__gte=scan_start_time` includes them.
    return sync_auto_channels(
        account.id,
        scan_start_time=(timezone.now() - timezone.timedelta(minutes=1)).isoformat(),
    )


class CustomPropertiesTypeHandlingTests(TestCase):
    """
    `custom_properties` is a JSONField but at least one historical
    code path stored a JSON string instead of a dict. When
    `sync_auto_channels` reads `group_relation.custom_properties` and calls
    `.get()` on it, AttributeError is raised because the value is a string.

    Failure mode on unpatched code:
      AttributeError: 'str' object has no attribute 'get'

    The outer try/except in sync_auto_channels catches the exception and
    returns an error string, aborting the sync for every other well-formed
    group in the same account.
    """

    def test_group_custom_properties_as_string_does_not_abort_sync(self):
        account = _make_account()
        group = _make_group(name="Sports")
        # Deliberately stored as a JSON-encoded string (reproducing #432).
        _attach_group_to_account(
            account,
            group,
            custom_properties='{"force_dummy_epg": true}',
        )
        _make_stream(account, group)

        result = _sync(account)

        # Post-fix: sync does not abort with an error and the stream is
        # processed normally. Pre-fix this returned "Auto sync error: ...".
        self.assertEqual(result.get("status"), "ok")

    def test_group_custom_properties_as_string_with_streams_still_creates_channels(self):
        # Tighter version of the first test: with a real stream attached to
        # the group, the pre-fix failure aborts before creating the channel.
        # Post-fix, the channel is created normally and the string-typed
        # custom_properties is treated as an empty dict (no custom regex,
        # no group_override, etc.).
        account = _make_account()
        group = _make_group(name="Sports")
        _attach_group_to_account(
            account,
            group,
            custom_properties='{"name_regex_pattern": "HD"}',
        )
        _make_stream(account, group, name="ESPN HD", tvg_id="espn")

        result = _sync(account)

        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(
            Channel.objects.filter(auto_created=True, auto_created_by=account).count(),
            1,
            "Exactly one channel should have been created from the single stream",
        )


class NullAutoCreatedByOrphanTests(TestCase):
    """
    Channels with `auto_created=True, auto_created_by=NULL` are never touched
    by sync (it filters on `auto_created_by=account`). These rows accumulate
    indefinitely.

    The fix is a backfill migration that either re-attributes the row by
    matching its linked stream to an M3U account, or deletes it if
    unattributable. Until that migration runs, sync has no way to clean them
    up. This test confirms the current behavior so we can write the migration
    with correct expectations.
    """

    def test_null_auto_created_by_rows_are_untouched_by_sync(self):
        account = _make_account()
        group = _make_group(name="Entertainment")
        _attach_group_to_account(account, group)

        orphan = Channel.objects.create(
            name="OrphanChannel",
            channel_number=999,
            channel_group=group,
            auto_created=True,
            auto_created_by=None,
        )

        # Run sync with no streams; normal orphan cleanup only deletes rows
        # scoped to the account. The NULL-owner row should still be there.
        _sync(account)

        orphan.refresh_from_db()
        self.assertIsNotNone(orphan.id, "Pre-fix: NULL-owner rows are not cleaned")


class AccountDeleteCleanupTests(TestCase):
    """
    Deleting an M3UAccount unconditionally cascades auto-created
    channels owned by the account. An auto-created channel without a
    surviving provider has no useful state (it cannot sync, its
    streams cascade away), so the destroy endpoint always removes
    them. The legacy ``cleanup_channels`` query parameter is accepted
    for backward compatibility but ignored.
    """

    def test_destroy_cascades_auto_created_channels_unconditionally(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User

        admin = User.objects.create_superuser(
            username="admin_delcleanup_a",
            password="pw",
            user_level=10,
        )
        account = _make_account()
        group = _make_group(name="Entertainment")
        Channel.objects.create(
            name="ShouldCascade",
            channel_number=700,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.delete(f"/api/m3u/accounts/{account.id}/")

        # Cascade returns 200 with the deleted count body so the UI can
        # toast the number of channels removed alongside the account.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("deleted_channels"), 1)
        self.assertEqual(
            Channel.objects.filter(auto_created=True).count(), 0
        )

    def test_destroy_with_cleanup_removes_auto_created_channels(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User

        admin = User.objects.create_superuser(
            username="admin_delcleanup_b",
            password="pw",
            user_level=10,
        )
        account = _make_account()
        group = _make_group(name="News")
        Channel.objects.create(
            name="Cleanme1",
            channel_number=710,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        Channel.objects.create(
            name="Cleanme2",
            channel_number=711,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.delete(
            f"/api/m3u/accounts/{account.id}/?cleanup_channels=true"
        )

        # Cleanup returns 200 with the deleted count body (so the UI can
        # toast "Deleted N channels"). Without cleanup it would be 204.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("deleted_channels"), 2)
        self.assertEqual(
            Channel.objects.filter(auto_created=True).count(),
            0,
        )

    def test_auto_created_channels_count_endpoint(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User

        admin = User.objects.create_superuser(
            username="admin_delcleanup_c",
            password="pw",
            user_level=10,
        )
        account = _make_account()
        group = _make_group(name="Sports")
        for i in range(3):
            Channel.objects.create(
                name=f"AutoChan{i}",
                channel_number=800 + i,
                channel_group=group,
                auto_created=True,
                auto_created_by=account,
            )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(
            f"/api/m3u/accounts/{account.id}/auto-created-channels-count/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["sample_names"]), 3)


class ChannelDeleteStopsProxyTests(TestCase):
    """
    Issue #870: When an auto-sync refresh deletes a channel that has an
    active proxy session, the session's Redis state survives, making the UI
    "Stop" button fail with 'Channel not found'. Fix is a pre_delete signal
    on Channel that calls ChannelService.stop_channel first, covering
    manual, bulk, and sync-triggered deletes uniformly.
    """

    def test_pre_delete_signal_calls_stop_channel(self):
        from unittest.mock import patch

        account = _make_account()
        group = _make_group(name="Sports")
        channel = Channel.objects.create(
            name="ESPN",
            channel_number=1,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        channel_uuid = str(channel.uuid)

        with patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService.stop_channel"
        ) as mock_stop:
            channel.delete()

        mock_stop.assert_called_once_with(channel_uuid)

    def test_pre_delete_signal_swallows_stop_errors(self):
        """Proxy failure must not block the DB delete."""
        from unittest.mock import patch

        account = _make_account()
        group = _make_group(name="Sports")
        channel = Channel.objects.create(
            name="ESPN",
            channel_number=1,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )

        with patch(
            "apps.proxy.live_proxy.services.channel_service.ChannelService.stop_channel",
            side_effect=Exception("proxy is down"),
        ):
            channel.delete()

        self.assertFalse(Channel.objects.filter(id=channel.id).exists())


class RangeEnforcementTests(TestCase):
    """
    Tier 4 feature: optional per-group `auto_sync_channel_end` caps the
    number range a group can use. Streams that don't fit get surfaced in
    the completion notification as failures rather than silently spilling
    into a neighboring group's range.
    """

    def test_range_allows_streams_within_bounds(self):
        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_end = 105
        rel.auto_sync_channel_start = 100
        rel.save()

        for i in range(3):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_created"], 3)
        self.assertEqual(result["channels_failed"], 0)

    def test_range_exhaustion_surfaces_failures(self):
        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(account, group)
        # Range holds 2 slots: 100, 101.
        rel.auto_sync_channel_start = 100
        rel.auto_sync_channel_end = 101
        rel.save()

        for i in range(4):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_created"], 2)
        self.assertEqual(result["channels_failed"], 2)
        self.assertEqual(len(result["failed_stream_details"]), 2)
        for detail in result["failed_stream_details"]:
            self.assertIn("range", detail["error"].lower())
            self.assertEqual(detail["reason"], "RANGE_EXHAUSTED")

    def test_used_numbers_seed_includes_override_pinned_values(self):
        # Channel A has override.channel_number=42 pinning effective #42
        # globally. Sync creating a new channel B in fixed mode starting
        # at 1 must skip 42; otherwise B's raw channel_number=42 collides
        # with A's effective number, producing duplicate output entries
        # at the same channel number.
        from apps.channels.models import ChannelOverride

        account = _make_account()
        group = _make_group(name="News")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 1.0
        rel.save()

        # A: pre-existing manual channel with override pinning #42.
        a = Channel.objects.create(
            channel_number=999.0,
            name="UserPinned",
            tvg_id="user_pinned",
            channel_group=group,
            auto_created=False,
        )
        ChannelOverride.objects.create(channel=a, channel_number=42.0)

        # Provide enough new streams to walk past 42 in fixed mode.
        for i in range(45):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        result = _sync(account)
        self.assertEqual(result["status"], "ok")

        new_numbers = list(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).values_list("channel_number", flat=True)
        )
        self.assertNotIn(
            42.0,
            new_numbers,
            "Sync must skip override-pinned numbers; assigning #42 to a "
            "new auto-channel duplicates A's effective channel number.",
        )

    def test_provider_mode_numberless_fallback_uses_visible_start(self):
        # In provider mode the visible "Start #" is channel_numbering_fallback,
        # so a numberless stream's fallback walks from there, not from the
        # hidden auto_sync_channel_start (set far above the range here to prove
        # it is ignored).
        # Fail signature: 0 channels created, or a channel below 100 = fallback
        # seeded from the wrong field.
        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 5000  # hidden; must be ignored
        rel.auto_sync_channel_end = 200
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 100,  # the visible "Start #"
        }
        rel.save()

        _make_stream(account, group, name="NoChno", tvg_id="nc")

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_created"], 1)
        created = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertGreaterEqual(created.channel_number, 100)
        self.assertLessEqual(created.channel_number, 200)


class ReservationBehaviorTests(TestCase):
    """
    Ranges with both `auto_sync_channel_start` and `auto_sync_channel_end`
    set are advisory at the UI layer. Sync does not treat another group's
    declared range as off-limits; only channels that are actually assigned
    a number count toward used_numbers. This lets two groups carrying the
    same category (e.g. "Entertainment" from two different providers)
    share a number range by cooperative fill, which is the intended UX
    for merged-provider setups.

    The UI surfaces overlap between ranges as an advisory heads-up rather
    than a blocking error, and the sync task enforces only real occupancy.
    """

    def test_self_reservation_lets_group_use_its_own_range(self):
        # A group with a range assigns within that range. This is the
        # baseline case the UI advisory is built around.
        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 1000
        rel.auto_sync_channel_end = 1010
        rel.save()

        for i in range(3):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_created"], 3)
        numbers = sorted(
            Channel.objects.filter(
                channel_group=group,
                auto_created=True,
                auto_created_by=account,
            ).values_list("channel_number", flat=True)
        )
        self.assertTrue(
            all(1000 <= n <= 1010 for n in numbers),
            f"Channels outside own range: {numbers}",
        )

    def test_overlapping_ranges_cooperate_when_no_existing_channels(self):
        # Two groups with overlapping ranges but no pre-existing channels
        # in the overlap should both be able to fill numbers in the shared
        # range. Sync only avoids actual occupancy, not declared intent.
        account_a = _make_account(name="Provider A")
        account_b = _make_account(name="Provider B")
        group_a = _make_group(name="Entertainment A")
        group_b = _make_group(name="Entertainment B")

        rel_a = _attach_group_to_account(account_a, group_a)
        rel_a.auto_sync_channel_start = 1
        rel_a.auto_sync_channel_end = 10
        rel_a.save()

        rel_b = _attach_group_to_account(account_b, group_b)
        rel_b.auto_sync_channel_start = 1
        rel_b.auto_sync_channel_end = 10
        rel_b.save()

        # 3 streams in A, 3 in B. With shared range 1-10 and no prior
        # occupancy, A fills some numbers, B fills the remaining free ones.
        for i in range(3):
            _make_stream(account_a, group_a, name=f"A{i}", tvg_id=f"a{i}")
            _make_stream(account_b, group_b, name=f"B{i}", tvg_id=f"b{i}")

        _sync(account_a)
        _sync(account_b)

        all_numbers = sorted(
            Channel.objects.filter(auto_created=True).values_list(
                "channel_number", flat=True
            )
        )
        self.assertEqual(len(all_numbers), 6)
        # All numbers are unique and all fit inside the shared range.
        self.assertEqual(len(set(all_numbers)), 6)
        self.assertTrue(
            all(1 <= n <= 10 for n in all_numbers),
            f"Channels outside the shared range: {all_numbers}",
        )


class NumbersInRangeLookupTests(TestCase):
    """
    Backend support for the inline range conflict warning on the group
    settings form. Returns every channel whose effective channel_number
    falls within [start, end], with context fields the frontend uses to
    classify each hit (auto-created from this group + account vs anything
    else). Matching uses effective values so overrides participate.
    """

    def _client(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User

        admin = User.objects.create_superuser(
            username="admin_inrange",
            password="pw",
            user_level=10,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        return client

    def test_returns_occupants_within_range(self):
        group = _make_group(name="Sports")
        Channel.objects.create(
            name="CNN", channel_number=100, channel_group=group
        )
        Channel.objects.create(
            name="Local 5", channel_number=105, channel_group=group
        )
        client = self._client()

        response = client.get(
            "/api/channels/channels/numbers-in-range/?start=100&end=110"
        )

        self.assertEqual(response.status_code, 200)
        names = sorted(o["name"] for o in response.data["occupants"])
        self.assertEqual(names, ["CNN", "Local 5"])

    def test_returns_empty_when_no_channels_in_range(self):
        client = self._client()
        response = client.get(
            "/api/channels/channels/numbers-in-range/?start=900&end=999"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["occupants"], [])

    def test_single_number_lookup_when_end_omitted(self):
        # Mirrors the case where the user has set Start # but not End #.
        # Endpoint should treat omitted end as a single-number lookup.
        group = _make_group(name="Sports")
        Channel.objects.create(
            name="CNN", channel_number=100, channel_group=group
        )
        client = self._client()
        response = client.get(
            "/api/channels/channels/numbers-in-range/?start=100"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["occupants"]), 1)

    def test_override_channel_number_is_treated_as_effective(self):
        from apps.channels.models import ChannelOverride

        group = _make_group(name="News")
        ch = Channel.objects.create(
            name="Raw",
            channel_number=500,
            channel_group=group,
            auto_created=True,
        )
        ChannelOverride.objects.create(channel=ch, channel_number=777)
        client = self._client()

        # Raw value 500 must NOT match - overrides are authoritative.
        miss = client.get(
            "/api/channels/channels/numbers-in-range/?start=500&end=500"
        )
        self.assertEqual(miss.data["occupants"], [])

        hit = client.get(
            "/api/channels/channels/numbers-in-range/?start=777&end=777"
        )
        self.assertEqual(len(hit.data["occupants"]), 1)
        self.assertTrue(
            hit.data["occupants"][0]["has_channel_number_override"]
        )

    def test_response_includes_group_account_and_override_flags(self):
        # The frontend uses these three fields to decide whether a hit is
        # a genuine collision or the expected output of the group it's
        # currently configuring. The endpoint must carry them through.
        account = _make_account()
        group = _make_group(name="Sports")
        Channel.objects.create(
            name="CNN",
            channel_number=100,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        client = self._client()

        response = client.get(
            "/api/channels/channels/numbers-in-range/?start=100&end=100"
        )

        occupant = response.data["occupants"][0]
        self.assertEqual(occupant["channel_group_id"], group.id)
        self.assertTrue(occupant["auto_created"])
        self.assertEqual(
            occupant["auto_created_by_account_id"], account.id
        )
        self.assertFalse(occupant["has_channel_number_override"])

    def test_manual_channel_exposed_with_auto_created_false(self):
        # Manual channels are always a real collision worth surfacing.
        # The response must flag them with auto_created=False and a null
        # account id so the frontend classifier warns.
        group = _make_group(name="Sports")
        Channel.objects.create(
            name="MyManual", channel_number=100, channel_group=group
        )
        client = self._client()

        response = client.get(
            "/api/channels/channels/numbers-in-range/?start=100&end=100"
        )

        occupant = response.data["occupants"][0]
        self.assertFalse(occupant["auto_created"])
        self.assertIsNone(occupant["auto_created_by_account_id"])

    def test_results_are_capped_at_50_entries(self):
        # The endpoint caps at 50 to keep payloads bounded; the frontend
        # only needs to know whether any unfiltered occupants remain.
        group = _make_group(name="Sports")
        for i in range(60):
            Channel.objects.create(
                name=f"Ch{i}",
                channel_number=1000 + i,
                channel_group=group,
            )
        client = self._client()
        response = client.get(
            "/api/channels/channels/numbers-in-range/?start=1000&end=1100"
        )
        self.assertEqual(len(response.data["occupants"]), 50)


class RegexPreviewTests(TestCase):
    """
    Backend support for the find/replace and filter regex previews in the
    auto-sync gear modal. Returns matched names plus full-group counts so
    the UI can show "12 matches across 5,000 streams" without loading the
    whole stream list client-side. Hard-caps at SCAN_CAP=5000 names per
    call to keep the endpoint bounded on huge groups.
    """

    def _client(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User

        admin = User.objects.create_superuser(
            username="admin_regex_preview",
            password="pw",
            user_level=10,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        return client

    def _make_account(self):
        return _make_account(name="Regex Preview Provider")

    def test_find_replace_returns_only_changed_names(self):
        account = self._make_account()
        group = _make_group(name="Sports")
        for name in ["ESPN HD", "Fox Sports HD", "CNN"]:
            Stream.objects.create(
                name=name,
                url=f"http://example.com/{name}.m3u8",
                m3u_account=account,
                channel_group=group,
                last_seen=timezone.now(),
            )
        client = self._client()

        response = client.get(
            "/api/channels/streams/regex-preview/"
            "?channel_group=Sports&find=%20HD%24&replace="
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["find_match_count"], 2)
        names = sorted(m["before"] for m in response.data["find_matches"])
        self.assertEqual(names, ["ESPN HD", "Fox Sports HD"])
        # Replacement is correctly applied in the after field.
        self.assertEqual(
            sorted(m["after"] for m in response.data["find_matches"]),
            ["ESPN", "Fox Sports"],
        )
        self.assertEqual(response.data["total_in_group"], 3)
        self.assertEqual(response.data["total_scanned"], 3)
        self.assertFalse(response.data["scan_limit_hit"])

    def test_filter_returns_matched_names_with_count(self):
        account = self._make_account()
        group = _make_group(name="Sports")
        for name in ["Sports Central", "News 24", "Sports Live"]:
            Stream.objects.create(
                name=name,
                url=f"http://example.com/{name}.m3u8",
                m3u_account=account,
                channel_group=group,
                last_seen=timezone.now(),
            )
        client = self._client()

        response = client.get(
            "/api/channels/streams/regex-preview/"
            "?channel_group=Sports&match=%5ESports"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["filter_match_count"], 2)
        matched_names = sorted(
            m["name"] for m in response.data["filter_matches"]
        )
        self.assertEqual(matched_names, ["Sports Central", "Sports Live"])

    def test_returns_zero_match_counts_when_pattern_matches_nothing(self):
        account = self._make_account()
        group = _make_group(name="Sports")
        for name in ["CNN", "MSNBC"]:
            Stream.objects.create(
                name=name,
                url=f"http://example.com/{name}.m3u8",
                m3u_account=account,
                channel_group=group,
                last_seen=timezone.now(),
            )
        client = self._client()

        response = client.get(
            "/api/channels/streams/regex-preview/"
            "?channel_group=Sports&find=ESPN&replace=Whatever"
        )

        self.assertEqual(response.data["find_match_count"], 0)
        self.assertEqual(response.data["find_matches"], [])

    def test_invalid_find_pattern_returns_error_field(self):
        # The endpoint reports compile errors via response fields rather
        # than 400 so the UI can surface them inline without the request
        # being treated as a hard failure.
        account = self._make_account()
        group = _make_group(name="Sports")
        Stream.objects.create(
            name="ESPN",
            url="http://example.com/espn.m3u8",
            m3u_account=account,
            channel_group=group,
            last_seen=timezone.now(),
        )
        client = self._client()

        response = client.get(
            "/api/channels/streams/regex-preview/"
            "?channel_group=Sports&find=("
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("find_error", response.data)

    def test_scan_limit_hit_when_group_exceeds_5000_streams(self):
        # Build a group with 5050 streams so we cross the SCAN_CAP boundary.
        # The endpoint must still return promptly and flag scan_limit_hit
        # so the UI can disclose that the preview isn't full coverage.
        account = self._make_account()
        group = _make_group(name="Bigly")
        Stream.objects.bulk_create(
            [
                Stream(
                    name=f"Stream {i}",
                    url=f"http://example.com/{i}.m3u8",
                    m3u_account=account,
                    channel_group=group,
                    last_seen=timezone.now(),
                )
                for i in range(5050)
            ]
        )
        client = self._client()

        response = client.get(
            "/api/channels/streams/regex-preview/"
            "?channel_group=Bigly&find=Stream"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["scan_limit_hit"])
        self.assertEqual(response.data["total_in_group"], 5050)
        self.assertEqual(response.data["total_scanned"], 5000)

    def test_channel_group_required(self):
        client = self._client()
        response = client.get("/api/channels/streams/regex-preview/")
        self.assertEqual(response.status_code, 400)

    def test_exclude_returns_matched_names_with_count(self):
        # Exclude pattern returns the streams it would remove, mirroring
        # the include preview shape so the UI can render both side-by-side.
        account = self._make_account()
        group = _make_group(name="Sports")
        for name in ["Sports Live", "Sports TEST", "Sports BACKUP"]:
            Stream.objects.create(
                name=name,
                url=f"http://example.com/{name}.m3u8",
                m3u_account=account,
                channel_group=group,
                last_seen=timezone.now(),
            )
        client = self._client()

        response = client.get(
            "/api/channels/streams/regex-preview/"
            "?channel_group=Sports&exclude=TEST%7CBACKUP"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["exclude_match_count"], 2)
        names = sorted(m["name"] for m in response.data["exclude_matches"])
        self.assertEqual(names, ["Sports BACKUP", "Sports TEST"])


class ExcludeRegexSyncTests(TestCase):
    """
    Sync respects the per-group `name_match_exclude_regex` custom property
    by dropping any stream whose name matches the pattern, after any
    include filter narrows the set. Invalid patterns are logged and
    skipped rather than aborting the whole sync.
    """

    def test_exclude_pattern_skips_matching_streams(self):
        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(
            account,
            group,
            custom_properties={"name_match_exclude_regex": "TEST|BACKUP"},
        )
        rel.auto_sync_channel_start = 100
        rel.save()
        for name in ["Sports Live", "Sports TEST", "Sports BACKUP", "Sports Pro"]:
            _make_stream(
                account, group, name=name, tvg_id=name.replace(" ", "_")
            )

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        # Only Sports Live and Sports Pro should have been turned into channels.
        names = sorted(
            Channel.objects.filter(
                channel_group=group,
                auto_created=True,
                auto_created_by=account,
            ).values_list("name", flat=True)
        )
        self.assertEqual(names, ["Sports Live", "Sports Pro"])

    def test_invalid_exclude_pattern_does_not_abort_sync(self):
        # Bad regex must be logged + ignored, not crash the sync. The
        # streams are imported as if no exclude filter was set.
        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(
            account,
            group,
            custom_properties={"name_match_exclude_regex": "("},
        )
        rel.auto_sync_channel_start = 100
        rel.save()
        _make_stream(account, group, name="ESPN", tvg_id="espn")

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_created"], 1)


class ChannelOverrideClearResponseTests(TestCase):
    """
    Clearing all overrides on a channel via PATCH `override=null` must
    return a response where `override` is null and every effective_*
    value reflects the post-clear (provider) state. The previous
    implementation used a queryset-level delete which left Django's
    reverse-OneToOne cache pointing at the just-deleted row; serializing
    the response on the same instance returned the stale override data
    and kept the frontend's "Clear All Overrides" button stuck visible
    after a successful clear.
    """

    def test_clear_response_carries_null_override(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User
        from apps.channels.models import ChannelOverride

        admin = User.objects.create_superuser(
            username="admin_clear_response",
            password="pw",
            user_level=10,
        )
        group = _make_group(name="Sports")
        ch = Channel.objects.create(
            name="ProviderName",
            channel_number=200,
            channel_group=group,
            auto_created=True,
        )
        ChannelOverride.objects.create(
            channel=ch, name="UserOverrideName"
        )
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(
            f"/api/channels/channels/{ch.id}/",
            {"override": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["override"])
        # The effective name must come from the provider value now that
        # the override is gone, not the cached override that was still
        # attached to the in-memory instance.
        self.assertEqual(response.data["effective_name"], "ProviderName")


class HiddenChannelPreservationTests(TestCase):
    """
    Hidden channels (`hidden_from_output=True`) must be preserved across every
    sync cleanup path so users can rely on the hide flag as "keep this
    channel even if its source stream temporarily disappears". Common
    case: event / PPV / seasonal channels whose provider stream comes
    and goes between refreshes - if they get deleted, the user loses
    the hide state, any overrides, and the channel's identity.
    """

    def test_hidden_channel_survives_when_its_stream_disappears(self):
        # Build a channel auto-created from a stream that exists in the
        # group, then mark it hidden, then run a sync where the stream is
        # absent from the current scan window. The channel must remain.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 100
        rel.save()

        from datetime import timedelta

        old_stream_seen = timezone.now() - timedelta(days=1)
        stream = Stream.objects.create(
            name="Event A",
            url="http://example.com/event-a.m3u8",
            m3u_account=account,
            channel_group=group,
            tvg_id="event-a",
            last_seen=old_stream_seen,
        )
        ch = Channel.objects.create(
            name="Event A",
            channel_number=100,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
            hidden_from_output=True,
        )
        ChannelStream.objects.create(channel=ch, stream=stream, order=0)

        # Sync's scan_start_time is now (stream's last_seen is older,
        # so the stream is excluded from current_streams - simulating
        # the provider dropping it). Without the hidden_from_output guard, the
        # channel would be cleaned up here.
        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(
            Channel.objects.filter(id=ch.id).exists(),
            "Hidden channel was deleted when its source stream "
            "disappeared from the current sync window",
        )

    def test_visible_channel_for_disappeared_stream_is_still_deleted(self):
        # The hide-preservation rule must not accidentally apply to
        # visible channels - those should still get cleaned up when
        # their source stream goes away. Otherwise sync would never
        # remove anything.
        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 100
        rel.save()

        from datetime import timedelta

        stream = Stream.objects.create(
            name="OldStream",
            url="http://example.com/old.m3u8",
            m3u_account=account,
            channel_group=group,
            tvg_id="old",
            last_seen=timezone.now() - timedelta(days=1),
        )
        ch = Channel.objects.create(
            name="OldStream",
            channel_number=100,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
            hidden_from_output=False,
        )
        ChannelStream.objects.create(channel=ch, stream=stream, order=0)

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(
            Channel.objects.filter(id=ch.id).exists(),
            "Visible channel should have been cleaned up when its "
            "source stream disappeared",
        )


class CompactNumberingTests(TestCase):
    """
    Per-group `compact_numbering` custom_property packs visible auto-
    created channels into the group's [start, end] range; hidden channels
    release their channel numbers; channel_number overrides act as
    reservations that survive hide/unhide cycles. Exercised across full
    sync, the post_save signal for single-channel unhide, and the
    explicit re-pack endpoint.
    """

    def _compact_account_with_group(self, start=100, end=110, name="Sports"):
        account = _make_account()
        group = _make_group(name=name)
        rel = _attach_group_to_account(
            account, group, custom_properties={"compact_numbering": True}
        )
        rel.auto_sync_channel_start = start
        rel.auto_sync_channel_end = end
        rel.save()
        return account, group, rel

    def test_full_sync_packs_visible_and_releases_hidden(self):
        # Five streams, three of which produce visible channels and two of
        # which we mark hidden after the first sync. Compact pack should
        # leave the three visible channels at 100/101/102 and NULL out the
        # hidden ones.
        account, group, rel = self._compact_account_with_group(
            start=100, end=110
        )
        for i in range(5):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        first = _sync(account)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["channels_created"], 5)

        # Hide two of the resulting channels.
        hidden_targets = list(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).order_by("id")[:2]
        )
        Channel.objects.filter(
            id__in=[c.id for c in hidden_targets]
        ).update(hidden_from_output=True)

        # Re-run sync; compact pack runs at the end.
        _sync(account)

        nums = sorted(
            Channel.objects.filter(
                auto_created=True,
                auto_created_by=account,
                hidden_from_output=False,
            ).values_list("channel_number", flat=True)
        )
        self.assertEqual(nums, [100, 101, 102])

        hidden_nums = list(
            Channel.objects.filter(
                auto_created=True,
                auto_created_by=account,
                hidden_from_output=True,
            ).values_list("channel_number", flat=True)
        )
        self.assertTrue(
            all(n is None for n in hidden_nums),
            f"Hidden channels still hold numbers: {hidden_nums}",
        )

    def test_override_pinned_number_survives_compact_pass(self):
        # Channel B has a channel_number override of 105. After compact
        # pack, B's effective number stays at 105, and the other visible
        # channels get packed around it (skipping 105 in the pool).
        from apps.channels.models import ChannelOverride

        account, group, rel = self._compact_account_with_group(
            start=100, end=110
        )
        for i in range(4):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        _sync(account)
        all_channels = list(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).order_by("id")
        )
        ChannelOverride.objects.create(
            channel=all_channels[1], channel_number=105
        )

        _sync(account)

        # Override-pinned channel: raw cleared to None (override controls
        # effective). The other three channels packed into 100/101/102 -
        # skipping 105 because the override reserved it.
        non_pinned = sorted(
            float(n)
            for n in Channel.objects.filter(
                auto_created=True,
                auto_created_by=account,
                override__isnull=True,
            ).values_list("channel_number", flat=True)
            if n is not None
        )
        self.assertEqual(non_pinned, [100.0, 101.0, 102.0])
        pinned = Channel.objects.get(id=all_channels[1].id)
        self.assertIsNone(pinned.channel_number)

    def test_unhide_signal_assigns_immediately(self):
        # Toggle hide → unhide on a single channel; the post_save signal
        # under compact mode should give it a number from the range
        # without requiring a sync pass to run.
        account, group, rel = self._compact_account_with_group(
            start=100, end=110
        )
        ch = Channel.objects.create(
            name="Test",
            channel_number=None,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
            hidden_from_output=True,
        )

        ch.hidden_from_output = False
        ch.save()
        ch.refresh_from_db()

        self.assertEqual(ch.channel_number, 100)

    def test_repack_endpoint_packs_around_overrides(self):
        # Simulate a user who set overrides on a couple of channels to
        # pin specific numbers and then clicks Re-pack to compact the
        # rest. Override-pinned channels survive; everything else fills
        # the remaining slots in order.
        from rest_framework.test import APIClient
        from apps.accounts.models import User
        from apps.channels.models import ChannelOverride

        account, group, rel = self._compact_account_with_group(
            start=100, end=110
        )
        # Six visible channels, no overrides
        channels = [
            Channel.objects.create(
                name=f"C{i}",
                channel_number=200 + i,  # arbitrary starting numbers
                channel_group=group,
                auto_created=True,
                auto_created_by=account,
            )
            for i in range(6)
        ]
        # Pin two of them via override
        ChannelOverride.objects.create(channel=channels[0], channel_number=110)
        ChannelOverride.objects.create(channel=channels[1], channel_number=105)

        admin = User.objects.create_superuser(
            username="admin_repack", password="pw", user_level=10
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            f"/api/m3u/accounts/{account.id}/repack-group/?channel_group_id={group.id}"
        )

        self.assertEqual(response.status_code, 200)
        # 4 non-pinned channels assigned, no failures
        self.assertEqual(response.data["assigned"], 4)
        self.assertEqual(response.data["failed"], 0)
        # Non-pinned channels get the lowest available numbers in the
        # range, skipping 105 and 110 (override reservations).
        non_pinned_nums = sorted(
            Channel.objects.filter(
                id__in=[c.id for c in channels[2:]]
            ).values_list("channel_number", flat=True)
        )
        self.assertEqual(non_pinned_nums, [100, 101, 102, 103])

    def test_repack_reports_failed_when_range_too_small(self):
        # Range covers 3 slots but visible channels need 5; the extra 2
        # are reported as failed and have their channel_number set to
        # None so their state is unambiguous.
        account, group, rel = self._compact_account_with_group(
            start=100, end=102
        )
        for i in range(5):
            Channel.objects.create(
                name=f"C{i}",
                channel_number=900 + i,
                channel_group=group,
                auto_created=True,
                auto_created_by=account,
            )

        from apps.channels.compact_numbering import repack_group

        result = repack_group(rel)
        self.assertEqual(result["assigned"], 3)
        self.assertEqual(result["failed"], 2)
        # Those that didn't fit got their channel_number nulled
        nulled = Channel.objects.filter(
            channel_group=group,
            channel_number__isnull=True,
        ).count()
        self.assertEqual(nulled, 2)

    def test_assign_releases_lock_on_outer_atomic_rollback(self):
        # The Redis-backed task lock is not transactional, so a release
        # scheduled via `transaction.on_commit` is silently discarded
        # when the caller's outer atomic rolls back. This left the lock
        # held until its 5-minute TTL expired and silently blocked all
        # subsequent syncs for the affected account. The function now
        # releases via try/finally so the lock comes back regardless
        # of outer transaction state.
        from unittest.mock import patch
        from django.db import transaction
        from apps.channels.compact_numbering import (
            assign_compact_numbers_for_channels,
        )
        from core.utils import acquire_task_lock, release_task_lock

        account, group, rel = self._compact_account_with_group(
            start=100, end=105
        )
        ch = Channel.objects.create(
            name="C1",
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
            hidden_from_output=False,
        )

        # Make sure the lock starts free.
        release_task_lock("refresh_single_m3u_account", account.id)

        try:
            with transaction.atomic():
                assign_compact_numbers_for_channels([ch.id])
                # Simulate downstream work in the outer atomic blowing up
                # AFTER the inner assignment succeeded.
                raise RuntimeError("simulated downstream failure")
        except RuntimeError:
            pass

        # If the lock is still held, the next acquire returns False and
        # subsequent syncs would silently skip auto-sync.
        self.assertTrue(
            acquire_task_lock("refresh_single_m3u_account", account.id),
            "Lock leaked after outer atomic rollback",
        )
        # Clean up so other tests in this class are not affected.
        release_task_lock("refresh_single_m3u_account", account.id)


class OverrideChannelNumberValidationTests(TestCase):
    """
    Override PATCH intentionally permits duplicate channel_number values:
    users may want two entries at the same number (e.g., one of them
    hidden from output). Sync's used_numbers set still avoids collisions
    on its own writes via set membership, so cross-provider merge
    behavior is unaffected by allowing user-set duplicates.
    """

    def test_override_channel_number_duplicate_is_allowed(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User
        from apps.channels.models import ChannelOverride

        admin = User.objects.create_superuser(
            username="admin_override_a",
            password="pw",
            user_level=10,
        )
        group = _make_group(name="Sports")
        Channel.objects.create(
            name="Existing",
            channel_number=500,
            channel_group=group,
        )
        target = Channel.objects.create(
            name="Target",
            channel_number=501,
            channel_group=group,
            auto_created=True,
        )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(
            f"/api/channels/channels/{target.id}/",
            {"override": {"channel_number": 500}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ChannelOverride.objects.get(channel=target).channel_number, 500
        )

    def test_override_channel_number_reusing_own_is_allowed(self):
        # Editing an override and re-submitting the same number the channel
        # already effectively holds must succeed (no "conflicts with itself").
        from rest_framework.test import APIClient
        from apps.accounts.models import User

        admin = User.objects.create_superuser(
            username="admin_override_b",
            password="pw",
            user_level=10,
        )
        group = _make_group(name="Sports")
        ch = Channel.objects.create(
            name="Target",
            channel_number=700,
            channel_group=group,
            auto_created=True,
        )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(
            f"/api/channels/channels/{ch.id}/",
            {"override": {"channel_number": 700, "name": "Renamed"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)


class SyncPerformanceRegressionTests(TestCase):
    """
    Query-count and throughput guards. The numbers below are ceilings for the
    specific scenario, not tight lower bounds. They exist to catch regressions
    where a future edit reintroduces N+1 lookups on logos, EPG, or
    per-channel ChannelStream joins. If a ceiling needs to be raised,
    investigate first (the original audit documented the cost of each pattern).
    """

    def test_sync_of_ten_streams_is_not_n_plus_one_in_logo_lookups(self):
        from apps.channels.models import Logo

        account = _make_account()
        group = _make_group(name="Sports")
        _attach_group_to_account(account, group)

        # Seed 10 streams with 3 distinct logo URLs so the batch cache has
        # an interesting ratio of cache hits to misses.
        logo_urls = [
            "http://logos.example.com/a.png",
            "http://logos.example.com/b.png",
            "http://logos.example.com/c.png",
        ]
        for i in range(10):
            Stream.objects.create(
                name=f"Chan{i}",
                url=f"http://example.com/{i}.m3u8",
                m3u_account=account,
                channel_group=group,
                tvg_id=f"tvg{i}",
                logo_url=logo_urls[i % 3],
                last_seen=timezone.now(),
            )

        # Count Logo queries during the sync. Without batching, this would
        # issue at least one SELECT per stream (10+) plus 10 separate INSERTs.
        # With batching, a single SELECT populates the cache for all 3 URLs
        # and each new Logo row requires one INSERT (the get_or_create miss
        # path). Allow headroom for the initial cache-populate query and
        # per-insert overhead, but keep the total well below the N+1 count.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            result = _sync(account)

        logo_queries = [
            q for q in ctx.captured_queries
            if 'dispatcharr_channels_logo' in q['sql'].lower()
        ]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_created"], 10)
        # Target: at most ~6 Logo-related queries for 10 streams / 3 urls.
        # Without the batch cache the count would be 10+ SELECTs + 3 INSERTs.
        self.assertLessEqual(
            len(logo_queries),
            8,
            f"Logo queries: {len(logo_queries)} (expected <= 8 after batching)",
        )


class OrphanCleanupModeTests(TestCase):
    """
    Account-level `custom_properties.orphan_channel_cleanup` is a 3-state
    selector that governs how sync handles auto-created channels whose
    source streams have disappeared.

    - "always" (default; absent key behaves the same): delete every orphan
      auto-created channel.
    - "preserve_customized": delete orphans without a ChannelOverride row;
      preserve those with one.
    - "never": preserve every orphan auto-created channel.

    Hidden channels (`hidden_from_output=True`) are universally preserved
    regardless of mode, because the user has explicitly signaled "keep this
    around but do not show clients".
    """

    def _set_mode(self, account, mode):
        account.custom_properties = {"orphan_channel_cleanup": mode}
        account.save()

    def test_default_mode_when_key_absent_is_always(self):
        # Account with no custom_properties.orphan_channel_cleanup value
        # behaves like "always": orphans get cleaned up.
        account = _make_account()
        group = _make_group(name="Sports")
        _attach_group_to_account(account, group)
        Channel.objects.create(
            name="OldESPN",
            channel_number=500,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_deleted"], 1)
        self.assertEqual(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).count(),
            0,
            "Default (absent key): orphans must be cleaned up",
        )

    def test_always_mode_removes_orphan_with_override(self):
        from apps.channels.models import ChannelOverride

        account = _make_account()
        self._set_mode(account, "always")
        group = _make_group(name="Sports")
        _attach_group_to_account(account, group)
        ch = Channel.objects.create(
            name="OldESPN",
            channel_number=500,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        ChannelOverride.objects.create(channel=ch, name="My Custom ESPN")

        result = _sync(account)

        self.assertEqual(result["channels_deleted"], 1)
        self.assertFalse(
            Channel.objects.filter(id=ch.id).exists(),
            "Always mode: even customized orphans get deleted",
        )

    def test_preserve_customized_mode_spares_overrides(self):
        from apps.channels.models import ChannelOverride

        account = _make_account()
        self._set_mode(account, "preserve_customized")
        group = _make_group(name="Sports")
        _attach_group_to_account(account, group)
        plain = Channel.objects.create(
            name="OldPlain",
            channel_number=500,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        customized = Channel.objects.create(
            name="OldCustomized",
            channel_number=501,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        ChannelOverride.objects.create(channel=customized, name="My Renamed")

        _sync(account)

        self.assertFalse(
            Channel.objects.filter(id=plain.id).exists(),
            "Preserve-customized mode: orphan without override is removed",
        )
        self.assertTrue(
            Channel.objects.filter(id=customized.id).exists(),
            "Preserve-customized mode: orphan WITH override is preserved",
        )

    def test_never_mode_preserves_all_orphans(self):
        account = _make_account()
        self._set_mode(account, "never")
        group = _make_group(name="Sports")
        _attach_group_to_account(account, group)
        Channel.objects.create(
            name="OldA",
            channel_number=500,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        Channel.objects.create(
            name="OldB",
            channel_number=501,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )

        result = _sync(account)

        self.assertEqual(result["channels_deleted"], 0)
        self.assertEqual(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).count(),
            2,
            "Never mode: every orphan survives",
        )

    def test_hidden_channels_universally_preserved(self):
        # Hidden orphans must survive in every mode, including the
        # default "always" mode.
        for mode in ("always", "preserve_customized", "never"):
            with self.subTest(mode=mode):
                account = _make_account(name=f"Provider-{mode}")
                self._set_mode(account, mode)
                group = _make_group(name=f"Sports-{mode}")
                _attach_group_to_account(account, group)
                Channel.objects.create(
                    name=f"Hidden-{mode}",
                    channel_number=600,
                    channel_group=group,
                    auto_created=True,
                    auto_created_by=account,
                    hidden_from_output=True,
                )

                _sync(account)

                self.assertEqual(
                    Channel.objects.filter(
                        auto_created=True,
                        auto_created_by=account,
                        hidden_from_output=True,
                    ).count(),
                    1,
                    f"Hidden channel must survive cleanup in mode={mode}",
                )


class MultiStreamChannelTests(TestCase):
    """
    A user can manually attach more than one Stream to an auto-created
    Channel (typical for backup feeds: same channel, two providers'
    versions). Sync must not delete the channel just because ONE of
    those streams disappears - other streams may still be valid.

    The deletion path was per-stream: for stream_id, channel in
    existing_channel_map.items(): delete the channel if stream_id is not
    in processed_stream_ids. With two map entries pointing at the same
    channel, the first iteration would queue the channel for delete even
    if the second stream is still alive.

    Even more subtle: existing_channel_map gets a fresh Channel instance
    per ChannelStream row from the joined query. With two entries,
    in-memory mutations during the per-stream iteration would land on
    different Python instances and silently drop changes from later
    iterations when bulk_update fires on only one of them.
    """

    def test_channel_with_two_streams_survives_when_one_disappears(self):
        from datetime import timedelta

        account = _make_account()
        group = _make_group(name="Movies")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 100
        rel.save()

        # Two streams in the same group, same account, attached to one
        # auto-created channel. Stream A is current, Stream B is stale
        # (provider dropped it).
        stream_a = Stream.objects.create(
            name="StarMovie HD",
            url="http://example.com/star-a.m3u8",
            m3u_account=account,
            channel_group=group,
            tvg_id="star",
            last_seen=timezone.now(),
        )
        stream_b = Stream.objects.create(
            name="StarMovie HD",
            url="http://example.com/star-b.m3u8",
            m3u_account=account,
            channel_group=group,
            tvg_id="star",
            last_seen=timezone.now() - timedelta(days=1),
        )
        ch = Channel.objects.create(
            name="StarMovie HD",
            channel_number=100,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        ChannelStream.objects.create(channel=ch, stream=stream_a, order=0)
        ChannelStream.objects.create(channel=ch, stream=stream_b, order=1)

        # Sync sees stream_a as current (live) and stream_b as gone.
        # Stream_a means the channel is still wanted; the channel must
        # survive. Direct DB check works on both old and new sync return
        # shapes (baseline returns a string, overhaul returns a dict).
        _sync(account)

        self.assertTrue(
            Channel.objects.filter(id=ch.id).exists(),
            "Multi-stream channel was deleted even though one of its "
            "streams is still alive",
        )

    def test_channel_with_two_streams_metadata_consistent_after_sync(self):
        # When two ChannelStream rows resolve to the same Channel,
        # in-memory mutations from each iteration must land on the SAME
        # Channel instance so the post-loop bulk_update writes the
        # merged final state. With per-row Channel instances (the bug),
        # later iterations would mutate a different in-memory copy and
        # those changes would be lost.

        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 100
        rel.save()

        # Two streams attached to the same channel, both currently
        # served by the provider. Each carries different tvg_id so the
        # sync code wants to update the channel's tvg_id field.
        stream_a = Stream.objects.create(
            name="SportsCh HD",
            url="http://example.com/sports-a.m3u8",
            m3u_account=account,
            channel_group=group,
            tvg_id="sports-a",
            last_seen=timezone.now(),
        )
        stream_b = Stream.objects.create(
            name="SportsCh HD",
            url="http://example.com/sports-b.m3u8",
            m3u_account=account,
            channel_group=group,
            tvg_id="sports-b",
            last_seen=timezone.now(),
        )
        ch = Channel.objects.create(
            name="OldName",
            tvg_id="initial",
            channel_number=100,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        ChannelStream.objects.create(channel=ch, stream=stream_a, order=0)
        ChannelStream.objects.create(channel=ch, stream=stream_b, order=1)

        _sync(account)

        ch.refresh_from_db()
        # The channel exists, was updated, and either tvg_id ('sports-a'
        # or 'sports-b') is acceptable - the key invariant is that it is
        # NOT 'initial' (the pre-sync value), which would mean updates
        # were silently dropped because they targeted a different
        # in-memory instance than the one bulk_update'd.
        self.assertNotEqual(
            ch.tvg_id,
            "initial",
            "tvg_id was not updated; in-memory mutations to the "
            "channel were dropped (multi-stream identity bug)",
        )


class HiddenChannelNumberCollisionTests(TestCase):
    """
    Sync seeds `used_numbers` from existing channels EXCEPT those owned by
    the account being synced (those will be re-numbered). The original
    pattern excluded ALL of the account's auto-created channels - including
    HIDDEN ones, which the renumber loop never visits because they are not
    in `current_streams`. Result: the hidden channel's number was free to
    be re-assigned to a brand-new visible channel, producing two channels
    with the same channel_number on disk.
    """

    def test_hidden_channels_keep_their_number_reserved_during_sync(self):
        from datetime import timedelta

        account = _make_account()
        group_a = _make_group(name="Hidden Group")
        group_b = _make_group(name="New Group")
        rel_a = _attach_group_to_account(account, group_a)
        rel_a.auto_sync_channel_start = 100
        rel_a.save()
        rel_b = _attach_group_to_account(account, group_b)
        rel_b.auto_sync_channel_start = 100
        rel_b.save()

        # A hidden auto-created channel pinned at #100 in group_a.
        # Its source stream is gone (last_seen old), but hidden_from_output=True
        # protects the channel from cleanup.
        old_seen = timezone.now() - timedelta(days=1)
        Stream.objects.create(
            name="HiddenStream",
            url="http://example.com/hidden.m3u8",
            m3u_account=account,
            channel_group=group_a,
            tvg_id="hid",
            last_seen=old_seen,
        )
        hidden_ch = Channel.objects.create(
            name="HiddenChannel",
            channel_number=100,
            channel_group=group_a,
            auto_created=True,
            auto_created_by=account,
            hidden_from_output=True,
        )

        # A NEW stream in group_b, no channel yet. Sync should create a
        # channel for it and pick its number. If hidden_ch's number is
        # free (the bug), this new channel would also get 100, colliding.
        Stream.objects.create(
            name="NewStream",
            url="http://example.com/new.m3u8",
            m3u_account=account,
            channel_group=group_b,
            tvg_id="new",
            last_seen=timezone.now(),
        )

        _sync(account)

        new_ch = Channel.objects.filter(
            auto_created=True,
            auto_created_by=account,
            channel_group=group_b,
        ).first()
        self.assertIsNotNone(new_ch, "Sync did not create a channel for the new stream")

        # Both rows must coexist with DIFFERENT channel_numbers.
        hidden_ch.refresh_from_db()
        self.assertNotEqual(
            new_ch.channel_number,
            hidden_ch.channel_number,
            f"New channel #{new_ch.channel_number} collides with hidden "
            f"channel #{hidden_ch.channel_number}; sync did not reserve "
            f"the hidden channel's number",
        )


class HDHRLineupNullChannelNumberTests(TestCase):
    """
    With nullable channel_number (migration 0039) it is now valid for a
    channel to have effective_channel_number=None - typically a hidden
    channel under compact numbering whose number was released. Both HDHR
    lineup endpoints (legacy `apps/hdhr/views.py` and new
    `apps/hdhr/api_views.py`) must skip those rows rather than emit
    `"GuideNumber": "None"` or `"GuideNumber": ""`. HDHR clients reject
    such entries and may drop the entire lineup.
    """

    def test_legacy_lineup_skips_channels_with_null_effective_number(self):
        # Set up two channels: one with a number, one without.
        account = _make_account()
        group = _make_group(name="Legacy")
        with_number = Channel.objects.create(
            name="WithNum",
            channel_number=42,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )
        Channel.objects.create(
            name="NoNum",
            channel_number=None,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
        )

        from apps.accounts.models import User
        from rest_framework.test import APIClient

        admin = User.objects.create_superuser(
            username="hdhr_legacy_admin", password="x", user_level=10
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get("/hdhr/lineup.json")

        self.assertEqual(response.status_code, 200)
        body = response.json() if hasattr(response, "json") else response.data
        # Body is a list of {GuideNumber, GuideName, URL, ...}
        guide_numbers = {entry.get("GuideNumber") for entry in body}
        self.assertIn(
            "42", guide_numbers, "Numbered channel must appear in lineup"
        )
        self.assertNotIn(
            "None", guide_numbers,
            "Lineup must not contain literal 'None' GuideNumber",
        )
        self.assertNotIn(
            "", guide_numbers,
            "Lineup must not contain empty GuideNumber",
        )


class DuplicateOverrideChannelNumberAllowedTests(TestCase):
    """
    Override channel_number is intentionally allowed to duplicate an
    existing channel's effective number. Downstream clients render two
    entries at the same number; users decide whether that is desired
    (e.g., one of the duplicates is hidden from output). Sync still
    avoids collisions on its own writes via set-membership on
    used_numbers, so the merge behavior across providers is unaffected.
    """

    def test_override_channel_number_duplicate_is_accepted(self):
        from rest_framework.test import APIClient
        from apps.accounts.models import User
        from apps.channels.models import Channel as Ch
        from apps.channels.models import ChannelOverride

        admin = User.objects.create_superuser(
            username="dup_override_admin", password="x", user_level=10
        )

        # Existing channel claiming #50 by raw channel_number.
        Ch.objects.create(
            name="Existing",
            channel_number=50,
            auto_created=False,
        )
        editable = Ch.objects.create(
            name="Editable",
            channel_number=51,
            auto_created=True,
            auto_created_by=_make_account(),
        )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(
            f"/api/channels/channels/{editable.id}/",
            {"override": {"channel_number": 50}},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            200,
            f"Expected 200; got {response.status_code} "
            f"body={getattr(response, 'data', None)}",
        )
        override = ChannelOverride.objects.get(channel=editable)
        self.assertEqual(override.channel_number, 50)


class EPGDispatchExistingChannelTests(TestCase):
    """
    The new-channel sync path manually dispatches `parse_programs_for_tvg_id`
    once per unique epg_data_id (because bulk_create bypasses post_save).
    The existing-channel path (bulk_update) ALSO bypasses post_save, so it
    needs the same manual dispatch when `epg_data` is in the dirty set;
    otherwise EPG re-parse never fires for channels whose epg link was
    just changed by sync.
    """

    def test_existing_channel_epg_change_triggers_parse_dispatch(self):
        from unittest.mock import patch

        account = _make_account()
        group = _make_group(name="EPG Test")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 100
        rel.save()

        # First sync: create channel with one tvg_id.
        s1 = Stream.objects.create(
            name="EPGCh",
            url="http://example.com/epg.m3u8",
            m3u_account=account,
            channel_group=group,
            tvg_id="initial-tvg",
            last_seen=timezone.now(),
        )
        _sync(account)

        ch = Channel.objects.get(
            auto_created=True, auto_created_by=account
        )
        # Force epg_data divergence on the next sync by changing the
        # stream's tvg_id (the resolver will see a different EPG link).
        # Without changing the actual EPG resolution logic here we just
        # set epg_data_id to something different in DB and verify the
        # next sync detects the change via update_fields="epg_data" in
        # the dirty set; the dispatch loop must fire.
        ch.epg_data_id = None
        ch.save(update_fields=["epg_data"])

        # Update the stream's tvg_id so the resolver picks up a new
        # EPGData on the next sync.
        from apps.epg.models import EPGData, EPGSource

        src = EPGSource.objects.create(
            name="TestSrc", source_type="manual", url=""
        )
        new_epg = EPGData.objects.create(
            tvg_id="initial-tvg", name="EPGCh", epg_source=src
        )
        # Sync should now associate ch with new_epg via tvg_id match.

        with patch(
            "apps.epg.tasks.parse_programs_for_tvg_id.delay"
        ) as mock_dispatch:
            _sync(account)

        # The exact number of calls is 1 per unique epg_data_id; for one
        # changed channel that is at least 1 call.
        called_for = {c.args[0] for c in mock_dispatch.call_args_list}
        self.assertIn(
            new_epg.id,
            called_for,
            f"parse_programs_for_tvg_id was not dispatched for the EPG "
            f"id {new_epg.id} that the existing channel was just "
            f"associated with. mock calls: {mock_dispatch.call_args_list}",
        )


class Migration0037DemoteOrphansTests(TestCase):
    """
    The 0037 auto-sync overhaul migration's `backfill_auto_created_by_null`
    step demotes orphaned `auto_created=True, auto_created_by=NULL` channels
    to `auto_created=False` instead of deleting them, preserving the
    channel and any overrides that may exist on it.
    """

    def test_orphan_with_no_streams_is_demoted_not_deleted(self):
        # Create an orphaned auto-created channel with no streams. This
        # is the case that a delete-on-orphan strategy would silently lose.
        ch = Channel.objects.create(
            name="OrphanGhost",
            channel_number=999,
            auto_created=True,
            auto_created_by=None,
        )

        # The migration's backfill function takes (apps, schema_editor)
        # where `apps` is normally the historical app registry. For this
        # unit test we call with the live registry. The migration file
        # name starts with a digit so it must be loaded via importlib.
        from importlib import import_module
        from django.apps import apps as django_apps

        module = import_module(
            "apps.channels.migrations.0037_auto_sync_overhaul"
        )

        # The migration function takes (apps, schema_editor); apps is
        # the historical app registry. For this unit test we call with
        # the live registry.
        module.backfill_auto_created_by_null(django_apps, None)

        ch.refresh_from_db()
        self.assertFalse(
            ch.auto_created,
            "Orphaned auto-created channel with no streams must be "
            "demoted to manual (auto_created=False), not left as "
            "auto_created=True or deleted",
        )
        self.assertIsNone(ch.auto_created_by)


class CompactNumberingWithGroupOverrideTests(TestCase):
    """
    Compact numbering must keep working when a Channel Group Override is
    configured on the source ChannelGroupM3UAccount. With an override,
    sync stores auto-created channels under the OVERRIDE TARGET group's id
    rather than the source group's id recorded on the relation. The
    compact paths resolve the relation from the channel's group id, so
    without the override-aware fallback they all miss and slot accounting
    silently breaks (hidden channels keep their numbers, unhides get none,
    repack sees zero channels).

    Fix location: apps/channels/compact_numbering.py
    (get_group_relation_for_channel fallback, _repack_inner group_ids,
    assign_compact_numbers_for_channels bulk fallback).
    """

    def _override_setup(self, start=100, end=110):
        account = _make_account()
        source_group = _make_group(name="SourcePPV")
        target_group = _make_group(name="TargetAll")
        rel = _attach_group_to_account(
            account,
            source_group,
            custom_properties={
                "compact_numbering": True,
                "group_override": target_group.id,
            },
        )
        rel.auto_sync_channel_start = start
        rel.auto_sync_channel_end = end
        rel.save()
        return account, source_group, target_group, rel

    def _auto_channel(self, account, group, number=None, hidden=False, name="PPV"):
        return Channel.objects.create(
            name=name,
            channel_number=number,
            channel_group=group,
            auto_created=True,
            auto_created_by=account,
            hidden_from_output=hidden,
        )

    def test_hide_releases_slot_under_group_override(self):
        # Fail signature: channel_number stays populated after hide =
        # release_compact_number_on_hide bailed because
        # get_group_relation_for_channel returned None for the override
        # target group.
        account, source, target, rel = self._override_setup()
        ch = self._auto_channel(account, target, number=100)

        ch.hidden_from_output = True
        ch.save()
        ch.refresh_from_db()

        self.assertIsNone(
            ch.channel_number,
            "Hiding an auto channel under a Channel Group Override must "
            "release its compact slot (channel_number=None)",
        )

    def test_unhide_assigns_slot_under_group_override(self):
        # Fail signature: channel_number stays None after unhide =
        # assign_compact_number_on_unhide bailed on the override target.
        account, source, target, rel = self._override_setup()
        ch = self._auto_channel(account, target, number=None, hidden=True)

        ch.hidden_from_output = False
        ch.save()
        ch.refresh_from_db()

        self.assertEqual(
            ch.channel_number,
            100,
            "Unhiding an auto channel under a Channel Group Override must "
            "assign a number from the compact range",
        )

    def test_repack_sees_channels_under_override_target(self):
        # Fail signature: assigned=0 = _repack_inner filtered on the source
        # group id and found none of the channels stored under the target.
        from apps.channels.compact_numbering import repack_group

        account, source, target, rel = self._override_setup()
        channels = [
            self._auto_channel(account, target, number=900 + i, name=f"C{i}")
            for i in range(3)
        ]

        result = repack_group(rel)

        self.assertEqual(result["assigned"], 3)
        self.assertEqual(result["failed"], 0)
        nums = sorted(
            Channel.objects.filter(
                id__in=[c.id for c in channels]
            ).values_list("channel_number", flat=True)
        )
        self.assertEqual(nums, [100, 101, 102])

    def test_no_override_fast_path_still_resolves(self):
        # Regression guard: the common no-override case must still resolve
        # the relation via the direct lookup (channel.channel_group_id ==
        # source group id), unaffected by the override fallback.
        from apps.channels.compact_numbering import (
            get_group_relation_for_channel,
        )

        account = _make_account()
        group = _make_group(name="PlainSports")
        rel = _attach_group_to_account(
            account, group, custom_properties={"compact_numbering": True}
        )
        ch = self._auto_channel(account, group, number=100)

        resolved = get_group_relation_for_channel(ch)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, rel.id)

    def test_repack_under_override_query_count_does_not_scale(self):
        # Perf guard: the override-aware repack widens the channel lookup's
        # IN clause; it must not add a query per channel. Query count must
        # be identical for N and 3*N channels.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.channels.compact_numbering import repack_group

        account, source, target, rel = self._override_setup(start=100, end=300)

        def measure(n):
            Channel.objects.filter(auto_created_by=account).delete()
            for i in range(n):
                self._auto_channel(account, target, number=900 + i, name=f"C{i}")
            with CaptureQueriesContext(connection) as ctx:
                repack_group(rel)
            return len(ctx.captured_queries)

        small = measure(5)
        large = measure(15)
        self.assertEqual(
            small,
            large,
            f"repack query count scaled with channel count: {small} -> {large}",
        )


@skipUnless(
    connection.vendor == "postgresql",
    "Idempotency repro forces a physical heap reorder via CLUSTER, which is "
    "PostgreSQL-specific (the suite's target DB).",
)
class CompactNumberingIdempotencyTests(TransactionTestCase):
    """
    A compact repack must be idempotent: with no change to hide state or
    overrides, repacking again must leave every channel on the same number.

    The unpatched _repack_inner read its channels with no ORDER BY, so the
    pack followed PostgreSQL's physical row order. That order drifts after
    the UPDATEs each repack issues (and after autovacuum), so successive
    syncs packed the same channels into different numbers. That is the daily
    channel-number churn users reported.

    This test forces the divergence deterministically. After the first pack
    it rewrites every channel_number to the reverse of id order, then
    physically clusters the table on that column so the heap order becomes
    the reverse of id order. An unordered SELECT then returns the rows in the
    opposite order from the first pass. Unpatched, the second pack assigns
    numbers in that reversed order and the channel->number mapping flips;
    patched, .order_by("id") keeps both packs identical.

    Fail signature: channel->number mapping differs between the two repacks
    = _repack_inner is following physical row order instead of id order.

    Fix location: apps/channels/compact_numbering.py (_repack_inner channel
    query .order_by("id")).
    """

    # TransactionTestCase commits its rows (TestCase's savepoint rollback
    # would hide them from CLUSTER, which also cannot run inside the
    # transaction block TestCase wraps each test in).

    def _mapping(self, account):
        return {
            c.id: c.channel_number
            for c in Channel.objects.filter(
                auto_created=True, auto_created_by=account
            )
        }

    def test_repack_is_idempotent_under_physical_reorder(self):
        from apps.channels.compact_numbering import repack_group

        account = _make_account()
        group = _make_group(name="Sports")
        rel = _attach_group_to_account(
            account, group, custom_properties={"compact_numbering": True}
        )
        rel.auto_sync_channel_start = 8000
        rel.auto_sync_channel_end = 8099
        rel.save()

        # Eight visible auto channels; ascending id is creation order.
        channels = [
            Channel.objects.create(
                name=f"C{i}",
                channel_group=group,
                auto_created=True,
                auto_created_by=account,
            )
            for i in range(8)
        ]

        repack_group(rel)
        first = self._mapping(account)
        # Provider-order pack (the default) assigns by id, so the lowest id
        # takes the range start.
        lowest_id = min(c.id for c in channels)
        self.assertEqual(first[lowest_id], 8000)

        # Set channel_number to the reverse of id order, then cluster the
        # heap on that column so physical order becomes reverse-id order.
        # Values sit above the range so they cannot collide with the pack.
        table = Channel._meta.db_table
        with connection.cursor() as cur:
            for pos, ch in enumerate(channels):
                cur.execute(
                    f"UPDATE {table} SET channel_number = %s WHERE id = %s",
                    [9000 - pos, ch.id],
                )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS churn_cn_idx "
                f"ON {table} (channel_number)"
            )
            cur.execute(f"CLUSTER {table} USING churn_cn_idx")
            cur.execute("DROP INDEX IF EXISTS churn_cn_idx")

        repack_group(rel)
        second = self._mapping(account)

        self.assertEqual(
            first,
            second,
            "Repack is not idempotent: channel numbers changed on a second "
            "pass with no hide or override change. _repack_inner is following "
            "physical row order instead of id order.",
        )


class ProviderNumberingHonorsProviderNumberTests(TestCase):
    """
    Provider numbering uses a stream's provider number (stream_chno) verbatim.
    The group start is auto-populated by the UI and is not editable in provider
    mode (the UI binds "Start #" to channel_numbering_fallback), so treating it
    as a lower bound silently discarded valid provider numbers: on a lineup
    topping out near 5000, provider numbers 100-150 landed at ~5000.

    The start and end bound only the fallback for numberless streams.
    """

    def test_provider_number_below_high_auto_start_is_honored(self):
        # Provider numbers 100-104 with an auto-set start of 5000 must land at
        # their provider numbers.
        # Fail signature: channels at 5000-5004 = start used as a hard floor.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 5000
        rel.auto_sync_channel_end = None
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 1,
        }
        rel.save()
        for i in range(5):
            _make_stream(
                account, group, name=f"PPV {i}", tvg_id=f"ppv{i}",
                stream_chno=100 + i,
            )

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        numbers = sorted(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).values_list("channel_number", flat=True)
        )
        self.assertEqual(numbers, [100.0, 101.0, 102.0, 103.0, 104.0])

    def test_provider_number_honored_when_start_unset(self):
        # start blank -> defaults to 1.0; provider numbers still honored.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = None
        rel.auto_sync_channel_end = None
        rel.custom_properties = {"channel_numbering_mode": "provider"}
        rel.save()
        _make_stream(account, group, name="PPV", tvg_id="ppv", stream_chno=100)

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        created = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertEqual(created.channel_number, 100.0)

    def test_numberless_stream_uses_fallback_not_hidden_start(self):
        # In provider mode without a range, a stream lacking a provider
        # number falls back to channel_numbering_fallback (the visible
        # "Start #"), not the hidden auto_sync_channel_start.
        # Fail signature: channel at 5000 = fallback bumped to hidden start.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 5000
        rel.auto_sync_channel_end = None
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 300,
        }
        rel.save()
        _make_stream(account, group, name="NoChno", tvg_id="nc")

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        created = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertEqual(created.channel_number, 300.0)

    def test_provider_number_below_range_is_honored_verbatim(self):
        # A provider number below the group's Start/End is used as-is, not
        # coerced into the range.
        # Fail signature: channel pulled to >= 100 = range coercing a provider
        # number.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_end = 200
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 100,
        }
        rel.save()
        _make_stream(account, group, name="Low", tvg_id="low", stream_chno=50)

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        created = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertEqual(created.channel_number, 50.0)

    def test_provider_number_above_end_is_honored_verbatim(self):
        # Provider numbers above the configured End are also honored as-is;
        # the End caps only the fallback for numberless streams.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_end = 200
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 1,
        }
        rel.save()
        _make_stream(account, group, name="High", tvg_id="high", stream_chno=5000)

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        created = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertEqual(created.channel_number, 5000.0)

    def test_provider_number_within_range_is_honored(self):
        # An in-range provider number is used as-is.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_end = 200
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 1,
        }
        rel.save()
        _make_stream(account, group, name="Mid", tvg_id="mid", stream_chno=150)

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        created = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertEqual(created.channel_number, 150.0)

    def test_duplicate_provider_numbers_keep_one_and_fall_back_the_other(self):
        # Two streams claim the same provider number (common in messy event
        # feeds). One keeps it; the colliding one falls back to a different free
        # number rather than being dropped or overwriting the first.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 1,
        }
        rel.save()
        _make_stream(account, group, name="A", tvg_id="a", stream_chno=77250)
        _make_stream(account, group, name="B", tvg_id="b", stream_chno=77250)

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        numbers = sorted(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).values_list("channel_number", flat=True)
        )
        self.assertEqual(len(numbers), 2)
        self.assertIn(77250.0, numbers)
        self.assertNotEqual(numbers[0], numbers[1])

    def test_provider_number_colliding_with_manual_channel_falls_back(self):
        # A provider number matching an existing channel must not overwrite it;
        # the auto-created channel falls back to a different free number.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 1,
        }
        rel.save()
        manual = Channel.objects.create(name="Manual", channel_number=88250)
        _make_stream(account, group, name="P", tvg_id="p", stream_chno=88250)

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        created = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertNotEqual(created.channel_number, 88250.0)
        manual.refresh_from_db()
        self.assertEqual(manual.channel_number, 88250.0)


class CrossModeNumberingFieldTests(TestCase):
    """
    Each numbering mode's UI exposes only a subset of the persisted fields,
    and switching modes does not reset the others. The backend must therefore
    read only the fields a mode actually owns, so a stale/hidden value left by
    another mode cannot silently change numbering. These guard the two
    remaining facets of that family (the provider-floor facet is covered by
    ProviderNumberingHonorsProviderNumberTests).
    """

    def _restamp(self, account):
        Stream.objects.filter(m3u_account=account).update(
            last_seen=timezone.now()
        )

    def test_next_available_ignores_configured_end(self):
        # next_available exposes no Start/End in its UI, so a stale End left
        # over from a prior mode must not cap it. Every stream gets the lowest
        # free number from 1 regardless of the End.
        # Fail signature: streams beyond the End fail = next_available honoring
        # a hidden cap.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 1
        rel.auto_sync_channel_end = 3  # stale cap from a prior mode
        rel.custom_properties = {"channel_numbering_mode": "next_available"}
        rel.save()
        for i in range(5):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        result = _sync(account)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["channels_created"], 5)
        self.assertEqual(result["channels_failed"], 0)

    def test_provider_channels_outside_range_are_not_deleted(self):
        # Range enforcement (the overflow-delete) is fixed-mode only. A provider
        # channel whose number is outside [start, end] is authoritative and must
        # survive sync, not be deleted and churned into a new row.
        # Fail signature: channels_deleted > 0 on the second sync = overflow
        # delete firing in provider mode.
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_end = 200
        rel.custom_properties = {
            "channel_numbering_mode": "provider",
            "channel_numbering_fallback": 1,
        }
        rel.save()
        _make_stream(account, group, name="High", tvg_id="high", stream_chno=5000)

        first = _sync(account)
        self.assertEqual(first["channels_created"], 1)
        original = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertEqual(original.channel_number, 5000.0)

        self._restamp(account)
        second = _sync(account)

        self.assertEqual(second["channels_deleted"], 0)
        survivor = Channel.objects.get(auto_created=True, auto_created_by=account)
        self.assertEqual(survivor.id, original.id)
        self.assertEqual(survivor.channel_number, 5000.0)

    def test_next_available_channels_outside_stale_range_not_deleted(self):
        # Same gate for next_available: tightening a stale End must not delete
        # already-assigned channels (range enforcement is fixed-mode only).
        account = _make_account()
        group = _make_group(name="PPV")
        rel = _attach_group_to_account(account, group)
        rel.auto_sync_channel_start = 1
        rel.auto_sync_channel_end = None
        rel.custom_properties = {"channel_numbering_mode": "next_available"}
        rel.save()
        for i in range(5):
            _make_stream(account, group, name=f"S{i}", tvg_id=f"s{i}")

        self.assertEqual(_sync(account)["channels_created"], 5)

        rel.auto_sync_channel_end = 3  # stale cap appears
        rel.save()
        self._restamp(account)
        second = _sync(account)

        self.assertEqual(second["channels_deleted"], 0)
        self.assertEqual(
            Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).count(),
            5,
        )
