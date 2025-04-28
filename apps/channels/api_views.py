from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.shortcuts import get_object_or_404, get_list_or_404
from django.db import transaction
import os, json, requests

from .models import Stream, Channel, ChannelGroup, Logo, ChannelProfile, ChannelProfileMembership, Recording
from .serializers import StreamSerializer, ChannelSerializer, ChannelGroupSerializer, LogoSerializer, ChannelProfileMembershipSerializer, BulkChannelProfileMembershipSerializer, ChannelProfileSerializer, RecordingSerializer
from .tasks import match_epg_channels
import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from apps.epg.models import EPGData
from django.db.models import Q
from django.http import StreamingHttpResponse, FileResponse, Http404
import mimetypes

from rest_framework.pagination import PageNumberPagination


class OrInFilter(django_filters.Filter):
    """
    Custom filter that handles the OR condition instead of AND.
    """
    def filter(self, queryset, value):
        if value:
            # Create a Q object for each value and combine them with OR
            query = Q()
            for val in value.split(','):
                query |= Q(**{self.field_name: val})
            return queryset.filter(query)
        return queryset

class StreamPagination(PageNumberPagination):
    page_size = 25  # Default page size
    page_size_query_param = 'page_size'  # Allow clients to specify page size
    max_page_size = 10000  # Prevent excessive page sizes

class StreamFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr='icontains')
    channel_group_name = OrInFilter(field_name="channel_group__name", lookup_expr="icontains")
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
            group_names = channel_group.split(',')
            qs = qs.filter(channel_group__name__in=group_names)

        return qs

    def list(self, request, *args, **kwargs):
        ids = request.query_params.get('ids', None)
        if ids:
            ids = ids.split(',')
            streams = get_list_or_404(Stream, id__in=ids)
            serializer = self.get_serializer(streams, many=True)
            return Response(serializer.data)

        return super().list(request, *args, **kwargs)

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
class ChannelPagination(PageNumberPagination):
    page_size = 25  # Default page size
    page_size_query_param = 'page_size'  # Allow clients to specify page size
    max_page_size = 10000  # Prevent excessive page sizes


    def paginate_queryset(self, queryset, request, view=None):
        if not request.query_params.get(self.page_query_param):
            return None  # disables pagination, returns full queryset

        return super().paginate_queryset(queryset, request, view)

class ChannelFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr='icontains')
    channel_group_name = OrInFilter(field_name="channel_group__name", lookup_expr="icontains")

    class Meta:
        model = Channel
        fields = ['name', 'channel_group_name',]

class ChannelViewSet(viewsets.ModelViewSet):
    queryset = Channel.objects.all()
    serializer_class = ChannelSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ChannelPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ChannelFilter
    search_fields = ['name', 'channel_group__name']
    ordering_fields = ['channel_number', 'name', 'channel_group__name']
    ordering = ['-channel_number']

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            'channel_group',
            'logo',
            'epg_data',
            'stream_profile',
        ).prefetch_related('streams')

        channel_group = self.request.query_params.get('channel_group')
        if channel_group:
            group_names = channel_group.split(',')
            qs = qs.filter(channel_group__name__in=group_names)

        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        include_streams = self.request.query_params.get('include_streams', 'false') == 'true'
        context['include_streams'] = include_streams
        return context

    @action(detail=False, methods=['get'], url_path='ids')
    def get_ids(self, request, *args, **kwargs):
        # Get the filtered queryset
        queryset = self.get_queryset()

        # Apply filtering, search, and ordering
        queryset = self.filter_queryset(queryset)

        # Return only the IDs from the queryset
        channel_ids = queryset.values_list('id', flat=True)

        # Return the response with the list of IDs
        return Response(list(channel_ids))

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
        with transaction.atomic():
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

        name = request.data.get('name')
        if name is None:
            name = stream.name

        # Check if client provided a channel_number; if not, auto-assign one.
        stream_custom_props = json.loads(stream.custom_properties) if stream.custom_properties else {}

        channel_number = None
        if 'tv-chno' in stream_custom_props:
            channel_number = int(stream_custom_props['tv-chno'])
        elif 'tvg-chno' in stream_custom_props:
            channel_number = int(stream_custom_props['tvg-chno'])
        elif 'channel-number' in stream_custom_props:
            channel_number = int(stream_custom_props['channel-number'])

        if channel_number is None:
            provided_number = request.data.get('channel_number')
            if provided_number is None:
                channel_number = Channel.get_next_available_channel_number()
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



        channel_data = {
            'channel_number': channel_number,
            'name': name,
            'tvg_id': stream.tvg_id,
            'channel_group_id': channel_group.id,
            'streams': [stream_id],
        }

        if stream.logo_url:
            logo, _ = Logo.objects.get_or_create(url=stream.logo_url, defaults={
                "name": stream.name or stream.tvg_id
            })
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

        logos_to_create = []
        channels_to_create = []
        streams_map = []
        logo_map = []
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

            name = item.get('name')
            if name is None:
                name = stream.name

            channel_group = stream.channel_group

            stream_custom_props = json.loads(stream.custom_properties) if stream.custom_properties else {}

            channel_number = None
            if 'tv-chno' in stream_custom_props:
                channel_number = int(stream_custom_props['tv-chno'])
            elif 'channel-number' in stream_custom_props:
                channel_number = int(stream_custom_props['channel-number'])

            # Determine channel number: if provided, use it (if free); else auto assign.
            if channel_number is None:
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

            channel_data = {
                "channel_number": channel_number,
                "name": name,
                "tvg_id": stream.tvg_id,
                "channel_group_id": channel_group.id,
            }

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
                    logos_to_create.append(Logo(
                        url=stream.logo_url,
                        name=stream.name or stream.tvg_id,
                    ))
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

        channel_logos = {logo.url: logo for logo in Logo.objects.filter(url__in=[url for url in logo_map if url is not None])}

        profiles = ChannelProfile.objects.all()
        channel_profile_memberships = []
        if channels_to_create:
            with transaction.atomic():
                created_channels = Channel.objects.bulk_create(channels_to_create)

                update = []
                for channel, stream_ids, logo_url in zip(created_channels, streams_map, logo_map):
                    if logo_url:
                        channel.logo = channel_logos[logo_url]
                    update.append(channel)
                    channel_profile_memberships = channel_profile_memberships + [
                       ChannelProfileMembership(channel_profile=profile, channel=channel)
                        for profile in profiles
                    ]

                ChannelProfileMembership.objects.bulk_create(channel_profile_memberships)
                Channel.objects.bulk_update(update, ['logo'])

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
        method='post',
        operation_description="Kick off a Celery task that tries to fuzzy-match channels with EPG data.",
        responses={202: "EPG matching task initiated"}
    )
    @action(detail=False, methods=['post'], url_path='match-epg')
    def match_epg(self, request):
        match_epg_channels.delay()
        return Response({"message": "EPG matching task initiated."}, status=status.HTTP_202_ACCEPTED)

    # ─────────────────────────────────────────────────────────
    # 7) Set EPG and Refresh
    # ─────────────────────────────────────────────────────────
    @swagger_auto_schema(
        method='post',
        operation_description="Set EPG data for a channel and refresh program data",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['epg_data_id'],
            properties={
                'epg_data_id': openapi.Schema(
                    type=openapi.TYPE_INTEGER, description="EPG data ID to link"
                )
            }
        ),
        responses={200: "EPG data linked and refresh triggered"}
    )
    @action(detail=True, methods=['post'], url_path='set-epg')
    def set_epg(self, request, pk=None):
        channel = self.get_object()
        epg_data_id = request.data.get('epg_data_id')

        # Handle removing EPG link
        if epg_data_id in (None, '', '0', 0):
            channel.epg_data = None
            channel.save(update_fields=['epg_data'])
            return Response({"message": f"EPG data removed from channel {channel.name}"})

        try:
            # Get the EPG data object
            from apps.epg.models import EPGData
            epg_data = EPGData.objects.get(pk=epg_data_id)

            # Set the EPG data and save
            channel.epg_data = epg_data
            channel.save(update_fields=['epg_data'])

            # Explicitly trigger program refresh for this EPG
            from apps.epg.tasks import parse_programs_for_tvg_id
            task_result = parse_programs_for_tvg_id.delay(epg_data.id)

            # Prepare response with task status info
            status_message = "EPG refresh queued"
            if task_result.result == "Task already running":
                status_message = "EPG refresh already in progress"

            return Response({
                "message": f"EPG data set to {epg_data.tvg_id} for channel {channel.name}. {status_message}.",
                "channel": self.get_serializer(channel).data,
                "task_status": status_message
            })
        except Exception as e:
            return Response({"error": str(e)}, status=400)

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

class LogoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Logo.objects.all()
    serializer_class = LogoSerializer
    parser_classes = (MultiPartParser, FormParser)

    @action(detail=False, methods=['post'])
    def upload(self, request):
        if 'file' not in request.FILES:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        file = request.FILES['file']
        file_name = file.name
        file_path = os.path.join('/data/logos', file_name)

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        logo, _ = Logo.objects.get_or_create(url=file_path, defaults={
            "name": file_name,
        })

        return Response({'id': logo.id, 'name': logo.name, 'url': logo.url}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def cache(self, request, pk=None):
        """Streams the logo file, whether it's local or remote."""
        logo = self.get_object()
        logo_url = logo.url

        if logo_url.startswith("/data"):  # Local file
            if not os.path.exists(logo_url):
                raise Http404("Image not found")
            mimetype = mimetypes.guess_type(logo_url)
            return FileResponse(open(logo_url, "rb"), content_type=mimetype)

        else:  # Remote image
            try:
                remote_response = requests.get(logo_url, stream=True)
                if remote_response.status_code == 200:
                    return StreamingHttpResponse(remote_response.iter_content(chunk_size=8192), content_type=remote_response.headers['Content-Type'])
                raise Http404("Remote image not found")
            except requests.RequestException:
                raise Http404("Error fetching remote image")

class ChannelProfileViewSet(viewsets.ModelViewSet):
    queryset = ChannelProfile.objects.all()
    serializer_class = ChannelProfileSerializer
    permission_classes = [IsAuthenticated]

class GetChannelStreamsAPIView(APIView):
    def get(self, request, channel_id):
        channel = get_object_or_404(Channel, id=channel_id)
        # Order the streams by channelstream__order to match the order in the channel view
        streams = channel.streams.all().order_by('channelstream__order')
        serializer = StreamSerializer(streams, many=True)
        return Response(serializer.data)

class UpdateChannelMembershipAPIView(APIView):
    def patch(self, request, profile_id, channel_id):
        """Enable or disable a channel for a specific group"""
        channel_profile = get_object_or_404(ChannelProfile, id=profile_id)
        channel = get_object_or_404(Channel, id=channel_id)
        membership = get_object_or_404(ChannelProfileMembership, channel_profile=channel_profile, channel=channel)

        serializer = ChannelProfileMembershipSerializer(membership, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BulkUpdateChannelMembershipAPIView(APIView):
    def patch(self, request, profile_id):
        """Bulk enable or disable channels for a specific profile"""
        # Get the channel profile
        channel_profile = get_object_or_404(ChannelProfile, id=profile_id)

        # Validate the incoming data using the serializer
        serializer = BulkChannelProfileMembershipSerializer(data=request.data)

        if serializer.is_valid():
            updates = serializer.validated_data['channels']
            channel_ids = [entry['channel_id'] for entry in updates]

            memberships = ChannelProfileMembership.objects.filter(
                channel_profile=channel_profile,
                channel_id__in=channel_ids
            )

            membership_dict = {m.channel.id: m for m in memberships}

            for entry in updates:
                channel_id = entry['channel_id']
                enabled_status = entry['enabled']
                if channel_id in membership_dict:
                    membership_dict[channel_id].enabled = enabled_status

            ChannelProfileMembership.objects.bulk_update(memberships, ['enabled'])

            return Response({"status": "success"}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class RecordingViewSet(viewsets.ModelViewSet):
    queryset = Recording.objects.all()
    serializer_class = RecordingSerializer
    permission_classes = [IsAuthenticated]
