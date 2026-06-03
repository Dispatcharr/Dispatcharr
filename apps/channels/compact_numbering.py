"""Compact channel numbering helpers.

The per-group `compact_numbering` custom_property is opt-in. When enabled
on a ChannelGroupM3UAccount, the group's auto-created channels get packed
contiguously into the group's [start, end] range:

  * Visible without channel_number override: assigned sequentially
  * Hidden without channel_number override:  channel_number set to NULL
    (released; the slot becomes available for visible channels)
  * Override-pinned (any visibility): untouched; the override's
    channel_number is treated as a global reservation that other channels
    skip when packing

Used by sync_auto_channels (full-pack pass), the post_save Channel signal
(single-channel unhide), the bulk-edit endpoint (bulk unhide), and a
manual per-group re-pack endpoint.

Trade-off the user opts into: channel numbers may shift when hide / unhide
state changes. To pin a number through hide/unhide cycles, set a
channel_number override - the override is honored as a reservation.
"""

import logging

from django.db import transaction

from .models import Channel, ChannelOverride, ChannelGroupM3UAccount
from apps.m3u.tasks import _custom_properties_as_dict, _next_available_number
from core.utils import (
    acquire_task_lock,
    natural_sort_key,
    release_task_lock,
)

logger = logging.getLogger(__name__)


def is_compact_group(group_relation):
    """Return True if the given ChannelGroupM3UAccount is in compact mode."""
    cp = _custom_properties_as_dict(group_relation.custom_properties)
    return bool(cp.get("compact_numbering"))


def get_group_relation_for_channel(channel):
    """Resolve the ChannelGroupM3UAccount that owns this auto-created
    channel. Returns None for manual channels, or when the relation has
    been deleted.

    With a Channel Group Override active, sync stores the channel under
    the override target group's id, not the source group's id recorded on
    the relation. The direct lookup then misses, so fall back to scanning
    the account's relations for one whose group_override points at the
    channel's current group. The fallback runs only on a direct miss, so
    the common no-override path keeps its single SELECT.
    """
    if not channel.auto_created or not channel.auto_created_by_id:
        return None
    if not channel.channel_group_id:
        return None

    try:
        return ChannelGroupM3UAccount.objects.get(
            m3u_account_id=channel.auto_created_by_id,
            channel_group_id=channel.channel_group_id,
        )
    except ChannelGroupM3UAccount.DoesNotExist:
        pass

    # group_override may be stored as int or str; compare as strings so
    # the match is type-agnostic.
    target = str(channel.channel_group_id)
    for rel in ChannelGroupM3UAccount.objects.filter(
        m3u_account_id=channel.auto_created_by_id
    ):
        cp = _custom_properties_as_dict(rel.custom_properties)
        if str(cp.get("group_override", "")) == target:
            return rel
    return None


def build_reserved_set(exclude_channel_ids=None, range_start=None, range_end=None):
    """Return the set of channel numbers currently 'claimed' system-wide
    for the purposes of a compact pack:

      * Every ChannelOverride.channel_number value (overrides reserve
        their effective number; duplicates across overrides are allowed
        and collapse to a single reservation via set semantics)
      * Every Channel.channel_number value EXCEPT for channels in the
        passed-in exclude set (those are about to be reassigned)

    When the caller knows the target group has a bounded range, pass
    `range_start` and `range_end` to scope the scan to numbers that
    could possibly collide. Without scoping, a single signal-driven
    unhide reads every channel_number in the database; with scoping it
    reads at most the values within [start, end] which for typical
    cable-style ranges is hundreds rather than tens of thousands.

    Float vs int normalization is unnecessary because Python treats
    50 and 50.0 as equal and produces the same hash, so set membership
    works directly across both types.
    """
    exclude_channel_ids = set(exclude_channel_ids or [])
    override_qs = ChannelOverride.objects.filter(channel_number__isnull=False)
    other_qs = Channel.objects.exclude(channel_number__isnull=True).exclude(
        id__in=exclude_channel_ids
    )
    if range_start is not None:
        override_qs = override_qs.filter(channel_number__gte=range_start)
        other_qs = other_qs.filter(channel_number__gte=range_start)
    if range_end is not None:
        override_qs = override_qs.filter(channel_number__lte=range_end)
        other_qs = other_qs.filter(channel_number__lte=range_end)
    reserved = set(override_qs.values_list("channel_number", flat=True))
    reserved.update(other_qs.values_list("channel_number", flat=True))
    reserved.discard(None)
    return reserved


def _channel_has_number_override(channel):
    try:
        ov = channel.override
    except ChannelOverride.DoesNotExist:
        return False
    return ov is not None and ov.channel_number is not None


def assign_compact_numbers_for_channels(channel_ids):
    """For each channel ID in the input that became eligible for a number
    (visible, auto-created, no number override, in a compact-mode group),
    assign the next available channel number in the group's [start, end]
    range. Channels whose group is not in compact mode are skipped silently
    so callers can pass mixed batches without filtering up front.

    Used by both the post_save signal (single-channel unhide) and the bulk
    edit endpoint (bulk unhide). Returns dict {channel_id: number_or_None}.
    """
    if not channel_ids:
        return {}
    channels = list(
        Channel.objects.filter(
            id__in=channel_ids,
            auto_created=True,
            auto_created_by__isnull=False,
            hidden_from_output=False,
            channel_number__isnull=True,
        ).select_related("override", "channel_group", "auto_created_by")
    )
    if not channels:
        return {}

    # Group channels by (account_id, group_id) so each unique pair's
    # ChannelGroupM3UAccount is resolved with a single SELECT rather than
    # one per channel.
    by_pair = {}
    for ch in channels:
        if _channel_has_number_override(ch):
            continue
        key = (ch.auto_created_by_id, ch.channel_group_id)
        by_pair.setdefault(key, []).append(ch)
    if not by_pair:
        return {}

    pair_keys = list(by_pair.keys())
    relations_by_pair = {}
    relations_qs = ChannelGroupM3UAccount.objects.filter(
        m3u_account_id__in={k[0] for k in pair_keys},
        channel_group_id__in={k[1] for k in pair_keys},
    )
    for rel in relations_qs:
        relations_by_pair[(rel.m3u_account_id, rel.channel_group_id)] = rel

    # Override fallback: pairs the direct lookup missed carry an override-
    # target channel_group_id. Resolve them with one extra query over the
    # unresolved accounts (not one per pair), so the common path keeps its
    # single narrow query.
    unresolved = [k for k in pair_keys if k not in relations_by_pair]
    if unresolved:
        override_relations = {}
        for rel in ChannelGroupM3UAccount.objects.filter(
            m3u_account_id__in={k[0] for k in unresolved}
        ):
            cp = _custom_properties_as_dict(rel.custom_properties)
            target = cp.get("group_override")
            if not target:
                continue
            try:
                override_relations[(rel.m3u_account_id, int(target))] = rel
            except (TypeError, ValueError):
                continue
        for key in unresolved:
            rel = override_relations.get(key)
            if rel is not None:
                relations_by_pair[key] = rel

    by_relation = {}
    for key, group_channels in by_pair.items():
        rel = relations_by_pair.get(key)
        if rel is None or not is_compact_group(rel):
            continue
        by_relation[rel.id] = (rel, group_channels)

    # Group by account so writes share the `refresh_single_m3u_account`
    # lock used by sync_auto_channels and the manual repack endpoint.
    # If sync is in flight for an account, defer to it.
    by_account = {}
    for rel, group_channels in by_relation.values():
        by_account.setdefault(rel.m3u_account_id, []).append(
            (rel, group_channels)
        )

    results = {}
    for account_id, account_pairs in by_account.items():
        if not acquire_task_lock(
            "refresh_single_m3u_account", account_id
        ):
            logger.info(
                "Compact unhide deferred for account %s: refresh in progress; "
                "next sync will assign numbers.",
                account_id,
            )
            for _, group_channels in account_pairs:
                for ch in group_channels:
                    results[ch.id] = None
            continue

        # try/finally release: the Redis lock is not transactional, so a
        # transaction.on_commit release would leak the lock when an
        # outer atomic rolls back, blocking subsequent syncs until TTL.
        try:
            with transaction.atomic():
                for rel, group_channels in account_pairs:
                    start = int(rel.auto_sync_channel_start or 1)
                    end = (
                        int(rel.auto_sync_channel_end)
                        if rel.auto_sync_channel_end
                        else None
                    )
                    reserved = build_reserved_set(
                        exclude_channel_ids=[c.id for c in group_channels],
                        range_start=start,
                        range_end=end,
                    )
                    to_update = []
                    for ch in group_channels:
                        next_num = _next_available_number(
                            reserved, start, end=end
                        )
                        if next_num is None:
                            results[ch.id] = None
                            continue
                        ch.channel_number = next_num
                        reserved.add(next_num)
                        results[ch.id] = next_num
                        to_update.append(ch)
                    if to_update:
                        Channel.objects.bulk_update(
                            to_update, ["channel_number"], batch_size=100
                        )
        finally:
            try:
                release_task_lock(
                    "refresh_single_m3u_account", account_id
                )
            except Exception as e:
                logger.warning(
                    "Failed to release compact-unhide lock for account "
                    "%s: %s",
                    account_id,
                    e,
                )
    return results


def repack_group(group_relation):
    """Renumber every auto-created channel in the given group+account.

    Visible non-override channels are assigned sequentially in
    [start, end] using the group's configured channel_sort_order.
    Hidden non-override channels have their channel_number set to
    None (slot released). Override-pinned channels are untouched.

    Returns a dict with assigned/released/failed counts. ``failed``
    counts visible channels that could not fit because the range was
    exhausted; their channel_number is set to None so the state is
    unambiguous instead of stuck at a stale number.

    All writes run inside a single transaction so concurrent readers
    (HDHR/M3U/EPG output paths) never observe a half-packed state.
    """
    with transaction.atomic():
        return _repack_inner(group_relation)


def _repack_inner(group_relation):
    account_id = group_relation.m3u_account_id
    group_id = group_relation.channel_group_id

    cp = _custom_properties_as_dict(group_relation.custom_properties)
    sort_order = cp.get("channel_sort_order") or ""
    sort_reverse = bool(cp.get("channel_sort_reverse"))

    start = int(group_relation.auto_sync_channel_start or 1)
    end = (
        int(group_relation.auto_sync_channel_end)
        if group_relation.auto_sync_channel_end
        else None
    )

    # Match the override target group too: channels created under an
    # override live under the target's id, not the source group's.
    group_ids = {group_id}
    override_group_id = cp.get("group_override")
    if override_group_id:
        try:
            group_ids.add(int(override_group_id))
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring non-numeric group_override %r on relation %s",
                override_group_id,
                group_relation.id,
            )

    # Known limitation: if two source groups on the same account override
    # into the SAME target group, their channels are indistinguishable
    # here (channels carry no source-group back-reference), so each repack
    # renumbers the shared target's channels into its own range.
    channels = list(
        Channel.objects.filter(
            auto_created=True,
            auto_created_by_id=account_id,
            channel_group_id__in=group_ids,
        ).select_related("override")
    )

    visible = []
    hidden = []
    pinned = []
    for ch in channels:
        if _channel_has_number_override(ch):
            pinned.append(ch)
        elif ch.hidden_from_output:
            hidden.append(ch)
        else:
            visible.append(ch)

    # Sort the visible set by the group's configured channel_sort_order.
    # Provider order (the default) preserves DB-iteration order which is
    # roughly creation order; treat unrecognized values the same way.
    if sort_order == "name":
        visible.sort(
            key=lambda c: natural_sort_key(c.name or ""),
            reverse=sort_reverse,
        )
    elif sort_order == "tvg_id":
        visible.sort(
            key=lambda c: c.tvg_id or "",
            reverse=sort_reverse,
        )
    elif sort_order == "updated_at":
        visible.sort(
            key=lambda c: c.updated_at,
            reverse=sort_reverse,
        )

    # Exclude every channel in this group: the pinned channel's raw value
    # is irrelevant (the override is reserved globally and cleared below).
    # Scope to the group's range when bounded to keep the set small.
    affected_ids = [c.id for c in (visible + hidden + pinned)]
    reserved = build_reserved_set(
        exclude_channel_ids=affected_ids,
        range_start=start,
        range_end=end,
    )

    assigned_count = 0
    failed_count = 0
    visible_to_update = []
    for ch in visible:
        next_num = _next_available_number(reserved, start, end=end)
        if next_num is None:
            failed_count += 1
            if ch.channel_number is not None:
                ch.channel_number = None
                visible_to_update.append(ch)
            continue
        if ch.channel_number != next_num:
            ch.channel_number = next_num
            visible_to_update.append(ch)
        reserved.add(next_num)
        assigned_count += 1

    if visible_to_update:
        Channel.objects.bulk_update(
            visible_to_update, ["channel_number"], batch_size=100
        )

    released_count = 0
    hidden_with_num = [c for c in hidden if c.channel_number is not None]
    if hidden_with_num:
        for c in hidden_with_num:
            c.channel_number = None
        Channel.objects.bulk_update(
            hidden_with_num, ["channel_number"], batch_size=100
        )
        released_count = len(hidden_with_num)

    # Pinned channels: clear raw channel_number. The override controls
    # their effective number; leaving a stale raw value would pollute
    # uniqueness checks and could resurrect on override clear.
    pinned_with_num = [c for c in pinned if c.channel_number is not None]
    if pinned_with_num:
        for c in pinned_with_num:
            c.channel_number = None
        Channel.objects.bulk_update(
            pinned_with_num, ["channel_number"], batch_size=100
        )

    return {
        "assigned": assigned_count,
        "released": released_count,
        "failed": failed_count,
    }
