from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import Authenticated, permission_classes_by_action
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
import logging
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.shortcuts import get_object_or_404
from django.db import models
from apps.channels.models import Channel, ChannelProfile, Stream
from .models import HDHRDevice
from .serializers import HDHRDeviceSerializer
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views import View
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

# Configure logger
logger = logging.getLogger(__name__)


@login_required
def hdhr_dashboard_view(request):
    """Render the HDHR management page."""
    hdhr_devices = HDHRDevice.objects.all()
    return render(request, "hdhr/hdhr.html", {"hdhr_devices": hdhr_devices})


# 🔹 1) HDHomeRun Device API
class HDHRDeviceViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for HDHomeRun devices"""

    queryset = HDHRDevice.objects.all()
    serializer_class = HDHRDeviceSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]


# 🔹 2) Discover API
class DiscoverAPIView(APIView):
    """Returns device discovery information"""

    @extend_schema(
        description="Retrieve HDHomeRun device discovery information",
    )
    def get(self, request, profile=None):
        uri_parts = ["hdhr"]
        if profile is not None:
            uri_parts.append(profile)

        base_url = request.build_absolute_uri(f'/{"/".join(uri_parts)}/').rstrip("/")
        device = HDHRDevice.objects.first()

        # Calculate tuner count using centralized function
        from apps.m3u.utils import calculate_tuner_count
        tuner_count = calculate_tuner_count(minimum=1, unlimited_default=10)

        # Create a unique DeviceID for the HDHomeRun device based on profile ID or a default value
        device_ID = "12345678"  # Default DeviceID
        friendly_name = "Dispatcharr HDHomeRun"
        if profile is not None:
            device_ID = f"dispatcharr-hdhr-{profile}"
            friendly_name = f"Dispatcharr HDHomeRun - {profile}"
        if not device:
            data = {
                "FriendlyName": friendly_name,
                "ModelNumber": "HDTC-2US",
                "FirmwareName": "hdhomerun3_atsc",
                "FirmwareVersion": "20200101",
                "DeviceID": device_ID,
                "DeviceAuth": "test_auth_token",
                "BaseURL": base_url,
                "LineupURL": f"{base_url}/lineup.json",
                "TunerCount": tuner_count,
            }
        else:
            data = {
                "FriendlyName": device.friendly_name,
                "ModelNumber": "HDTC-2US",
                "FirmwareName": "hdhomerun3_atsc",
                "FirmwareVersion": "20200101",
                "DeviceID": device.device_id,
                "DeviceAuth": "test_auth_token",
                "BaseURL": base_url,
                "LineupURL": f"{base_url}/lineup.json",
                "TunerCount": tuner_count,
            }
        return JsonResponse(data)


# 🔹 3) Lineup API
class LineupAPIView(APIView):
    """Returns available channel lineup"""

    @extend_schema(
        description="Retrieve the available channel lineup",
    )
    def get(self, request, profile=None):
        if profile is not None:
            channel_profile = ChannelProfile.objects.get(name=profile)
            channels = Channel.objects.filter(
                channelprofilemembership__channel_profile=channel_profile,
                channelprofilemembership__enabled=True,
            ).order_by("channel_number")
        else:
            channels = Channel.objects.all().order_by("channel_number")

        lineup = []
        for ch in channels:
            # Format channel number as integer if it has no decimal component
            if ch.channel_number is not None:
                if ch.channel_number == int(ch.channel_number):
                    formatted_channel_number = str(int(ch.channel_number))
                else:
                    formatted_channel_number = str(ch.channel_number)
            else:
                formatted_channel_number = ""

            lineup.append(
                {
                    "GuideNumber": formatted_channel_number,
                    "GuideName": ch.name,
                    "URL": request.build_absolute_uri(f"/proxy/ts/stream/{ch.uuid}"),
                    "Guide_ID": formatted_channel_number,
                    "Station": formatted_channel_number,
                }
            )
        return JsonResponse(lineup, safe=False)


# 🔹 4) Lineup Status API
class LineupStatusAPIView(APIView):
    """Returns the current status of the HDHR lineup"""

    @extend_schema(
        description="Retrieve the HDHomeRun lineup status",
    )
    def get(self, request, profile=None):
        data = {
            "ScanInProgress": 0,
            "ScanPossible": 0,
            "Source": "Cable",
            "SourceList": ["Cable"],
        }
        return JsonResponse(data)


# 🔹 5) Device XML API
class HDHRDeviceXMLAPIView(APIView):
    """Returns HDHomeRun device configuration in XML"""

    @extend_schema(
        description="Retrieve the HDHomeRun device XML configuration",
    )
    def get(self, request):
        base_url = request.build_absolute_uri("/hdhr/").rstrip("/")

        xml_response = f"""<?xml version="1.0" encoding="utf-8"?>
        <root>
            <DeviceID>12345678</DeviceID>
            <FriendlyName>Dispatcharr HDHomeRun</FriendlyName>
            <ModelNumber>HDTC-2US</ModelNumber>
            <FirmwareName>hdhomerun3_atsc</FirmwareName>
            <FirmwareVersion>20200101</FirmwareVersion>
            <DeviceAuth>test_auth_token</DeviceAuth>
            <BaseURL>{base_url}</BaseURL>
            <LineupURL>{base_url}/lineup.json</LineupURL>
        </root>"""

        return HttpResponse(xml_response, content_type="application/xml")
