"""
HLS output HTTP endpoints.

HLS clients are pull-based: there is no long-lived response whose generator
can observe a disconnect. Instead, every playlist/segment request touches
the client's Redis record (last_active + TTLs), so a player that polls the
playlist keeps its client alive and a player that stops gets reaped by the
existing ghost-client heartbeat, which feeds the existing zero-clients
shutdown chain. No new teardown machinery.

Follow-up URLs are opaque capability tokens (`/proxy/hls/<token>/...`), not
channel uuids or XC credentials. Possession of the token is the session;
playlist/segment polls do not hit the ORM.
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
from ...constants import ChannelMetadataField, ChannelState
from ...redis_keys import RedisKeys
from ...server import ProxyServer
from ...utils import get_logger
from .segmenter import render_media_playlist
from .session import touch_hls_session

logger = get_logger()

# A playlist descriptor that has not been rewritten for this long has no
# segmenter behind it any more (worker gone, thread dead). Scaled up for
# configurations with long segments, where legitimate gaps are longer.
HLS_STALE_PLAYLIST_SECONDS = 45
# Once channel input is live, how long to keep waiting for the output to
# publish its first playlist (the media-duration gate). Counted from the
# moment the channel was first seen ready, not from request start, so time
# spent in startup/failover does not use it up. While the channel is still
# starting, the wait follows channel_init_grace_period instead.
HLS_READY_PLAYLIST_WAIT_SECONDS = 10
_PLAYLIST_WAIT_POLL_SECONDS = 0.25
# Channel metadata states where startup/failover is still in progress. A
# missing state is treated the same way: metadata is written during setup.
_CHANNEL_STARTING_STATES = frozenset({
    ChannelState.INITIALIZING,
    ChannelState.CONNECTING,
    ChannelState.BUFFERING,
})
_CHANNEL_DEAD_STATES = frozenset({
    ChannelState.ERROR,
    ChannelState.STOPPING,
    ChannelState.STOPPED,
})


def _resolved_format(client_hash):
    """Compose the output manager key from the client's registered format."""
    profile_id = (client_hash or {}).get("output_profile_id") or ""
    return f"hls:p{profile_id}" if profile_id else "hls"


def _drop_hls_session(redis_client, token):
    """Forget a capability URL once the live client is gone or stopped."""
    if redis_client and token:
        redis_client.delete(RedisKeys.hls_session(token))


def _playlist_is_stale(state):
    """True when the descriptor stopped advancing long enough that whatever was
    producing segments for it is gone. Nothing will publish another segment
    under these keys, so the session is over."""
    updated = state.get("ts")
    if not updated:
        return False  # descriptor predates the timestamp; assume it is live
    limit = max(HLS_STALE_PLAYLIST_SECONDS, 3 * (state.get("adv_target") or 0))
    return (time.time() - updated) > limit


def _load_live_session(redis_client, token):
    """Resolve + refresh the capability URL, or return a 410 response."""
    loaded, reason = touch_hls_session(redis_client, token)
    if reason == "stopped":
        return None, JsonResponse({"error": "Stream stopped"}, status=410)
    if reason is not None:
        # expired / lapsed: player re-enters via stream_ts, which rebuilds
        # a complete client record (including output format/profile binding).
        return None, JsonResponse({"error": "Session expired"}, status=410)
    return loaded, None


def _touch_interval_seconds():
    """How often a held playlist request must refresh its client record.

    last_active is only advanced by touch_hls_session, and an HLS client is
    reaped as a ghost after HLS_SEGMENT_DURATION * HLS_CLIENT_GHOST_SEGMENTS
    seconds without it. A request parked for the whole channel init grace
    would otherwise be reaped mid-wait.
    """
    ghost_timeout = float(ConfigHelper.get("HLS_SEGMENT_DURATION", 4)) * float(
        ConfigHelper.get("HLS_CLIENT_GHOST_SEGMENTS", 3)
    )
    return max(0.5, min(3.0, ghost_timeout / 4))


def _wait_for_playlist(redis_client, token, channel_id, client_id, fmt):
    """Hold a playlist request until the output publishes its first playlist.

    Returns (playlist_json, error_response). (None, None) means the wait
    budget ran out and the caller should answer 503.

    While the channel is still starting or failing over, the wait follows
    channel_init_grace_period, matching how long a TS client is held. After
    the channel is ready, only the HLS media-duration gate remains, so the
    wait drops to HLS_READY_PLAYLIST_WAIT_SECONDS measured from the moment
    the channel was first seen ready.
    """
    playlist_key = RedisKeys.output_playlist(channel_id, fmt)
    # Steady-state polls hit this single GET and never enter the wait loop.
    playlist_json = redis_client.get(playlist_key)
    if playlist_json:
        return playlist_json, None

    output_state_key = RedisKeys.output_state(channel_id, fmt)
    metadata_key = RedisKeys.channel_metadata(channel_id)
    stopping_key = RedisKeys.channel_stopping(channel_id)
    client_stop_key = RedisKeys.client_stop(channel_id, client_id)

    init_grace = float(ConfigHelper.channel_init_grace_period())
    touch_interval = _touch_interval_seconds()
    started = last_touch = time.monotonic()
    ready_since = None

    while True:
        # One round trip per poll for everything the loop decides on.
        pipe = redis_client.pipeline(transaction=False)
        pipe.get(playlist_key)
        pipe.get(output_state_key)
        pipe.hget(metadata_key, ChannelMetadataField.STATE)
        pipe.exists(stopping_key)
        pipe.exists(client_stop_key)
        playlist_json, output_state, channel_state, stopping, client_stop = pipe.execute()

        if playlist_json:
            return playlist_json, None
        if (
            output_state == "stopped"
            or stopping
            or client_stop
            or channel_state in _CHANNEL_DEAD_STATES
        ):
            _drop_hls_session(redis_client, token)
            return None, JsonResponse({"error": "Stream stopped"}, status=410)

        now = time.monotonic()
        if channel_state is None or channel_state in _CHANNEL_STARTING_STATES:
            ready_since = None
            if now - started >= init_grace:
                return None, None
        else:
            if ready_since is None:
                ready_since = now
            if now - ready_since >= HLS_READY_PLAYLIST_WAIT_SECONDS:
                return None, None

        if now - last_touch >= touch_interval:
            _, reason = touch_hls_session(redis_client, token)
            if reason is not None:
                status_error = "Stream stopped" if reason == "stopped" else "Session expired"
                return None, JsonResponse({"error": status_error}, status=410)
            last_touch = now

        gevent.sleep(_PLAYLIST_WAIT_POLL_SECONDS)


def _serve_hls_playlist(token):
    """Build the rolling live media playlist response for one capability URL."""
    proxy_server = ProxyServer.get_instance()
    redis_client = proxy_server.redis_client
    if not redis_client:
        return JsonResponse({"error": "Proxy unavailable"}, status=503)

    loaded, error = _load_live_session(redis_client, token)
    if error is not None:
        return error
    channel_id, client_id, client_hash = loaded
    fmt = _resolved_format(client_hash)

    playlist_json, error = _wait_for_playlist(
        redis_client, token, channel_id, client_id, fmt
    )
    if error is not None:
        return error
    if not playlist_json:
        response = JsonResponse({"error": "Stream not ready"}, status=503)
        response["Retry-After"] = "2"
        return response

    try:
        state = json.loads(playlist_json)
        if _playlist_is_stale(state):
            # Temporary unavailability of a live playlist update: 404 so
            # clients retry, rather than 410 Gone for a permanent end.
            logger.warning(
                f"[{client_id}] HLS playlist for {channel_id} stopped advancing"
            )
            return JsonResponse({"error": "Playlist stale"}, status=404)
        body = render_media_playlist(
            state.get("window", []),
            state.get("target", 4),
            adv_target=state.get("adv_target"),
            disc_sequence=state.get("disc_seq", 0),
            start_behind_seconds=state.get("start_behind"),
        )
    except (TypeError, ValueError, KeyError) as e:
        logger.error(f"[{client_id}] Malformed HLS playlist state for {channel_id}: {e}")
        return JsonResponse({"error": "Playlist unavailable"}, status=500)

    response = HttpResponse(body, content_type="application/vnd.apple.mpegurl")
    response["Cache-Control"] = "no-cache"
    return response


def _serve_hls_segment(token, seq):
    """Fetch one media segment by sequence number for a capability URL."""
    proxy_server = ProxyServer.get_instance()
    redis_client = proxy_server.redis_client
    if not redis_client:
        return JsonResponse({"error": "Proxy unavailable"}, status=503)

    loaded, error = _load_live_session(redis_client, token)
    if error is not None:
        return error
    channel_id, _client_id, client_hash = loaded
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


@api_view(["GET"])
@permission_classes([AllowAny])
def hls_playlist(request, token):
    """Rolling live media playlist for one HLS capability URL."""
    try:
        if not network_access_allowed(request, "STREAMS"):
            return Response({"error": "Forbidden"}, status=403)
        return _serve_hls_playlist(token)
    finally:
        # Settings lookup above hits the ORM; this endpoint is polled every
        # few seconds per client, so release stale connections promptly.
        close_old_connections()


@api_view(["GET"])
@permission_classes([AllowAny])
def hls_segment(request, token, seq):
    """One HLS media segment for an opaque capability URL."""
    try:
        if not network_access_allowed(request, "STREAMS"):
            return Response({"error": "Forbidden"}, status=403)
        return _serve_hls_segment(token, seq)
    finally:
        # Settings lookup above hits the ORM; this endpoint is polled every
        # few seconds per client, so release stale connections promptly.
        close_old_connections()
