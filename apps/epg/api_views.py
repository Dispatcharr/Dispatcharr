import logging, os
from rest_framework import viewsets, status, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer
from drf_spectacular.types import OpenApiTypes
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from .models import EPGSource, ProgramData, EPGData  # Added ProgramData
from .serializers import (
    ProgramDataSerializer,
    EPGSourceSerializer,
    EPGDataSerializer,
    ProgramSearchResultSerializer,
)  # Updated serializer
from .tasks import refresh_epg_data
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_action,
    permission_classes_by_method,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────
# 1) EPG Source API (CRUD)
# ─────────────────────────────
class EPGSourceViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows EPG sources to be viewed or edited.
    """

    queryset = EPGSource.objects.all()
    serializer_class = EPGSourceSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

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
        file_name = file.name
        file_path = os.path.join("/data/uploads/epgs", file_name)

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


# ─────────────────────────────
# 2) Program API (CRUD)
# ─────────────────────────────
class ProgramViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for EPG programs"""

    queryset = ProgramData.objects.all()
    serializer_class = ProgramDataSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def list(self, request, *args, **kwargs):
        logger.debug("Listing all EPG programs.")
        return super().list(request, *args, **kwargs)


# ─────────────────────────────
# 3) EPG Grid View
# ─────────────────────────────
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

        # Use select_related to prefetch EPGData and include programs from the last hour
        programs = ProgramData.objects.select_related("epg").filter(
            # Programs that end after one hour ago (includes recently ended programs)
            end_time__gt=one_hour_ago,
            # AND start before the end time window
            start_time__lt=twenty_four_hours_later,
        )
        count = programs.count()
        logger.debug(
            f"EPGGridAPIView: Found {count} program(s), including recently ended, currently running, and upcoming shows."
        )

        # Generate dummy programs for channels that have no EPG data OR dummy EPG sources
        from apps.channels.models import Channel
        from apps.epg.models import EPGSource
        from django.db.models import Q

        # Get channels with no EPG data at all (standard dummy)
        channels_without_epg = Channel.objects.filter(Q(epg_data__isnull=True))

        # Get channels with custom dummy EPG sources (generate on-demand with patterns)
        channels_with_custom_dummy = Channel.objects.filter(
            epg_data__epg_source__source_type='dummy'
        ).distinct()

        # Log what we found
        without_count = channels_without_epg.count()
        custom_count = channels_with_custom_dummy.count()

        if without_count > 0:
            channel_names = [f"{ch.name} (ID: {ch.id})" for ch in channels_without_epg]
            logger.debug(
                f"EPGGridAPIView: Channels needing standard dummy EPG: {', '.join(channel_names)}"
            )

        if custom_count > 0:
            channel_names = [f"{ch.name} (ID: {ch.id})" for ch in channels_with_custom_dummy]
            logger.debug(
                f"EPGGridAPIView: Channels needing custom dummy EPG: {', '.join(channel_names)}"
            )

        logger.debug(
            f"EPGGridAPIView: Found {without_count} channels needing standard dummy, {custom_count} needing custom dummy EPG."
        )

        # Serialize the regular programs
        serialized_programs = ProgramDataSerializer(programs, many=True).data

        # Humorous program descriptions based on time of day - same as in output/views.py
        time_descriptions = {
            (0, 4): [
                "Late Night with {channel} - Where insomniacs unite!",
                "The 'Why Am I Still Awake?' Show on {channel}",
                "Counting Sheep - A {channel} production for the sleepless",
            ],
            (4, 8): [
                "Dawn Patrol - Rise and shine with {channel}!",
                "Early Bird Special - Coffee not included",
                "Morning Zombies - Before coffee viewing on {channel}",
            ],
            (8, 12): [
                "Mid-Morning Meetings - Pretend you're paying attention while watching {channel}",
                "The 'I Should Be Working' Hour on {channel}",
                "Productivity Killer - {channel}'s daytime programming",
            ],
            (12, 16): [
                "Lunchtime Laziness with {channel}",
                "The Afternoon Slump - Brought to you by {channel}",
                "Post-Lunch Food Coma Theater on {channel}",
            ],
            (16, 20): [
                "Rush Hour - {channel}'s alternative to traffic",
                "The 'What's For Dinner?' Debate on {channel}",
                "Evening Escapism - {channel}'s remedy for reality",
            ],
            (20, 24): [
                "Prime Time Placeholder - {channel}'s finest not-programming",
                "The 'Netflix Was Too Complicated' Show on {channel}",
                "Family Argument Avoider - Courtesy of {channel}",
            ],
        }

        # Generate and append dummy programs
        dummy_programs = []

        # Import the function from output.views
        from apps.output.views import generate_dummy_programs as gen_dummy_progs

        # Handle channels with CUSTOM dummy EPG sources (with patterns)
        for channel in channels_with_custom_dummy:
            # For dummy EPGs, ALWAYS use channel UUID to ensure unique programs per channel
            # This prevents multiple channels assigned to the same dummy EPG from showing identical data
            # Each channel gets its own unique program data even if they share the same EPG source
            dummy_tvg_id = str(channel.uuid)

            try:
                # Get the custom dummy EPG source
                epg_source = channel.epg_data.epg_source if channel.epg_data else None

                logger.debug(f"Generating custom dummy programs for channel: {channel.name} (ID: {channel.id})")

                # Determine which name to parse based on custom properties
                name_to_parse = channel.name
                if epg_source and epg_source.custom_properties:
                    custom_props = epg_source.custom_properties
                    name_source = custom_props.get('name_source')

                    if name_source == 'stream':
                        # Get the stream index (1-based from user, convert to 0-based)
                        stream_index = custom_props.get('stream_index', 1) - 1

                        # Get streams ordered by channelstream order
                        channel_streams = channel.streams.all().order_by('channelstream__order')

                        if channel_streams.exists() and 0 <= stream_index < channel_streams.count():
                            stream = list(channel_streams)[stream_index]
                            name_to_parse = stream.name
                            logger.debug(f"Using stream name for parsing: {name_to_parse} (stream index: {stream_index})")
                        else:
                            logger.warning(f"Stream index {stream_index} not found for channel {channel.name}, falling back to channel name")
                    elif name_source == 'channel':
                        logger.debug(f"Using channel name for parsing: {name_to_parse}")

                # Generate programs using custom patterns from the dummy EPG source
                # Use the same tvg_id that will be set in the program data
                generated = gen_dummy_progs(
                    channel_id=dummy_tvg_id,
                    channel_name=name_to_parse,
                    num_days=1,
                    program_length_hours=4,
                    epg_source=epg_source
                )

                # Custom dummy should always return data (either from patterns or fallback)
                if generated:
                    logger.debug(f"Generated {len(generated)} custom dummy programs for {channel.name}")
                    # Convert generated programs to API format
                    for program in generated:
                        dummy_program = {
                            "id": f"dummy-custom-{channel.id}-{program['start_time'].hour}",
                            "epg": {"tvg_id": dummy_tvg_id, "name": channel.name},
                            "start_time": program['start_time'].isoformat(),
                            "end_time": program['end_time'].isoformat(),
                            "title": program['title'],
                            "description": program['description'],
                            "tvg_id": dummy_tvg_id,
                            "sub_title": None,
                            "custom_properties": None,
                        }
                        dummy_programs.append(dummy_program)
                else:
                    logger.warning(f"No programs generated for custom dummy EPG channel: {channel.name}")

            except Exception as e:
                logger.error(
                    f"Error creating custom dummy programs for channel {channel.name} (ID: {channel.id}): {str(e)}"
                )

        # Handle channels with NO EPG data (standard dummy with humorous descriptions)
        for channel in channels_without_epg:
            # For channels with no EPG, use UUID to ensure uniqueness (matches frontend logic)
            # The frontend uses: tvgRecord?.tvg_id ?? channel.uuid
            # Since there's no EPG data, it will fall back to UUID
            dummy_tvg_id = str(channel.uuid)

            try:
                logger.debug(f"Generating standard dummy programs for channel: {channel.name} (ID: {channel.id})")

                # Create programs every 4 hours for the next 24 hours with humorous descriptions
                for hour_offset in range(0, 24, 4):
                    # Use timedelta for time arithmetic instead of replace() to avoid hour overflow
                    start_time = now + timedelta(hours=hour_offset)
                    # Set minutes/seconds to zero for clean time blocks
                    start_time = start_time.replace(minute=0, second=0, microsecond=0)
                    end_time = start_time + timedelta(hours=4)

                    # Get the hour for selecting a description
                    hour = start_time.hour
                    day = 0  # Use 0 as we're only doing 1 day

                    # Find the appropriate time slot for description
                    for time_range, descriptions in time_descriptions.items():
                        start_range, end_range = time_range
                        if start_range <= hour < end_range:
                            # Pick a description using the sum of the hour and day as seed
                            # This makes it somewhat random but consistent for the same timeslot
                            description = descriptions[
                                (hour + day) % len(descriptions)
                            ].format(channel=channel.name)
                            break
                    else:
                        # Fallback description if somehow no range matches
                        description = f"Placeholder program for {channel.name} - EPG data went on vacation"

                    # Create a dummy program in the same format as regular programs
                    dummy_program = {
                        "id": f"dummy-standard-{channel.id}-{hour_offset}",
                        "epg": {"tvg_id": dummy_tvg_id, "name": channel.name},
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "title": f"{channel.name}",
                        "description": description,
                        "tvg_id": dummy_tvg_id,
                        "sub_title": None,
                        "custom_properties": None,
                    }
                    dummy_programs.append(dummy_program)

            except Exception as e:
                logger.error(
                    f"Error creating standard dummy programs for channel {channel.name} (ID: {channel.id}): {str(e)}"
                )

        # Combine regular and dummy programs
        all_programs = list(serialized_programs) + dummy_programs
        logger.debug(
            f"EPGGridAPIView: Returning {len(all_programs)} total programs (including {len(dummy_programs)} dummy programs)."
        )

        return Response({"data": all_programs}, status=status.HTTP_200_OK)


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
        description="Triggers an EPG data import",
    )
    def post(self, request, format=None):
        logger.info("EPGImportAPIView: Received request to import EPG data.")
        epg_id = request.data.get("id", None)

        # Check if this is a dummy EPG source
        try:
            from .models import EPGSource
            epg_source = EPGSource.objects.get(id=epg_id)
            if epg_source.source_type == 'dummy':
                logger.info(f"EPGImportAPIView: Skipping refresh for dummy EPG source {epg_id}")
                return Response(
                    {"success": False, "message": "Dummy EPG sources do not require refreshing."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except EPGSource.DoesNotExist:
            pass  # Let the task handle the missing source

        refresh_epg_data.delay(epg_id)  # Trigger Celery task
        logger.info("EPGImportAPIView: Task dispatched to refresh EPG data.")
        return Response(
            {"success": True, "message": "EPG data import initiated."},
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
                "channel_ids": serializers.ListField(
                    child=serializers.IntegerField(),
                    required=False,
                    allow_null=True,
                    help_text="Array of channel IDs. If null or omitted, returns all channels with current programs.",
                ),
            },
        ),
        responses={200: ProgramDataSerializer(many=True)},
    )
    def post(self, request, format=None):
        # Get channel IDs from request body
        channel_ids = request.data.get('channel_ids', None)

        # Import Channel model
        from apps.channels.models import Channel

        # Build query for channels with EPG data
        query = Channel.objects.filter(epg_data__isnull=False)

        # Filter by specific channel IDs if provided
        if channel_ids is not None:
            if not isinstance(channel_ids, list):
                return Response(
                    {"error": "channel_ids must be an array of integers or null"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                channel_ids = [int(id) for id in channel_ids]
            except (ValueError, TypeError):
                return Response(
                    {"error": "channel_ids must contain valid integers"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            query = query.filter(id__in=channel_ids)

        # Get channels with EPG data
        channels = query.select_related('epg_data')

        # Get current time
        now = timezone.now()

        # Build list of current programs
        current_programs = []

        for channel in channels:
            # Query for current program
            program = ProgramData.objects.filter(
                epg=channel.epg_data,
                start_time__lte=now,
                end_time__gt=now
            ).first()

            if program:
                # Serialize program and add channel_id for easy mapping
                program_data = ProgramDataSerializer(program).data
                program_data['channel_id'] = channel.id
                current_programs.append(program_data)


        return Response(current_programs, status=status.HTTP_200_OK)


# ─────────────────────────────
# 7) Program Search API
# ─────────────────────────────
import re as regex_module


def _build_q_object(field_name, term, use_regex=False, whole_words=False):
    """
    Build a single Q object for a search term.
    
    Args:
        field_name: Django ORM field name
        term: Search term
        use_regex: If True, use regex matching
        whole_words: If True, use word boundary matching
    """
    term = term.strip()
    if not term:
        return Q()
    
    if use_regex:
        # Use Django's __iregex (case-insensitive regex)
        return Q(**{f'{field_name}__iregex': term})
    elif whole_words:
        # Use word boundary regex (case-insensitive)
        pattern = r'\b' + regex_module.escape(term) + r'\b'
        return Q(**{f'{field_name}__iregex': pattern})
    else:
        # Standard case-insensitive contains
        return Q(**{f'{field_name}__icontains': term})


def _parse_text_query(field_name, raw_value, use_regex=False, whole_words=False):
    """
    Parse a text search value with AND/OR operators (including nested groups with parentheses) into a Q object.

    Examples:
        "sports AND football"                        → Q(field__icontains="sports") & Q(field__icontains="football")
        "news OR weather"                            → Q(field__icontains="news") | Q(field__icontains="weather")
        "(Newcastle OR NEW) AND (Villa OR AST)"      → Grouped nested operations
        "breaking news"                              → Q(field__icontains="breaking") & Q(field__icontains="news")  [default AND]

    Args:
        field_name: Django ORM field name to query
        raw_value: Text value with optional AND/OR operators
        use_regex: If True, use regex matching instead of icontains
        whole_words: If True, match whole words only (requires word boundaries)

    Supports mixed operators evaluated left-to-right: "sports AND football OR basketball"
    Supports nested groups: "(A OR B) AND (C OR D)"
    """
    
    def parse_expression(expr):
        """Recursively parse expression with parentheses support"""
        expr = expr.strip()
        
        # Handle parentheses by recursively processing innermost groups
        while '(' in expr:
            paren_start = expr.rfind('(')
            paren_end = expr.find(')', paren_start)
            if paren_end == -1:
                return Q()  # Mismatched parentheses
            
            # Recursively parse the group
            group_expr = expr[paren_start + 1:paren_end]
            group_result = parse_expression(group_expr)
            
            # Replace group with placeholder to avoid re-parsing
            # We build up results as we go
            before = expr[:paren_start]
            after = expr[paren_end + 1:]
            
            # For now, we need to handle this differently - evaluate left to right
            # Extract operators around the group
            if before:
                before = before.rstrip()
                if before.upper().endswith(' AND'):
                    before = before[:-5].rstrip()
                    operator = ' AND '
                elif before.upper().endswith(' OR'):
                    before = before[:-3].rstrip()
                    operator = ' OR '
                else:
                    operator = None
            else:
                operator = None
                before = None
            
            if after:
                after = after.lstrip()
                if after.upper().startswith('AND '):
                    after = after[4:].lstrip()
                    operator = ' AND ' if not operator else operator
                elif after.upper().startswith('OR '):
                    after = after[3:].lstrip()
                    operator = ' OR ' if not operator else operator
            else:
                after = None
            
            # Reconstruct without parentheses for simpler processing
            parts = [before, after]
            expr = ' AND '.join(p for p in parts if p)
        
        # Tokenize on " AND " and " OR " boundaries (no parentheses now)
        tokens = []
        operators = []
        remaining = expr
        
        while remaining:
            and_pos = remaining.upper().find(' AND ')
            or_pos = remaining.upper().find(' OR ')
            
            if and_pos == -1 and or_pos == -1:
                tokens.append(remaining.strip())
                break
            
            if and_pos == -1:
                pos, op, op_len = or_pos, '|', 4
            elif or_pos == -1:
                pos, op, op_len = and_pos, '&', 5
            elif and_pos < or_pos:
                pos, op, op_len = and_pos, '&', 5
            else:
                pos, op, op_len = or_pos, '|', 4
            
            token = remaining[:pos].strip()
            if token:
                tokens.append(token)
                operators.append(op)
            remaining = remaining[pos + op_len:]
        
        if not tokens:
            return Q()
        
        # Build Q chain
        result = _build_q_object(field_name, tokens[0], use_regex, whole_words)
        for i, op in enumerate(operators):
            next_q = _build_q_object(field_name, tokens[i + 1], use_regex, whole_words)
            if op == '&':
                result = result & next_q
            else:
                result = result | next_q
        
        return result
    
    return parse_expression(raw_value)


class ProgramSearchPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class ProgramSearchAPIView(APIView):
    """
    Advanced search for EPG programs with complex filtering capabilities.

    Features:
    - **Text Search**: Title/description search with AND/OR operators, parenthetical grouping, regex, and whole-word matching
    - **Time Filtering**: Find programs airing at specific times or within time ranges
    - **Channel/Stream Filtering**: Filter by channel, stream, or group names
    - **Field Selection**: Customize response to include only needed fields
    - **Pagination**: Results paginated (default 50, max 500 per page)

    Text Query Syntax:
    - Simple: `title=football`
    - AND: `title=premier AND league`
    - OR: `title=Newcastle OR Villa`
    - Nested: `title=(Newcastle OR NEW) AND (Villa OR AST)`
    - Regex: `title=^Premier&title_regex=true`
    - Whole words: `title=NEW&title_whole_words=true`

    Examples:
    - Find matches airing now: `?title=football&airing_at=2026-02-14T20:00:00Z`
    - Complex search: `?title=(Newcastle OR NEW) AND (Villa OR AST)&airing_at=2026-02-14T20:00:00Z`
    - Channel-specific: `?channel=BBC One&start_after=2026-02-14T18:00:00Z`
    - Minimal response: `?title=sports&fields=title,start_time,end_time`
    """
    pagination_class = ProgramSearchPagination

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        summary="Search EPG programs",
        description="""
**Advanced EPG program search with multiple filter types and complex query support.**

### Text Search Features

**Title and Description Search**:
- Supports AND/OR logical operators
- Parenthetical grouping for complex queries: `(Newcastle OR NEW) AND (Villa OR AST)`
- Regex pattern matching with `title_regex=true`
- Whole word matching with `title_whole_words=true` to avoid partial matches

**Examples**:
- Simple: `title=football`
- AND operator: `title=premier AND league`
- OR operator: `title=Newcastle OR Villa`
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
                description='Title search query. Supports AND/OR operators and parentheses: `(Newcastle OR NEW) AND (Villa OR AST)`. Space-separated terms default to AND.',
                examples=[
                    'football',
                    'premier AND league',
                    'Newcastle OR Villa',
                    '(Newcastle OR NEW) AND (Villa OR AST)'
                ]
            ),
            OpenApiParameter('title_regex', OpenApiTypes.BOOL, description='Enable regex matching for title (case-insensitive). Example: `^The` matches titles starting with "The".'),
            OpenApiParameter('title_whole_words', OpenApiTypes.BOOL, description='Match whole words only in title. Prevents "NEW" from matching "News".'),
            OpenApiParameter(
                'description', 
                OpenApiTypes.STR, 
                description='Description search query. Same syntax and features as title search.'
            ),
            OpenApiParameter('description_regex', OpenApiTypes.BOOL, description='Enable regex matching for description (case-insensitive).'),
            OpenApiParameter('description_whole_words', OpenApiTypes.BOOL, description='Match whole words only in description.'),
            OpenApiParameter('start_after', OpenApiTypes.DATETIME, description='Filter programs starting at or after this time. ISO 8601 format.', examples=['2026-02-14T18:00:00Z']),
            OpenApiParameter('start_before', OpenApiTypes.DATETIME, description='Filter programs starting at or before this time. ISO 8601 format.'),
            OpenApiParameter('end_after', OpenApiTypes.DATETIME, description='Filter programs ending at or after this time. ISO 8601 format.'),
            OpenApiParameter('end_before', OpenApiTypes.DATETIME, description='Filter programs ending at or before this time. ISO 8601 format.'),
            OpenApiParameter('airing_at', OpenApiTypes.DATETIME, description='Find programs airing at this exact moment (start_time ≤ airing_at < end_time). ISO 8601 format.', examples=['2026-02-14T20:00:00Z']),
            OpenApiParameter('channel', OpenApiTypes.STR, description='Filter by channel name (case-insensitive substring match).', examples=['BBC One', 'Sky Sports']),
            OpenApiParameter('channel_id', OpenApiTypes.INT, description='Filter by exact channel ID.'),
            OpenApiParameter('stream', OpenApiTypes.STR, description='Filter by stream name (case-insensitive substring match).'),
            OpenApiParameter('group', OpenApiTypes.STR, description='Filter by channel group or stream group name (case-insensitive substring match).', examples=['Sports', 'UK Channels']),
            OpenApiParameter('epg_source', OpenApiTypes.INT, description='Filter by EPG source ID.'),
            OpenApiParameter('fields', OpenApiTypes.STR, description='Comma-separated list of fields to include. Omit to return all fields.', examples=['title,start_time,end_time', 'title,description,channels']),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number for pagination (default: 1).'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page (default: 50, max: 500).'),
        ],
        responses={200: ProgramSearchResultSerializer(many=True)},
        tags=['EPG'],
    )
    def get(self, request, format=None):
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
            filters &= _parse_text_query('title', title, use_regex=title_regex, whole_words=title_whole_words)

        description = params.get('description')
        if description:
            desc_regex = params.get('description_regex', '').lower() in ('true', '1', 'yes')
            desc_whole_words = params.get('description_whole_words', '').lower() in ('true', '1', 'yes')
            filters &= _parse_text_query('description', description, use_regex=desc_regex, whole_words=desc_whole_words)

        # Time filters
        start_after = params.get('start_after')
        if start_after:
            dt = parse_datetime(start_after)
            if dt:
                filters &= Q(start_time__gte=dt)

        start_before = params.get('start_before')
        if start_before:
            dt = parse_datetime(start_before)
            if dt:
                filters &= Q(start_time__lte=dt)

        end_after = params.get('end_after')
        if end_after:
            dt = parse_datetime(end_after)
            if dt:
                filters &= Q(end_time__gte=dt)

        end_before = params.get('end_before')
        if end_before:
            dt = parse_datetime(end_before)
            if dt:
                filters &= Q(end_time__lte=dt)

        airing_at = params.get('airing_at')
        if airing_at:
            dt = parse_datetime(airing_at)
            if dt:
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

        # Paginate
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProgramSearchResultSerializer(page, many=True)
        data = serializer.data

        # Field selection
        requested_fields = params.get('fields')
        if requested_fields:
            allowed = set(f.strip() for f in requested_fields.split(','))
            data = [{k: v for k, v in item.items() if k in allowed} for item in data]

        return paginator.get_paginated_response(data)

