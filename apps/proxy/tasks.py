from celery import shared_task
import json
import logging
import re
import gc
from core.utils import RedisClient
from apps.proxy.ts_proxy.channel_status import ChannelStatus
from core.utils import send_websocket_update

logger = logging.getLogger(__name__)

# Store the last known value to compare with new data
last_known_data = {}

@shared_task
def fetch_channel_stats():
    redis_client = RedisClient.get_client()

    try:
        # Basic info for all channels
        channel_pattern = "ts_proxy:channel:*:metadata"
        all_channels = []

        # Extract channel IDs from keys
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=channel_pattern)
            for key in keys:
                channel_id_match = re.search(r"ts_proxy:channel:(.*):metadata", key)
                if channel_id_match:
                    ch_id = channel_id_match.group(1)
                    channel_info = ChannelStatus.get_basic_channel_info(ch_id)
                    if channel_info:
                        all_channels.append(channel_info)

            if cursor == 0:
                break

    except Exception as e:
        logger.error(f"Error in channel_status: {e}", exc_info=True)
        return
        # return JsonResponse({'error': str(e)}, status=500)

    send_websocket_update(
        "updates",
        "update",
        {
            "success": True,
            "type": "channel_stats",
            "stats": json.dumps({'channels': all_channels, 'count': len(all_channels)})
        },
        collect_garbage=True
    )

    # Explicitly clean up large data structures
    all_channels = None
    gc.collect()


