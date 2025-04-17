import logging, os
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.utils import timezone
from datetime import timedelta
from .models import EPGSource, ProgramData, EPGData  # Added ProgramData
from .serializers import ProgramDataSerializer, EPGSourceSerializer, EPGDataSerializer # Updated serializer
from .tasks import refresh_epg_data

logger = logging.getLogger(__name__)

# ─────────────────────────────
# 1) EPG Source API (CRUD)
# ─────────────────────────────
class EPGSourceViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for EPG sources"""
    queryset = EPGSource.objects.all()
    serializer_class = EPGSourceSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        logger.debug("Listing all EPG sources.")
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['post'])
    def upload(self, request):
        if 'file' not in request.FILES:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        file = request.FILES['file']
        file_name = file.name
        file_path = os.path.join('/data/uploads/epgs', file_name)

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        new_obj_data = request.data.copy()
        new_obj_data['file_path'] = file_path

        serializer = self.get_serializer(data=new_obj_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

# ─────────────────────────────
# 2) Program API (CRUD)
# ─────────────────────────────
class ProgramViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for EPG programs"""
    queryset = ProgramData.objects.all()
    serializer_class = ProgramDataSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        logger.debug("Listing all EPG programs.")
        return super().list(request, *args, **kwargs)

# ─────────────────────────────
# 3) EPG Grid View
# ─────────────────────────────
class EPGGridAPIView(APIView):
    """Returns all programs airing in the next 24 hours including currently running ones and recent ones"""

    @swagger_auto_schema(
        operation_description="Retrieve programs from the previous hour, currently running and upcoming for the next 24 hours",
        responses={200: ProgramDataSerializer(many=True)}
    )
    def get(self, request, format=None):
        # Use current time instead of midnight
        now = timezone.now()
        one_hour_ago = now - timedelta(hours=1)
        twenty_four_hours_later = now + timedelta(hours=24)
        logger.debug(f"EPGGridAPIView: Querying programs between {one_hour_ago} and {twenty_four_hours_later}.")

        # Use select_related to prefetch EPGData and include programs from the last hour
        programs = ProgramData.objects.select_related('epg').filter(
            # Programs that end after one hour ago (includes recently ended programs)
            end_time__gt=one_hour_ago,
            # AND start before the end time window
            start_time__lt=twenty_four_hours_later
        )
        count = programs.count()
        logger.debug(f"EPGGridAPIView: Found {count} program(s), including recently ended, currently running, and upcoming shows.")

        # Generate dummy programs for channels that have no EPG data
        from apps.channels.models import Channel
        from django.db.models import Q

        # Get channels with no EPG data
        channels_without_epg = Channel.objects.filter(Q(epg_data__isnull=True))
        channels_count = channels_without_epg.count()

        # Log more detailed information about channels missing EPG data
        if channels_count > 0:
            channel_names = [f"{ch.name} (ID: {ch.id})" for ch in channels_without_epg]
            logger.warning(f"EPGGridAPIView: Missing EPG data for these channels: {', '.join(channel_names)}")

        logger.debug(f"EPGGridAPIView: Found {channels_count} channels with no EPG data.")

        # Serialize the regular programs
        serialized_programs = ProgramDataSerializer(programs, many=True).data

        # Generate and append dummy programs
        dummy_programs = []
        for channel in channels_without_epg:
            # Use the channel UUID as tvg_id for dummy programs to match in the guide
            dummy_tvg_id = str(channel.uuid)

            try:
                # Create programs every 4 hours for the next 24 hours
                for hour_offset in range(0, 24, 4):
                    # Use timedelta for time arithmetic instead of replace() to avoid hour overflow
                    start_time = now + timedelta(hours=hour_offset)
                    # Set minutes/seconds to zero for clean time blocks
                    start_time = start_time.replace(minute=0, second=0, microsecond=0)
                    end_time = start_time + timedelta(hours=4)

                    # Create a dummy program in the same format as regular programs
                    dummy_program = {
                        'id': f"dummy-{channel.id}-{hour_offset}",  # Create a unique ID
                        'epg': {
                            'tvg_id': dummy_tvg_id,
                            'name': channel.name
                        },
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'title': f"{channel.name}",
                        'description': f"Placeholder program for {channel.name}",
                        'tvg_id': dummy_tvg_id,
                        'sub_title': None,
                        'custom_properties': None
                    }
                    dummy_programs.append(dummy_program)

                # Also update the channel to use this dummy tvg_id
                channel.tvg_id = dummy_tvg_id
                channel.save(update_fields=['tvg_id'])

            except Exception as e:
                logger.error(f"Error creating dummy programs for channel {channel.name} (ID: {channel.id}): {str(e)}")

        # Combine regular and dummy programs
        all_programs = list(serialized_programs) + dummy_programs
        logger.debug(f"EPGGridAPIView: Returning {len(all_programs)} total programs (including {len(dummy_programs)} dummy programs).")

        return Response({'data': all_programs}, status=status.HTTP_200_OK)

# ─────────────────────────────
# 4) EPG Import View
# ─────────────────────────────
class EPGImportAPIView(APIView):
    """Triggers an EPG data refresh"""

    @swagger_auto_schema(
        operation_description="Triggers an EPG data import",
        responses={202: "EPG data import initiated"}
    )
    def post(self, request, format=None):
        logger.info("EPGImportAPIView: Received request to import EPG data.")
        refresh_epg_data.delay(request.data.get('id', None))  # Trigger Celery task
        logger.info("EPGImportAPIView: Task dispatched to refresh EPG data.")
        return Response({'success': True, 'message': 'EPG data import initiated.'}, status=status.HTTP_202_ACCEPTED)


# ─────────────────────────────
# 5) EPG Data View
# ─────────────────────────────
class EPGDataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows EPGData objects to be viewed.
    """
    queryset = EPGData.objects.all()
    serializer_class = EPGDataSerializer
    permission_classes = [IsAuthenticated]
