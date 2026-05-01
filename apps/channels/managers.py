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
