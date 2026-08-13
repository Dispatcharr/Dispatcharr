import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
import regex, logging

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

# m3u_profile_test runs sync regex on Daphne's event loop. Cap inputs and
# apply a short timeout so a catastrophic pattern cannot stall other sockets.
# Pattern max matches M3UAccountProfile.search_pattern / replace_pattern.
_M3U_PROFILE_TEST_URL_MAX_LEN = 8192
_M3U_PROFILE_TEST_PATTERN_MAX_LEN = 255
_M3U_PROFILE_TEST_REGEX_TIMEOUT = 0.1


def user_is_admin(user):
    """True when *user* is an authenticated admin-level principal."""
    # Lazy import: consumers is imported from asgi/routing before Django apps
    # are ready, so accounts.models cannot be loaded at module import time.
    from apps.accounts.models import User

    return (
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "user_level", 0) >= User.UserLevel.ADMIN
    )


def user_may_receive_update(user, data):
    """Return True when *user* is allowed to receive this update payload.

    Connection telemetry types are always admin-only. ``system_notification``
    payloads with ``admin_only: true`` are also restricted (the REST list
    endpoint already filters those; this keeps the live push path aligned).
    """
    data = data or {}
    event_type = data.get("type")
    if event_type in ADMIN_ONLY_UPDATE_TYPES:
        return user_is_admin(user)
    if event_type == "system_notification":
        notification = data.get("notification") or {}
        if notification.get("admin_only"):
            return user_is_admin(user)
    return True


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
            if not user_is_admin(self.scope.get("user")):
                return

            from apps.proxy.live_proxy.url_utils import transform_url

            url = data.get("url") or ""
            search = data.get("search") or ""
            replace = data.get("replace") or ""
            if (
                not isinstance(url, str)
                or not isinstance(search, str)
                or not isinstance(replace, str)
                or len(url) > _M3U_PROFILE_TEST_URL_MAX_LEN
                or len(search) > _M3U_PROFILE_TEST_PATTERN_MAX_LEN
                or len(replace) > _M3U_PROFILE_TEST_PATTERN_MAX_LEN
            ):
                # Oversized or non-string fields: refuse regex work and echo
                # the original URL so the UI preview stays responsive.
                safe_url = url if isinstance(url, str) else ""
                if len(safe_url) > _M3U_PROFILE_TEST_URL_MAX_LEN:
                    safe_url = safe_url[:_M3U_PROFILE_TEST_URL_MAX_LEN]
                await self.send(text_data=json.dumps({
                    "data": {
                        "type": "m3u_profile_test",
                        "search_preview": safe_url,
                        "result": safe_url,
                    }
                }))
                return

            def replace_with_mark(match):
                # Wrap the match in <mark> tags
                return f"<mark>{match.group(0)}</mark>"

            # Apply the transformation using the replace_with_mark function
            try:
                search_preview = regex.sub(
                    search,
                    replace_with_mark,
                    url,
                    timeout=_M3U_PROFILE_TEST_REGEX_TIMEOUT,
                )
            except Exception as e:
                search_preview = url
                logger.error(f"Failed to generate replace preview: {e}")

            result = transform_url(url, search, replace)
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
