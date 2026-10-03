"""
HLS output HTTP endpoints.

Steady-state HLS is pull-based: playlist/segment polls touch the client's
Redis record (last_active + TTLs), and a player that stops gets reaped by
the ghost-client heartbeat. The cold first playlist is different: while the
output has not published yet (channel init / media-duration gate), that
request is a chunked streaming response so the wait is visible on the wire:

- RFC 8216 4.3.1.1: #EXTM3U MUST be the first line, so it goes out at once.
- RFC 8216 4.1: other lines starting with '#' are comments that clients
  SHOULD ignore. A periodic comment forces a socket write, so a client that
  has gone away ends the response (the server closes the iterator) instead
  of only being noticed when the wait budget runs out.
- The response is completed with the real playlist. It is never closed with
  a header-only one: RFC 8216 section 2 defines a Media Playlist as
  containing Media Segments, so that would read as a finished empty
  playlist rather than an in-progress wait.

That held request is also the one place an HLS player is seen leaving. Held
requests are counted per session in Redis. When the last one disconnects
before the playlist is published, the client is stopped after a short
reconnect grace, unless the player came back in the meantime. Once the
playlist is published, or if the count is lost, the ghost reaper owns cleanup.
The wait for that first publish is signalled (local Event + Redis pubsub),
not a blind sleep, so the client gets the playlist as soon as the media
gate clears rather than on the next poll tick.

Follow-up URLs are opaque capability tokens (`/proxy/hls/<token>/...`), not
channel uuids or XC credentials. Possession of the token is the session;
playlist/segment polls do not hit the ORM.
"""

import json
import time

import gevent
from django.db import close_old_connections
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.utils import RedisClient
from dispatcharr.utils import network_access_allowed

from ...config_helper import ConfigHelper
from ...constants import ChannelMetadataField, ChannelState
from ...redis_keys import RedisKeys
from ...server import ProxyServer
from ...services.channel_service import ChannelService
from ...utils import get_logger
from .segmenter import render_media_playlist
from .session import (
    claim_abandoned_session,
    enter_cold_start,
    exit_cold_start,
    touch_hls_session,
)
from .waiters import register_playlist_waiter, unregister_playlist_waiter

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
# How often the cold-start stream re-checks Redis while still waiting, and how
# often it drips a comment so a leave is noticed. The wait itself wakes early
# when the playlist is published (see waiters.notify_playlist_ready).
_PLAYLIST_WAIT_POLL_SECONDS = 0.25
# After the last held cold-start request disconnects, how long to wait for the
# player to come back before stopping its client. A leave is noticed within one
# poll tick; a retrying player usually opens its next request after that, so
# this window is what keeps that retry's session alive. Measured gaps after the
# notice were about 80 to 165 ms on loopback, and later on a real network by
# about a round trip (a new connection is needed).
HLS_COLD_START_RECONNECT_GRACE_SECONDS = 0.5
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
    """How often a cold-start stream must refresh its client record.

    last_active is only advanced by touch_hls_session, and an HLS client is
    reaped as a ghost after HLS_SEGMENT_DURATION * HLS_CLIENT_GHOST_SEGMENTS
    seconds without it. A request parked for the whole channel init grace
    would otherwise be reaped mid-wait.
    """
    ghost_timeout = float(ConfigHelper.get("HLS_SEGMENT_DURATION", 4)) * float(
        ConfigHelper.get("HLS_CLIENT_GHOST_SEGMENTS", 3)
    )
    return max(0.5, min(3.0, ghost_timeout / 4))


def _playlist_wait_keys(channel_id, client_id, fmt):
    """Redis keys read on every cold-start wait poll."""
    return (
        RedisKeys.output_playlist(channel_id, fmt),
        RedisKeys.output_state(channel_id, fmt),
        RedisKeys.channel_metadata(channel_id),
        RedisKeys.channel_stopping(channel_id),
        RedisKeys.client_stop(channel_id, client_id),
    )


def _poll_playlist_wait(redis_client, playlist_key, output_state_key,
                        metadata_key, stopping_key, client_stop_key):
    """One Redis round trip for cold-start wait decisions."""
    pipe = redis_client.pipeline(transaction=False)
    pipe.get(playlist_key)
    pipe.get(output_state_key)
    pipe.hget(metadata_key, ChannelMetadataField.STATE)
    pipe.exists(stopping_key)
    pipe.exists(client_stop_key)
    playlist_json, output_state, channel_state, stopping, client_stop = pipe.execute()
    dead = (
        output_state == "stopped"
        or bool(stopping)
        or bool(client_stop)
        or channel_state in _CHANNEL_DEAD_STATES
    )
    return playlist_json, channel_state, dead


def _wait_budget_exceeded(channel_state, now, started, ready_since, init_grace):
    """Return (exceeded, ready_since) for the two-phase cold-start budget."""
    if channel_state is None or channel_state in _CHANNEL_STARTING_STATES:
        return (now - started >= init_grace), None
    if ready_since is None:
        ready_since = now
    return (now - ready_since >= HLS_READY_PLAYLIST_WAIT_SECONDS), ready_since


class _StalePlaylist(Exception):
    """The playlist descriptor stopped advancing (see _playlist_is_stale)."""


def _render_playlist_text(playlist_json):
    """Render playlist JSON to m3u8 text.

    Raises _StalePlaylist for a descriptor nothing is advancing any more, and
    ValueError / TypeError / KeyError for a malformed one.
    """
    state = json.loads(playlist_json)
    if _playlist_is_stale(state):
        raise _StalePlaylist()
    return render_media_playlist(
        state.get("window", []),
        state.get("target", 4),
        adv_target=state.get("adv_target"),
        disc_sequence=state.get("disc_seq", 0),
        start_behind_seconds=state.get("start_behind"),
    )


def _cold_start_playlist_chunks(redis_client, token, channel_id, client_id, fmt,
                                init_grace):
    """Yield a chunked first playlist: comments while waiting, then the real body.

    Sent only when Redis has no playlist yet. Finishes with the rendered
    playlist once the manager publishes (after the media-duration gate). When
    giving up it just ends the response; it never appends a header-only
    playlist (see the module docstring).

    ``init_grace`` is resolved by the caller: the settings lookup can hit the
    ORM, and this generator runs after the view has released its connection.
    """
    playlist_key, output_state_key, metadata_key, stopping_key, client_stop_key = (
        _playlist_wait_keys(channel_id, client_id, fmt)
    )
    touch_interval = _touch_interval_seconds()
    started = last_touch = time.monotonic()
    ready_since = None
    comment_n = 0
    sent_extm3u = False
    disconnected_at = None
    counted = _count_cold_start(redis_client, token, client_id)
    waiter = register_playlist_waiter(channel_id, fmt)

    try:
        while True:
            playlist_json, channel_state, dead = _poll_playlist_wait(
                redis_client,
                playlist_key,
                output_state_key,
                metadata_key,
                stopping_key,
                client_stop_key,
            )
            if dead:
                _drop_hls_session(redis_client, token)
                logger.info(
                    f"[{client_id}] HLS cold-start ending: channel/output "
                    f"stopped for {channel_id}"
                )
                return

            if playlist_json:
                try:
                    body = _render_playlist_text(playlist_json)
                except (_StalePlaylist, TypeError, ValueError, KeyError) as e:
                    logger.error(
                        f"[{client_id}] HLS cold-start got unusable playlist "
                        f"for {channel_id}: {e!r}"
                    )
                    return
                # #EXTM3U may already be on the wire; if the playlist won the
                # race before any bytes went out, send the whole document.
                yield body.removeprefix("#EXTM3U\n") if sent_extm3u else body
                return

            if not sent_extm3u:
                yield "#EXTM3U\n"
                sent_extm3u = True
            else:
                comment_n += 1
                yield f"# dispatcharr: waiting {comment_n}\n"

            now = time.monotonic()
            exceeded, ready_since = _wait_budget_exceeded(
                channel_state, now, started, ready_since, init_grace
            )
            if exceeded:
                logger.warning(
                    f"[{client_id}] HLS cold-start timed out waiting for "
                    f"playlist on {channel_id}"
                )
                return

            if now - last_touch >= touch_interval:
                # The script already forgets the session on every failure.
                _, reason = touch_hls_session(redis_client, token)
                if reason is not None:
                    logger.info(
                        f"[{client_id}] HLS cold-start ending: session "
                        f"{reason} for {channel_id}"
                    )
                    return
                last_touch = now

            # Timeout keeps drip/dead/touch checks moving. A playlist-ready
            # signal wakes this early so we do not wait out the full tick.
            waiter.wait(timeout=_PLAYLIST_WAIT_POLL_SECONDS)
            waiter.clear()
    except GeneratorExit:
        # A failed write makes the server close the iterator, always while
        # suspended at a yield. Stop polling and touching; whether the client
        # is gone for good is decided in _release_cold_start.
        disconnected_at = time.time()
        logger.info(
            f"[{client_id}] HLS cold-start client disconnected "
            f"for {channel_id}"
        )
        raise
    finally:
        unregister_playlist_waiter(channel_id, fmt, waiter)
        if counted:
            _release_cold_start(
                redis_client, token, channel_id, client_id, fmt, disconnected_at
            )


def _count_cold_start(redis_client, token, client_id):
    """Register this held request on the session. True when it was counted."""
    try:
        return enter_cold_start(redis_client, token) is not None
    except Exception as e:
        logger.warning(f"[{client_id}] HLS cold-start could not be counted: {e}")
        return False


def _release_cold_start(redis_client, token, channel_id, client_id, fmt,
                        disconnected_at):
    """Drop this request from the session count; maybe schedule a teardown.

    Only a disconnect (``disconnected_at`` set) can lead to a teardown, and
    only when it was the last held request. Finishing normally, timing out
    or being told the channel is dead never does: in those cases the player
    got an answer, or the channel is already ending.
    """
    try:
        remaining = exit_cold_start(redis_client, token)
    except Exception as e:
        logger.warning(f"[{client_id}] HLS cold-start count release failed: {e}")
        return
    if disconnected_at is None or remaining != 0:
        return
    gevent.spawn_later(
        HLS_COLD_START_RECONNECT_GRACE_SECONDS,
        _stop_abandoned_cold_start,
        redis_client,
        token,
        channel_id,
        client_id,
        fmt,
        disconnected_at,
    )


def _stop_abandoned_cold_start(redis_client, token, channel_id, client_id, fmt,
                               disconnected_at):
    """Stop the client if the player did not come back during the grace.

    The claim is atomic with its conditions (see claim_abandoned_session), so
    a request landing at the same moment either cancels the stop or finds the
    session gone and gets a 410.
    """
    try:
        claimed = claim_abandoned_session(
            redis_client,
            token,
            RedisKeys.output_playlist(channel_id, fmt),
            disconnected_at,
        )
        if claimed is None:
            logger.debug(
                f"[{client_id}] HLS cold-start client came back or the "
                f"playlist was published for {channel_id}; not stopping"
            )
            return
        logger.info(
            f"[{client_id}] HLS cold-start client did not return within "
            f"{HLS_COLD_START_RECONNECT_GRACE_SECONDS}s; stopping it "
            f"on {channel_id}"
        )
        ChannelService.stop_client(*claimed)
    except Exception as e:
        logger.error(
            f"[{client_id}] HLS cold-start teardown failed for {channel_id}: {e}"
        )


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

    # Steady-state polls are the common path: one GET, normal response.
    playlist_json = redis_client.get(RedisKeys.output_playlist(channel_id, fmt))
    if playlist_json:
        try:
            body = _render_playlist_text(playlist_json)
        except _StalePlaylist:
            # Temporary unavailability of a live playlist update: 404 so
            # clients retry, rather than 410 Gone for a permanent end.
            logger.warning(
                f"[{client_id}] HLS playlist for {channel_id} stopped advancing"
            )
            return JsonResponse({"error": "Playlist stale"}, status=404)
        except (TypeError, ValueError, KeyError) as e:
            logger.error(
                f"[{client_id}] Malformed HLS playlist state for {channel_id}: {e}"
            )
            return JsonResponse({"error": "Playlist unavailable"}, status=500)
        response = HttpResponse(body, content_type="application/vnd.apple.mpegurl")
        response["Cache-Control"] = "no-cache"
        return response

    # Before committing to a streamed 200, fail fast if the channel is already
    # dead so the client still gets a proper 410 status code.
    _, _, dead = _poll_playlist_wait(
        redis_client, *_playlist_wait_keys(channel_id, client_id, fmt)
    )
    if dead:
        _drop_hls_session(redis_client, token)
        return JsonResponse({"error": "Stream stopped"}, status=410)

    response = StreamingHttpResponse(
        _cold_start_playlist_chunks(
            redis_client,
            token,
            channel_id,
            client_id,
            fmt,
            float(ConfigHelper.channel_init_grace_period()),
        ),
        content_type="application/vnd.apple.mpegurl",
    )
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
