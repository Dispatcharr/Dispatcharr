"""
Differential parity tests: the auto-sync rename preview must predict the exact
name the live rename produces, across a broad matrix of regex strategies.

Both the preview and the live rename compile with the third-party `regex`
module (for its JS-aligned syntax and per-call timeout). They can only be
trusted together if, for every find/replace a user might author, the preview's
predicted `after` equals the channel name the sync actually writes.

Each case is run end-to-end: real streams, the real sync_auto_channels rename,
and the real regex-preview endpoint, compared per original stream name.
"""
from django.test import TestCase
from django.utils import timezone

from apps.channels.models import Channel, ChannelGroup, ChannelStream, Stream
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import sync_auto_channels


# Diverse names: distinct word-prefixes (collision-resistant), with quality
# tags, brackets, pipes, ampersands, extra whitespace, underscores, dots, CJK,
# and emoji, to exercise anchors, classes, boundaries, and Unicode handling.
NAMES = [
    "Alpha Channel 11",
    "Bravo Sports HD",
    "Charlie News FHD",
    "Delta Movie (2024)",
    "Echo [UK] 4K",
    "Foxtrot   spaced",
    "Golf|Pipe|Name",
    "Hotel & Inn <x>",
    "India 日本語 77",
    "Juliet 📺 88",
    "Kilo_under_9",
    "Lima.dot.name",
]

# (find, replace) pairs spanning common user strategies and edge cases.
STRATEGIES = [
    # --- capture groups ---
    (r"(.+) Channel (\d+)", r"$1 #$2"),
    (r"(\w+) (\w+)", r"$2 $1"),
    (r"(.+)", r"$1 - $1"),
    (r"(.+)", r"[$1]"),
    (r"(.+) (\d+)$", r"$2 $1"),
    # --- strip / delete ---
    (r" (HD|FHD|4K|SD)\b", r""),
    (r"\s+", r" "),
    (r"[\[\(].*?[\]\)]", r""),
    (r"\d+", r""),
    (r"[_.]", r" "),
    # --- anchors / inserts ---
    (r"^", r"NEW "),
    (r"$", r" LIVE"),
    (r"^(\w+)", r"<$1>"),
    # --- char classes / Unicode (divergence hunters) ---
    (r"\w+", r"W"),
    (r"\b\w", r"_"),
    (r"[A-Z]", r"*"),
    (r"\s", r"_"),
    (r"[^\x00-\x7F]+", r"?"),
    # --- non-capturing / lookaround / in-pattern backref ---
    (r"(?:Channel|Movie|News) ", r""),
    (r"(\w)\1", r"$1"),
    (r"\w+(?= )", r"X"),
    (r"(?<=\d)\d", r"#"),
    # --- literal $ and odd replacements ---
    (r" ", r" $ "),
    (r"o", r"0"),
    # --- invalid group references (rejected by both engines) ---
    (r"(.+)", r"$2"),
    (r"(.+)", r"$10"),
    # --- rename that expands past Channel.name's column length ---
    (r"(.+)", r"$1" * 40),
    # --- regex-module syntax: quantified anchor, JS-style and duplicate
    #     named groups (these transform; both paths use the regex module) ---
    (r"^*", r"$"),
    (r"(?<season>\d+)", r"S$1"),
    (r"(?P<n>x)(?P<n>y)", r"z"),
]


class RenamePreviewParityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from rest_framework.test import APIClient
        from apps.accounts.models import User

        admin = User.objects.create_superuser(
            username="admin_rename_parity", password="pw", user_level=10
        )
        cls.client_api = APIClient()
        cls.client_api.force_authenticate(user=admin)
        cls.account = M3UAccount.objects.create(
            name="Rename Parity Provider",
            server_url="http://example.com/test.m3u",
        )

    def _sync(self):
        return sync_auto_channels(
            self.account.id,
            scan_start_time=(
                timezone.now() - timezone.timedelta(minutes=1)
            ).isoformat(),
        )

    def _run_case(self, group_name, find, replace):
        """Returns a list of human-readable mismatch strings (empty == parity)."""
        group = ChannelGroup.objects.create(name=group_name)
        from apps.channels.models import ChannelGroupM3UAccount

        ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account,
            channel_group=group,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=1000,
            custom_properties={
                "name_regex_pattern": find,
                "name_replace_pattern": replace,
            },
        )
        for i, name in enumerate(NAMES):
            Stream.objects.create(
                name=name,
                url=f"http://example.com/{group_name}_{i}.m3u8",
                m3u_account=self.account,
                channel_group=group,
                tvg_id=f"{group_name}-{i}",
                last_seen=timezone.now(),
            )

        # --- live rename via sync ---
        result = self._sync()
        if result.get("status") != "ok":
            return [f"[{find!r} -> {replace!r}] sync status={result.get('status')}"]

        channels = Channel.objects.filter(
            auto_created_by=self.account, channel_group=group
        )
        cs_rows = ChannelStream.objects.filter(
            channel__in=channels
        ).select_related("channel", "stream")
        sync_map = {row.stream.name: row.channel.name for row in cs_rows}

        # --- preview endpoint ---
        response = self.client_api.get(
            "/api/channels/streams/regex-preview/",
            {
                "channel_group": group_name,
                "find": find,
                "replace": replace,
                "limit": 50,
            },
        )
        if response.status_code != 200:
            return [f"[{find!r} -> {replace!r}] preview HTTP {response.status_code}"]
        data = response.data
        # When the preview reports find_error it predicts no rename at all.
        preview_map = {name: name for name in NAMES}
        if "find_error" not in data:
            for m in data.get("find_matches", []):
                preview_map[m["before"]] = m["after"]

        mismatches = []
        for name in NAMES:
            sync_after = sync_map.get(name)
            if sync_after is None:
                mismatches.append(
                    f"[{find!r} -> {replace!r}] {name!r}: no channel created"
                )
                continue
            preview_after = preview_map[name]
            if preview_after != sync_after:
                mismatches.append(
                    f"[{find!r} -> {replace!r}] {name!r}: "
                    f"preview={preview_after!r} sync={sync_after!r} "
                    f"(find_error={data.get('find_error')!r})"
                )
        return mismatches

    def test_preview_predicts_rename_across_strategies(self):
        all_mismatches = []
        for idx, (find, replace) in enumerate(STRATEGIES):
            all_mismatches.extend(
                self._run_case(f"ParityG{idx}", find, replace)
            )
        self.assertEqual(
            all_mismatches,
            [],
            "Preview diverged from the live rename:\n"
            + "\n".join(all_mismatches),
        )

    def test_overlong_rename_is_bounded_not_aborting_sync(self):
        # A rename that expands past Channel.name's column length must not
        # abort the bulk_create sync. Both sync and preview cap at the column
        # length so the channel is created (truncated) and the preview shows
        # the same bounded name.
        max_len = Channel._meta.get_field("name").max_length
        mismatches = self._run_case("OverlongG", r"(.+)", "$1" * 40)
        self.assertEqual(mismatches, [], "\n".join(mismatches))

        group = ChannelGroup.objects.get(name="OverlongG")
        channels = Channel.objects.filter(
            auto_created_by=self.account, channel_group=group
        )
        self.assertEqual(channels.count(), len(NAMES))
        self.assertTrue(all(len(c.name) <= max_len for c in channels))
        self.assertTrue(any(len(c.name) == max_len for c in channels))
