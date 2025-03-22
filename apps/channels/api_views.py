from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.shortcuts import get_object_or_404

from .models import Stream, Channel, ChannelGroup
from .serializers import StreamSerializer, ChannelSerializer, ChannelGroupSerializer
from .tasks import match_epg_channels
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from rest_framework.pagination import PageNumberPagination

class StreamPagination(PageNumberPagination):
    page_size = 25  # Default page size
    page_size_query_param = 'page_size'  # Allow clients to specify page size
    max_page_size = 10000  # Prevent excessive page sizes

class StreamFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr='icontains')
    channel_group_name = django_filters.CharFilter(field_name="channel_group__name", lookup_expr="icontains")
    m3u_account = django_filters.NumberFilter(field_name="m3u_account__id")
    m3u_account_name = django_filters.CharFilter(field_name="m3u_account__name", lookup_expr="icontains")
    m3u_account_is_active = django_filters.BooleanFilter(field_name="m3u_account__is_active")

    class Meta:
        model = Stream
        fields = ['name', 'channel_group_name', 'm3u_account', 'm3u_account_name', 'm3u_account_is_active']

# ─────────────────────────────────────────────────────────
# 1) Stream API (CRUD)
# ─────────────────────────────────────────────────────────
class StreamViewSet(viewsets.ModelViewSet):
    queryset = Stream.objects.all()
    serializer_class = StreamSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StreamPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StreamFilter
    search_fields = ['name', 'channel_group__name']
    ordering_fields = ['name', 'channel_group__name']
    ordering = ['-name']

    def get_queryset(self):
        qs = super().get_queryset()
        # Exclude streams from inactive M3U accounts
        qs = qs.exclude(m3u_account__is_active=False)

        assigned = self.request.query_params.get('assigned')
        if assigned is not None:
            qs = qs.filter(channels__id=assigned)

        unassigned = self.request.query_params.get('unassigned')
        if unassigned == '1':
            qs = qs.filter(channels__isnull=True)

        channel_group = self.request.query_params.get('channel_group')
        if channel_group:
            qs = qs.filter(channel_group__name=channel_group)

        return qs

    @action(detail=False, methods=['get'], url_path='ids')
    def get_ids(self, request, *args, **kwargs):
        # Get the filtered queryset
        queryset = self.get_queryset()

        # Apply filtering, search, and ordering
        queryset = self.filter_queryset(queryset)

        # Return only the IDs from the queryset
        stream_ids = queryset.values_list('id', flat=True)

        # Return the response with the list of IDs
        return Response(list(stream_ids))

    @action(detail=False, methods=['get'], url_path='groups')
    def get_groups(self, request, *args, **kwargs):
        # Get unique ChannelGroup names that are linked to streams
        group_names = ChannelGroup.objects.filter(streams__isnull=False).order_by('name').values_list('name', flat=True).distinct()

        # Return the response with the list of unique group names
        return Response(list(group_names))

# ─────────────────────────────────────────────────────────
# 2) Channel Group Management (CRUD)
# ─────────────────────────────────────────────────────────
class ChannelGroupViewSet(viewsets.ModelViewSet):
    queryset = ChannelGroup.objects.all()
    serializer_class = ChannelGroupSerializer
    permission_classes = [IsAuthenticated]


# ─────────────────────────────────────────────────────────
# 3) Channel Management (CRUD)
# ─────────────────────────────────────────────────────────
class ChannelViewSet(viewsets.ModelViewSet):
    queryset = Channel.objects.all()
    serializer_class = ChannelSerializer
    permission_classes = [IsAuthenticated]

    def get_next_available_channel_number(self, starting_from=1):
        used_numbers = set(Channel.objects.all().values_list('channel_number', flat=True))
        n = starting_from
        while n in used_numbers:
            n += 1
        return n

    @swagger_auto_schema(
        method='post',
        operation_description="Auto-assign channel_number in bulk by an ordered list of channel IDs.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["channel_order"],
            properties={
                "channel_order": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="List of channel IDs in the new order"
                )
            }
        ),
        responses={200: "Channels have been auto-assigned!"}
    )
    @action(detail=False, methods=['post'], url_path='assign')
    def assign(self, request):
        channel_order = request.data.get('channel_order', [])
        for order, channel_id in enumerate(channel_order, start=1):
            Channel.objects.filter(id=channel_id).update(channel_number=order)
        return Response({"message": "Channels have been auto-assigned!"}, status=status.HTTP_200_OK)

    @swagger_auto_schema(
        method='post',
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
                    type=openapi.TYPE_INTEGER,
                    description="(Optional) Desired channel number. Must not be in use."
                ),
                "name": openapi.Schema(
                    type=openapi.TYPE_STRING, description="Desired channel name"
                )
            }
        ),
        responses={201: ChannelSerializer()}
    )
    @action(detail=False, methods=['post'], url_path='from-stream')
    def from_stream(self, request):
        stream_id = request.data.get('stream_id')
        if not stream_id:
            return Response({"error": "Missing stream_id"}, status=status.HTTP_400_BAD_REQUEST)
        stream = get_object_or_404(Stream, pk=stream_id)
        channel_group = stream.channel_group

        # Check if client provided a channel_number; if not, auto-assign one.
        provided_number = request.data.get('channel_number')
        if provided_number is None:
            channel_number = self.get_next_available_channel_number()
        else:
            try:
                channel_number = int(provided_number)
            except ValueError:
                return Response({"error": "channel_number must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
            # If the provided number is already used, return an error.
            if Channel.objects.filter(channel_number=channel_number).exists():
                return Response(
                    {"error": f"Channel number {channel_number} is already in use. Please choose a different number."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        name = request.data.get('name')
        if name is None:
            name = stream.name

        channel_data = {
            'channel_number': channel_number,
            'name': name,
            'tvg_id': stream.tvg_id,
            'channel_group_id': channel_group.id,
            'logo_url': stream.logo_url,
            'streams': [stream_id]
        }
        serializer = self.get_serializer(data=channel_data)
        serializer.is_valid(raise_exception=True)
        channel = serializer.save()
        channel.streams.add(stream)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        method='post',
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
                        type=openapi.TYPE_INTEGER, description="ID of the stream to link"
                    ),
                    "channel_number": openapi.Schema(
                        type=openapi.TYPE_INTEGER,
                        description="(Optional) Desired channel number. Must not be in use."
                    ),
                    "name": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Desired channel name"
                    )
                }
            )
        ),
        responses={201: "Bulk channels created"}
    )
    @action(detail=False, methods=['post'], url_path='from-stream/bulk')
    def from_stream_bulk(self, request):
        data_list = request.data
        if not isinstance(data_list, list):
            return Response({"error": "Expected a list of channel objects"}, status=status.HTTP_400_BAD_REQUEST)

        created_channels = []
        errors = []

        # Gather current used numbers once.
        used_numbers = set(Channel.objects.all().values_list('channel_number', flat=True))
        next_number = 1

        def get_auto_number():
            nonlocal next_number
            while next_number in used_numbers:
                next_number += 1
            used_numbers.add(next_number)
            return next_number

        for item in data_list:
            stream_id = item.get('stream_id')
            if not all([stream_id]):
                errors.append({"item": item, "error": "Missing required fields: stream_id and name are required."})
                continue

            try:
                stream = get_object_or_404(Stream, pk=stream_id)
            except Exception as e:
                errors.append({"item": item, "error": str(e)})
                continue

            channel_group = stream.channel_group

            # Determine channel number: if provided, use it (if free); else auto assign.
            provided_number = item.get('channel_number')
            if provided_number is None:
                channel_number = get_auto_number()
            else:
                try:
                    channel_number = int(provided_number)
                except ValueError:
                    errors.append({"item": item, "error": "channel_number must be an integer."})
                    continue
                if channel_number in used_numbers or Channel.objects.filter(channel_number=channel_number).exists():
                    errors.append({"item": item, "error": f"Channel number {channel_number} is already in use."})
                    continue
                used_numbers.add(channel_number)

            name = item.get('name')
            if name is None:
                name = stream.name

            channel_data = {
                "channel_number": channel_number,
                "name": name,
                "tvg_id": stream.tvg_id,
                "channel_group_id": channel_group.id,
                "logo_url": stream.logo_url,
                "streams": [stream_id],
            }
            serializer = self.get_serializer(data=channel_data)
            if serializer.is_valid():
                channel = serializer.save()
                channel.streams.add(stream)
                created_channels.append(serializer.data)
            else:
                errors.append({"item": item, "error": serializer.errors})

        response_data = {"created": created_channels}
        if errors:
            response_data["errors"] = errors

        return Response(response_data, status=status.HTTP_201_CREATED)

    # ─────────────────────────────────────────────────────────
    # 6) EPG Fuzzy Matching
    # ─────────────────────────────────────────────────────────
    @swagger_auto_schema(
        method='post',
        operation_description="Kick off a Celery task that tries to fuzzy-match channels with EPG data.",
        responses={202: "EPG matching task initiated"}
    )
    @action(detail=False, methods=['post'], url_path='match-epg')
    def match_epg(self, request):
        match_epg_channels.delay()
        return Response({"message": "EPG matching task initiated."}, status=status.HTTP_202_ACCEPTED)


# ─────────────────────────────────────────────────────────
# 4) Bulk Delete Streams
# ─────────────────────────────────────────────────────────
class BulkDeleteStreamsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Bulk delete streams by ID",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["stream_ids"],
            properties={
                "stream_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="Stream IDs to delete"
                )
            },
        ),
        responses={204: "Streams deleted"}
    )
    def delete(self, request, *args, **kwargs):
        stream_ids = request.data.get('stream_ids', [])
        Stream.objects.filter(id__in=stream_ids).delete()
        return Response({"message": "Streams deleted successfully!"}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────
# 5) Bulk Delete Channels
# ─────────────────────────────────────────────────────────
class BulkDeleteChannelsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Bulk delete channels by ID",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["channel_ids"],
            properties={
                "channel_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="Channel IDs to delete"
                )
            },
        ),
        responses={204: "Channels deleted"}
    )
    def delete(self, request):
        channel_ids = request.data.get('channel_ids', [])
        Channel.objects.filter(id__in=channel_ids).delete()
        return Response({"message": "Channels deleted"}, status=status.HTTP_204_NO_CONTENT)
