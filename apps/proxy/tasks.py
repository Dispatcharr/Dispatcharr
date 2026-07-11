from celery import shared_task
import json
import logging
import gc
from core.utils import RedisClient
from apps.proxy.live_proxy.channel_status import build_live_channel_stats_data
from core.utils import send_websocket_update

logger = logging.getLogger(__name__)

# Store the last known value to compare with new data
last_known_data = {}

@shared_task
def fetch_channel_stats():
    redis_client = RedisClient.get_client()

    try:
        live_stats = build_live_channel_stats_data(redis_client)
    except Exception as e:
        logger.error(f"Error in channel_status: {e}", exc_info=True)
        return

    send_websocket_update(
        "updates",
        "update",
        {
            "success": True,
            "type": "channel_stats",
            "stats": json.dumps(live_stats),
        },
        collect_garbage=True
    )

    gc.collect()


