# core/api_views.py

import json
import ipaddress
import logging
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, action
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from .models import (
    UserAgent,
    StreamProfile,
    CoreSettings,
    STREAM_SETTINGS_KEY,
    DVR_SETTINGS_KEY,
    NETWORK_ACCESS_KEY,
    PROXY_SETTINGS_KEY,
)
from .serializers import (
    UserAgentSerializer,
    StreamProfileSerializer,
    CoreSettingsSerializer,
    ProxySettingsSerializer,
)

import socket
import requests
import os
from core.tasks import rehash_streams
from apps.accounts.permissions import (
    Authenticated,
    IsAdmin,
)
from dispatcharr.utils import get_client_ip


logger = logging.getLogger(__name__)


class UserAgentViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows user agents to be viewed, created, edited, or deleted.
    """
    queryset = UserAgent.objects.all()
    serializer_class = UserAgentSerializer
    permission_classes = [IsAdmin]


class StreamProfileViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows stream profiles to be viewed, created, edited, or deleted.
    """
    queryset = StreamProfile.objects.all()
    serializer_class = StreamProfileSerializer
    permission_classes = [IsAdmin]


class CoreSettingsViewSet(viewsets.ModelViewSet):
    """
    API endpoint for editing core settings.
    This is treated as a singleton: only one instance should exist.
    """
    queryset = CoreSettings.objects.all()
    serializer_class = CoreSettingsSerializer
    permission_classes = [IsAdmin]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_value = instance.value
        response = super().update(request, *args, **kwargs)

        # If stream settings changed and m3u_hash_key is different, rehash streams
        if instance.key == STREAM_SETTINGS_KEY:
            new_value = request.data.get("value", {})
            if isinstance(new_value, dict) and isinstance(old_value, dict):
                old_hash = old_value.get("m3u_hash_key", "")
                new_hash = new_value.get("m3u_hash_key", "")
                if old_hash != new_hash:
                    hash_keys = new_hash.split(",") if isinstance(new_hash, str) else new_hash
                    rehash_streams.delay(hash_keys)

        # If DVR settings changed and pre/post offsets are different, reschedule upcoming recordings
        if instance.key == DVR_SETTINGS_KEY:
            new_value = request.data.get("value", {})
            if isinstance(new_value, dict) and isinstance(old_value, dict):
                old_pre = old_value.get("pre_offset_minutes")
                new_pre = new_value.get("pre_offset_minutes")
                old_post = old_value.get("post_offset_minutes")
                new_post = new_value.get("post_offset_minutes")
                if old_pre != new_pre or old_post != new_post:
                    try:
                        # Prefer async task if Celery is available
                        from apps.channels.tasks import reschedule_upcoming_recordings_for_offset_change
                        reschedule_upcoming_recordings_for_offset_change.delay()
                    except Exception:
                        # Fallback to synchronous implementation
                        from apps.channels.tasks import reschedule_upcoming_recordings_for_offset_change_impl
                        reschedule_upcoming_recordings_for_offset_change_impl()

        return response

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        # If creating DVR settings with offset values, reschedule upcoming recordings
        try:
            key = request.data.get("key")
            if key == DVR_SETTINGS_KEY:
                value = request.data.get("value", {})
                if isinstance(value, dict) and ("pre_offset_minutes" in value or "post_offset_minutes" in value):
                    try:
                        from apps.channels.tasks import reschedule_upcoming_recordings_for_offset_change
                        reschedule_upcoming_recordings_for_offset_change.delay()
                    except Exception:
                        from apps.channels.tasks import reschedule_upcoming_recordings_for_offset_change_impl
                        reschedule_upcoming_recordings_for_offset_change_impl()
        except Exception:
            pass
        return response
    @action(detail=False, methods=["post"], url_path="check")
    def check(self, request, *args, **kwargs):
        data = request.data

        if data.get("key") == NETWORK_ACCESS_KEY:
            client_ip = ipaddress.ip_address(get_client_ip(request))

            in_network = {}
            invalid = []

            value = data.get("value", {})
            for key, val in value.items():
                in_network[key] = []
                cidrs = val.split(",")
                for cidr in cidrs:
                    try:
                        network = ipaddress.ip_network(cidr)

                        if client_ip in network:
                            in_network[key] = []
                            break

                        in_network[key].append(cidr)
                    except:
                        invalid.append(cidr)

            if len(invalid) > 0:
                return Response(
                    {
                        "error": True,
                        "message": "Invalid CIDR(s)",
                        "data": invalid,
                    },
                    status=status.HTTP_200_OK,
                )

            response_data = {
                **in_network,
                "client_ip": str(client_ip)
            }
            return Response(response_data, status=status.HTTP_200_OK)

        return Response({}, status=status.HTTP_200_OK)

class ProxySettingsViewSet(viewsets.ViewSet):
    """
    API endpoint for proxy settings stored as JSON in CoreSettings.
    """
    serializer_class = ProxySettingsSerializer
    permission_classes = [IsAdmin]

    def _get_or_create_settings(self):
        """Get or create the proxy settings CoreSettings entry"""
        try:
            settings_obj = CoreSettings.objects.get(key=PROXY_SETTINGS_KEY)
            settings_data = settings_obj.value
        except CoreSettings.DoesNotExist:
            # Create default settings
            settings_data = {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 5,
            }
            settings_obj, created = CoreSettings.objects.get_or_create(
                key=PROXY_SETTINGS_KEY,
                defaults={
                    "name": "Proxy Settings",
                    "value": settings_data
                }
            )
        return settings_obj, settings_data

    def list(self, request):
        """Return proxy settings"""
        settings_obj, settings_data = self._get_or_create_settings()
        return Response(settings_data)

    def retrieve(self, request, pk=None):
        """Return proxy settings regardless of ID"""
        settings_obj, settings_data = self._get_or_create_settings()
        return Response(settings_data)

    def update(self, request, pk=None):
        """Update proxy settings"""
        settings_obj, current_data = self._get_or_create_settings()

        serializer = ProxySettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Update the JSON data - store as dict directly
        settings_obj.value = serializer.validated_data
        settings_obj.save()

        return Response(serializer.validated_data)

    def partial_update(self, request, pk=None):
        """Partially update proxy settings"""
        settings_obj, current_data = self._get_or_create_settings()

        # Merge current data with new data
        updated_data = {**current_data, **request.data}

        serializer = ProxySettingsSerializer(data=updated_data)
        serializer.is_valid(raise_exception=True)

        # Update the JSON data - store as dict directly
        settings_obj.value = serializer.validated_data
        settings_obj.save()

        return Response(serializer.validated_data)

    @action(detail=False, methods=['get', 'patch'])
    def settings(self, request):
        """Get or update the proxy settings."""
        if request.method == 'GET':
            return self.list(request)
        elif request.method == 'PATCH':
            return self.partial_update(request)



@extend_schema(
    description="Endpoint for environment details",
)
@api_view(["GET"])
@permission_classes([Authenticated])
def environment(request):
    public_ip = None
    local_ip = None
    country_code = None
    country_name = None

    # 1) Get the public IP from ipify.org API
    try:
        r = requests.get("https://api64.ipify.org?format=json", timeout=5)
        r.raise_for_status()
        public_ip = r.json().get("ip")
    except requests.RequestException as e:
        public_ip = f"Error: {e}"

    # 2) Get the local IP by connecting to a public DNS server
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # connect to a "public" address so the OS can determine our local interface
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception as e:
        local_ip = f"Error: {e}"

    # 3) Get geolocation data from ipapi.co or ip-api.com
    if public_ip and "Error" not in public_ip:
        try:
            # Attempt to get geo information from ipapi.co first
            r = requests.get(f"https://ipapi.co/{public_ip}/json/", timeout=5)

            if r.status_code == requests.codes.ok:
                geo = r.json()
                country_code = geo.get("country_code")  # e.g. "US"
                country_name = geo.get("country_name")  # e.g. "United States"

            else:
                # If ipapi.co fails, fallback to ip-api.com
                # only supports http requests for free tier
                r = requests.get("http://ip-api.com/json/", timeout=5)

                if r.status_code == requests.codes.ok:
                    geo = r.json()
                    country_code = geo.get("countryCode")  # e.g. "US"
                    country_name = geo.get("country")  # e.g. "United States"

                else:
                    raise Exception("Geo lookup failed with both services")

        except Exception as e:
            logger.error(f"Error during geo lookup: {e}")
            country_code = None
            country_name = None

    # 4) Get environment mode from system environment variable
    return Response(
        {
            "authenticated": True,
            "public_ip": public_ip,
            "local_ip": local_ip,
            "country_code": country_code,
            "country_name": country_name,
            "env_mode": "dev" if os.getenv("DISPATCHARR_ENV") == "dev" else "prod",
        }
    )


@extend_schema(
    description="Get application version information",
)

@api_view(["GET"])
def version(request):
    # Import version information
    from version import __version__, __timestamp__

    return Response(
        {
            "version": __version__,
            "timestamp": __timestamp__,
        }
    )


@extend_schema(
    description="Trigger rehashing of all streams",
)
@api_view(["POST"])
@permission_classes([Authenticated])
def rehash_streams_endpoint(request):
    """Trigger the rehash streams task"""
    try:
        # Get the current hash keys from settings
        hash_key = CoreSettings.get_m3u_hash_key()
        hash_keys = hash_key.split(",") if isinstance(hash_key, str) else hash_key

        # Queue the rehash task
        task = rehash_streams.delay(hash_keys)

        return Response({
            "success": True,
            "message": "Stream rehashing task has been queued",
            "task_id": task.id
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "success": False,
            "message": f"Error triggering rehash: {str(e)}"
        }, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error triggering rehash streams: {e}")
        return Response({
            "success": False,
            "message": "Failed to trigger rehash task"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─────────────────────────────
# Timezone List API
# ─────────────────────────────
class TimezoneListView(APIView):
    """
    API endpoint that returns all available timezones supported by pytz.
    Returns a list of timezone names grouped by region for easy selection.
    This is a general utility endpoint that can be used throughout the application.
    """

    def get_permissions(self):
        return [Authenticated()]

    @extend_schema(
        description="Get list of all supported timezones",
    )
    def get(self, request):
        import pytz

        # Get all common timezones (excludes deprecated ones)
        all_timezones = sorted(pytz.common_timezones)

        # Group by region for better UX
        grouped = {}
        for tz in all_timezones:
            if '/' in tz:
                region = tz.split('/')[0]
                if region not in grouped:
                    grouped[region] = []
                grouped[region].append(tz)
            else:
                # Handle special zones like UTC, GMT, etc.
                if 'Other' not in grouped:
                    grouped['Other'] = []
                grouped['Other'].append(tz)

        return Response({
            'timezones': all_timezones,
            'grouped': grouped,
            'count': len(all_timezones)
        })


# ─────────────────────────────
# System Events API
# ─────────────────────────────
# ─────────────────────────────
# Event Discovery & Configuration API
# ─────────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_event_catalog(request):
    """
    Get the full catalog of available events for agent/plugin discovery.

    Returns all events with their:
    - level: CRITICAL, SYSTEM, or FULL
    - description: Human-readable description

    This enables agents to discover what events they can subscribe to.
    """
    from core.events import get_event_catalog, EVENT_LEVELS, get_event_level, EVENT_LEVEL_NAMES

    catalog = get_event_catalog()
    current_level = get_event_level()

    return Response({
        'events': catalog,
        'levels': list(EVENT_LEVELS.keys()),
        'current_level': EVENT_LEVEL_NAMES.get(current_level, 'UNKNOWN'),
        'total_events': len(catalog),
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def event_level(request):
    """
    Get or set the current event level.

    GET: Returns the current event level
    POST: Sets a new event level (requires {"level": "NONE|CRITICAL|SYSTEM|FULL"})

    Note: Setting via this API updates the database setting. The
    DISPATCHARR_EVENT_LEVEL environment variable takes priority if set.
    """
    from core.events import (
        get_event_level, EVENT_LEVELS, EVENT_LEVEL_NAMES,
        invalidate_event_level_cache
    )
    import os

    if request.method == 'GET':
        current_level = get_event_level()
        env_override = os.environ.get('DISPATCHARR_EVENT_LEVEL', '').upper()

        return Response({
            'level': EVENT_LEVEL_NAMES.get(current_level, 'UNKNOWN'),
            'level_value': current_level,
            'available_levels': list(EVENT_LEVELS.keys()),
            'env_override': env_override if env_override else None,
            'env_override_active': bool(env_override and env_override in EVENT_LEVELS),
        })

    # POST - update the level (requires admin privileges)
    if not request.user.user_level >= 10:
        return Response({
            'error': 'Admin privileges required to change event level'
        }, status=status.HTTP_403_FORBIDDEN)

    new_level = request.data.get('level', '').upper()

    if new_level not in EVENT_LEVELS:
        return Response({
            'error': f'Invalid level: {new_level}. Must be one of: {list(EVENT_LEVELS.keys())}'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Check if env var is set (it takes priority)
    env_override = os.environ.get('DISPATCHARR_EVENT_LEVEL', '').upper()
    if env_override and env_override in EVENT_LEVELS:
        return Response({
            'warning': f'DISPATCHARR_EVENT_LEVEL environment variable is set to {env_override}. '
                       f'Database setting will be saved but env var takes priority.',
            'level': new_level,
            'effective_level': env_override,
        })

    # Save to database
    try:
        system_settings = CoreSettings.get_system_settings()
        system_settings['event_level'] = new_level
        CoreSettings.set_system_settings(system_settings)

        # Invalidate the cache so new level takes effect immediately
        invalidate_event_level_cache()

        return Response({
            'level': new_level,
            'message': f'Event level set to {new_level}',
        })
    except Exception as e:
        logger.error(f"Error setting event level: {e}")
        return Response({
            'error': 'Failed to save event level'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_system_events(request):
    """
    Get recent system events (channel start/stop, buffering, client connections, etc.)

    Query Parameters:
        limit: Number of events to return per page (default: 100, max: 1000)
        offset: Number of events to skip (for pagination, default: 0)
        event_type: Filter by specific event type (optional)
    """
    from core.models import SystemEvent

    try:
        # Get pagination params
        limit = min(int(request.GET.get('limit', 100)), 1000)
        offset = int(request.GET.get('offset', 0))

        # Start with all events
        events = SystemEvent.objects.all()

        # Filter by event_type if provided
        event_type = request.GET.get('event_type')
        if event_type:
            events = events.filter(event_type=event_type)

        # Get total count before applying pagination
        total_count = events.count()

        # Apply offset and limit for pagination
        events = events[offset:offset + limit]

        # Serialize the data
        events_data = [{
            'id': event.id,
            'event_type': event.event_type,
            'event_type_display': event.get_event_type_display(),
            'timestamp': event.timestamp.isoformat(),
            'channel_id': str(event.channel_id) if event.channel_id else None,
            'channel_name': event.channel_name,
            'details': event.details
        } for event in events]

        return Response({
            'events': events_data,
            'count': len(events_data),
            'total': total_count,
            'offset': offset,
            'limit': limit
        })

    except Exception as e:
        logger.error(f"Error fetching system events: {e}")
        return Response({
            'error': 'Failed to fetch system events'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
