"""EPG grid API: programs overlapping a caller-selected time window.

Keeps the TV guide payload path (window parsing, dummy generation, and the
dense JSON response) out of the general EPG view module.

The successful response body keeps the historical ``{"data":[...]}`` shape so
existing clients (including the web guide) keep working, but it is streamed in
batches so worker memory does not hold the full program list plus a second
rendered-JSON copy at once.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, time, timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields.json import KeyTransform
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import Authenticated, permission_classes_by_method
from apps.channels.managers import with_effective_values
from apps.channels.models import Channel
from apps.epg.models import ProgramData
from apps.epg.serializers import EPGGridResponseSerializer
from apps.output.dummy_epg import (
    dummy_program_to_api_dict,
    generate_dummy_programs,
    prefetch_streams_for_stream_named_sources,
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

# Serialize this many program objects before yielding a chunk.
_GRID_JSON_YIELD_BATCH_SIZE = 500
_GRID_DB_ITERATOR_CHUNK_SIZE = 2000


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


def _parse_channel_profile_id(params):
    """Return an optional channel profile id, or raise ``GridWindowError``."""
    raw = params.get('channel_profile_id')
    if raw is None or raw == '' or str(raw).lower() == 'all':
        return None
    try:
        profile_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise GridWindowError(
            f"Invalid integer for channel_profile_id: {raw}."
        ) from exc
    if profile_id < 1:
        raise GridWindowError(
            f"Invalid channel_profile_id: {raw}."
        )
    return profile_id


def _visible_channels_queryset(user, profile_id=None):
    """Channels the caller may see, matching the TV Guide summary filters.

    Default (no profile) is the guide's ALL view: every non-hidden channel the
    user is allowed to access by ``user_level`` (and adult-content preference).
    When ``profile_id`` is set, membership must be enabled for that profile.
    Effective EPG / name / tvg fields come from ``with_effective_values``.

    Streams are not prefetched here: only custom dummy sources with
    ``name_source='stream'`` need them, and that happens after partitioning.
    """
    qs = Channel.objects.filter(hidden_from_output=False)
    if user is not None and getattr(user, 'user_level', 10) < 10:
        qs = qs.filter(user_level__lte=user.user_level)
        custom_props = getattr(user, 'custom_properties', None) or {}
        if custom_props.get('hide_adult_content', False):
            qs = qs.filter(is_adult=False)
    if profile_id is not None:
        qs = qs.filter(
            channelprofilemembership__channel_profile_id=profile_id,
            channelprofilemembership__enabled=True,
        ).distinct()
    return with_effective_values(
        qs.select_related(
            'epg_data__epg_source',
            'override__epg_data__epg_source',
        ),
        select_related_fks=True,
    )


def _partition_visible_channels(channels_qs):
    """Split visible channels into real-EPG ids vs dummy-generation lists.

    Uses each channel's effective EPG assignment (override wins). Shared EPG
    rows stay shared: one Programme set can still fan out to many channels on
    the client via ``tvg_id``.
    """
    epg_ids = set()
    dummy_custom = []
    no_epg = []
    for channel in channels_qs:
        epg = channel.effective_epg_data_obj
        if epg is None:
            no_epg.append(channel)
            continue
        source = epg.epg_source
        if source is not None and source.source_type == 'dummy':
            dummy_custom.append(channel)
        else:
            epg_ids.add(epg.id)
    return epg_ids, dummy_custom, no_epg


def _premiere_text_value(raw):
    if raw is None:
        return ''
    if isinstance(raw, str):
        return raw
    return str(raw)


def _program_value_to_dict(p):
    """Convert one annotated grid ``.values()`` row into a response dict."""
    premiere_text = _premiere_text_value(p.get('premiere_text'))
    return {
        'id': p['id'],
        'start_time': p['start_time'],
        'end_time': p['end_time'],
        'title': p['title'],
        'sub_title': p['sub_title'],
        'description': p['description'],
        'tvg_id': p['tvg_id'],
        'season': p.get('season'),
        'episode': p.get('episode'),
        'is_new': bool(p.get('flag_new')),
        'is_live': bool(p.get('flag_live')),
        'is_premiere': bool(p.get('flag_premiere')),
        'is_finale': bool(premiere_text and 'finale' in premiere_text.lower()),
    }


def _iter_real_program_dicts(lookback, cutoff, epg_ids):
    """Yield stored programs for the caller's visible, non-dummy EPG rows."""
    if not epg_ids:
        return

    programs_qs = (
        ProgramData.objects.filter(
            epg_id__in=epg_ids,
            end_time__gt=lookback,
            start_time__lt=cutoff,
        )
        .annotate(
            season=KeyTransform('season', 'custom_properties'),
            episode=KeyTransform('episode', 'custom_properties'),
            flag_new=KeyTransform('new', 'custom_properties'),
            flag_live=KeyTransform('live', 'custom_properties'),
            flag_premiere=KeyTransform('premiere', 'custom_properties'),
            premiere_text=KeyTransform('premiere_text', 'custom_properties'),
        )
        .values(
            'id', 'start_time', 'end_time', 'title', 'sub_title',
            'description', 'tvg_id',
            'season', 'episode',
            'flag_new', 'flag_live', 'flag_premiere', 'premiere_text',
        )
        .iterator(chunk_size=_GRID_DB_ITERATOR_CHUNK_SIZE)
    )
    for row in programs_qs:
        yield _program_value_to_dict(row)


def _iter_dummy_for_channels(
    channels, id_prefix, *, custom_source, lookback, cutoff, dummy_start, dummy_days
):
    """Yield on-demand dummy programs for a prepared channel list."""
    if custom_source:
        prefetch_streams_for_stream_named_sources(channels)

    for channel in channels:
        dummy_tvg_id = str(channel.uuid)
        effective_name = channel.effective_name
        if custom_source:
            epg = channel.effective_epg_data_obj
            epg_source = epg.epg_source if epg else None
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
        except Exception:
            logger.exception(
                "Error creating %s programs for channel %s (ID: %s)",
                id_prefix,
                channel.name,
                channel.id,
            )
            continue

        for program in generated or []:
            yield dummy_program_to_api_dict(
                channel,
                program,
                dummy_tvg_id=dummy_tvg_id,
                program_id_prefix=id_prefix,
            )


def _encode_program_batch(programs, *, first):
    """JSON-encode *programs* as array elements for the streamed ``data`` list.

    Encodes the whole batch in one ``json.dumps`` call (then strips the list
    brackets) so clients still receive the same compact JSON document as
    per-object encoding, without a dumps-per-row tax.
    """
    if not programs:
        return b'', first

    encoded = json.dumps(programs, cls=DjangoJSONEncoder, separators=(',', ':'))
    # encoded is "[...]" ; strip brackets to splice into the outer data array.
    body = encoded[1:-1].encode('utf-8')
    if first:
        return body, False
    return b',' + body, False


def _iter_grid_json_chunks(
    lookback,
    cutoff,
    now,
    *,
    epg_ids,
    dummy_custom_channels,
    no_epg_channels,
):
    """Yield UTF-8 chunks of ``{"data":[...]}`` without buffering every program."""
    yield b'{"data":['

    first = True
    batch = []
    real_count = 0
    dummy_count = 0
    dummy_start, dummy_days = _dummy_generation_span(now, lookback, cutoff)

    try:
        for program in _iter_real_program_dicts(lookback, cutoff, epg_ids):
            batch.append(program)
            real_count += 1
            if len(batch) >= _GRID_JSON_YIELD_BATCH_SIZE:
                chunk, first = _encode_program_batch(batch, first=first)
                batch.clear()
                if chunk:
                    yield chunk

        for program in _iter_dummy_for_channels(
            dummy_custom_channels,
            'dummy-custom',
            custom_source=True,
            lookback=lookback,
            cutoff=cutoff,
            dummy_start=dummy_start,
            dummy_days=dummy_days,
        ):
            batch.append(program)
            dummy_count += 1
            if len(batch) >= _GRID_JSON_YIELD_BATCH_SIZE:
                chunk, first = _encode_program_batch(batch, first=first)
                batch.clear()
                if chunk:
                    yield chunk

        for program in _iter_dummy_for_channels(
            no_epg_channels,
            'dummy-standard',
            custom_source=False,
            lookback=lookback,
            cutoff=cutoff,
            dummy_start=dummy_start,
            dummy_days=dummy_days,
        ):
            batch.append(program)
            dummy_count += 1
            if len(batch) >= _GRID_JSON_YIELD_BATCH_SIZE:
                chunk, first = _encode_program_batch(batch, first=first)
                batch.clear()
                if chunk:
                    yield chunk

        if batch:
            chunk, first = _encode_program_batch(batch, first=first)
            batch.clear()
            if chunk:
                yield chunk

        yield b']}'
        logger.debug(
            "EPGGridAPIView: Streamed %s total programs "
            "(including %s dummy programs).",
            real_count + dummy_count,
            dummy_count,
        )
    finally:
        # Trim after the payload has been produced. Connection cleanup is left
        # to the normal request teardown so test clients can keep using the DB
        # after consuming streaming_content.
        spawn_memory_trim()


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
            "Retrieve programs overlapping a time window for channels the "
            "caller can see. With no query parameters the window is the "
            "previous hour through the next 24 hours (recently ended, "
            "currently airing, and upcoming). "
            "Use ``days``/``prev_days`` for XMLTV-style relative offsets, "
            "or ``start``/``end`` (ISO 8601) for an explicit range. "
            "Optional ``channel_profile_id`` limits output to that profile "
            "(default: all channels the user may access). EPG assignments "
            "honor channel overrides."
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
            OpenApiParameter(
                'channel_profile_id',
                OpenApiTypes.INT,
                description=(
                    "Limit programmes to channels enabled in this profile. "
                    "Omitted or ``all``: every non-hidden channel the caller "
                    "may access (same default as the TV Guide)."
                ),
            ),
        ],
        responses={200: EPGGridResponseSerializer},
    )
    def get(self, request, format=None):
        now = timezone.now()
        try:
            lookback, cutoff = _resolve_epg_grid_window(request, now=now)
            profile_id = _parse_channel_profile_id(request.query_params)
        except GridWindowError as exc:
            return Response(
                {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        epg_ids, dummy_custom, no_epg = _partition_visible_channels(
            _visible_channels_queryset(request.user, profile_id)
        )

        logger.debug(
            "EPGGridAPIView: Querying programs between %s and %s "
            "(profile=%s, epg_rows=%s, dummy_custom=%s, no_epg=%s).",
            lookback,
            cutoff,
            profile_id if profile_id is not None else 'all',
            len(epg_ids),
            len(dummy_custom),
            len(no_epg),
        )

        return StreamingHttpResponse(
            _iter_grid_json_chunks(
                lookback,
                cutoff,
                now,
                epg_ids=epg_ids,
                dummy_custom_channels=dummy_custom,
                no_epg_channels=no_epg,
            ),
            content_type='application/json',
            status=status.HTTP_200_OK,
        )
