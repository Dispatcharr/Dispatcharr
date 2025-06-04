# core/api_views.py

from rest_framework import viewsets, status
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import UserAgent, StreamProfile, CoreSettings, STREAM_HASH_KEY
from .serializers import UserAgentSerializer, StreamProfileSerializer, CoreSettingsSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from drf_yasg.utils import swagger_auto_schema
import socket
import requests
import os
from core.tasks import rehash_streams

class UserAgentViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows user agents to be viewed, created, edited, or deleted.
    """
    queryset = UserAgent.objects.all()
    serializer_class = UserAgentSerializer

class StreamProfileViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows stream profiles to be viewed, created, edited, or deleted.
    """
    queryset = StreamProfile.objects.all()
    serializer_class = StreamProfileSerializer

class CoreSettingsViewSet(viewsets.ModelViewSet):
    """
    API endpoint for editing core settings.
    This is treated as a singleton: only one instance should exist.
    """
    queryset = CoreSettings.objects.all()
    serializer_class = CoreSettingsSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        response = super().update(request, *args, **kwargs)
        if instance.key == STREAM_HASH_KEY:
            if instance.value != request.data['value']:
                rehash_streams.delay(request.data['value'].split(','))

        return response

@swagger_auto_schema(
    method='get',
    operation_description="Endpoint for environment details",
    responses={200: "Environment variables"}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def environment(request):


    public_ip = None
    local_ip = None
    country_code = None
    country_name = None

    # 1) Get the public IP
    try:
        r = requests.get("https://api64.ipify.org?format=json", timeout=5)
        r.raise_for_status()
        public_ip = r.json().get("ip")
    except requests.RequestException as e:
        public_ip = f"Error: {e}"

    # 2) Get the local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # connect to a “public” address so the OS can determine our local interface
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception as e:
        local_ip = f"Error: {e}"

    # 3) If we got a valid public_ip, fetch geo info from ipapi.co
    if public_ip and "Error" not in public_ip:
        try:
            geo = requests.get(f"https://ipapi.co/{public_ip}/json/", timeout=5).json()
            # ipapi returns fields like country_code, country_name, etc.
            country_code = geo.get("country_code", "")  # e.g. "US"
            country_name = geo.get("country_name", "")  # e.g. "United States"
        except requests.RequestException as e:
            country_code = None
            country_name = None

    return Response({
        'authenticated': True,
        'public_ip': public_ip,
        'local_ip': local_ip,
        'country_code': country_code,
        'country_name': country_name,
        'env_mode': "dev" if os.getenv('DISPATCHARR_ENV') == "dev" else "prod",
    })

@swagger_auto_schema(
    method='get',
    operation_description="Get application version information",
    responses={200: "Version information"}
)
@api_view(['GET'])
def version(request):
    # Import version information
    from version import __version__, __timestamp__
    update_version = CoreSettings.get_available_update_version()
    update_url = CoreSettings.get_available_update_url()
    return Response({
        'version': __version__,
        'timestamp': __timestamp__,
        'update_version': update_version,
        'update_url': update_url,
    })


@swagger_auto_schema(
    method='post',
    operation_description="Manually check for available updates",
    responses={200: "Version information"},
)
@api_view(['POST'])
def check_update(request):
    """Trigger an update check and return version info."""
    from version import __version__, __timestamp__
    from core.tasks import check_for_update

    # Run the check synchronously to immediately update DB values
    check_for_update()

    update_version = CoreSettings.get_available_update_version()
    update_url = CoreSettings.get_available_update_url()

    return Response({
        'version': __version__,
        'timestamp': __timestamp__,
        'update_version': update_version,
        'update_url': update_url,
    })
