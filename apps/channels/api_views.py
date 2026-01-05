from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.shortcuts import get_object_or_404, get_list_or_404
from django.db import transaction
from django.db.models import Q
import os, json, requests, logging
from urllib.parse import unquote
from apps.accounts.permissions import (
    Authenticated,
    IsAdmin,
    IsOwnerOfObject,
    permission_classes_by_action,
    permission_classes_by_method,
)

from core.models import UserAgent, CoreSettings
from core.utils import RedisClient

from .models import (
    Stream,
    Channel,
    ChannelGroup,
    Logo,
    ChannelProfile,
    ChannelProfileMembership,
    Recording,
    RecurringRecordingRule,
)
from .serializers import (
    StreamSerializer,
    ChannelSerializer,
    ChannelGroupSerializer,
    LogoSerializer,
    ChannelProfileMembershipSerializer,
    BulkChannelProfileMembershipSerializer,
    ChannelProfileSerializer,
    RecordingSerializer,
    RecurringRecordingRuleSerializer,
)
from .tasks import (
    match_epg_channels,
    evaluate_series_rules,
    evaluate_series_rules_impl,
    match_single_channel_epg,
    match_selected_channels_epg,
    sync_recurring_rule_impl,
    purge_recurring_rule_impl,
)
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from apps.epg.models import EPGData
from apps.vod.models import Movie, Series
from django.db.models import Q
from django.http import StreamingHttpResponse, FileResponse, Http404
from django.utils import timezone
import mimetypes
from django.conf import settings

from rest_framework.pagination import PageNumberPagination



logger = logging.getLogger(__name__)


class OrInFilter(django_filters.Filter):
    """
    Custom filter that handles the OR condition instead of AND.
    """

    def filter(self, queryset, value):
        if value:
            # Create a Q object for each value and combine them with OR
            query = Q()
            for val in value.split(","):
                query |= Q(**{self.field_name: val})
            return queryset.filter(query)
        return queryset


class StreamPagination(PageNumberPagination):
    page_size = 50  # Default page size to match frontend default
    page_size_query_param = "page_size"  # Allow clients to specify page size
    max_page_size = 10000  # Prevent excessive page sizes


class StreamFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    channel_group_name = OrInFilter(
        field_name="channel_group__name", lookup_expr="icontains"
    )
    m3u_account = django_filters.NumberFilter(field_name="m3u_account__id")
    m3u_account_name = django_filters.CharFilter(
        field_name="m3u_account__name", lookup_expr="icontains"
    )
    m3u_account_is_active = django_filters.BooleanFilter(
        field_name="m3u_account__is_active"
    )

    class Meta:
        model = Stream
        fields = [
            "name",
            "channel_group_name",
            "m3u_account",
            "m3u_account_name",
            "m3u_account_is_active",
        ]


# ─────────────────────────────────────────────────────────
# 1) Stream API (CRUD)
# ─────────────────────────────────────────────────────────
class StreamViewSet(viewsets.ModelViewSet):
    queryset = Stream.objects.all()
    serializer_class = StreamSerializer
    pagination_class = StreamPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StreamFilter
    search_fields = ["name", "channel_group__name"]
    ordering_fields = ["name", "channel_group__name", "m3u_account__name"]
    ordering = ["-name"]

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        # Exclude streams from inactive M3U accounts
        qs = qs.exclude(m3u_account__is_active=False)

        assigned = self.request.query_params.get("assigned")
        if assigned is not None:
            qs = qs.filter(channels__id=assigned)

        unassigned = self.request.query_params.get("unassigned")
        if unassigned == "1":
            qs = qs.filter(channels__isnull=True)

        channel_group = self.request.query_params.get("channel_group")
        if channel_group:
            group_names = channel_group.split(",")
            qs = qs.filter(channel_group__name__in=group_names)

        return qs

    def list(self, request, *args, **kwargs):
        ids = request.query_params.get("ids", None)
        if ids:
            ids = ids.split(",")
            streams = get_list_or_404(Stream, id__in=ids)
            serializer = self.get_serializer(streams, many=True)
            return Response(serializer.data)

        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="ids")
    def get_ids(self, request, *args, **kwargs):
        # Get the filtered queryset
        queryset = self.get_queryset()

        # Apply filtering, search, and ordering
        queryset = self.filter_queryset(queryset)

        # Return only the IDs from the queryset
        stream_ids = queryset.values_list("id", flat=True)

        # Return the response with the list of IDs
        return Response(list(stream_ids))

    @action(detail=False, methods=["get"], url_path="groups")
    def get_groups(self, request, *args, **kwargs):
        # Get unique ChannelGroup names that are linked to streams
        group_names = (
            ChannelGroup.objects.filter(streams__isnull=False)
            .order_by("name")
            .values_list("name", flat=True)
            .distinct()
        )

        # Return the response with the list of unique group names
        return Response(list(group_names))

    @swagger_auto_schema(
        method="post",
        operation_description="Retrieve streams by a list of IDs using POST to avoid URL length limitations",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["ids"],
            properties={
                "ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="List of stream IDs to retrieve"
                ),
            },
        ),
        responses={200: StreamSerializer(many=True)},
    )
    @action(detail=False, methods=["post"], url_path="by-ids")
    def get_by_ids(self, request, *args, **kwargs):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list):
            return Response(
                {"error": "ids must be a list of integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        streams = Stream.objects.filter(id__in=ids)
        serializer = self.get_serializer(streams, many=True)
        return Response(serializer.data)


# ─────────────────────────────────────────────────────────
# 2) Channel Group Management (CRUD)
# ─────────────────────────────────────────────────────────
class ChannelGroupViewSet(viewsets.ModelViewSet):
    queryset = ChannelGroup.objects.all()
    serializer_class = ChannelGroupSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        """Return channel groups with prefetched relations for efficient counting"""
        return ChannelGroup.objects.prefetch_related('channels', 'm3u_accounts').all()

    def update(self, request, *args, **kwargs):
        """Override update to check M3U associations"""
        instance = self.get_object()

        # Check if group has M3U account associations
        if hasattr(instance, 'm3u_account') and instance.m3u_account.exists():
            return Response(
                {"error": "Cannot edit group with M3U account associations"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """Override partial_update to check M3U associations"""
        instance = self.get_object()

        # Check if group has M3U account associations
        if hasattr(instance, 'm3u_account') and instance.m3u_account.exists():
            return Response(
                {"error": "Cannot edit group with M3U account associations"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(
        method="post",
        operation_description="Delete all channel groups that have no associations (no channels or M3U accounts)",
        responses={200: "Cleanup completed"},
    )
    @action(detail=False, methods=["post"], url_path="cleanup")
    def cleanup_unused_groups(self, request):
        """Delete all channel groups with no channels or M3U account associations"""
        from django.db.models import Q, Exists, OuterRef

        # Find groups with no channels and no M3U account associations using Exists subqueries
        from .models import Channel, ChannelGroupM3UAccount

        has_channels = Channel.objects.filter(channel_group_id=OuterRef('pk'))
        has_accounts = ChannelGroupM3UAccount.objects.filter(channel_group_id=OuterRef('pk'))

        unused_groups = ChannelGroup.objects.annotate(
            has_channels=Exists(has_channels),
            has_accounts=Exists(has_accounts)
        ).filter(
            has_channels=False,
            has_accounts=False
        )

        deleted_count = unused_groups.count()
        group_names = list(unused_groups.values_list('name', flat=True))

        # Delete the unused groups
        unused_groups.delete()

        return Response({
            "message": f"Successfully deleted {deleted_count} unused channel groups",
            "deleted_count": deleted_count,
            "deleted_groups": group_names
        })

    def destroy(self, request, *args, **kwargs):
        """Override destroy to check for associations before deletion"""
        instance = self.get_object()

        # Check if group has associated channels
        if instance.channels.exists():
            return Response(
                {"error": "Cannot delete group with associated channels"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if group has M3U account associations
        if hasattr(instance, 'm3u_account') and instance.m3u_account.exists():
            return Response(
                {"error": "Cannot delete group with M3U account associations"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().destroy(request, *args, **kwargs)


# ─────────────────────────────────────────────────────────
# 3) Channel Management (CRUD)
# ─────────────────────────────────────────────────────────
class ChannelPagination(PageNumberPagination):
    page_size = 50  # Default page size to match frontend default
    page_size_query_param = "page_size"  # Allow clients to specify page size
    max_page_size = 10000  # Prevent excessive page sizes

    def paginate_queryset(self, queryset, request, view=None):
        if not request.query_params.get(self.page_query_param):
            return None  # disables pagination, returns full queryset

        return super().paginate_queryset(queryset, request, view)


class EPGFilter(django_filters.Filter):
    """
    Filter channels by EPG source name or null (unlinked).
    """
    def filter(self, queryset, value):
        if not value:
            return queryset

        # Split comma-separated values
        values = [v.strip() for v in value.split(',')]
        query = Q()

        for val in values:
            if val == 'null':
                # Filter for channels with no EPG data
                query |= Q(epg_data__isnull=True)
            else:
                # Filter for channels with specific EPG source name
                query |= Q(epg_data__epg_source__name__icontains=val)

        return queryset.filter(query)


class ChannelFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    channel_group = OrInFilter(
        field_name="channel_group__name", lookup_expr="icontains"
    )
    epg = EPGFilter()

    class Meta:
        model = Channel
        fields = [
            "name",
            "channel_group",
            "epg",
        ]


class ChannelViewSet(viewsets.ModelViewSet):
    queryset = Channel.objects.all()
    serializer_class = ChannelSerializer
    pagination_class = ChannelPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ChannelFilter
    search_fields = ["name", "channel_group__name"]
    ordering_fields = ["channel_number", "name", "channel_group__name"]
    ordering = ["-channel_number"]

    def get_permissions(self):
        if self.action in [
            "edit_bulk",
            "assign",
            "from_stream",
            "from_stream_bulk",
            "match_epg",
            "set_epg",
            "batch_set_epg",
        ]:
            return [IsAdmin()]

        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related(
                "channel_group",
                "logo",
                "epg_data",
                "stream_profile",
            )
            .prefetch_related("streams")
        )

        channel_group = self.request.query_params.get("channel_group")
        if channel_group:
            group_names = channel_group.split(",")
            qs = qs.filter(channel_group__name__in=group_names)

        filters = {}
        q_filters = Q()

        channel_profile_id = self.request.query_params.get("channel_profile_id")
        show_disabled_param = self.request.query_params.get("show_disabled", None)
        only_streamless = self.request.query_params.get("only_streamless", None)

        if channel_profile_id:
            try:
                profile_id_int = int(channel_profile_id)
                filters["channelprofilemembership__channel_profile_id"] = profile_id_int

                if show_disabled_param is None:
                    filters["channelprofilemembership__enabled"] = True
            except (ValueError, TypeError):
                # Ignore invalid profile id values
                pass

        if only_streamless:
            q_filters &= Q(streams__isnull=True)

        if self.request.user.user_level < 10:
            filters["user_level__lte"] = self.request.user.user_level

        if filters:
            qs = qs.filter(**filters)
        if q_filters:
            qs = qs.filter(q_filters)

        return qs.distinct()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        include_streams = (
            self.request.query_params.get("include_streams", "false") == "true"
        )
        context["include_streams"] = include_streams
        return context

    @action(detail=False, methods=["patch"], url_path="edit/bulk")
    def edit_bulk(self, request):
        """
        Bulk edit channels efficiently.
        Validates all updates first, then applies in a single transaction.
        """
        data = request.data
        if not isinstance(data, list):
            return Response(
                {"error": "Expected a list of channel updates"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract IDs and validate presence
        channel_updates = {}
        missing_ids = []

        for i, channel_data in enumerate(data):
            channel_id = channel_data.get("id")
            if not channel_id:
                missing_ids.append(f"Item {i}: Channel ID is required")
            else:
                channel_updates[channel_id] = channel_data

        if missing_ids:
            return Response(
                {"errors": missing_ids},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Fetch all channels at once (one query)
        channels_dict = {
            c.id: c for c in Channel.objects.filter(id__in=channel_updates.keys())
        }

        # Validate and prepare updates
        validated_updates = []
        errors = []

        for channel_id, channel_data in channel_updates.items():
            channel = channels_dict.get(channel_id)

            if not channel:
                errors.append({
                    "channel_id": channel_id,
                    "error": "Channel not found"
                })
                continue

            # Handle channel_group_id conversion
            if 'channel_group_id' in channel_data:
                group_id = channel_data['channel_group_id']
                if group_id is not None:
                    try:
                        channel_data['channel_group_id'] = int(group_id)
                    except (ValueError, TypeError):
                        channel_data['channel_group_id'] = None

            # Validate with serializer
            serializer = ChannelSerializer(
                channel, data=channel_data, partial=True
            )

            if serializer.is_valid():
                validated_updates.append((channel, serializer.validated_data))
            else:
                errors.append({
                    "channel_id": channel_id,
                    "errors": serializer.errors
                })

        if errors:
            return Response(
                {"errors": errors, "updated_count": len(validated_updates)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Apply all updates in a transaction
        with transaction.atomic():
            for channel, validated_data in validated_updates:
                for key, value in validated_data.items():
                    setattr(channel, key, value)

            # Single bulk_update query instead of individual saves
            channels_to_update = [channel for channel, _ in validated_updates]
            if channels_to_update:
                Channel.objects.bulk_update(
                    channels_to_update,
                    fields=list(validated_updates[0][1].keys()),
                    batch_size=100
                )

        # Return the updated objects (already in memory)
        serialized_channels = ChannelSerializer(
            [channel for channel, _ in validated_updates],
            many=True,
            context=self.get_serializer_context()
        ).data

        return Response({
            "message": f"Successfully updated {len(validated_updates)} channels",
            "channels": serialized_channels
        })

    @action(detail=False, methods=["post"], url_path="set-names-from-epg")
    def set_names_from_epg(self, request):
        """
        Trigger a Celery task to set channel names from EPG data
        """
        from .tasks import set_channels_names_from_epg

        data = request.data
        channel_ids = data.get("channel_ids", [])

        if not channel_ids:
            return Response(
                {"error": "channel_ids is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(channel_ids, list):
            return Response(
                {"error": "channel_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Start the Celery task
        task = set_channels_names_from_epg.delay(channel_ids)

        return Response({
            "message": f"Started EPG name setting task for {len(channel_ids)} channels",
            "task_id": task.id,
            "channel_count": len(channel_ids)
        })

    @action(detail=False, methods=["post"], url_path="set-logos-from-epg")
    def set_logos_from_epg(self, request):
        """
        Trigger a Celery task to set channel logos from EPG data
        """
        from .tasks import set_channels_logos_from_epg

        data = request.data
        channel_ids = data.get("channel_ids", [])

        if not channel_ids:
            return Response(
                {"error": "channel_ids is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(channel_ids, list):
            return Response(
                {"error": "channel_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Start the Celery task
        task = set_channels_logos_from_epg.delay(channel_ids)

        return Response({
            "message": f"Started EPG logo setting task for {len(channel_ids)} channels",
            "task_id": task.id,
            "channel_count": len(channel_ids)
        })

    @action(detail=False, methods=["post"], url_path="set-tvg-ids-from-epg")
    def set_tvg_ids_from_epg(self, request):
        """
        Trigger a Celery task to set channel TVG-IDs from EPG data
        """
        from .tasks import set_channels_tvg_ids_from_epg

        data = request.data
        channel_ids = data.get("channel_ids", [])

        if not channel_ids:
            return Response(
                {"error": "channel_ids is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(channel_ids, list):
            return Response(
                {"error": "channel_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Start the Celery task
        task = set_channels_tvg_ids_from_epg.delay(channel_ids)

        return Response({
            "message": f"Started EPG TVG-ID setting task for {len(channel_ids)} channels",
            "task_id": task.id,
            "channel_count": len(channel_ids)
        })

    @action(detail=False, methods=["get"], url_path="ids")
    def get_ids(self, request, *args, **kwargs):
        # Get the filtered queryset
        queryset = self.get_queryset()

        # Apply filtering, search, and ordering
        queryset = self.filter_queryset(queryset)

        # Return only the IDs from the queryset
        channel_ids = queryset.values_list("id", flat=True)

        # Return the response with the list of IDs
        return Response(list(channel_ids))

    @swagger_auto_schema(
        method="post",
        operation_description="Auto-assign channel_number in bulk by an ordered list of channel IDs.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["channel_ids"],
            properties={
                "starting_number": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="Starting channel number to assign (can be decimal)",
                ),
                "channel_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="Channel IDs to assign",
                ),
            },
        ),
        responses={200: "Channels have been auto-assigned!"},
    )
    @action(detail=False, methods=["post"], url_path="assign")
    def assign(self, request):
        with transaction.atomic():
            channel_ids = request.data.get("channel_ids", [])
            # Ensure starting_number is processed as a float
            try:
                channel_num = float(request.data.get("starting_number", 1))
            except (ValueError, TypeError):
                channel_num = 1.0

            for channel_id in channel_ids:
                Channel.objects.filter(id=channel_id).update(channel_number=channel_num)
                channel_num = channel_num + 1

        return Response(
            {"message": "Channels have been auto-assigned!"}, status=status.HTTP_200_OK
        )

    @swagger_auto_schema(
        method="post",
        operation_description=(
            "Create a new channel from an existing stream. "
            "If 'channel_number' is provided, it will be used (if available); "
            "otherwise, the next available channel number is assigned. "
            "If 'channel_profile_ids' is provided, the channel will only be added to those profiles. "
            "Accepts either a single ID or an array of IDs."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["stream_id"],
            properties={
                "stream_id": openapi.Schema(
                    type=openapi.TYPE_INTEGER, description="ID of the stream to link"
                ),
                "channel_number": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="(Optional) Desired channel number. Must not be in use.",
                ),
                "name": openapi.Schema(
                    type=openapi.TYPE_STRING, description="Desired channel name"
                ),
                "channel_profile_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="(Optional) Channel profile ID(s) to add the channel to. Can be a single ID or array of IDs. If not provided, channel is added to all profiles."
                ),
            },
        ),
        responses={201: ChannelSerializer()},
    )
    @action(detail=False, methods=["post"], url_path="from-stream")
    def from_stream(self, request):
        stream_id = request.data.get("stream_id")
        if not stream_id:
            return Response(
                {"error": "Missing stream_id"}, status=status.HTTP_400_BAD_REQUEST
            )
        stream = get_object_or_404(Stream, pk=stream_id)
        channel_group = stream.channel_group

        name = request.data.get("name")


        if name is None:
            name = stream.name

        # Check if client provided a channel_number; if not, auto-assign one.
        stream_custom_props = stream.custom_properties or {}
        channel_number = request.data.get("channel_number")

        if channel_number is None:
            # Channel number not provided by client, check stream properties or auto-assign
            if "tvg-chno" in stream_custom_props:
                channel_number = float(stream_custom_props["tvg-chno"])
            elif "channel-number" in stream_custom_props:
                channel_number = float(stream_custom_props["channel-number"])
            elif "num" in stream_custom_props:
                channel_number = float(stream_custom_props["num"])
        elif channel_number == 0:
            # Special case: 0 means ignore provider numbers and auto-assign
            channel_number = None

        if channel_number is None:
            # Still None, auto-assign the next available channel number
            channel_number = Channel.get_next_available_channel_number()


        try:
            channel_number = float(channel_number)
        except ValueError:
            return Response(
                {"error": "channel_number must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # If the provided number is already used, return an error.
        if Channel.objects.filter(channel_number=channel_number).exists():
            channel_number = Channel.get_next_available_channel_number(channel_number)
        # Get the tvc_guide_stationid from custom properties if it exists
        tvc_guide_stationid = None
        if "tvc-guide-stationid" in stream_custom_props:
            tvc_guide_stationid = stream_custom_props["tvc-guide-stationid"]

        channel_data = {
            "channel_number": channel_number,
            "name": name,
            "tvg_id": stream.tvg_id,
            "tvc_guide_stationid": tvc_guide_stationid,
            "streams": [stream_id],
        }

        # Only add channel_group_id if the stream has a channel group
        if channel_group:
            channel_data["channel_group_id"] = channel_group.id

        if stream.logo_url:
            # Import validation function
            from apps.channels.tasks import validate_logo_url
            validated_logo_url = validate_logo_url(stream.logo_url)
            if validated_logo_url:
                logo, _ = Logo.objects.get_or_create(
                    url=validated_logo_url, defaults={"name": stream.name or stream.tvg_id}
                )
                channel_data["logo_id"] = logo.id

        # Attempt to find existing EPGs with the same tvg-id
        epgs = EPGData.objects.filter(tvg_id=stream.tvg_id)
        if epgs:
            channel_data["epg_data_id"] = epgs.first().id

        serializer = self.get_serializer(data=channel_data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            channel = serializer.save()
            channel.streams.add(stream)

            # Handle channel profile membership
            channel_profile_ids = request.data.get("channel_profile_ids")
            if channel_profile_ids is not None:
                # Normalize single ID to array
                if not isinstance(channel_profile_ids, list):
                    channel_profile_ids = [channel_profile_ids]

            if channel_profile_ids:
                # Add channel only to the specified profiles
                try:
                    channel_profiles = ChannelProfile.objects.filter(id__in=channel_profile_ids)
                    if len(channel_profiles) != len(channel_profile_ids):
                        missing_ids = set(channel_profile_ids) - set(channel_profiles.values_list('id', flat=True))
                        return Response(
                            {"error": f"Channel profiles with IDs {list(missing_ids)} not found"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    ChannelProfileMembership.objects.bulk_create([
                        ChannelProfileMembership(
                            channel_profile=profile,
                            channel=channel,
                            enabled=True
                        )
                        for profile in channel_profiles
                    ])
                except Exception as e:
                    return Response(
                        {"error": f"Error creating profile memberships: {str(e)}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                # Default behavior: add to all profiles
                profiles = ChannelProfile.objects.all()
                ChannelProfileMembership.objects.bulk_create([
                    ChannelProfileMembership(channel_profile=profile, channel=channel, enabled=True)
                    for profile in profiles
                ])

        # Send WebSocket notification for single channel creation
        from core.utils import send_websocket_update
        send_websocket_update('updates', 'update', {
            'type': 'channels_created',
            'count': 1,
            'channel_id': channel.id,
            'channel_name': channel.name,
            'channel_number': channel.channel_number
        })

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        method="post",
        operation_description=(
            "Asynchronously bulk create channels from stream IDs. "
            "Returns a task ID to track progress via WebSocket. "
            "This is the recommended approach for large bulk operations."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["stream_ids"],
            properties={
                "stream_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="List of stream IDs to create channels from"
                ),
                "channel_profile_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="(Optional) Channel profile ID(s) to add the channels to. If not provided, channels are added to all profiles."
                ),
                "starting_channel_number": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="(Optional) Starting channel number mode: null=use provider numbers, 0=lowest available, other=start from specified number"
                ),
            },
        ),
        responses={202: "Task started successfully"},
    )
    @action(detail=False, methods=["post"], url_path="from-stream/bulk")
    def from_stream_bulk(self, request):
        from .tasks import bulk_create_channels_from_streams

        stream_ids = request.data.get("stream_ids", [])
        channel_profile_ids = request.data.get("channel_profile_ids")
        starting_channel_number = request.data.get("starting_channel_number")

        if not stream_ids:
            return Response(
                {"error": "stream_ids is required and cannot be empty"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(stream_ids, list):
            return Response(
                {"error": "stream_ids must be a list of integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Normalize channel_profile_ids to array if single ID provided
        if channel_profile_ids is not None:
            if not isinstance(channel_profile_ids, list):
                channel_profile_ids = [channel_profile_ids]

        # Start the async task
        task = bulk_create_channels_from_streams.delay(stream_ids, channel_profile_ids, starting_channel_number)

        return Response({
            "task_id": task.id,
            "message": f"Bulk channel creation task started for {len(stream_ids)} streams",
            "stream_count": len(stream_ids),
            "status": "started"
        }, status=status.HTTP_202_ACCEPTED)

    # ─────────────────────────────────────────────────────────
    # 6) EPG Fuzzy Matching
    # ─────────────────────────────────────────────────────────
    @swagger_auto_schema(
        method="post",
        operation_description="Kick off a Celery task that tries to fuzzy-match channels with EPG data. If channel_ids are provided, only those channels will be processed.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'channel_ids': openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    description='List of channel IDs to process. If empty or not provided, all channels without EPG will be processed.'
                )
            }
        ),
        responses={202: "EPG matching task initiated"},
    )
    @action(detail=False, methods=["post"], url_path="match-epg")
    def match_epg(self, request):
        # Get channel IDs from request body if provided
        channel_ids = request.data.get('channel_ids', [])

        if channel_ids:
            # Process only selected channels
            from .tasks import match_selected_channels_epg
            match_selected_channels_epg.delay(channel_ids)
            message = f"EPG matching task initiated for {len(channel_ids)} selected channel(s)."
        else:
            # Process all channels without EPG (original behavior)
            match_epg_channels.delay()
            message = "EPG matching task initiated for all channels without EPG."

        return Response(
            {"message": message}, status=status.HTTP_202_ACCEPTED
        )

    @swagger_auto_schema(
        method="post",
        operation_description="Try to auto-match this specific channel with EPG data.",
        responses={200: "EPG matching completed", 202: "EPG matching task initiated"},
    )
    @action(detail=True, methods=["post"], url_path="match-epg")
    def match_channel_epg(self, request, pk=None):
        channel = self.get_object()

        # Import the matching logic
        from apps.channels.tasks import match_single_channel_epg

        try:
            # Try to match this specific channel - call synchronously for immediate response
            result = match_single_channel_epg.apply_async(args=[channel.id]).get(timeout=30)

            # Refresh the channel from DB to get any updates
            channel.refresh_from_db()

            return Response({
                "message": result.get("message", "Channel matching completed"),
                "matched": result.get("matched", False),
                "channel": self.get_serializer(channel).data
            })
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    # ─────────────────────────────────────────────────────────
    # 7) Set EPG and Refresh
    # ─────────────────────────────────────────────────────────
    @swagger_auto_schema(
        method="post",
        operation_description="Set EPG data for a channel and refresh program data",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["epg_data_id"],
            properties={
                "epg_data_id": openapi.Schema(
                    type=openapi.TYPE_INTEGER, description="EPG data ID to link"
                )
            },
        ),
        responses={200: "EPG data linked and refresh triggered"},
    )
    @action(detail=True, methods=["post"], url_path="set-epg")
    def set_epg(self, request, pk=None):
        channel = self.get_object()
        epg_data_id = request.data.get("epg_data_id")

        # Handle removing EPG link
        if epg_data_id in (None, "", "0", 0):
            channel.epg_data = None
            channel.save(update_fields=["epg_data"])
            return Response(
                {"message": f"EPG data removed from channel {channel.name}"}
            )

        try:
            # Get the EPG data object
            from apps.epg.models import EPGData

            epg_data = EPGData.objects.get(pk=epg_data_id)

            # Set the EPG data and save
            channel.epg_data = epg_data
            channel.save(update_fields=["epg_data"])

            # Only trigger program refresh for non-dummy EPG sources
            status_message = None
            if epg_data.epg_source.source_type != 'dummy':
                # Explicitly trigger program refresh for this EPG
                from apps.epg.tasks import parse_programs_for_tvg_id

                task_result = parse_programs_for_tvg_id.delay(epg_data.id)

                # Prepare response with task status info
                status_message = "EPG refresh queued"
                if task_result.result == "Task already running":
                    status_message = "EPG refresh already in progress"

            # Build response message
            message = f"EPG data set to {epg_data.tvg_id} for channel {channel.name}"
            if status_message:
                message += f". {status_message}"

            return Response(
                {
                    "message": message,
                    "channel": self.get_serializer(channel).data,
                    "task_status": status_message,
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    @swagger_auto_schema(
        method="post",
        operation_description="Associate multiple channels with EPG data without triggering a full refresh",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "associations": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "channel_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "epg_data_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                        },
                    ),
                )
            },
        ),
        responses={200: "EPG data linked for multiple channels"},
    )
    @action(detail=False, methods=["post"], url_path="batch-set-epg")
    def batch_set_epg(self, request):
        """Efficiently associate multiple channels with EPG data at once."""
        associations = request.data.get("associations", [])

        if not associations:
            return Response(
                {"error": "associations list is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract channel IDs upfront
        channel_updates = {}
        unique_epg_ids = set()

        for assoc in associations:
            channel_id = assoc.get("channel_id")
            epg_data_id = assoc.get("epg_data_id")

            if not channel_id:
                continue

            channel_updates[channel_id] = epg_data_id
            if epg_data_id:
                unique_epg_ids.add(epg_data_id)

        # Batch fetch all channels (single query)
        channels_dict = {
            c.id: c for c in Channel.objects.filter(id__in=channel_updates.keys())
        }

        # Collect channels to update
        channels_to_update = []
        for channel_id, epg_data_id in channel_updates.items():
            if channel_id not in channels_dict:
                logger.error(f"Channel with ID {channel_id} not found")
                continue

            channel = channels_dict[channel_id]
            channel.epg_data_id = epg_data_id
            channels_to_update.append(channel)

        # Bulk update all channels (single query)
        if channels_to_update:
            with transaction.atomic():
                Channel.objects.bulk_update(
                    channels_to_update,
                    fields=["epg_data_id"],
                    batch_size=100
                )

        channels_updated = len(channels_to_update)

        # Trigger program refresh for unique EPG data IDs (skip dummy EPGs)
        from apps.epg.tasks import parse_programs_for_tvg_id
        from apps.epg.models import EPGData

        # Batch fetch EPG data (single query)
        epg_data_dict = {
            epg.id: epg
            for epg in EPGData.objects.filter(id__in=unique_epg_ids).select_related('epg_source')
        }

        programs_refreshed = 0
        for epg_id in unique_epg_ids:
            epg_data = epg_data_dict.get(epg_id)
            if not epg_data:
                logger.error(f"EPGData with ID {epg_id} not found")
                continue

            # Only refresh non-dummy EPG sources
            if epg_data.epg_source.source_type != 'dummy':
                parse_programs_for_tvg_id.delay(epg_id)
                programs_refreshed += 1

        return Response(
            {
                "success": True,
                "channels_updated": channels_updated,
                "programs_refreshed": programs_refreshed,
            }
        )


# ─────────────────────────────────────────────────────────
# 4) Bulk Delete Streams
# ─────────────────────────────────────────────────────────
class BulkDeleteStreamsAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @swagger_auto_schema(
        operation_description="Bulk delete streams by ID",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["stream_ids"],
            properties={
                "stream_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="Stream IDs to delete",
                )
            },
        ),
        responses={204: "Streams deleted"},
    )
    def delete(self, request, *args, **kwargs):
        stream_ids = request.data.get("stream_ids", [])
        Stream.objects.filter(id__in=stream_ids).delete()
        return Response(
            {"message": "Streams deleted successfully!"},
            status=status.HTTP_204_NO_CONTENT,
        )


# ─────────────────────────────────────────────────────────
# 5) Bulk Delete Channels
# ─────────────────────────────────────────────────────────
class BulkDeleteChannelsAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @swagger_auto_schema(
        operation_description="Bulk delete channels by ID",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["channel_ids"],
            properties={
                "channel_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="Channel IDs to delete",
                )
            },
        ),
        responses={204: "Channels deleted"},
    )
    def delete(self, request):
        channel_ids = request.data.get("channel_ids", [])
        Channel.objects.filter(id__in=channel_ids).delete()
        return Response(
            {"message": "Channels deleted"}, status=status.HTTP_204_NO_CONTENT
        )


# ─────────────────────────────────────────────────────────
# 6) Bulk Delete Logos
# ─────────────────────────────────────────────────────────
class BulkDeleteLogosAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @swagger_auto_schema(
        operation_description="Bulk delete logos by ID",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["logo_ids"],
            properties={
                "logo_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="Logo IDs to delete",
                )
            },
        ),
        responses={204: "Logos deleted"},
    )
    def delete(self, request):
        logo_ids = request.data.get("logo_ids", [])
        delete_files = request.data.get("delete_files", False)

        # Get logos and their usage info before deletion
        logos_to_delete = Logo.objects.filter(id__in=logo_ids)
        total_channels_affected = 0
        local_files_deleted = 0

        for logo in logos_to_delete:
            # Handle file deletion for local files
            if delete_files and logo.url and logo.url.startswith('/data/logos'):
                try:
                    if os.path.exists(logo.url):
                        os.remove(logo.url)
                        local_files_deleted += 1
                        logger.info(f"Deleted local logo file: {logo.url}")
                except Exception as e:
                    logger.error(f"Failed to delete logo file {logo.url}: {str(e)}")
                    return Response(
                        {"error": f"Failed to delete logo file {logo.url}: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            if logo.channels.exists():
                channel_count = logo.channels.count()
                total_channels_affected += channel_count
                # Remove logo from channels
                logo.channels.update(logo=None)
                logger.info(f"Removed logo {logo.name} from {channel_count} channels before deletion")

        # Delete logos
        deleted_count = logos_to_delete.delete()[0]

        message = f"Successfully deleted {deleted_count} logos"
        if total_channels_affected > 0:
            message += f" and removed them from {total_channels_affected} channels"
        if local_files_deleted > 0:
            message += f" and deleted {local_files_deleted} local files"

        return Response(
            {"message": message},
            status=status.HTTP_204_NO_CONTENT
        )


class CleanupUnusedLogosAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @swagger_auto_schema(
        operation_description="Delete all channel logos that are not used by any channels",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "delete_files": openapi.Schema(
                    type=openapi.TYPE_BOOLEAN,
                    description="Whether to delete local logo files from disk",
                    default=False
                )
            },
        ),
        responses={200: "Cleanup completed"},
    )
    def post(self, request):
        """Delete all channel logos with no channel associations"""
        delete_files = request.data.get("delete_files", False)

        # Find logos that are not used by any channels
        unused_logos = Logo.objects.filter(channels__isnull=True)
        deleted_count = unused_logos.count()
        logo_names = list(unused_logos.values_list('name', flat=True))
        local_files_deleted = 0

        # Handle file deletion for local files if requested
        if delete_files:
            for logo in unused_logos:
                if logo.url and logo.url.startswith('/data/logos'):
                    try:
                        if os.path.exists(logo.url):
                            os.remove(logo.url)
                            local_files_deleted += 1
                            logger.info(f"Deleted local logo file: {logo.url}")
                    except Exception as e:
                        logger.error(f"Failed to delete logo file {logo.url}: {str(e)}")
                        return Response(
                            {"error": f"Failed to delete logo file {logo.url}: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )

        # Delete the unused logos
        unused_logos.delete()

        message = f"Successfully deleted {deleted_count} unused logos"
        if local_files_deleted > 0:
            message += f" and deleted {local_files_deleted} local files"

        return Response({
            "message": message,
            "deleted_count": deleted_count,
            "deleted_logos": logo_names,
            "local_files_deleted": local_files_deleted
        })


class LogoPagination(PageNumberPagination):
    page_size = 50  # Default page size to match frontend default
    page_size_query_param = "page_size"  # Allow clients to specify page size
    max_page_size = 1000  # Prevent excessive page sizes

    def paginate_queryset(self, queryset, request, view=None):
        # Check if pagination should be disabled for specific requests
        if request.query_params.get('no_pagination') == 'true':
            return None  # disables pagination, returns full queryset

        return super().paginate_queryset(queryset, request, view)


class LogoViewSet(viewsets.ModelViewSet):
    queryset = Logo.objects.all()
    serializer_class = LogoSerializer
    pagination_class = LogoPagination
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_permissions(self):
        if self.action in ["upload"]:
            return [IsAdmin()]

        if self.action in ["cache"]:
            return [AllowAny()]

        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        """Optimize queryset with prefetch and add filtering"""
        # Start with basic prefetch for channels
        queryset = Logo.objects.prefetch_related('channels').order_by('name')

        # Filter by specific IDs
        ids = self.request.query_params.getlist('ids')
        if ids:
            try:
                # Convert string IDs to integers and filter
                id_list = [int(id_str) for id_str in ids if id_str.isdigit()]
                if id_list:
                    queryset = queryset.filter(id__in=id_list)
            except (ValueError, TypeError):
                pass  # Invalid IDs, return empty queryset
                queryset = Logo.objects.none()

        # Filter by usage
        used_filter = self.request.query_params.get('used', None)
        if used_filter == 'true':
            # Logo is used if it has any channels
            queryset = queryset.filter(channels__isnull=False).distinct()
        elif used_filter == 'false':
            # Logo is unused if it has no channels
            queryset = queryset.filter(channels__isnull=True)

        # Filter by name
        name_filter = self.request.query_params.get('name', None)
        if name_filter:
            queryset = queryset.filter(name__icontains=name_filter)

        return queryset

    def create(self, request, *args, **kwargs):
        """Create a new logo entry"""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            logo = serializer.save()
            return Response(self.get_serializer(logo).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        """Update an existing logo"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if serializer.is_valid():
            logo = serializer.save()
            return Response(self.get_serializer(logo).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        """Delete a logo and remove it from any channels using it"""
        logo = self.get_object()
        delete_file = request.query_params.get('delete_file', 'false').lower() == 'true'

        # Check if it's a local file that should be deleted
        if delete_file and logo.url and logo.url.startswith('/data/logos'):
            try:
                if os.path.exists(logo.url):
                    os.remove(logo.url)
                    logger.info(f"Deleted local logo file: {logo.url}")
            except Exception as e:
                logger.error(f"Failed to delete logo file {logo.url}: {str(e)}")
                return Response(
                    {"error": f"Failed to delete logo file: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Instead of preventing deletion, remove the logo from channels
        if logo.channels.exists():
            channel_count = logo.channels.count()
            logo.channels.update(logo=None)
            logger.info(f"Removed logo {logo.name} from {channel_count} channels before deletion")

        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["post"])
    def upload(self, request):
        if "file" not in request.FILES:
            return Response(
                {"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST
            )

        file = request.FILES["file"]

        # Validate file
        try:
            from dispatcharr.utils import validate_logo_file
            validate_logo_file(file)
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

        file_name = file.name
        file_path = os.path.join("/data/logos", file_name)

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb+") as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        # Mark file as processed in Redis to prevent file scanner notifications
        try:
            redis_client = RedisClient.get_client()
            if redis_client:
                # Use the same key format as the file scanner
                redis_key = f"processed_file:{file_path}"
                # Store the actual file modification time to match the file scanner's expectation
                file_mtime = os.path.getmtime(file_path)
                redis_client.setex(redis_key, 60 * 60 * 24 * 3, str(file_mtime))  # 3 day TTL
                logger.debug(f"Marked uploaded logo file as processed in Redis: {file_path} (mtime: {file_mtime})")
        except Exception as e:
            logger.warning(f"Failed to mark logo file as processed in Redis: {e}")

        # Get custom name from request data, fallback to filename
        custom_name = request.data.get('name', '').strip()
        logo_name = custom_name if custom_name else file_name

        logo, _ = Logo.objects.get_or_create(
            url=file_path,
            defaults={
                "name": logo_name,
            },
        )

        # Use get_serializer to ensure proper context
        serializer = self.get_serializer(logo)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def cache(self, request, pk=None):
        """Streams the logo file, whether it's local or remote."""
        logo = self.get_object()
        logo_url = logo.url

        if logo_url.startswith("/data"):  # Local file
            if not os.path.exists(logo_url):
                raise Http404("Image not found")

            # Get proper mime type (first item of the tuple)
            content_type, _ = mimetypes.guess_type(logo_url)
            if not content_type:
                content_type = "image/jpeg"  # Default to a common image type

            # Use context manager and set Content-Disposition to inline
            response = StreamingHttpResponse(
                open(logo_url, "rb"), content_type=content_type
            )
            response["Content-Disposition"] = 'inline; filename="{}"'.format(
                os.path.basename(logo_url)
            )
            return response

        else:  # Remote image
            try:
                # Get the default user agent
                try:
                    default_user_agent_id = CoreSettings.get_default_user_agent_id()
                    user_agent_obj = UserAgent.objects.get(id=int(default_user_agent_id))
                    user_agent = user_agent_obj.user_agent
                except (CoreSettings.DoesNotExist, UserAgent.DoesNotExist, ValueError):
                    # Fallback to hardcoded if default not found
                    user_agent = 'Dispatcharr/1.0'

                # Add proper timeouts to prevent hanging
                remote_response = requests.get(
                    logo_url,
                    stream=True,
                    timeout=(3, 5),  # (connect_timeout, read_timeout)
                    headers={'User-Agent': user_agent}
                )
                if remote_response.status_code == 200:
                    # Try to get content type from response headers first
                    content_type = remote_response.headers.get("Content-Type")

                    # If no content type in headers or it's empty, guess based on URL
                    if not content_type:
                        content_type, _ = mimetypes.guess_type(logo_url)

                    # If still no content type, default to common image type
                    if not content_type:
                        content_type = "image/jpeg"

                    response = StreamingHttpResponse(
                        remote_response.iter_content(chunk_size=8192),
                        content_type=content_type,
                    )
                    response["Content-Disposition"] = 'inline; filename="{}"'.format(
                        os.path.basename(logo_url)
                    )
                    return response
                raise Http404("Remote image not found")
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout fetching logo from {logo_url}")
                raise Http404("Logo request timed out")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error fetching logo from {logo_url}")
                raise Http404("Unable to connect to logo server")
            except requests.RequestException as e:
                logger.warning(f"Error fetching logo from {logo_url}: {e}")
                raise Http404("Error fetching remote image")


class ChannelProfileViewSet(viewsets.ModelViewSet):
    queryset = ChannelProfile.objects.all()
    serializer_class = ChannelProfileSerializer

    def get_queryset(self):
        user = self.request.user

        # If user_level is 10, return all ChannelProfiles
        if hasattr(user, "user_level") and user.user_level == 10:
            return ChannelProfile.objects.all()

        # Otherwise, return only ChannelProfiles related to the user
        return self.request.user.channel_profiles.all()

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]


class GetChannelStreamsAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def get(self, request, channel_id):
        channel = get_object_or_404(Channel, id=channel_id)
        # Order the streams by channelstream__order to match the order in the channel view
        streams = channel.streams.all().order_by("channelstream__order")
        serializer = StreamSerializer(streams, many=True)
        return Response(serializer.data)


class UpdateChannelMembershipAPIView(APIView):
    permission_classes = [IsOwnerOfObject]

    def patch(self, request, profile_id, channel_id):
        """Enable or disable a channel for a specific group"""
        channel_profile = get_object_or_404(ChannelProfile, id=profile_id)
        channel = get_object_or_404(Channel, id=channel_id)
        try:
            membership = ChannelProfileMembership.objects.get(
                channel_profile=channel_profile, channel=channel
            )
        except ChannelProfileMembership.DoesNotExist:
            # Create the membership if it does not exist (for custom channels)
            membership = ChannelProfileMembership.objects.create(
                channel_profile=channel_profile,
                channel=channel,
                enabled=False  # Default to False, will be updated below
            )

        serializer = ChannelProfileMembershipSerializer(
            membership, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BulkUpdateChannelMembershipAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def patch(self, request, profile_id):
        """Bulk enable or disable channels for a specific profile"""
        # Get the channel profile
        channel_profile = get_object_or_404(ChannelProfile, id=profile_id)

        # Validate the incoming data using the serializer
        serializer = BulkChannelProfileMembershipSerializer(data=request.data)

        if serializer.is_valid():
            updates = serializer.validated_data["channels"]
            channel_ids = [entry["channel_id"] for entry in updates]

            memberships = ChannelProfileMembership.objects.filter(
                channel_profile=channel_profile, channel_id__in=channel_ids
            )

            membership_dict = {m.channel.id: m for m in memberships}

            for entry in updates:
                channel_id = entry["channel_id"]
                enabled_status = entry["enabled"]
                if channel_id in membership_dict:
                    membership_dict[channel_id].enabled = enabled_status

            ChannelProfileMembership.objects.bulk_update(memberships, ["enabled"])

            return Response({"status": "success"}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RecurringRecordingRuleViewSet(viewsets.ModelViewSet):
    queryset = RecurringRecordingRule.objects.all().select_related("channel")
    serializer_class = RecurringRecordingRuleSerializer

    def get_permissions(self):
        return [IsAdmin()]

    def perform_create(self, serializer):
        rule = serializer.save()
        try:
            sync_recurring_rule_impl(rule.id, drop_existing=True)
        except Exception as err:
            logger.warning(f"Failed to initialize recurring rule {rule.id}: {err}")
        return rule

    def perform_update(self, serializer):
        rule = serializer.save()
        try:
            if rule.enabled:
                sync_recurring_rule_impl(rule.id, drop_existing=True)
            else:
                purge_recurring_rule_impl(rule.id)
        except Exception as err:
            logger.warning(f"Failed to resync recurring rule {rule.id}: {err}")
        return rule

    def perform_destroy(self, instance):
        rule_id = instance.id
        super().perform_destroy(instance)
        try:
            purge_recurring_rule_impl(rule_id)
        except Exception as err:
            logger.warning(f"Failed to purge recordings for rule {rule_id}: {err}")


class RecordingViewSet(viewsets.ModelViewSet):
    queryset = Recording.objects.all()
    serializer_class = RecordingSerializer

    def get_permissions(self):
        # Allow unauthenticated playback of recording files (like other streaming endpoints)
        if getattr(self, 'action', None) == 'file':
            return [AllowAny()]
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    @action(detail=True, methods=["post"], url_path="comskip")
    def comskip(self, request, pk=None):
        """Trigger comskip processing for this recording."""
        from .tasks import comskip_process_recording
        rec = get_object_or_404(Recording, pk=pk)
        try:
            comskip_process_recording.delay(rec.id)
            return Response({"success": True, "queued": True})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=400)

    @action(detail=True, methods=["get"], url_path="file")
    def file(self, request, pk=None):
        """Stream a recorded file with HTTP Range support for seeking."""
        recording = get_object_or_404(Recording, pk=pk)
        cp = recording.custom_properties or {}
        file_path = cp.get("file_path")
        file_name = cp.get("file_name") or "recording"

        if not file_path or not os.path.exists(file_path):
            raise Http404("Recording file not found")

        # Guess content type
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".mp4":
            content_type = "video/mp4"
        elif ext == ".mkv":
            content_type = "video/x-matroska"
        else:
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        file_size = os.path.getsize(file_path)
        range_header = request.META.get("HTTP_RANGE", "").strip()

        def file_iterator(path, start=0, end=None, chunk_size=8192):
            with open(path, "rb") as f:
                f.seek(start)
                remaining = (end - start + 1) if end is not None else None
                while True:
                    if remaining is not None and remaining <= 0:
                        break
                    bytes_to_read = min(chunk_size, remaining) if remaining is not None else chunk_size
                    data = f.read(bytes_to_read)
                    if not data:
                        break
                    if remaining is not None:
                        remaining -= len(data)
                    yield data

        if range_header and range_header.startswith("bytes="):
            # Parse Range header
            try:
                range_spec = range_header.split("=", 1)[1]
                start_str, end_str = range_spec.split("-", 1)
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                start = max(0, start)
                end = min(file_size - 1, end)
                length = end - start + 1

                resp = StreamingHttpResponse(
                    file_iterator(file_path, start, end),
                    status=206,
                    content_type=content_type,
                )
                resp["Content-Range"] = f"bytes {start}-{end}/{file_size}"
                resp["Content-Length"] = str(length)
                resp["Accept-Ranges"] = "bytes"
                resp["Content-Disposition"] = f"inline; filename=\"{file_name}\""
                return resp
            except Exception:
                # Fall back to full file if parsing fails
                pass

        # Full file response
        response = FileResponse(open(file_path, "rb"), content_type=content_type)
        response["Content-Length"] = str(file_size)
        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = f"inline; filename=\"{file_name}\""
        return response

    def destroy(self, request, *args, **kwargs):
        """Delete the Recording and ensure any active DVR client connection is closed.

        Also removes the associated file(s) from disk if present.
        """
        instance = self.get_object()

        # Attempt to close the DVR client connection for this channel if active
        try:
            channel_uuid = str(instance.channel.uuid)
            # Lazy imports to avoid module overhead if proxy isn't used
            from core.utils import RedisClient
            from apps.proxy.ts_proxy.redis_keys import RedisKeys
            from apps.proxy.ts_proxy.services.channel_service import ChannelService

            r = RedisClient.get_client()
            if r:
                client_set_key = RedisKeys.clients(channel_uuid)
                client_ids = r.smembers(client_set_key) or []
                stopped = 0
                for raw_id in client_ids:
                    try:
                        cid = raw_id.decode("utf-8") if isinstance(raw_id, (bytes, bytearray)) else str(raw_id)
                        meta_key = RedisKeys.client_metadata(channel_uuid, cid)
                        ua = r.hget(meta_key, "user_agent")
                        ua_s = ua.decode("utf-8") if isinstance(ua, (bytes, bytearray)) else (ua or "")
                        # Identify DVR recording client by its user agent
                        if ua_s and "Dispatcharr-DVR" in ua_s:
                            try:
                                ChannelService.stop_client(channel_uuid, cid)
                                stopped += 1
                            except Exception as inner_e:
                                logger.debug(f"Failed to stop DVR client {cid} for channel {channel_uuid}: {inner_e}")
                    except Exception as inner:
                        logger.debug(f"Error while checking client metadata: {inner}")
                if stopped:
                    logger.info(f"Stopped {stopped} DVR client(s) for channel {channel_uuid} due to recording cancellation")
                # If no clients remain after stopping DVR clients, proactively stop the channel
                try:
                    remaining = r.scard(client_set_key) or 0
                except Exception:
                    remaining = 0
                if remaining == 0:
                    try:
                        ChannelService.stop_channel(channel_uuid)
                        logger.info(f"Stopped channel {channel_uuid} (no clients remain)")
                    except Exception as sc_e:
                        logger.debug(f"Unable to stop channel {channel_uuid}: {sc_e}")
        except Exception as e:
            logger.debug(f"Unable to stop DVR clients for cancelled recording: {e}")

        # Capture paths before deletion
        cp = instance.custom_properties or {}
        file_path = cp.get("file_path")
        temp_ts_path = cp.get("_temp_file_path")

        # Perform DB delete first, then try to remove files
        response = super().destroy(request, *args, **kwargs)

        # Notify frontends to refresh recordings
        try:
            from core.utils import send_websocket_update
            send_websocket_update('updates', 'update', {"success": True, "type": "recordings_refreshed"})
        except Exception:
            pass

        library_dir = '/data'
        allowed_roots = ['/data/', library_dir.rstrip('/') + '/']

        def _safe_remove(path: str):
            if not path or not isinstance(path, str):
                return
            try:
                if any(path.startswith(root) for root in allowed_roots) and os.path.exists(path):
                    os.remove(path)
                    logger.info(f"Deleted recording artifact: {path}")
            except Exception as ex:
                logger.warning(f"Failed to delete recording artifact {path}: {ex}")

        _safe_remove(file_path)
        _safe_remove(temp_ts_path)

        return response


class ComskipConfigAPIView(APIView):
    """Upload or inspect the custom comskip.ini used by DVR processing."""

    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        return [IsAdmin()]

    def get(self, request):
        path = CoreSettings.get_dvr_comskip_custom_path()
        exists = bool(path and os.path.exists(path))
        return Response({"path": path, "exists": exists})

    def post(self, request):
        uploaded = request.FILES.get("file") or request.FILES.get("comskip_ini")
        if not uploaded:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        name = (uploaded.name or "").lower()
        if not name.endswith(".ini"):
            return Response({"error": "Only .ini files are allowed"}, status=status.HTTP_400_BAD_REQUEST)

        if uploaded.size and uploaded.size > 1024 * 1024:
            return Response({"error": "File too large (limit 1MB)"}, status=status.HTTP_400_BAD_REQUEST)

        dest_dir = os.path.join(settings.MEDIA_ROOT, "comskip")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, "comskip.ini")

        try:
            with open(dest_path, "wb") as dest:
                for chunk in uploaded.chunks():
                    dest.write(chunk)
        except Exception as e:
            logger.error(f"Failed to save uploaded comskip.ini: {e}")
            return Response({"error": "Unable to save file"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Persist path setting so DVR processing picks it up immediately
        CoreSettings.set_dvr_comskip_custom_path(dest_path)

        return Response({"success": True, "path": dest_path, "exists": os.path.exists(dest_path)})


class BulkDeleteUpcomingRecordingsAPIView(APIView):
    """Delete all upcoming (future) recordings."""
    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_method[self.request.method]]
        except KeyError:
            return [Authenticated()]

    def post(self, request):
        now = timezone.now()
        qs = Recording.objects.filter(start_time__gt=now)
        removed = qs.count()
        qs.delete()
        try:
            from core.utils import send_websocket_update
            send_websocket_update('updates', 'update', {"success": True, "type": "recordings_refreshed", "removed": removed})
        except Exception:
            pass
        return Response({"success": True, "removed": removed})


class SeriesRulesAPIView(APIView):
    """Manage DVR series recording rules (list/add)."""
    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_method[self.request.method]]
        except KeyError:
            return [Authenticated()]

    def get(self, request):
        return Response({"rules": CoreSettings.get_dvr_series_rules()})

    def post(self, request):
        data = request.data or {}
        tvg_id = str(data.get("tvg_id") or "").strip()
        mode = (data.get("mode") or "all").lower()
        title = data.get("title") or ""
        if mode not in ("all", "new"):
            return Response({"error": "mode must be 'all' or 'new'"}, status=status.HTTP_400_BAD_REQUEST)
        if not tvg_id:
            return Response({"error": "tvg_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        rules = CoreSettings.get_dvr_series_rules()
        # Upsert by tvg_id
        existing = next((r for r in rules if str(r.get("tvg_id")) == tvg_id), None)
        if existing:
            existing.update({"mode": mode, "title": title})
        else:
            rules.append({"tvg_id": tvg_id, "mode": mode, "title": title})
        CoreSettings.set_dvr_series_rules(rules)
        # Evaluate immediately for this tvg_id (async)
        try:
            evaluate_series_rules.delay(tvg_id)
        except Exception:
            pass
        return Response({"success": True, "rules": rules})


class DeleteSeriesRuleAPIView(APIView):
    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_method[self.request.method]]
        except KeyError:
            return [Authenticated()]

    def delete(self, request, tvg_id):
        tvg_id = unquote(str(tvg_id or ""))
        rules = [r for r in CoreSettings.get_dvr_series_rules() if str(r.get("tvg_id")) != tvg_id]
        CoreSettings.set_dvr_series_rules(rules)
        return Response({"success": True, "rules": rules})


class EvaluateSeriesRulesAPIView(APIView):
    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_method[self.request.method]]
        except KeyError:
            return [Authenticated()]

    def post(self, request):
        tvg_id = request.data.get("tvg_id")
        # Run synchronously so UI sees results immediately
        result = evaluate_series_rules_impl(str(tvg_id)) if tvg_id else evaluate_series_rules_impl()
        return Response({"success": True, **result})


class BulkRemoveSeriesRecordingsAPIView(APIView):
    """Bulk remove scheduled recordings for a series rule.

    POST body:
      - tvg_id: required (EPG channel id)
      - title: optional (series title)
      - scope: 'title' (default) or 'channel'
    """
    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_method[self.request.method]]
        except KeyError:
            return [Authenticated()]

    def post(self, request):
        from django.utils import timezone
        tvg_id = str(request.data.get("tvg_id") or "").strip()
        title = request.data.get("title")
        scope = (request.data.get("scope") or "title").lower()
        if not tvg_id:
            return Response({"error": "tvg_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        qs = Recording.objects.filter(
            start_time__gte=timezone.now(),
            custom_properties__program__tvg_id=tvg_id,
        )
        if scope == "title" and title:
            qs = qs.filter(custom_properties__program__title=title)

        count = qs.count()
        qs.delete()
        try:
            from core.utils import send_websocket_update
            send_websocket_update('updates', 'update', {"success": True, "type": "recordings_refreshed", "removed": count})
        except Exception:
            pass
        return Response({"success": True, "removed": count})
