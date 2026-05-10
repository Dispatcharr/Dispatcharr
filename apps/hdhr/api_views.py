from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
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
from dispatcharr.utils import network_access_allowed

# Configure logger
logger = logging.getLogger(__name__)


def _hdhr_network_check(request):
    """Return a 403 JsonResponse if the client IP is not allowed by the
    M3U_EPG network access policy. HDHR discovery endpoints expose channel
    inventory and stream URLs, so they share the same allowlist as M3U/EPG.
    """
    if not network_access_allowed(request, "M3U_EPG"):
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


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
    permission_classes = [AllowAny]

    @extend_schema(
        description="Retrieve HDHomeRun device discovery information",
    )
    def get(self, request, channel_profile=None, output_profile_id=None):
        blocked = _hdhr_network_check(request)
        if blocked is not None:
            return blocked

        uri_parts = ["hdhr"]
        if channel_profile is not None:
            uri_parts.append(channel_profile)
        if output_profile_id is not None:
            uri_parts.append("output_profile")
            uri_parts.append(str(output_profile_id))

        base_url = request.build_absolute_uri(f'/{"/".join(uri_parts)}/').rstrip("/")
        device = HDHRDevice.objects.first()

        from apps.m3u.utils import calculate_tuner_count
        tuner_count = calculate_tuner_count(minimum=1, unlimited_default=10)

        slug_parts = [p for p in [channel_profile, str(output_profile_id) if output_profile_id is not None else None] if p]
        device_ID = f"dispatcharr-hdhr-{'-'.join(slug_parts)}" if slug_parts else "12345678"
        friendly_name = f"Dispatcharr HDHomeRun - {' / '.join(slug_parts)}" if slug_parts else "Dispatcharr HDHomeRun"

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


def _resolve_hdhr_output_profile_id(output_profile_id):
    """Return a validated output profile ID for HDHR lineup stream URLs.

    Priority: URL path segment -> system default -> None (pass-through).
    """
    from core.models import OutputProfile, CoreSettings
    candidate = output_profile_id if output_profile_id is not None else CoreSettings.get_hdhr_output_profile_id()
    if candidate is None:
        return None
    try:
        OutputProfile.objects.get(id=candidate, is_active=True)
        return candidate
    except OutputProfile.DoesNotExist:
        source = "URL" if output_profile_id is not None else "system default"
        logger.warning("HDHR output profile id=%s (%s) not found or inactive - serving without transcoding", candidate, source)
        return None


# 🔹 3) Lineup API
class LineupAPIView(APIView):
    """Returns available channel lineup"""
    permission_classes = [AllowAny]

    @extend_schema(
        description="Retrieve the available channel lineup",
    )
    def get(self, request, channel_profile=None, output_profile_id=None):
        blocked = _hdhr_network_check(request)
        if blocked is not None:
            return blocked

        from apps.channels.managers import with_effective_values
        from apps.channels.utils import format_channel_number

        if channel_profile is not None:
            try:
                cp = ChannelProfile.objects.get(name=channel_profile)
            except ChannelProfile.DoesNotExist:
                return JsonResponse([], safe=False)
            base_qs = Channel.objects.filter(
                channelprofilemembership__channel_profile=cp,
                channelprofilemembership__enabled=True,
            )
        else:
            base_qs = Channel.objects.all()

        channels = (
            with_effective_values(base_qs)
            .exclude(hidden_from_output=True)
            .order_by("effective_channel_number")
        )

        resolved_output_profile_id = _resolve_hdhr_output_profile_id(output_profile_id)

        lineup = []
        for ch in channels:
            formatted = format_channel_number(ch.effective_channel_number, empty=None)
            if formatted is None:
                continue
            formatted_channel_number = str(formatted)

            stream_url = request.build_absolute_uri(f"/proxy/ts/stream/{ch.uuid}")
            if resolved_output_profile_id is not None:
                stream_url += f"?output_profile={resolved_output_profile_id}"

            lineup.append(
                {
                    "GuideNumber": formatted_channel_number,
                    "GuideName": ch.effective_name,
                    "URL": stream_url,
                    "Guide_ID": formatted_channel_number,
                    "Station": formatted_channel_number,
                }
            )
        return JsonResponse(lineup, safe=False)


# 🔹 4) Lineup Status API
class LineupStatusAPIView(APIView):
    """Returns the current status of the HDHR lineup"""
    permission_classes = [AllowAny]

    @extend_schema(
        description="Retrieve the HDHomeRun lineup status",
    )
    def get(self, request, channel_profile=None, output_profile_id=None):
        blocked = _hdhr_network_check(request)
        if blocked is not None:
            return blocked

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
    permission_classes = [AllowAny]

    @extend_schema(
        description="Retrieve the HDHomeRun device XML configuration",
    )
    def get(self, request):
        blocked = _hdhr_network_check(request)
        if blocked is not None:
            return blocked

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
