"""
HLS output HTTP endpoints.

HLS clients are pull-based: there is no long-lived response whose generator
can observe a disconnect. Instead, every playlist/segment request touches
the client's Redis record (last_active + TTLs), so a player that polls the
playlist keeps its client alive and a player that stops gets reaped by the
existing ghost-client heartbeat, which feeds the existing zero-clients
shutdown chain. No new teardown machinery.
"""

import json
import time

import gevent
from django.db import close_old_connections
from django.http import HttpResponse, JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.utils import RedisClient
from dispatcharr.utils import network_access_allowed

from ...config_helper import ConfigHelper
from ...redis_keys import RedisKeys
from ...server import ProxyServer
from ...utils import get_logger
from .segmenter import render_media_playlist

logger = get_logger()

# A playlist descriptor that has not been rewritten for this long has no
# segmenter behind it any more (worker gone, thread dead). Scaled up for
# configurations with long segments, where legitimate gaps are longer.
HLS_STALE_PLAYLIST_SECONDS = 45


def _resolved_format(client_hash):
    """Compose the output manager key from the client's registered format."""
    profile_id = (client_hash or {}).get("output_profile_id") or ""
    return f"hls:p{profile_id}" if profile_id else "hls"


def _touch_client(channel_id, client_id):
    """
    Refresh the client's activity record; returns the client hash, or None
    when the record has lapsed (e.g. a player paused past the ghost window).

    A lapsed client is deliberately NOT re-registered here: the expired hash
    carried the client's output format/profile binding, and recreating it
    from nothing would silently rebind a profiled client (hls:p3) to the
    plain output. The caller answers 410 instead, so the player re-enters
    through the normal stream_ts handshake, which rebuilds a complete record.
    """
    proxy_server = ProxyServer.get_instance()
    redis_client = proxy_server.redis_client

    client_key = RedisKeys.client_metadata(channel_id, client_id)
    clients_key = RedisKeys.clients(channel_id)

    client_hash = redis_client.hgetall(client_key)
    if not client_hash:
        # Drop any stale set entry so it cannot linger as a phantom consumer.
        redis_client.srem(clients_key, client_id)
        return None

    ttl = ConfigHelper.get('CLIENT_RECORD_TTL', 60)
    pipe = redis_client.pipeline(transaction=False)
    pipe.hset(client_key, "last_active", str(time.time()))
    pipe.expire(client_key, ttl)
    pipe.sadd(clients_key, client_id)
    pipe.expire(clients_key, ttl)
    pipe.execute()
    return client_hash


def _playlist_is_stale(state):
    """True when the descriptor stopped advancing long enough that whatever was
    producing segments for it is gone. Nothing will publish another segment
    under these keys, so the session is over."""
    updated = state.get("ts")
    if not updated:
        return False  # descriptor predates the timestamp; assume it is live
    limit = max(HLS_STALE_PLAYLIST_SECONDS, 3 * (state.get("adv_target") or 0))
    return (time.time() - updated) > limit


def _session_gone(channel_id, client_id):
    """True when the channel or this specific client has been stopped."""
    proxy_server = ProxyServer.get_instance()
    redis_client = proxy_server.redis_client
    if not redis_client:
        return False
    if redis_client.exists(RedisKeys.channel_stopping(channel_id)):
        return True
    if redis_client.exists(RedisKeys.client_stop(channel_id, client_id)):
        return True
    return False


@api_view(["GET"])
@permission_classes([AllowAny])
def hls_playlist(request, channel_id, client_id):
    """Rolling live media playlist for one HLS client."""
    try:
        if not network_access_allowed(request, "STREAMS"):
            return Response({"error": "Forbidden"}, status=403)

        if _session_gone(channel_id, client_id):
            return JsonResponse({"error": "Stream stopped"}, status=410)

        proxy_server = ProxyServer.get_instance()
        redis_client = proxy_server.redis_client
        if not redis_client:
            return JsonResponse({"error": "Proxy unavailable"}, status=503)

        client_hash = _touch_client(channel_id, client_id)
        if not client_hash:
            # Record lapsed; no guessing (see _touch_client). The player
            # re-enters via the stream URL, which rebuilds its registration.
            return JsonResponse({"error": "Session expired"}, status=410)

        fmt = _resolved_format(client_hash)

        # The segmenter needs a couple of segments after a cold start; wait
        # briefly (gevent-friendly) instead of bouncing the player.
        playlist_key = RedisKeys.output_playlist(channel_id, fmt)
        deadline = time.time() + 10
        playlist_json = redis_client.get(playlist_key)
        while not playlist_json and time.time() < deadline:
            state = redis_client.get(RedisKeys.output_state(channel_id, fmt))
            if state == 'stopped' or _session_gone(channel_id, client_id):
                return JsonResponse({"error": "Stream stopped"}, status=410)
            gevent.sleep(0.25)
            playlist_json = redis_client.get(playlist_key)

        if not playlist_json:
            response = JsonResponse({"error": "Stream not ready"}, status=503)
            response["Retry-After"] = "2"
            return response

        try:
            state = json.loads(playlist_json)
            if _playlist_is_stale(state):
                # Temporary unavailability of a live playlist update (Apple
                # WWDC17 / RFC 7231): 404 so the player retries rather than
                # treating the session as permanently gone (410).
                logger.warning(
                    f"[{client_id}] HLS playlist for {channel_id} stopped advancing"
                )
                return JsonResponse({"error": "Playlist stale"}, status=404)
            body = render_media_playlist(
                state.get("window", []),
                state.get("target", 4),
                adv_target=state.get("adv_target"),
                disc_sequence=state.get("disc_seq", 0),
            )
        except (TypeError, ValueError, KeyError) as e:
            logger.error(f"[{client_id}] Malformed HLS playlist state for {channel_id}: {e}")
            return JsonResponse({"error": "Playlist unavailable"}, status=500)

        response = HttpResponse(body, content_type="application/vnd.apple.mpegurl")
        response["Cache-Control"] = "no-cache"
        return response
    finally:
        # Settings lookup above hits the ORM; this endpoint is polled every
        # few seconds per client, so release stale connections promptly.
        close_old_connections()


@api_view(["GET"])
@permission_classes([AllowAny])
def hls_segment(request, channel_id, client_id, seq):
    """One HLS media segment, fetched by media sequence number from Redis."""
    try:
        if not network_access_allowed(request, "STREAMS"):
            return Response({"error": "Forbidden"}, status=403)

        if _session_gone(channel_id, client_id):
            return JsonResponse({"error": "Stream stopped"}, status=410)

        proxy_server = ProxyServer.get_instance()
        if not proxy_server.redis_client:
            return JsonResponse({"error": "Proxy unavailable"}, status=503)

        client_hash = _touch_client(channel_id, client_id)
        if not client_hash:
            # Record lapsed; no guessing (see _touch_client). The player
            # re-enters via the stream URL, which rebuilds its registration.
            return JsonResponse({"error": "Session expired"}, status=410)

        fmt = _resolved_format(client_hash)

        redis_buffer = RedisClient.get_buffer()
        if not redis_buffer:
            return JsonResponse({"error": "Proxy unavailable"}, status=503)

        data = redis_buffer.get(RedisKeys.output_buffer_chunk(channel_id, fmt, int(seq)))
        if not data:
            # Expired out of the rolling window (player fell too far behind).
            return JsonResponse({"error": "Segment expired"}, status=404)

        response = HttpResponse(data, content_type="video/mp2t")
        response["Cache-Control"] = "no-cache"
        return response
    finally:
        # Settings lookup above hits the ORM; this endpoint is polled every
        # few seconds per client, so release stale connections promptly.
        close_old_connections()
