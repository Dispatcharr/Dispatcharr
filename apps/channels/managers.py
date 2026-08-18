"""
Queryset helpers that resolve effective Channel field values.

Each Channel can optionally have a related ChannelOverride row carrying user
edits to any subset of its user-facing fields. Sync never touches the override
row; provider metadata flows directly into Channel.* and the override table
sits alongside with a nullable value per field. The helpers here coalesce the
two sources into `effective_*` annotations so output querysets can sort,
filter, and emit values correctly at SQL level (avoiding 23+ Python-side
resolutions across the codebase).
"""

from django.db.models import Q
from django.db.models.functions import Coalesce


OVERRIDABLE_FIELDS = (
    "name",
    "channel_number",
    "channel_group_id",
    "logo_id",
    "tvg_id",
    "tvc_guide_stationid",
    "epg_data_id",
    "stream_profile_id",
)


def with_effective_values(queryset, select_related_fks=False):
    """
    Annotate the channels queryset with `effective_*` columns that resolve to
    the override value when set, otherwise fall back to the channel's own
    value. Always eagerly loads the override one-to-one to avoid N+1 when the
    caller reads annotated attributes and then the related override.

    Pass `select_related_fks=True` when the output path will access FK objects
    through the `effective_*_obj` Channel properties; this pulls the override's
    logo, channel_group, epg_data, and stream_profile in the same query so
    those accessors do not trigger per-row lookups.
    """
    annotations = {
        f"effective_{field}": Coalesce(
            f"override__{field}",
            field,
        )
        for field in OVERRIDABLE_FIELDS
    }
    qs = queryset.select_related("override").annotate(**annotations)
    if select_related_fks:
        qs = qs.select_related(
            "override__logo",
            "override__channel_group",
            "override__epg_data",
            "override__stream_profile",
        )
    return qs


def epg_ids_mapped_to_channels(epg_source=None, epg_source_id=None):
    """
    EPGData ids effectively assigned to at least one channel.

    An assignment counts whether it lives on Channel.epg_data or on
    ChannelOverride.epg_data (hand-assigned overrides for auto-synced
    channels). Programme import and orphan cleanup use this so
    override-only mappings still get ProgramData rows.
    """
    from apps.channels.models import Channel, ChannelOverride

    channel_filter = {"epg_data__isnull": False}
    override_filter = {"epg_data__isnull": False}
    if epg_source is not None:
        channel_filter["epg_data__epg_source"] = epg_source
        override_filter["epg_data__epg_source"] = epg_source
    elif epg_source_id is not None:
        channel_filter["epg_data__epg_source_id"] = epg_source_id
        override_filter["epg_data__epg_source_id"] = epg_source_id

    mapped = set(
        Channel.objects.filter(**channel_filter).values_list(
            "epg_data_id", flat=True
        )
    )
    mapped.update(
        ChannelOverride.objects.filter(**override_filter).values_list(
            "epg_data_id", flat=True
        )
    )
    return mapped


def is_epg_mapped_to_channel(epg):
    """True if any channel effectively uses this EPGData row."""
    from apps.channels.models import Channel, ChannelOverride

    if Channel.objects.filter(epg_data=epg).exists():
        return True
    return ChannelOverride.objects.filter(epg_data=epg).exists()


def parse_optional_epg_source_id(value):
    """Return a positive int epg_source_id, or None if missing/invalid."""
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def future_recordings_for_series(tvg_id="", title="", epg_source_id=None):
    """Upcoming recordings that belong to a series rule.

    When epg_source_id is set, only snapshots tagged with that source are
    included, plus untagged legacy snapshots (scheduled before the tag
    existed). Recordings tagged with a different source are left alone.
    When epg_source_id is omitted, every matching tvg_id/title recording
    is included, which is the unsourced-rule / delete-all-copies path.
    """
    from django.utils import timezone
    from apps.channels.models import Recording

    qs = Recording.objects.filter(start_time__gte=timezone.now())
    tvg_id = str(tvg_id or "").strip()
    if tvg_id:
        qs = qs.filter(custom_properties__program__tvg_id=tvg_id)
    if title:
        qs = qs.filter(custom_properties__program__title=title)
    source_id = parse_optional_epg_source_id(epg_source_id)
    if source_id is not None:
        qs = qs.filter(
            Q(custom_properties__program__epg_source_id=source_id)
            | Q(custom_properties__program__epg_source_id__isnull=True)
        )
    return qs


def resolve_epg_data_for_series_rule(tvg_id, epg_source_id=None, mapped_epg_ids=None):
    """Resolve EPGData rows for a series rule keyed by tvg_id.

    tvg_id is unique per EPG source, not globally. Picking .first() can hit an
    unmapped duplicate and skip the mapped copy the guide actually uses.

    When epg_source_id is set, return that exact (tvg_id, source) row if it is
    mapped to a channel. When it is omitted (legacy rules), return every mapped
    row with that tvg_id.

    Pass mapped_epg_ids (from epg_ids_mapped_to_channels) when resolving several
    rules in one pass so the mapping is not re-queried per rule.

    Returns (epgs, status) where status is None on success, else
    "no_epg_match" or "no_channel_for_epg".
    """
    from apps.epg.models import EPGData

    tvg_id = str(tvg_id or "").strip()
    if not tvg_id:
        return [], "no_epg_match"

    # A tvg_id resolves to a handful of rows at most (one per source), so the
    # mapped-set membership check happens in Python rather than as a SQL IN
    # over every mapped EPG id in the install.
    candidates = list(EPGData.objects.filter(tvg_id=tvg_id))
    if not candidates:
        return [], "no_epg_match"

    if epg_source_id is not None:
        candidates = [e for e in candidates if e.epg_source_id == epg_source_id]
        if not candidates:
            return [], "no_epg_match"

    if mapped_epg_ids is None:
        mapped_epg_ids = epg_ids_mapped_to_channels()

    mapped = [e for e in candidates if e.id in mapped_epg_ids]
    if mapped:
        return mapped, None
    return [], "no_channel_for_epg"
