"""Admin API views for catch-up connection statistics."""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes

from apps.accounts.permissions import IsAdmin
from apps.proxy.utils import stop_timeshift_client
from apps.timeshift.helpers import get_catchup_programmes_for_sessions
from apps.timeshift.stats import (
    build_timeshift_stats_data,
    find_stats_channel_for_session,
)
from core.utils import RedisClient

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsAdmin])
def timeshift_stats(request):
    """Return active catch-up viewer sessions for the stats page."""
    redis_client = RedisClient.get_client()
    if not redis_client:
        return JsonResponse({"error": "Redis not available"}, status=500)
    return JsonResponse(build_timeshift_stats_data(redis_client))


@api_view(["POST"])
@permission_classes([IsAdmin])
def catchup_programmes(request):
    """Return EPG metadata for active catch-up sessions (batch)."""
    sessions = request.data.get("sessions")
    if sessions is None:
        return JsonResponse({"error": "sessions is required"}, status=400)
    if not isinstance(sessions, list):
        return JsonResponse({"error": "sessions must be an array"}, status=400)
    return JsonResponse({
        "sessions": get_catchup_programmes_for_sessions(sessions),
    })


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def stop_timeshift_session(request):
    """Stop a catch-up viewer by session id (one session = one stats channel)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    session_id = data.get("session_id")
    if not session_id:
        return JsonResponse({"error": "No session_id provided"}, status=400)

    redis_client = RedisClient.get_client()
    if not redis_client:
        return JsonResponse({"error": "Redis not available"}, status=500)

    stats_channel_id = find_stats_channel_for_session(redis_client, session_id)
    if not stats_channel_id:
        return JsonResponse({"error": "Connection not found"}, status=404)

    result = stop_timeshift_client(redis_client, stats_channel_id, session_id)
    if result.get("status") != "success":
        return JsonResponse(
            {"error": result.get("message", "Stop failed")},
            status=500,
        )

    return JsonResponse({
        "message": "Timeshift session stop signal sent",
        "session_id": session_id,
    })
