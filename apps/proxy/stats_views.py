"""Combined connection stats for live, VOD, and catch-up."""

import logging
import time

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes

from apps.accounts.permissions import IsAdmin
from apps.proxy.live_proxy.channel_status import build_live_channel_stats_data
from apps.proxy.vod_proxy.views import build_vod_stats_data
from apps.timeshift.stats import build_timeshift_stats_data
from core.utils import RedisClient

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsAdmin])
def combined_stats(request):
    """Return live, VOD, and catch-up stats in one response."""
    redis_client = RedisClient.get_client()
    if not redis_client:
        return JsonResponse({"error": "Redis not available"}, status=500)

    return JsonResponse({
        "live": build_live_channel_stats_data(redis_client),
        "vod": build_vod_stats_data(redis_client),
        "catchup": build_timeshift_stats_data(redis_client),
        "timestamp": time.time(),
    })
