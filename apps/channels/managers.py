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

from django.db.models import F, Max, Q
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
    "is_radio",
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


def effective_field_lookup_q(field, lookup, value):
    """
    Q matching Coalesce(override__field, field) for a text/scalar lookup.

    Override wins only when that override column is non-null, matching
    with_effective_values() / serializer coalesce semantics.
    """
    return Q(**{f"override__{field}__{lookup}": value}) | (
        Q(**{f"override__{field}__isnull": True})
        & Q(**{f"{field}__{lookup}": value})
    )


def effective_related_name_lookup_q(
    fk_field, value, lookup="icontains", name_path="name"
):
    """
    Q matching the effective FK target's `name_path` (override FK if set,
    otherwise the channel's own FK), e.g. ("channel_group", ...) or
    ("epg_data", ..., name_path="epg_source__name").

    The fallback to the channel's FK is gated on the override FK being null,
    not on the looked-up column, so a set override FK always wins.
    """
    return Q(**{f"override__{fk_field}__{name_path}__{lookup}": value}) | (
        Q(**{f"override__{fk_field}__isnull": True})
        & Q(**{f"{fk_field}__{name_path}__{lookup}": value})
    )


def max_reserved_channel_number():
    """
    Highest channel number claimed by a raw column or an override pin, or
    None when nothing is numbered.

    Uses the same "both are reserved" rule as build_reserved_set, so a number
    handed out after this can never collide with a raw number that an
    override is currently masking.
    """
    from apps.channels.models import Channel, ChannelOverride

    raw = Channel.objects.aggregate(m=Max("channel_number"))["m"]
    pinned = ChannelOverride.objects.aggregate(m=Max("channel_number"))["m"]
    return max((n for n in (raw, pinned) if n is not None), default=None)


def channel_number_is_reserved(number):
    """True if a raw channel number or an override pin already claims number."""
    from apps.channels.models import Channel, ChannelOverride

    if Channel.objects.filter(channel_number=number).exists():
        return True
    return ChannelOverride.objects.filter(channel_number=number).exists()


def effective_number_rows(queryset):
    """
    Narrow rows (id, raw number, override pin, effective number).

    Used to read the channel being dragged and its insert target without
    hydrating full Channel and ChannelOverride rows.
    """
    return queryset.annotate(
        _eff=Coalesce("override__channel_number", "channel_number")
    ).values(
        "id",
        "auto_created",
        "channel_number",
        "override__id",
        "override__channel_number",
        "_eff",
    )


def channel_from_number_row(row):
    """
    Build the minimal Channel (with its override relation pre-cached) that
    apply_effective_channel_numbers needs from an effective_number_rows row.
    """
    from apps.channels.models import Channel, ChannelOverride

    channel = Channel(
        id=row["id"],
        auto_created=row["auto_created"],
        channel_number=row["channel_number"],
    )
    override = None
    if row["override__id"]:
        override = ChannelOverride(
            id=row["override__id"],
            channel_id=row["id"],
            channel_number=row["override__channel_number"],
        )
    # Caching None makes `channel.override` raise DoesNotExist without a
    # query, exactly as select_related("override") does for a missing row.
    Channel._meta.get_field("override").set_cached_value(channel, override)
    return channel


def shift_effective_channel_numbers(
    *,
    exclude_channel_id,
    delta,
    gt=None,
    gte=None,
    lt=None,
    lte=None,
):
    """
    Add delta to every effective channel number in the given open/closed
    range, excluding one channel. Two SQL F() updates:

      * Channel rows whose effective number is Channel.channel_number
        (manual channels, and auto channels without a number pin)
      * ChannelOverride rows that pin a channel number (auto pins)

    This is the override-aware equivalent of the old single-table
    ``UPDATE ... SET channel_number = channel_number + delta`` path.
    """
    from django.db.models import Exists, OuterRef

    from apps.channels.models import Channel, ChannelOverride

    def apply_bounds(qs, field):
        if gt is not None:
            qs = qs.filter(**{f"{field}__gt": gt})
        if gte is not None:
            qs = qs.filter(**{f"{field}__gte": gte})
        if lt is not None:
            qs = qs.filter(**{f"{field}__lt": lt})
        if lte is not None:
            qs = qs.filter(**{f"{field}__lte": lte})
        return qs

    # A number pin is the effective value, so the raw column shifts only
    # when nothing is pinning it. Manual channels are included without the
    # anti-join: the API rejects number overrides on them, and their raw
    # column is the effective number.
    has_number_pin = ChannelOverride.objects.filter(
        channel_id=OuterRef("pk"),
        channel_number__isnull=False,
    )
    channel_targets = apply_bounds(
        Channel.objects.exclude(pk=exclude_channel_id).filter(
            Q(auto_created=False) | ~Exists(has_number_pin)
        ),
        "channel_number",
    )
    channel_targets.update(channel_number=F("channel_number") + delta)

    pinned = apply_bounds(
        ChannelOverride.objects.filter(channel_number__isnull=False).exclude(
            channel_id=exclude_channel_id
        ),
        "channel_number",
    )
    pinned.update(channel_number=F("channel_number") + delta)


def apply_effective_channel_numbers(assignments):
    """
    Persist effective channel numbers for (channel, number) pairs.

    Auto-created channels write ChannelOverride.channel_number so sync cannot
    clobber the pin (and clear that field when the value matches the provider
    number). Manual channels write Channel.channel_number directly.

    Channels must already have the override relation cached (select_related
    or channel_from_number_row) so this issues no per-channel queries. Every
    write is computed from those snapshots, then applied as bulk SQL. Call
    inside a transaction.
    """
    from apps.channels.models import Channel, ChannelOverride

    # Last write wins per channel. Protects assign/reorder if the same id
    # appears twice; without this, two override creates for one channel
    # would trip the OneToOne constraint on bulk_create.
    collapsed = {}
    order = []
    for channel, number in assignments:
        if channel.id not in collapsed:
            order.append(channel.id)
        collapsed[channel.id] = (channel, number)
    assignments = [collapsed[channel_id] for channel_id in order]

    channel_updates = []
    override_updates = []
    override_creates = []
    overrides_to_prune = []

    for channel, number in assignments:
        if channel.auto_created:
            try:
                override = channel.override
            except ChannelOverride.DoesNotExist:
                override = None

            if number == channel.channel_number:
                if override is not None and override.channel_number is not None:
                    override.channel_number = None
                    override_updates.append(override)
                    overrides_to_prune.append(override)
                continue

            if override is None:
                override_creates.append(
                    ChannelOverride(channel=channel, channel_number=number)
                )
            elif override.channel_number != number:
                override.channel_number = number
                override_updates.append(override)
            continue

        if channel.channel_number != number:
            channel.channel_number = number
            channel_updates.append(channel)

    if channel_updates:
        Channel.objects.bulk_update(channel_updates, ["channel_number"])
    if override_creates:
        ChannelOverride.objects.bulk_create(override_creates)
    if override_updates:
        ChannelOverride.objects.bulk_update(override_updates, ["channel_number"])
    if overrides_to_prune:
        # One DELETE for rows that no longer pin anything. Checking the
        # database (not the in-memory stub) keeps a name/logo/EPG override.
        ChannelOverride.objects.filter(
            pk__in=[override.pk for override in overrides_to_prune],
            name__isnull=True,
            channel_number__isnull=True,
            channel_group__isnull=True,
            logo__isnull=True,
            tvg_id__isnull=True,
            tvc_guide_stationid__isnull=True,
            epg_data__isnull=True,
            stream_profile__isnull=True,
            is_radio__isnull=True,
        ).delete()


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


def program_is_new_for_rule(custom_properties, untagged_is_new=False):
    """Return True if a programme matches series-rule mode="new".

    Default: only programmes tagged <new/>.
    With untagged_is_new: also accept programmes carrying neither <new/>
    nor <previously-shown/> (feeds that only tag repeats). An explicit
    <new/> always counts, even alongside <previously-shown/>.
    """
    props = custom_properties or {}
    if props.get("new"):
        return True
    return bool(untagged_is_new) and not props.get("previously_shown")


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
