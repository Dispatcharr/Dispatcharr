from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.shortcuts import get_object_or_404, get_list_or_404
from django.db import transaction
import os, json, requests, logging
from apps.accounts.permissions import (
    Authenticated,
    IsAdmin,
    IsOwnerOfObject,
    permission_classes_by_action,
    permission_classes_by_method,
)

from core.models import UserAgent, CoreSettings

from .models import (
    Stream,
    Channel,
    ChannelGroup,
    Logo,
    ChannelProfile,
    ChannelProfileMembership,
    Recording,
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
)
from .tasks import match_epg_channels
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from apps.epg.models import EPGData
from django.db.models import Q
from django.http import StreamingHttpResponse, FileResponse, Http404
import mimetypes

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
    ordering_fields = ["name", "channel_group__name"]
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
        """Add annotation for association counts"""
        from django.db.models import Count
        return ChannelGroup.objects.annotate(
            channel_count=Count('channels', distinct=True),
            m3u_account_count=Count('m3u_account', distinct=True)
        )

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
        from django.db.models import Count

        # Find groups with no channels and no M3U account associations
        unused_groups = ChannelGroup.objects.annotate(
            channel_count=Count('channels', distinct=True),
            m3u_account_count=Count('m3u_account', distinct=True)
        ).filter(
            channel_count=0,
            m3u_account_count=0
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


class ChannelFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    channel_group_name = OrInFilter(
        field_name="channel_group__name", lookup_expr="icontains"
    )

    class Meta:
        model = Channel
        fields = [
            "name",
            "channel_group_name",
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

        if self.request.user.user_level < 10:
            qs = qs.filter(user_level__lte=self.request.user.user_level)

        return qs

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
        Bulk edit channels.
        Expects a list of channels with their updates.
        """
        data = request.data
        if not isinstance(data, list):
            return Response(
                {"error": "Expected a list of channel updates"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated_channels = []
        errors = []

        for channel_data in data:
            channel_id = channel_data.get("id")
            if not channel_id:
                errors.append({"error": "Channel ID is required"})
                continue

            try:
                channel = Channel.objects.get(id=channel_id)

                # Handle channel_group_id properly - convert string to integer if needed
                if 'channel_group_id' in channel_data:
                    group_id = channel_data['channel_group_id']
                    if group_id is not None:
                        try:
                            channel_data['channel_group_id'] = int(group_id)
                        except (ValueError, TypeError):
                            channel_data['channel_group_id'] = None

                # Use the serializer to validate and update
                serializer = ChannelSerializer(
                    channel, data=channel_data, partial=True
                )

                if serializer.is_valid():
                    updated_channel = serializer.save()
                    updated_channels.append(updated_channel)
                else:
                    errors.append({
                        "channel_id": channel_id,
                        "errors": serializer.errors
                    })

            except Channel.DoesNotExist:
                errors.append({
                    "channel_id": channel_id,
                    "error": "Channel not found"
                })
            except Exception as e:
                errors.append({
                    "channel_id": channel_id,
                    "error": str(e)
                })

        if errors:
            return Response(
                {"errors": errors, "updated_count": len(updated_channels)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Serialize the updated channels for response
        serialized_channels = ChannelSerializer(updated_channels, many=True).data

        return Response({
            "message": f"Successfully updated {len(updated_channels)} channels",
            "channels": serialized_channels
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
            "otherwise, the next available channel number is assigned."
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
        stream_custom_props = (
            json.loads(stream.custom_properties) if stream.custom_properties else {}
        )

        channel_number = None
        if "tvg-chno" in stream_custom_props:
            channel_number = float(stream_custom_props["tvg-chno"])
        elif "channel-number" in stream_custom_props:
            channel_number = float(stream_custom_props["channel-number"])
        elif "num" in stream_custom_props:
            channel_number = float(stream_custom_props["num"])

        if channel_number is None:
            provided_number = request.data.get("channel_number")
            if provided_number is None:
                channel_number = Channel.get_next_available_channel_number()
            else:
                try:
                    channel_number = float(provided_number)
                except ValueError:
                    return Response(
                        {"error": "channel_number must be an integer."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # If the provided number is already used, return an error.
                if Channel.objects.filter(channel_number=channel_number).exists():
                    return Response(
                        {
                            "error": f"Channel number {channel_number} is already in use. Please choose a different number."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
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
            logo, _ = Logo.objects.get_or_create(
                url=stream.logo_url, defaults={"name": stream.name or stream.tvg_id}
            )
            channel_data["logo_id"] = logo.id

        # Attempt to find existing EPGs with the same tvg-id
        epgs = EPGData.objects.filter(tvg_id=stream.tvg_id)
        if epgs:
            channel_data["epg_data_id"] = epgs.first().id

        serializer = self.get_serializer(data=channel_data)
        serializer.is_valid(raise_exception=True)
        channel = serializer.save()
        channel.streams.add(stream)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        method="post",
        operation_description=(
            "Bulk create channels from existing streams. For each object, if 'channel_number' is provided, "
            "it is used (if available); otherwise, the next available number is auto-assigned. "
            "Each object must include 'stream_id' and 'name'."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_ARRAY,
            items=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                required=["stream_id"],
                properties={
                    "stream_id": openapi.Schema(
                        type=openapi.TYPE_INTEGER,
                        description="ID of the stream to link",
                    ),
                    "channel_number": openapi.Schema(
                        type=openapi.TYPE_NUMBER,
                        description="(Optional) Desired channel number. Must not be in use.",
                    ),
                    "name": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Desired channel name"
                    ),
                },
            ),
        ),
        responses={201: "Bulk channels created"},
    )
    @action(detail=False, methods=["post"], url_path="from-stream/bulk")
    def from_stream_bulk(self, request):
        data_list = request.data
        if not isinstance(data_list, list):
            return Response(
                {"error": "Expected a list of channel objects"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_channels = []
        errors = []

        # Gather current used numbers once.
        used_numbers = set(
            Channel.objects.all().values_list("channel_number", flat=True)
        )
        next_number = 1

        def get_auto_number():
            nonlocal next_number
            while next_number in used_numbers:
                next_number += 1
            used_numbers.add(next_number)
            return next_number

        logos_to_create = []
        channels_to_create = []
        streams_map = []
        logo_map = []
        for item in data_list:
            stream_id = item.get("stream_id")
            if not all([stream_id]):
                errors.append(
                    {
                        "item": item,
                        "error": "Missing required fields: stream_id and name are required.",
                    }
                )
                continue

            try:
                stream = get_object_or_404(Stream, pk=stream_id)
            except Exception as e:
                errors.append({"item": item, "error": str(e)})
                continue

            name = item.get("name")
            if name is None:
                name = stream.name

            channel_group = stream.channel_group

            stream_custom_props = (
                json.loads(stream.custom_properties) if stream.custom_properties else {}
            )

            channel_number = None
            if "tvg-chno" in stream_custom_props:
                channel_number = float(stream_custom_props["tvg-chno"])
            elif "channel-number" in stream_custom_props:
                channel_number = float(stream_custom_props["channel-number"])
            elif "num" in stream_custom_props:
                channel_number = float(stream_custom_props["num"])
            # Get the tvc_guide_stationid from custom properties if it exists
            tvc_guide_stationid = None
            if "tvc-guide-stationid" in stream_custom_props:
                tvc_guide_stationid = stream_custom_props["tvc-guide-stationid"]

            # Determine channel number: if provided, use it (if free); else auto assign.
            if channel_number is None:
                provided_number = item.get("channel_number")
                if provided_number is None:
                    channel_number = get_auto_number()
                else:
                    try:
                        channel_number = float(provided_number)
                    except ValueError:
                        errors.append(
                            {
                                "item": item,
                                "error": "channel_number must be an integer.",
                            }
                        )
                        continue
                    if (
                        channel_number in used_numbers
                        or Channel.objects.filter(
                            channel_number=channel_number
                        ).exists()
                    ):
                        errors.append(
                            {
                                "item": item,
                                "error": f"Channel number {channel_number} is already in use.",
                            }
                        )
                        continue
                    used_numbers.add(channel_number)

            channel_data = {
                "channel_number": channel_number,
                "name": name,
                "tvc_guide_stationid": tvc_guide_stationid,
                "tvg_id": stream.tvg_id,
            }

            # Only add channel_group_id if the stream has a channel group
            if channel_group:
                channel_data["channel_group_id"] = channel_group.id

            # Attempt to find existing EPGs with the same tvg-id
            epgs = EPGData.objects.filter(tvg_id=stream.tvg_id)
            if epgs:
                channel_data["epg_data_id"] = epgs.first().id

            serializer = self.get_serializer(data=channel_data)
            if serializer.is_valid():
                validated_data = serializer.validated_data
                channel = Channel(**validated_data)
                channels_to_create.append(channel)

                streams_map.append([stream_id])
                if stream.logo_url:
                    logos_to_create.append(
                        Logo(
                            url=stream.logo_url,
                            name=stream.name or stream.tvg_id,
                        )
                    )
                    logo_map.append(stream.logo_url)
                else:
                    logo_map.append(None)

                # channel = serializer.save()
                # channel.streams.add(stream)
                # created_channels.append(serializer.data)
            else:
                errors.append({"item": item, "error": serializer.errors})

        if logos_to_create:
            Logo.objects.bulk_create(logos_to_create, ignore_conflicts=True)

        channel_logos = {
            logo.url: logo
            for logo in Logo.objects.filter(
                url__in=[url for url in logo_map if url is not None]
            )
        }

        profiles = ChannelProfile.objects.all()
        channel_profile_memberships = []
        if channels_to_create:
            with transaction.atomic():
                created_channels = Channel.objects.bulk_create(channels_to_create)

                update = []
                for channel, stream_ids, logo_url in zip(
                    created_channels, streams_map, logo_map
                ):
                    if logo_url:
                        channel.logo = channel_logos[logo_url]
                    update.append(channel)
                    channel_profile_memberships = channel_profile_memberships + [
                        ChannelProfileMembership(
                            channel_profile=profile, channel=channel
                        )
                        for profile in profiles
                    ]

                ChannelProfileMembership.objects.bulk_create(
                    channel_profile_memberships
                )
                Channel.objects.bulk_update(update, ["logo"])

                for channel, stream_ids in zip(created_channels, streams_map):
                    channel.streams.set(stream_ids)

        response_data = {"created": ChannelSerializer(created_channels, many=True).data}
        if errors:
            response_data["errors"] = errors

        return Response(response_data, status=status.HTTP_201_CREATED)

    # ─────────────────────────────────────────────────────────
    # 6) EPG Fuzzy Matching
    # ─────────────────────────────────────────────────────────
    @swagger_auto_schema(
        method="post",
        operation_description="Kick off a Celery task that tries to fuzzy-match channels with EPG data.",
        responses={202: "EPG matching task initiated"},
    )
    @action(detail=False, methods=["post"], url_path="match-epg")
    def match_epg(self, request):
        match_epg_channels.delay()
        return Response(
            {"message": "EPG matching task initiated."}, status=status.HTTP_202_ACCEPTED
        )

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

            # Explicitly trigger program refresh for this EPG
            from apps.epg.tasks import parse_programs_for_tvg_id

            task_result = parse_programs_for_tvg_id.delay(epg_data.id)

            # Prepare response with task status info
            status_message = "EPG refresh queued"
            if task_result.result == "Task already running":
                status_message = "EPG refresh already in progress"

            return Response(
                {
                    "message": f"EPG data set to {epg_data.tvg_id} for channel {channel.name}. {status_message}.",
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
        channels_updated = 0
        programs_refreshed = 0
        unique_epg_ids = set()

        for assoc in associations:
            channel_id = assoc.get("channel_id")
            epg_data_id = assoc.get("epg_data_id")

            if not channel_id:
                continue

            try:
                # Get the channel
                channel = Channel.objects.get(id=channel_id)

                # Set the EPG data
                channel.epg_data_id = epg_data_id
                channel.save(update_fields=["epg_data"])
                channels_updated += 1

                # Track unique EPG data IDs
                if epg_data_id:
                    unique_epg_ids.add(epg_data_id)

            except Channel.DoesNotExist:
                logger.error(f"Channel with ID {channel_id} not found")
            except Exception as e:
                logger.error(
                    f"Error setting EPG data for channel {channel_id}: {str(e)}"
                )

        # Trigger program refresh for unique EPG data IDs
        from apps.epg.tasks import parse_programs_for_tvg_id

        for epg_id in unique_epg_ids:
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
        operation_description="Delete all logos that are not used by any channels",
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
        """Delete all logos with no channel associations"""
        delete_files = request.data.get("delete_files", False)
        
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


class BulkDownloadLogosFromEPGAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]
    
    @swagger_auto_schema(
        operation_description="Download and save logos locally from EPGData logo_urls (Schedules Direct)",
        responses={200: "Logo download initiated"},
    )
    def post(self, request):
        """Download logos from EPGData records that have logo_urls"""
        try:
            from apps.epg.models import EPGData, EPGSource
            from apps.epg.tasks import download_logo_from_url
            
            # Check if any Schedules Direct sources exist
            schedules_direct_sources = EPGSource.objects.filter(source_type='schedules_direct')
            if not schedules_direct_sources.exists():
                return Response({
                    "error": "No Schedules Direct sources found"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get all EPG data with logo URLs that don't already have locally stored logos
            epg_data_with_logos = EPGData.objects.filter(
                logo_url__isnull=False,
                epg_source__source_type='schedules_direct'
            ).exclude(logo_url='')
            
            if not epg_data_with_logos.exists():
                return Response({
                    "message": "No EPG data with logo URLs found",
                    "downloaded_count": 0
                })
            
            downloaded_count = 0
            skipped_count = 0
            error_count = 0
            
            for epg_data in epg_data_with_logos:
                try:
                    # Check if we already have this logo URL
                    existing_logo = Logo.objects.filter(url=epg_data.logo_url).first()
                    if existing_logo:
                        skipped_count += 1
                        continue
                    
                    # Download and save the logo
                    downloaded_logo = download_logo_from_url(epg_data.logo_url, epg_data.name)
                    if downloaded_logo:
                        # Update any channels that use this EPG data to use the new logo
                        from apps.channels.models import Channel
                        channels_using_epg = Channel.objects.filter(epg_data=epg_data)
                        for channel in channels_using_epg:
                            if not channel.logo:  # Only set if channel doesn't already have a logo
                                channel.logo = downloaded_logo
                                channel.save(update_fields=['logo'])
                                logger.info(f"Updated channel {channel.name} to use downloaded logo")
                        
                        downloaded_count += 1
                        logger.info(f"Downloaded logo for {epg_data.name}")
                    else:
                        error_count += 1
                        
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error downloading logo for {epg_data.name}: {e}")
            
            return Response({
                "message": f"Logo download completed. Downloaded {downloaded_count}, skipped {skipped_count}, errors {error_count}",
                "downloaded_count": downloaded_count,
                "skipped_count": skipped_count,
                "error_count": error_count,
                "total_processed": epg_data_with_logos.count()
            })
            
        except Exception as e:
            logger.error(f"Error in bulk logo download: {e}")
            return Response({
                "error": f"Failed to download logos: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LogoViewSet(viewsets.ModelViewSet):
    queryset = Logo.objects.all()
    serializer_class = LogoSerializer
    parser_classes = (MultiPartParser, FormParser)

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
        queryset = Logo.objects.prefetch_related('channels').order_by('name')

        # Filter by usage
        used_filter = self.request.query_params.get('used', None)
        if used_filter == 'true':
            queryset = queryset.filter(channels__isnull=False).distinct()
        elif used_filter == 'false':
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
        return super().update(request, *args, **kwargs)

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

        logo, _ = Logo.objects.get_or_create(
            url=file_path,
            defaults={
                "name": file_name,
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
        membership = get_object_or_404(
            ChannelProfileMembership, channel_profile=channel_profile, channel=channel
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


class RecordingViewSet(viewsets.ModelViewSet):
    queryset = Recording.objects.all()
    serializer_class = RecordingSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]
