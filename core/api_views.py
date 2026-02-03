# core/api_views.py

import json
import ipaddress
import logging
from django.db import models
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
)
from dispatcharr.utils import get_client_ip


logger = logging.getLogger(__name__)


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


# ─────────────────────────────
# System Notifications API
# ─────────────────────────────
from .models import SystemNotification, NotificationDismissal
from .serializers import SystemNotificationSerializer, NotificationDismissalSerializer
from django.utils import timezone as dj_timezone


class SystemNotificationViewSet(viewsets.ModelViewSet):
    """
    API endpoint for system notifications.
    Users can view active notifications and dismiss them.
    Admins can create and manage notifications.
    """
    serializer_class = SystemNotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Return notifications based on user permissions.
        Filter out expired and dismissed notifications for regular users.
        Evaluate conditions for developer notifications.
        """
        from core.developer_notifications import evaluate_conditions
        from django.core.cache import cache

        user = self.request.user
        now = dj_timezone.now()

        queryset = SystemNotification.objects.filter(is_active=True)

        # Filter out expired notifications
        queryset = queryset.filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

        # Filter admin-only notifications for non-admins
        if not getattr(user, 'is_superuser', False) and getattr(user, 'user_level', 0) < 10:
            queryset = queryset.filter(admin_only=False)

        # For developer notifications, evaluate conditions
        # Cache the evaluation per notification to avoid repeated condition checks
        notifications_to_exclude = []
        developer_notifications = queryset.filter(source=SystemNotification.Source.DEVELOPER)

        for notification in developer_notifications:
            action_data = notification.action_data or {}
            conditions = action_data.get('condition', [])

            if not conditions:
                continue

            # Cache key based on notification ID and current settings
            # Cache for 5 minutes to balance freshness with performance
            cache_key = f'dev_notif_condition_{notification.id}_{user.id}'
            should_show = cache.get(cache_key)

            if should_show is None:
                should_show = evaluate_conditions(conditions, user)
                cache.set(cache_key, should_show, timeout=300)  # 5 minutes

            if not should_show:
                notifications_to_exclude.append(notification.id)

        if notifications_to_exclude:
            queryset = queryset.exclude(id__in=notifications_to_exclude)

        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def list(self, request):
        """
        List all active notifications for the current user.
        Optionally filter by dismissed status.
        """
        queryset = self.get_queryset()

        # Optional: filter out already dismissed notifications
        include_dismissed = request.query_params.get('include_dismissed', 'false').lower() == 'true'
        if not include_dismissed:
            dismissed_ids = NotificationDismissal.objects.filter(
                user=request.user
            ).values_list('notification_id', flat=True)
            queryset = queryset.exclude(id__in=dismissed_ids)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'notifications': serializer.data,
            'count': len(serializer.data),
            'unread_count': queryset.count()
        })

    @action(detail=True, methods=['post'], url_path='dismiss')
    def dismiss(self, request, pk=None):
        """Dismiss a notification for the current user."""
        notification = self.get_object()
        action_taken = request.data.get('action_taken', None)

        dismissal, created = NotificationDismissal.objects.get_or_create(
            user=request.user,
            notification=notification,
            defaults={'action_taken': action_taken}
        )

        if not created and action_taken:
            dismissal.action_taken = action_taken
            dismissal.save()

        return Response({
            'success': True,
            'message': 'Notification dismissed',
            'notification_key': notification.notification_key
        })

    @action(detail=False, methods=['post'], url_path='dismiss-all')
    def dismiss_all(self, request):
        """Dismiss all notifications for the current user."""
        notifications = self.get_queryset()

        # Get notifications not yet dismissed
        dismissed_ids = NotificationDismissal.objects.filter(
            user=request.user
        ).values_list('notification_id', flat=True)
        to_dismiss = notifications.exclude(id__in=dismissed_ids)

        # Create dismissals for all
        dismissals = [
            NotificationDismissal(user=request.user, notification=n)
            for n in to_dismiss
        ]
        NotificationDismissal.objects.bulk_create(dismissals, ignore_conflicts=True)

        return Response({
            'success': True,
            'dismissed_count': len(dismissals)
        })

    @action(detail=False, methods=['get'], url_path='count')
    def unread_count(self, request):
        """Get count of unread notifications."""
        queryset = self.get_queryset()
        dismissed_ids = NotificationDismissal.objects.filter(
            user=request.user
        ).values_list('notification_id', flat=True)
        unread_count = queryset.exclude(id__in=dismissed_ids).count()

        return Response({
            'unread_count': unread_count
        })

