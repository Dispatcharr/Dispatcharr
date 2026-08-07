import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
import regex, logging

from apps.accounts.models import User

logger = logging.getLogger(__name__)

# Connection telemetry on the shared "updates" group. These payloads include
# channel/content UUIDs (usable against anonymous /proxy/ts/stream/<uuid>),
# upstream stream URLs, client IPs, and session details. The Stats UI is
# already admin-only; keep that telemetry off Standard-user sockets.
ADMIN_ONLY_UPDATE_TYPES = frozenset({
    "channel_stats",
    "vod_stats",
    "timeshift_stats",
    "vod_started",
    "vod_stopped",
})


def user_may_receive_update(user, data):
    """Return True when *user* is allowed to receive this update payload."""
    event_type = (data or {}).get("type")
    if event_type not in ADMIN_ONLY_UPDATE_TYPES:
        return True
    return (
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "user_level", 0) >= User.UserLevel.ADMIN
    )


class MyWebSocketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = "updates"

        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close()
            return

        try:
            await self.accept()
            await self.channel_layer.group_add(self.room_name, self.channel_name)
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'data': {
                    'success': True,
                    'message': 'WebSocket connection established successfully'
                }
            }))
            # If the IP lookup already completed before the client connected,
            # push the cached result immediately so the Skeleton resolves.
            try:
                from django.core.cache import cache
                from core.api_views import _IP_CACHE_KEY
                cached_ip = await sync_to_async(cache.get)(_IP_CACHE_KEY)
                if cached_ip:
                    # Omit verified_at (cache-only) without mutating the cached value.
                    payload = {
                        k: v for k, v in cached_ip.items() if k != "verified_at"
                    }
                    await self.send(text_data=json.dumps({
                        'data': {'type': 'ip_lookup_complete', **payload}
                    }))
            except Exception as e:
                logger.warning(f"Could not push cached IP result on connect: {e}")
        except Exception as e:
            logger.error(f"Error in WebSocket connect: {str(e)}")
            try:
                await self.close(code=1011)
            except:
                pass

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.room_name, self.channel_name)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in WebSocket disconnect: {str(e)}")

    async def receive(self, text_data):
        data = json.loads(text_data)

        if data["type"] == "m3u_profile_test":
            user = self.scope.get("user")
            if (
                not user
                or not getattr(user, "is_authenticated", False)
                or getattr(user, "user_level", 0) < User.UserLevel.ADMIN
            ):
                return

            from apps.proxy.live_proxy.url_utils import transform_url

            def replace_with_mark(match):
                # Wrap the match in <mark> tags
                return f"<mark>{match.group(0)}</mark>"

            # Apply the transformation using the replace_with_mark function
            try:
                search_preview = regex.sub(data["search"], replace_with_mark, data["url"])
            except Exception as e:
                search_preview = data["url"]
                logger.error(f"Failed to generate replace preview: {e}")

            result = transform_url(data["url"], data["search"], data["replace"])
            await self.send(text_data=json.dumps({
                "data": {
                   'type': 'm3u_profile_test',
                    'search_preview': search_preview,
                    'result': result,
                }
            }))

    async def update(self, event):
        if not user_may_receive_update(self.scope.get("user"), event.get("data")):
            return
        await self.send(text_data=json.dumps(event))
