import logging
import os
import re
import time
from rest_framework import viewsets, status, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.epg.sd_api import (
    SchedulesDirectPosterMixin,
    SchedulesDirectSourceMixin,
)
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer
from drf_spectacular.types import OpenApiTypes
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from .models import EPGSource, ProgramData, EPGData
from .serializers import (
    ProgramDataSerializer,
    ProgramDetailSerializer,
    EPGSourceSerializer,
    EPGDataSerializer,
    ProgramSearchResultSerializer,
)
from .tasks import refresh_epg_data, find_current_program_for_tvg_id
from .query_utils import parse_text_query
from apps.accounts.permissions import (
    Authenticated,
    IsAdmin,
    IsStandardUser,
    permission_classes_by_action,
    permission_classes_by_method,
)
from core.utils import safe_upload_path

logger = logging.getLogger(__name__)


# ─────────────────────────────
# 1) EPG Source API (CRUD)
# ─────────────────────────────
class EPGSourceViewSet(SchedulesDirectSourceMixin, viewsets.ModelViewSet):
    """
    API endpoint that allows EPG sources to be viewed or edited.
    """

    queryset = EPGSource.objects.select_related(
        "refresh_task__crontab", "refresh_task__interval"
    ).all()
    serializer_class = EPGSourceSerializer

    def get_permissions(self):
        if self.action == "upload":
            return [IsAdmin()]
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            if self.action in ('sd_lineups', 'sd_lineups_search'):
                if self.request.method == 'GET':
                    return [IsStandardUser()]
                return [IsAdmin()]
            return [IsAdmin()]

    def get_queryset(self):
        from django.db.models import Exists, OuterRef
        from apps.channels.models import Channel
        return EPGSource.objects.select_related(
            "refresh_task__crontab", "refresh_task__interval"
        ).annotate(
            has_channels=Exists(
                Channel.objects.filter(epg_data__epg_source_id=OuterRef('pk'))
            )
        )

    def list(self, request, *args, **kwargs):
        logger.debug("Listing all EPG sources.")
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["post"])
    def upload(self, request):
        if "file" not in request.FILES:
            return Response(
                {"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES["file"]
        try:
            file_path = safe_upload_path(file.name, "/data/uploads/epgs")
        except ValueError:
            return Response(
                {"error": "Invalid filename"}, status=status.HTTP_400_BAD_REQUEST
            )

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb+") as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        new_obj_data = request.data.copy()
        new_obj_data["file_path"] = file_path

        serializer = self.get_serializer(data=new_obj_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        """Handle partial updates with special logic for is_active field"""
        instance = self.get_object()

        # Check if we're toggling is_active
        if (
            "is_active" in request.data
            and instance.is_active != request.data["is_active"]
        ):
            # Set appropriate status based on new is_active value
            if request.data["is_active"]:
                request.data["status"] = "idle"
            else:
                request.data["status"] = "disabled"

        # Continue with regular partial update
        return super().partial_update(request, *args, **kwargs)


class ProgramSearchPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class ProgramViewSet(SchedulesDirectPosterMixin, viewsets.ModelViewSet):
    """Handles CRUD operations for EPG programs"""

    queryset = ProgramData.objects.select_related("epg").all()
    serializer_class = ProgramDataSerializer

    # Short process-local cooldown for transient poster errors (auth/network).
    # Image download limits are persisted on the EPG source (shared across workers).

    def get_permissions(self):
        if self.action == 'poster':
            return [AllowAny()]
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProgramDetailSerializer
        return ProgramDataSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def list(self, request, *args, **kwargs):
        logger.debug("Listing all EPG programs.")
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Search EPG programs",
        description="""
**Advanced EPG program search with multiple filter types and complex query support.**

### Text Search Features

**Title and Description Search**:
- Supports AND/OR logical operators (case-insensitive: `and`/`AND` both work)
- Wrap phrases in double quotes to match them literally: `"Law and Order"`
- Parenthetical grouping for complex queries: `(Newcastle OR NEW) AND (Villa OR AST)`
- Regex pattern matching with `title_regex=true` (evaluated by the database engine)
- Whole word matching with `title_whole_words=true` to avoid partial matches

**Examples**:
- Simple: `title=football`
- AND operator: `title=premier AND league`
- OR operator: `title=Newcastle OR Villa`
- Quoted phrase: `title="Law and Order"` (matches the exact phrase; 'and' is literal)
- Mixed: `title="Law and Order" AND crime`
- Nested groups: `title=(Newcastle OR NEW) AND (Villa OR AST)`
- Regex: `title=^Premier&title_regex=true` (programs starting with "Premier")
- Whole words: `title=NEW&title_whole_words=true` (matches "NEW" but not "News")

### Time Filtering

**airing_at**: Find programs airing at a specific moment (start_time ≤ airing_at < end_time)

**Time ranges**: Use combinations of start_after, start_before, end_after, end_before

### Response Customization

**fields**: Comma-separated list to include only specific fields in response
- Available: id, title, sub_title, description, start_time, end_time, tvg_id, custom_properties, epg_source, epg_name, epg_icon_url, channels, streams

### Pagination

- Default: 50 results per page
- Maximum: 500 results per page
- Use `page` and `page_size` parameters to navigate results
        """,
        parameters=[
            OpenApiParameter(
                'title',
                OpenApiTypes.STR,
                description='Title search query. Supports AND/OR operators (case-insensitive), quoted phrases, and parentheses. Double-quote a phrase to match it literally: `"Law and Order"`. Unquoted space-separated terms are matched as a phrase; use AND/OR to combine separate terms.',
            ),
            OpenApiParameter('title_regex', OpenApiTypes.BOOL, description='Enable regex matching for title (case-insensitive, default: false). e.g. `^The` matches titles starting with "The".'),
            OpenApiParameter('title_whole_words', OpenApiTypes.BOOL, description='Match whole words only in title (default: false). e.g. `new` matches "Newcastle" normally but not with whole words enabled.'),
            OpenApiParameter(
                'description',
                OpenApiTypes.STR,
                description='Description search query. Same syntax and features as title search.'
            ),
            OpenApiParameter('description_regex', OpenApiTypes.BOOL, description='Enable regex matching for description (case-insensitive, default: false).'),
            OpenApiParameter('description_whole_words', OpenApiTypes.BOOL, description='Match whole words only in description (default: false). Same behaviour as title_whole_words.'),
            OpenApiParameter('start_after', OpenApiTypes.DATETIME, description='Filter programs starting at or after this time. ISO 8601 format, e.g. `2026-02-14T18:00:00Z`.'),
            OpenApiParameter('start_before', OpenApiTypes.DATETIME, description='Filter programs starting at or before this time. ISO 8601 format.'),
            OpenApiParameter('end_after', OpenApiTypes.DATETIME, description='Filter programs ending at or after this time. ISO 8601 format.'),
            OpenApiParameter('end_before', OpenApiTypes.DATETIME, description='Filter programs ending at or before this time. ISO 8601 format.'),
            OpenApiParameter('airing_at', OpenApiTypes.DATETIME, description='Find programs airing at this exact moment (start_time ≤ airing_at < end_time). ISO 8601 format, e.g. `2026-02-14T20:00:00Z`.'),
            OpenApiParameter('channel', OpenApiTypes.STR, description='Filter by channel name (case-insensitive substring match). e.g. `BBC One`, `Sky Sports`.'),
            OpenApiParameter('channel_id', OpenApiTypes.INT, description='Filter by exact channel ID.'),
            OpenApiParameter('tvg_id', OpenApiTypes.STR, description='Filter by EPG tvg_id (exact match). e.g. `bbcone.uk`.'),
            OpenApiParameter('stream', OpenApiTypes.STR, description='Filter by stream name (case-insensitive substring match).'),
            OpenApiParameter('group', OpenApiTypes.STR, description='Filter by channel group or stream group name (case-insensitive substring match). e.g. `Sports`, `UK Channels`.'),
            OpenApiParameter('epg_source', OpenApiTypes.INT, description='Filter by EPG source ID.'),
            OpenApiParameter('fields', OpenApiTypes.STR, description='Comma-separated list of fields to include. Omit to return all fields. e.g. `title,start_time,end_time`.'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number for pagination (default: 1).'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page (default: 50, max: 500).'),
        ],
        responses={200: ProgramSearchResultSerializer(many=True)},
        tags=['EPG'],
    )
    @action(detail=False, methods=['get'], url_path='search', permission_classes=[IsStandardUser])
    def search(self, request):
        params = request.query_params

        # Build base queryset with prefetching
        queryset = ProgramData.objects.select_related(
            'epg', 'epg__epg_source'
        ).prefetch_related(
            'epg__channels', 'epg__channels__channel_group',
            'epg__channels__streams', 'epg__channels__streams__channel_group',
            'epg__channels__streams__m3u_account',
        )

        filters = Q()

        # Text filters
        title = params.get('title')
        if title:
            title_regex = params.get('title_regex', '').lower() in ('true', '1', 'yes')
            title_whole_words = params.get('title_whole_words', '').lower() in ('true', '1', 'yes')
            filters &= parse_text_query('title', title, use_regex=title_regex, whole_words=title_whole_words)

        description = params.get('description')
        if description:
            desc_regex = params.get('description_regex', '').lower() in ('true', '1', 'yes')
            desc_whole_words = params.get('description_whole_words', '').lower() in ('true', '1', 'yes')
            filters &= parse_text_query('description', description, use_regex=desc_regex, whole_words=desc_whole_words)

        # Time filters with validation
        start_after = params.get('start_after')
        if start_after:
            dt = parse_datetime(start_after)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for start_after: {start_after}. Use ISO 8601 format (e.g., 2026-02-14T18:00:00Z)"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(start_time__gte=dt)

        start_before = params.get('start_before')
        if start_before:
            dt = parse_datetime(start_before)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for start_before: {start_before}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(start_time__lte=dt)

        end_after = params.get('end_after')
        if end_after:
            dt = parse_datetime(end_after)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for end_after: {end_after}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(end_time__gte=dt)

        end_before = params.get('end_before')
        if end_before:
            dt = parse_datetime(end_before)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for end_before: {end_before}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(end_time__lte=dt)

        airing_at = params.get('airing_at')
        if airing_at:
            dt = parse_datetime(airing_at)
            if dt is None:
                return Response(
                    {"error": f"Invalid datetime format for airing_at: {airing_at}. Use ISO 8601 format."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            filters &= Q(start_time__lte=dt, end_time__gt=dt)

        # Channel/stream filters
        channel = params.get('channel')
        if channel:
            filters &= Q(epg__channels__name__icontains=channel)

        channel_id = params.get('channel_id')
        if channel_id:
            try:
                filters &= Q(epg__channels__id=int(channel_id))
            except (ValueError, TypeError):
                pass

        tvg_id = params.get('tvg_id')
        if tvg_id:
            filters &= Q(epg__tvg_id=tvg_id)

        stream = params.get('stream')
        if stream:
            filters &= Q(epg__channels__streams__name__icontains=stream)

        group = params.get('group')
        if group:
            filters &= (
                Q(epg__channels__channel_group__name__icontains=group)
                | Q(epg__channels__streams__channel_group__name__icontains=group)
            )

        epg_source = params.get('epg_source')
        if epg_source:
            try:
                filters &= Q(epg__epg_source__id=int(epg_source))
            except (ValueError, TypeError):
                pass

        queryset = queryset.filter(filters).distinct().order_by('start_time')

        # Restrict results to programs on channels the user can access
        user = request.user
        if user.user_level < 10:
            access_filter = Q(epg__channels__user_level__lte=user.user_level)
            custom_props = user.custom_properties or {}
            if custom_props.get('hide_adult_content', False):
                access_filter &= Q(epg__channels__is_adult=False)
            queryset = queryset.filter(access_filter).distinct()

        # Resolve field selection before serialization so expensive methods can short-circuit
        requested_fields = params.get('fields')
        allowed = set(f.strip() for f in requested_fields.split(',')) if requested_fields else None

        # Paginate
        paginator = ProgramSearchPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProgramSearchResultSerializer(page, many=True, context={'fields': allowed, 'user': request.user})
        data = serializer.data

        if allowed:
            data = [{k: v for k, v in item.items() if k in allowed} for item in data]

        return paginator.get_paginated_response(data)


# ─────────────────────────────
# 3) EPG Grid View
# ─────────────────────────────
def custom_dummy_channels_queryset():
    """Channels backed by a dummy EPG source, ready for on-demand generation.

    Streams are prefetched in channelstream order because dummy sources configured
    with name_source='stream' resolve their regex input by stream index; without the
    explicit ordering the prefetch cache would fall back to Stream's own ordering
    and pick the wrong title.
    """
    from apps.channels.models import Channel, Stream
    from apps.channels.managers import with_effective_values

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


class EPGGridAPIView(APIView):
    """Returns all programs airing in the next 24 hours including currently running ones and recent ones"""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Retrieve programs from the previous hour, currently running and upcoming for the next 24 hours",
        responses={200: ProgramDataSerializer(many=True)},
    )
    def get(self, request, format=None):
        # Use current time instead of midnight
        now = timezone.now()
        one_hour_ago = now - timedelta(hours=1)
        twenty_four_hours_later = now + timedelta(hours=24)
        logger.debug(
            f"EPGGridAPIView: Querying programs between {one_hour_ago} and {twenty_four_hours_later}."
        )

        programs = ProgramData.objects.filter(
            end_time__gt=one_hour_ago,
            start_time__lt=twenty_four_hours_later,
        )

        # Generate dummy programs for channels that have no EPG data OR dummy EPG sources
        from apps.channels.models import Channel
        from apps.channels.managers import with_effective_values

        # Get channels with no EPG data at all (standard dummy)
        channels_without_epg = with_effective_values(
            Channel.objects.filter(epg_data__isnull=True)
        )
        channels_with_custom_dummy = custom_dummy_channels_queryset()

        # Serialize the regular programs using .values() to bypass DRF overhead
        programs_qs = programs.values(
            'id', 'start_time', 'end_time', 'title', 'sub_title',
            'description', 'tvg_id', 'custom_properties',
        )
        serialized_programs = []
        for p in programs_qs:
            cp = p['custom_properties'] or {}
            premiere_text = cp.get('premiere_text', '')
            serialized_programs.append({
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
        logger.debug(
            f"EPGGridAPIView: Found {len(serialized_programs)} program(s), including recently ended, currently running, and upcoming shows."
        )

        # Generate and append dummy programs for channels without real EPG data.
        from apps.output.dummy_epg import (
            dummy_program_to_api_dict,
            generate_dummy_programs,
            resolve_channel_parse_name,
        )

        dummy_programs = []

        for queryset, id_prefix, custom_source in (
            (channels_with_custom_dummy, 'dummy-custom', True),
            (channels_without_epg, 'dummy-standard', False),
        ):
            for channel in queryset:
                dummy_tvg_id = str(channel.uuid)
                effective_name = channel.effective_name
                if custom_source:
                    epg_source = channel.epg_data.epg_source if channel.epg_data else None
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
                        num_days=1,
                        program_length_hours=4,
                        epg_source=epg_source,
                        export_lookback=one_hour_ago,
                        export_cutoff=twenty_four_hours_later,
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
                except Exception as e:
                    logger.error(
                        "Error creating %s programs for channel %s (ID: %s): %s",
                        id_prefix,
                        channel.name,
                        channel.id,
                        e,
                    )

        # Combine regular and dummy programs in place to avoid copying the large list
        serialized_programs.extend(dummy_programs)
        logger.debug(
            f"EPGGridAPIView: Returning {len(serialized_programs)} total programs (including {len(dummy_programs)} dummy programs)."
        )

        # The grid materializes tens of thousands of program dicts plus the
        # rendered JSON; trim once the response is sent so worker RSS does not
        # ratchet up per request.
        from core.utils import spawn_memory_trim
        response = Response({"data": serialized_programs}, status=status.HTTP_200_OK)
        response._resource_closers.append(spawn_memory_trim)
        return response


# ─────────────────────────────
# 4) EPG Import View
# ─────────────────────────────
class EPGImportAPIView(APIView):
    """Triggers an EPG data refresh"""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Triggers an EPG data refresh for the given source.",
        request=inline_serializer(
            name="EPGImportRequest",
            fields={
                "id": serializers.IntegerField(help_text="ID of the EPG source to refresh."),
            },
        ),
    )
    def post(self, request, format=None):
        logger.info("EPGImportAPIView: Received request to import EPG data.")
        epg_id = request.data.get("id", None)
        force = bool(request.data.get("force", False))

        # Reject dummy sources with a narrow existence query, no full row load.
        if epg_id is not None:
            from .models import EPGSource

            if EPGSource.objects.filter(
                id=epg_id, source_type="dummy"
            ).exists():
                logger.info(
                    "EPGImportAPIView: Skipping refresh for dummy EPG source %s",
                    epg_id,
                )
                return Response(
                    {
                        "success": False,
                        "message": "Dummy EPG sources do not require refreshing.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        refresh_epg_data.delay(epg_id, force=force)  # Trigger Celery task
        logger.info("EPGImportAPIView: Task dispatched to refresh EPG data.")
        return Response(
            {"success": True, "message": "EPG data refresh initiated."},
            status=status.HTTP_202_ACCEPTED,
        )


# ─────────────────────────────
# 5) EPG Data View
# ─────────────────────────────
class EPGDataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows EPGData objects to be viewed.
    """

    queryset = EPGData.objects.all()
    serializer_class = EPGDataSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]


# ─────────────────────────────
# 6) Current Programs API
# ─────────────────────────────
class CurrentProgramsAPIView(APIView):
    """
    Lightweight endpoint that returns currently playing programs for specified channel IDs.
    Accepts POST with JSON body containing channel_ids array, or null/empty to fetch all channels.
    """

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Get currently playing programs for specified channels or all channels",
        request=inline_serializer(
            name="CurrentProgramsRequest",
            fields={
                "channel_uuids": serializers.ListField(
                    child=serializers.CharField(),
                    required=False,
                    allow_null=True,
                    help_text="Array of channel UUIDs. If null or omitted, returns all channels with current programs.",
                ),
                "epg_data_ids": serializers.ListField(
                    child=serializers.IntegerField(),
                    required=False,
                    allow_null=True,
                    help_text="Array of EPG data IDs. Can be used instead of channel_ids.",
                ),
            },
        ),
        responses={200: ProgramDataSerializer(many=True)},
    )
    def post(self, request, format=None):
        # Get IDs from request body
        channel_uuids = request.data.get('channel_uuids', None)
        epg_data_ids = request.data.get('epg_data_ids', None)

        # Validate that at most one type of ID is provided
        if channel_uuids is not None and epg_data_ids is not None:
            return Response(
                {"error": "Provide either channel_uuids or epg_data_ids, not both"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get current time
        now = timezone.now()

        # If epg_data_ids are provided, query directly by EPG data
        if epg_data_ids is not None:
            if not isinstance(epg_data_ids, list):
                return Response(
                    {"error": "epg_data_ids must be an array of integers or null"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                epg_data_ids = [int(eid) for eid in epg_data_ids]
            except (ValueError, TypeError):
                return Response(
                    {"error": "epg_data_ids must contain valid integers"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Limit to 50 IDs per request
            epg_data_ids = epg_data_ids[:50]

            epg_data_entries = EPGData.objects.select_related('epg_source').filter(
                id__in=epg_data_ids
            )

            # Batch-fetch current programs for all requested EPG entries in one query
            db_programs = ProgramData.objects.filter(
                epg__in=epg_data_entries, start_time__lte=now, end_time__gt=now
            ).select_related('epg')
            # Map epg_data id -> first matching program
            programs_by_epg = {}
            for prog in db_programs:
                if prog.epg_id not in programs_by_epg:
                    programs_by_epg[prog.epg_id] = prog

            current_programs = []
            for epg_data in epg_data_entries:
                # Check batch-fetched DB results first
                program = programs_by_epg.get(epg_data.id)

                if program:
                    program_data = ProgramDataSerializer(program).data
                    program_data['epg_data_id'] = epg_data.id
                    current_programs.append(program_data)
                    continue

                # Skip dummy sources
                if epg_data.epg_source and epg_data.epg_source.source_type == 'dummy':
                    continue

                # Fall back to byte-offset index lookup, pass the object to avoid re-fetch
                result = find_current_program_for_tvg_id(epg_data)

                if result == "timeout":
                    current_programs.append({
                        "epg_data_id": epg_data.id,
                        "parsing": True,
                    })
                elif result is not None:
                    result['epg_data_id'] = epg_data.id
                    current_programs.append(result)

            return Response(current_programs, status=status.HTTP_200_OK)

        # Otherwise, use channel-based query. Honour ChannelOverride.epg_data
        # via Coalesce; filtering on Channel.epg_data alone skips override-only
        # assignments (editor Current Program uses epg_data_ids and is fine).
        from django.db.models.functions import Coalesce
        from apps.channels.models import Channel

        query = Channel.objects.annotate(
            effective_epg_data_id=Coalesce("override__epg_data_id", "epg_data_id"),
        ).exclude(effective_epg_data_id__isnull=True)

        if channel_uuids is not None:
            if not isinstance(channel_uuids, list):
                return Response(
                    {"error": "channel_uuids must be an array of strings or null"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            query = query.filter(uuid__in=channel_uuids)

        current_programs = []

        for channel in query:
            program = ProgramData.objects.select_related("epg").filter(
                epg_id=channel.effective_epg_data_id,
                start_time__lte=now,
                end_time__gt=now
            ).first()

            if program:
                program_data = ProgramDataSerializer(program).data
                program_data['channel_uuid'] = str(channel.uuid)
                current_programs.append(program_data)


        return Response(current_programs, status=status.HTTP_200_OK)
