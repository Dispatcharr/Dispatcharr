from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import Authenticated, permission_classes_by_action
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.shortcuts import get_object_or_404
from apps.channels.models import Channel
from .models import HDHRDevice
from .serializers import HDHRDeviceSerializer
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views import View
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt


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
    def get(self, request):
        base_url = request.build_absolute_uri("/hdhr/").rstrip("/")
        device = HDHRDevice.objects.first()

        if not device:
            data = {
                "FriendlyName": "Dispatcharr HDHomeRun",
                "ModelNumber": "HDTC-2US",
                "FirmwareName": "hdhomerun3_atsc",
                "FirmwareVersion": "20200101",
                "DeviceID": "12345678",
                "DeviceAuth": "test_auth_token",
                "BaseURL": base_url,
                "LineupURL": f"{base_url}/lineup.json",
                "TunerCount": 10,
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
                "TunerCount": 10,
            }
        return JsonResponse(data)


# 🔹 3) Lineup API
class LineupAPIView(APIView):
    """Returns available channel lineup"""

    @extend_schema(
        description="Retrieve the available channel lineup",
    )
    def get(self, request):
        channels = Channel.objects.all().order_by("channel_number")
        lineup = [
            {
                "GuideNumber": str(ch.channel_number),
                "GuideName": ch.name,
                "URL": request.build_absolute_uri(f"/proxy/ts/stream/{ch.uuid}"),
            }
            for ch in channels
        ]
        return JsonResponse(lineup, safe=False)


# 🔹 4) Lineup Status API
class LineupStatusAPIView(APIView):
    """Returns the current status of the HDHR lineup"""

    @extend_schema(
        description="Retrieve the HDHomeRun lineup status",
    )
    def get(self, request):
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
