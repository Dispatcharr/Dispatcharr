"""EPG grid API: programs overlapping a caller-selected time window.

Keeps the TV guide payload path (window parsing, dummy generation, and the
dense ``.values()`` response) out of the general EPG view module.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, time, timedelta

from django.db.models import Prefetch
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import Authenticated, permission_classes_by_method
from apps.channels.managers import with_effective_values
from apps.channels.models import Channel, Stream
from apps.epg.models import ProgramData
from apps.epg.serializers import ProgramDataSerializer
from apps.output.dummy_epg import (
    dummy_program_to_api_dict,
    generate_dummy_programs,
    resolve_channel_parse_name,
)
from core.utils import spawn_memory_trim

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK = timedelta(hours=1)
_DEFAULT_FORWARD = timedelta(hours=24)
_MIN_DAYS = 1
_MAX_DAYS = 365
_MAX_PREV_DAYS = 30
_MAX_WINDOW = timedelta(days=_MAX_DAYS + _MAX_PREV_DAYS)
_SECONDS_PER_DAY = 86_400


class GridWindowError(ValueError):
    """Invalid grid window query parameters."""


def _parse_int_param(params, name):
    """Return an int from *params[name]*, or None if the key is absent."""
    raw = params.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise GridWindowError(
            f"Invalid integer for {name}: {raw}."
        ) from exc


def _parse_grid_datetime(raw, name):
    """Parse an ISO 8601 datetime (or bare date) from a query-string value."""
    dt = parse_datetime(raw)
    if dt is None:
        day = parse_date(raw)
        if day is None:
            raise GridWindowError(
                f"Invalid datetime for {name}: {raw}. "
                "Use ISO 8601 (e.g. 2026-02-14T18:00:00Z)."
            )
        dt = datetime.combine(day, time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.UTC)
    return dt


def _clamp_window(lookback, cutoff):
    """Validate that *cutoff* is after *lookback* and within the max span."""
    if cutoff <= lookback:
        raise GridWindowError("end must be after start.")
    if cutoff - lookback > _MAX_WINDOW:
        raise GridWindowError(
            f"Window is too large. Maximum span is {_MAX_WINDOW.days} days."
        )
    return lookback, cutoff


def _absolute_window(params, now):
    start_raw = params.get('start')
    end_raw = params.get('end')
    lookback = (
        _parse_grid_datetime(start_raw, 'start')
        if start_raw
        else now - _DEFAULT_LOOKBACK
    )
    cutoff = (
        _parse_grid_datetime(end_raw, 'end')
        if end_raw
        else lookback + _DEFAULT_FORWARD
    )
    return _clamp_window(lookback, cutoff)


def _relative_window(days, prev_days, now):
    if days is None:
        cutoff = now + _DEFAULT_FORWARD
    else:
        days = max(_MIN_DAYS, min(days, _MAX_DAYS))
        cutoff = now + timedelta(days=days)

    if prev_days is None:
        lookback = now - _DEFAULT_LOOKBACK
    else:
        prev_days = max(0, min(prev_days, _MAX_PREV_DAYS))
        lookback = now - timedelta(days=prev_days)
    return _clamp_window(lookback, cutoff)


def _resolve_epg_grid_window(request, now=None):
    """Return ``(lookback, cutoff)`` for the grid overlap filter.

    No params: ``now - 1 h`` to ``now + 24 h``.
    ``start``/``end`` present: absolute ISO 8601 range (either may be omitted).
    Otherwise ``days``/``prev_days``: relative offsets from now.
    """
    now = now if now is not None else timezone.now()
    params = request.query_params
    if params.get('start') or params.get('end'):
        return _absolute_window(params, now)

    days = _parse_int_param(params, 'days')
    prev_days = _parse_int_param(params, 'prev_days')
    if days is not None or prev_days is not None:
        return _relative_window(days, prev_days, now)

    return now - _DEFAULT_LOOKBACK, now + _DEFAULT_FORWARD


def _days_covering(span):
    """Minimum whole-day count that fully covers *span*."""
    seconds = span.total_seconds()
    if seconds <= 0:
        return 1
    return max(1, math.ceil(seconds / _SECONDS_PER_DAY))


def _dummy_generation_span(now, lookback, cutoff):
    """Return ``(generation_start, num_days)`` for dummy programs.

    Blocks stay aligned to the current hour so the default 24 h grid returns
    six 4 h standard-dummy slots, matching legacy behaviour (including its
    pre-existing up-to-1h tail slop when `now` is not itself hour-aligned).
    Generation rewinds only when lookback is earlier than the default 1 h
    window, and jumps forward only when the window starts at or after the
    current hour. Both of those cases size num_days off of the (already
    hour-aligned) generation start rather than `now`, since splitting the
    computation into separate back/forward day counts and adding them can
    under-count by up to a day when `now`'s minutes/seconds are non-zero.
    """
    truncated_now = now.replace(minute=0, second=0, microsecond=0)
    default_lookback = now - _DEFAULT_LOOKBACK

    if lookback >= truncated_now:
        # Future-only window: align to the start and size off of it directly.
        base = lookback.replace(minute=0, second=0, microsecond=0)
        return base, _days_covering(cutoff - base)

    if lookback < default_lookback:
        # Rewound further than the default lookback: extend backward, then
        # size num_days off of the rewound base so the far edge still reaches
        # cutoff.
        days_back = _days_covering(truncated_now - lookback)
        base = truncated_now - timedelta(days=days_back)
        return base, _days_covering(cutoff - base)

    # No rewind requested: keep the historical alignment and day count.
    return truncated_now, _days_covering(cutoff - now)


def custom_dummy_channels_queryset():
    """Channels backed by a dummy EPG source, ready for on-demand generation.

    Streams are prefetched in channelstream order because dummy sources configured
    with name_source='stream' resolve their regex input by stream index; without the
    explicit ordering the prefetch cache would fall back to Stream's own ordering
    and pick the wrong title.
    """
    return with_effective_values(
        Channel.objects.filter(epg_data__epg_source__source_type='dummy')
        .select_related('epg_data__epg_source')
        .prefetch_related(
            Prefetch(
                'streams',
                queryset=Stream.objects.only('id', 'name').order_by(
                    'channelstream__order'
                ),
            )
        )
        .distinct()
    )


def _serialize_program_values(programs_qs):
    """Turn a ``.values()`` queryset into the grid response dicts."""
    serialized = []
    for p in programs_qs:
        cp = p['custom_properties'] or {}
        premiere_text = cp.get('premiere_text', '')
        serialized.append({
            'id': p['id'],
            'start_time': p['start_time'],
            'end_time': p['end_time'],
            'title': p['title'],
            'sub_title': p['sub_title'],
            'description': p['description'],
            'tvg_id': p['tvg_id'],
            'season': cp.get('season'),
            'episode': cp.get('episode'),
            'is_new': bool(cp.get('new')),
            'is_live': bool(cp.get('live')),
            'is_premiere': bool(cp.get('premiere')),
            'is_finale': bool(premiere_text and 'finale' in premiere_text.lower()),
        })
    return serialized


class EPGGridAPIView(APIView):
    """Programs overlapping a time window, plus on-demand dummy programmes."""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description=(
            "Retrieve programs overlapping a time window. With no query "
            "parameters the window is the previous hour through the next "
            "24 hours (recently ended, currently airing, and upcoming). "
            "Use ``days``/``prev_days`` for XMLTV-style relative offsets, "
            "or ``start``/``end`` (ISO 8601) for an explicit range."
        ),
        parameters=[
            OpenApiParameter(
                'days',
                OpenApiTypes.INT,
                description=(
                    "Number of days forward from now (1-365). "
                    "Omitted: 24 hours forward. "
                    "0 is treated as 1. "
                    "Ignored when start or end is set."
                ),
            ),
            OpenApiParameter(
                'prev_days',
                OpenApiTypes.INT,
                description=(
                    "Number of days of lookback from now (0-30). "
                    "Omitted: 1 hour (recently ended plus currently on). "
                    "0 means start at now. "
                    "Ignored when start or end is set."
                ),
            ),
            OpenApiParameter(
                'start',
                OpenApiTypes.DATETIME,
                description=(
                    "Window start as ISO 8601 datetime. "
                    "Takes precedence over days/prev_days. "
                    "Omitted with end present: defaults to now minus 1 hour."
                ),
            ),
            OpenApiParameter(
                'end',
                OpenApiTypes.DATETIME,
                description=(
                    "Window end as ISO 8601 datetime. "
                    "Takes precedence over days/prev_days. "
                    "Omitted with start present: defaults to start plus 24 hours."
                ),
            ),
        ],
        responses={200: ProgramDataSerializer(many=True)},
    )
    def get(self, request, format=None):
        now = timezone.now()
        try:
            lookback, cutoff = _resolve_epg_grid_window(request, now=now)
        except GridWindowError as exc:
            return Response(
                {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        logger.debug(
            "EPGGridAPIView: Querying programs between %s and %s.",
            lookback,
            cutoff,
        )

        programs = ProgramData.objects.filter(
            end_time__gt=lookback,
            start_time__lt=cutoff,
        )

        channels_without_epg = with_effective_values(
            Channel.objects.filter(epg_data__isnull=True)
        )
        channels_with_custom_dummy = custom_dummy_channels_queryset()

        programs_qs = programs.values(
            'id', 'start_time', 'end_time', 'title', 'sub_title',
            'description', 'tvg_id', 'custom_properties',
        )
        serialized_programs = _serialize_program_values(programs_qs)
        logger.debug(
            "EPGGridAPIView: Found %s program(s) overlapping the window.",
            len(serialized_programs),
        )

        dummy_start, dummy_days = _dummy_generation_span(now, lookback, cutoff)
        dummy_programs = []

        for queryset, id_prefix, custom_source in (
            (channels_with_custom_dummy, 'dummy-custom', True),
            (channels_without_epg, 'dummy-standard', False),
        ):
            for channel in queryset:
                dummy_tvg_id = str(channel.uuid)
                effective_name = channel.effective_name
                if custom_source:
                    epg_source = (
                        channel.epg_data.epg_source if channel.epg_data else None
                    )
                    channel_name = resolve_channel_parse_name(
                        channel, epg_source, fallback_name=effective_name
                    )
                else:
                    epg_source = None
                    channel_name = effective_name
                try:
                    generated = generate_dummy_programs(
                        channel_id=dummy_tvg_id,
                        channel_name=channel_name,
                        num_days=dummy_days,
                        program_length_hours=4,
                        epg_source=epg_source,
                        export_lookback=lookback,
                        export_cutoff=cutoff,
                        generation_start=dummy_start,
                    )
                    for program in generated or []:
                        dummy_programs.append(
                            dummy_program_to_api_dict(
                                channel,
                                program,
                                dummy_tvg_id=dummy_tvg_id,
                                program_id_prefix=id_prefix,
                            )
                        )
                except Exception:
                    logger.exception(
                        "Error creating %s programs for channel %s (ID: %s)",
                        id_prefix,
                        channel.name,
                        channel.id,
                    )

        serialized_programs.extend(dummy_programs)
        logger.debug(
            "EPGGridAPIView: Returning %s total programs "
            "(including %s dummy programs).",
            len(serialized_programs),
            len(dummy_programs),
        )

        # The grid materializes tens of thousands of program dicts plus the
        # rendered JSON; trim once the response is sent so worker RSS does not
        # ratchet up per request.
        response = Response(
            {"data": serialized_programs}, status=status.HTTP_200_OK
        )
        response._resource_closers.append(spawn_memory_trim)
        return response
