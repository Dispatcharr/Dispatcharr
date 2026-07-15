"""Catch-up (timeshift) proxy with multi-provider failover."""

import hmac
import json
import logging
import secrets
import threading
import time
from urllib.parse import urlencode

import requests
from django.core.cache import cache
from django.db import close_old_connections
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
    StreamingHttpResponse,
)
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.accounts.authentication import ApiKeyAuthentication, QueryParamJWTAuthentication
from apps.accounts.models import User
from apps.channels.models import Channel
from apps.channels.utils import get_channel_catchup_streams
from apps.m3u.connection_pool import release_profile_slot, reserve_profile_slot
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.tasks import get_transformed_credentials
from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.timeshift.redis_keys import (
    TimeshiftRedisKeys,
    mint_session_id,
    programme_media_id,
    stats_channel_id as make_stats_channel_id,
    virtual_channel_id as make_virtual_channel_id,
)

stats_channel_id = make_stats_channel_id
from apps.proxy.live_proxy.utils import get_client_ip
from apps.proxy.utils import (
    _timeshift_stop_channel_id,
    check_user_stream_limits,
    find_ts_sync,
    get_user_active_connections,
)
from core.utils import RedisClient, _is_gevent_monkey_patched
from dispatcharr.utils import network_access_allowed

from .helpers import (
    TimeshiftCredentials,
    build_timeshift_candidate_urls,
    convert_timestamp_to_provider_tz,
    get_programme_duration,
    parse_catchup_timestamp,
)
from .sessions import catchup_session_exists, delete_catchup_session, resolve_catchup_playback
from .stats import (
    EOF_PROBE_TAIL_BYTES,
    resolve_stats_playback_fields,
    seed_stream_stats_metadata,
)

logger = logging.getLogger(__name__)

CLIENT_TTL_SECONDS = 60
_STATS_DISCONNECT_GRACE_SECONDS = 5  # VOD-style grace before dropping stats on disconnect.
_STATS_RECONNECT_SETTLE_SECONDS = 1.5  # Brief pause before arming grace (XC reconnects fast).
_STATS_GRACE_MIN_YIELDED_BYTES = 65536  # Ignore parallel startup probes that die immediately.
_STATS_GRACE_MIN_ELAPSED_SECONDS = 2.0
# Atomically drop the grace key only when its value still matches *token*.
_CLAIM_STATS_GRACE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""
_MATCH_SCORE_THRESHOLD = 8  # client_ip (5) + client_user_agent (3)
_STOP_REASON_REUSE = "reuse"
_STOP_REASON_HOP = "hop"
_STOP_REASON_ADMIN = "admin"
_STOP_REASON_LIMIT = "limit"
_TERMINAL_STOP_REASONS = frozenset({
    _STOP_REASON_HOP, _STOP_REASON_ADMIN, _STOP_REASON_LIMIT,
})


def _finalize_timeshift_response(response):
    """Release ORM database connections before returning to the client."""
    close_old_connections()
    return response


def timeshift_proxy(request, username, password, stream_id, timestamp, duration):  # noqa: ARG001 stream_id
    """Proxy an XC catch-up request to the provider with multi-stream failover.

    URL shape (XC catch-up clients):
        ``stream_id``: EPG channel number (ignored here).
        ``duration``: Dispatcharr ``Channel.id`` (XC API exposes channel.id as stream_id).
        ``timestamp``: UTC programme start (``YYYY-MM-DD:HH-MM`` or XC colon form
            ``YYYY-MM-DD:HH:MM:SS``).

    Session handling (``?session_id=``):
        First request with no ``session_id`` and no matching pool entry → ``301`` with a
        minted ``session_id``. Reconnects that omit ``session_id`` but fingerprint-match
        an in-flight or idle pool entry for the same viewer are served immediately
        (no redirect). Reuse ``session_id`` for all range/seek requests in a programme.
    """
    raw_id = duration[:-3] if duration.endswith(".ts") else duration

    user = _authenticate_user(username, password)
    if user is None:
        return _finalize_timeshift_response(HttpResponseForbidden("Invalid credentials"))

    if not network_access_allowed(request, "XC_API", user):
        return _finalize_timeshift_response(HttpResponseForbidden("Access denied"))

    try:
        channel = Channel.objects.get(id=int(raw_id))
    except (Channel.DoesNotExist, ValueError, TypeError):
        close_old_connections()
        raise Http404("Channel not found") from None

    if not _user_can_access_channel(user, channel):
        return _finalize_timeshift_response(HttpResponseForbidden("Access denied"))

    return _serve_catchup(request, user, channel, timestamp)


@extend_schema(
    description=(
        "Stream catch-up (TV archive) MPEG-TS for a channel.\n\n"
        "**Recommended (native apps):** call ``POST /api/catchup/sessions/`` "
        "with a JWT or API key to obtain a ``playback_url`` containing "
        "``session_id`` only. Pass that URL to the video player without an "
        "``?token=`` required. The session binds the programme ``start`` "
        "time server-side.\n\n"
        "**Legacy / direct auth:** supply ``start`` (programme UTC start "
        "time) plus ``Authorization: Bearer``, ``X-API-Key``, or "
        "``?token=<jwt>``. Optionally include a client ``session_id`` for "
        "provider pooling.\n\n"
        "**``session_id`` without a matching pool:** the server responds with "
        "**301** and a minted ``session_id`` (direct-auth / first play only).\n\n"
        "**``session_id`` omitted but pool match:** when the same viewer "
        "reconnects (e.g. IPTV fast-forward) and fingerprint-matches an "
        "existing pool entry, the stream is served on that request with no "
        "redirect round trip.\n\n"
        "**Plain GET (no ``Range``):** upstream archive is streamed from byte "
        "0 with ``Content-Length`` when the provider reports file size "
        "(provider-faithful behaviour for XC-style IPTV clients)."
    ),
    parameters=[
        OpenApiParameter(
            name="session_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                "Playback session from ``POST /api/catchup/sessions/`` or a "
                "prior **301** redirect. When present, JWT is optional. Reuse "
                "for all range/seek requests during the same programme. "
                "May be omitted on reconnect when the server adopts a "
                "fingerprint-matched pool entry."
            ),
        ),
        OpenApiParameter(
            name="start",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                "Programme start time in UTC. Required for direct-auth "
                "playback (no API session). Ignored when ``session_id`` was "
                "issued by ``POST /api/catchup/sessions/``."
            ),
        ),
        OpenApiParameter(
            name="token",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                "JWT access token when Authorization headers are unavailable. "
                "Not needed when using an API playback session."
            ),
        ),
    ],
    responses={
        200: {
            "description": (
                "MPEG-TS stream. Partial content (``206``) when the client "
                "sent ``Range``. Full-file ``200`` on plain GET includes "
                "``Content-Length`` when the upstream archive size is known."
            ),
        },
        301: {
            "description": (
                "Redirect to the same URL with a server-minted ``session_id`` "
                "when the client did not supply one and no fingerprint-matched "
                "pool entry exists (first play / direct-auth only)."
            ),
        },
        401: {"description": "Missing or expired authentication / session."},
        403: {"description": "Access denied or session/channel mismatch."},
    },
    tags=["proxy"],
)
@api_view(["GET"])
@authentication_classes([JWTAuthentication, ApiKeyAuthentication, QueryParamJWTAuthentication])
@permission_classes([AllowAny])
def catchup_proxy(request, channel_id):
    """Native API catch-up playback for a channel."""
    if not network_access_allowed(request, "STREAMS"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    auth_user = (
        request.user
        if getattr(request, "user", None) and request.user.is_authenticated
        else None
    )

    session_id = request.GET.get("session_id")
    timestamp = request.GET.get("start")
    user = auth_user

    if session_id:
        resolved = resolve_catchup_playback(session_id, channel_id)
        if resolved is None:
            if auth_user is None:
                return JsonResponse(
                    {"error": "Invalid or expired playback session"},
                    status=401,
                )
        else:
            session_user, bound_start = resolved
            if auth_user is not None and auth_user.id != session_user.id:
                return _finalize_timeshift_response(HttpResponseForbidden("Access denied"))
            user = session_user
            timestamp = bound_start

    if user is None:
        return JsonResponse({"error": "Authentication required"}, status=401)

    try:
        channel = Channel.objects.get(uuid=channel_id)
    except Channel.DoesNotExist:
        close_old_connections()
        raise Http404("Channel not found") from None

    if not _user_can_access_channel(user, channel):
        return _finalize_timeshift_response(HttpResponseForbidden("Access denied"))

    if not timestamp:
        return _finalize_timeshift_response(HttpResponseBadRequest("Missing start parameter"))

    return _serve_catchup(request, user, channel, timestamp)


def _serve_catchup(request, user, channel, timestamp):
    """Shared catch-up proxy logic for XC and native API entry points."""
    if parse_catchup_timestamp(timestamp) is None:
        return _finalize_timeshift_response(HttpResponseBadRequest("Invalid timestamp"))

    catchup_streams = get_channel_catchup_streams(channel)
    if not catchup_streams:
        return _finalize_timeshift_response(
            HttpResponseBadRequest("Timeshift not supported for this channel")
        )

    debug = logger.isEnabledFor(logging.DEBUG)

    # EPG duration lookup stays in UTC; provider TZ conversion is per-attempt below.
    duration_minutes = get_programme_duration(channel, timestamp)

    safe_ts = timestamp.replace(":", "-").replace("/", "-")
    client_ip = get_client_ip(request)
    client_user_agent = request.META.get("HTTP_USER_AGENT", "") or ""
    range_header = request.META.get("HTTP_RANGE")
    channel_logo_id = getattr(channel, "logo_id", None)

    redis_client = RedisClient.get_client()

    # One provider slot per session_id, not per programme.
    media_id = programme_media_id(channel.id, safe_ts)

    session_id = request.GET.get("session_id")
    if not session_id:
        matched = _find_matching_pool_session(
            redis_client,
            media_id=media_id,
            channel_id=channel.id,
            user_id=user.id,
            client_ip=client_ip,
            client_user_agent=client_user_agent,
            include_busy=True,
        )
        if matched:
            if debug:
                logger.debug(
                    "Timeshift session adopt: reusing %s for %s",
                    matched, request.path,
                )
            session_id = matched
        else:
            logger.debug("Timeshift session redirect: %s (new session)", request.path)
            return _finalize_timeshift_response(_redirect_with_new_session(request))

    session_entry = _get_pool_entry(redis_client, session_id)
    if session_entry and not _pool_entry_owned_by_user(session_entry, user.id):
        logger.info(
            "Timeshift: rejecting foreign session_id for user %s", user.id,
        )
        return _finalize_timeshift_response(_redirect_with_new_session(request))

    # Stable client identity for stats, stop keys, and the provider pool.
    effective_session_id = session_id
    client_id = session_id

    # Fingerprint-match when this session_id has no pool yet (e.g. after 301).
    # Do not adopt an idle exact-media pool: that is a duplicate reconnect to a
    # programme slot the viewer just left, not a programme hop.
    if not session_entry:
        matched = _find_matching_pool_session(
            redis_client,
            media_id=media_id,
            channel_id=channel.id,
            user_id=user.id,
            client_ip=client_ip,
            client_user_agent=client_user_agent,
            include_busy=True,
            fresh_session=True,
        )
        if matched:
            logger.info(
                "Timeshift fingerprint matched session %s for %s",
                matched, session_id,
            )
            effective_session_id = matched
            client_id = matched

    if debug:
        if effective_session_id != session_id:
            logger.debug(
                "Timeshift request: channel=%s media=%s session=%s "
                "effective=%s user=%s range=%s ip=%s",
                channel.name, media_id, session_id, effective_session_id,
                user.id, range_header or "(none)", client_ip,
            )
        else:
            logger.debug(
                "Timeshift request: channel=%s media=%s session=%s "
                "user=%s range=%s ip=%s",
                channel.name, media_id, effective_session_id, user.id,
                range_header or "(none)", client_ip,
            )

    # Displace this user's prior catch-up on other positions of this channel.
    _terminate_previous_timeshift_sessions(
        redis_client, user, channel.id, media_id, effective_session_id,
    )

    if not check_user_stream_limits(user, client_id, media_id=media_id):
        return _finalize_timeshift_response(HttpResponseForbidden("Stream limit exceeded"))

    _touch_stats_on_session_request(redis_client, channel.id, effective_session_id)

    if effective_session_id == session_id:
        pool = _snapshot_from_entry(session_entry)
    else:
        pool = _pool_snapshot(redis_client, effective_session_id)
    pool_exists = pool is not None
    pool_busy = pool["busy"] if pool else False
    pool_content_length = pool["content_length"] if pool else None
    busy_serving_range = pool["serving_range"] if pool else None
    pool_media_id = None
    pool_presentation_length = None
    if pool and pool.get("entry"):
        pool_media_id = pool["entry"].get("media_id")
        pool_presentation_length = pool["entry"].get("presentation_length")
    elif session_entry:
        pool_media_id = session_entry.get("media_id")
        pool_presentation_length = session_entry.get("presentation_length")
    # After a scrub rewrite the client sees a shorter file; EOF probes and
    # Range seeks are relative to that presentation, not the full CDN archive.
    probe_length = pool_presentation_length or pool_content_length

    scrub_displacement = (
        pool_exists
        and _should_displace_busy_pool(
            range_header,
            probe_length,
            busy_serving_range,
            pool_media_id=pool_media_id,
            media_id=media_id,
        )
    )
    # Pool may look idle while the replacement upstream is still active.
    if (
        scrub_displacement
        and not pool_busy
        and _session_has_active_timeshift_stream(user, effective_session_id)
    ):
        pool_busy = True

    acquired = None
    if pool_exists:
        if not pool_busy:
            acquired = _acquire_idle_pool_session(
                redis_client, effective_session_id, user_id=user.id,
            )
        elif _should_preempt_for_programme_change(
            redis_client, effective_session_id, pool_media_id, media_id,
            user=user,
        ):
            acquired = _try_reacquire_idle_pool(
                redis_client, effective_session_id,
                user_id=user.id, user=user,
            )
        elif _should_preempt_plain_reconnect(
            range_header,
            pool_exists=pool_exists,
            pool_busy=pool_busy,
            pool_media_id=pool_media_id,
            media_id=media_id,
        ):
            acquired = _try_reacquire_idle_pool(
                redis_client, effective_session_id,
                user_id=user.id, user=user,
            )
        elif scrub_displacement:
            acquired = _try_reacquire_idle_pool(
                redis_client, effective_session_id,
                user_id=user.id, user=user,
                wait_seconds=_POOL_SCRUB_WAIT_SECONDS,
            )
            if acquired is None:
                logger.warning(
                    "Timeshift: session %s still busy after scrub preempt, opening failover",
                    effective_session_id,
                )
                abandoned_profile_id = None
                abandoned_entry = pool["entry"] if pool and pool.get("entry") else session_entry
                if abandoned_entry:
                    abandoned_profile_id = abandoned_entry.get("profile_id")
                _force_abandon_busy_pool(
                    redis_client,
                    effective_session_id,
                    abandoned_profile_id,
                )
                pool_exists = False
                pool_busy = False

    last_response = None
    decisive_accounts = set()

    if acquired is not None:
        descriptor, profile = acquired
        reuse_response = _stream_reused_session(
            redis_client,
            session_id=effective_session_id,
            descriptor=descriptor,
            profile=profile,
            channel=channel,
            media_id=media_id,
            safe_ts=safe_ts,
            timestamp=timestamp,
            duration_minutes=duration_minutes,
            client_id=client_id,
            client_ip=client_ip,
            client_user_agent=client_user_agent,
            range_header=range_header,
            channel_logo_id=channel_logo_id,
            user=user,
            debug=debug,
        )
        if reuse_response is not None:
            if reuse_response.status_code < 400:
                return _finalize_timeshift_response(reuse_response)
            if getattr(reuse_response, "timeshift_passthrough", False) is True:
                return _finalize_timeshift_response(reuse_response)
            last_response = reuse_response
            if getattr(reuse_response, "timeshift_decisive", False):
                try:
                    decisive_accounts.add(int(descriptor["account_id"]))
                except (ValueError, TypeError):
                    pass

    if pool_exists and pool_busy and acquired is None:
        probe_entry = None
        if pool and pool.get("entry"):
            probe_entry = pool["entry"]
        elif session_entry:
            probe_entry = session_entry
        probe_response = _try_serve_busy_eof_probe(
            redis_client=redis_client,
            session_id=effective_session_id,
            entry=probe_entry,
            range_header=range_header,
            probe_length=probe_length,
            debug=debug,
        )
        if probe_response is not None:
            return probe_response
        logger.debug(
            "Timeshift: deferring busy session %s range=%s media=%s pool_media=%s",
            effective_session_id, range_header or "(none)", media_id, pool_media_id,
        )
        return _finalize_timeshift_response(HttpResponse("Stream slot busy", status=503))

    capacity_blocked = False
    for catchup_stream in catchup_streams:
        m3u_account = catchup_stream.m3u_account
        if m3u_account is None or m3u_account.account_type != "XC":
            continue
        if m3u_account.id in decisive_accounts:
            continue

        stream_id_value = (catchup_stream.custom_properties or {}).get("stream_id")
        if stream_id_value is None:
            continue

        m3u_profiles = list(m3u_account.profiles.filter(is_active=True))
        default_profile = next((p for p in m3u_profiles if p.is_default), None)
        if default_profile is None:
            logger.debug(
                "Timeshift: account %s has no active default profile, skipping",
                m3u_account.id,
            )
            continue
        profile_walk = [default_profile] + [
            p for p in m3u_profiles if not p.is_default
        ]

        # Providers index archives in their own timezone (from server_info on auth).
        provider_tz_name = None
        _server_info = (default_profile.custom_properties or {}).get("server_info") or {}
        if isinstance(_server_info, dict):
            provider_tz_name = _server_info.get("timezone")
        provider_timestamp = convert_timestamp_to_provider_tz(timestamp, provider_tz_name)

        # Reserve a provider profile slot before connecting (same contract as live/VOD).
        reserved_profile = None
        for profile in profile_walk:
            if redis_client is None:
                reserved_profile = profile
                break
            reserved, _count, reason = reserve_profile_slot(profile, redis_client)
            if reserved:
                reserved_profile = profile
                break
            logger.info(
                "Timeshift: profile %s %s on account %s, trying next profile",
                profile.id, reason or "unavailable", m3u_account.id,
            )
        if reserved_profile is None:
            capacity_blocked = True
            logger.warning(
                "Timeshift: all profiles at capacity on account %s for channel %s",
                m3u_account.id, channel.name,
            )
            continue

        if not _create_pool_session(
            redis_client,
            session_id=effective_session_id,
            media_id=media_id,
            user_id=user.id,
            client_ip=client_ip,
            client_user_agent=client_user_agent,
            account_id=m3u_account.id,
            profile_id=reserved_profile.id,
            stream_id=stream_id_value,
            dispatcharr_stream_id=catchup_stream.id,
            provider_timestamp=provider_timestamp,
            provider_tz_name=provider_tz_name,
        ):
            try:
                release_profile_slot(reserved_profile.id, redis_client)
            except Exception as exc:
                logger.warning(
                    "Timeshift slot release failed after pool race on profile %s: %s",
                    reserved_profile.id, exc,
                )
            logger.debug(
                "Timeshift: pool entry already exists for session %s, deferring",
                effective_session_id,
            )
            return _finalize_timeshift_response(
                HttpResponse("Stream slot busy", status=503)
            )
        release_cb = _make_release_once(
            redis_client, effective_session_id, reserved_profile.id
        )

        try:
            response = _attempt_timeshift_stream(
                m3u_account=m3u_account,
                profile=reserved_profile,
                stream_id_value=stream_id_value,
                provider_timestamp=provider_timestamp,
                provider_tz_name=provider_tz_name,
                duration_minutes=duration_minutes,
                channel=channel,
                safe_ts=safe_ts,
                timestamp=timestamp,
                client_id=client_id,
                client_ip=client_ip,
                client_user_agent=client_user_agent,
                range_header=range_header,
                channel_logo_id=channel_logo_id,
                user=user,
                redis_client=redis_client,
                debug=debug,
                release_cb=release_cb,
                pool_session_id=effective_session_id,
                stats_stream_id=catchup_stream.id,
                stream_stats=catchup_stream.stream_stats,
            )
        except Exception:
            _discard_pool_session(redis_client, effective_session_id, reserved_profile.id)
            close_old_connections()
            raise
        if response.status_code < 400:
            # Streaming: the generator's close path frees the slot via release_cb.
            return _finalize_timeshift_response(response)

        if getattr(response, "timeshift_passthrough", False) is True:
            # 416 etc.: release slot, keep idle pool, no failover.
            release_cb()
            return _finalize_timeshift_response(response)

        # Real failure: drop this session entirely and fail over.
        _discard_pool_session(redis_client, effective_session_id, reserved_profile.id)
        last_response = response
        if getattr(response, "timeshift_decisive", False):
            decisive_accounts.add(m3u_account.id)
        logger.warning(
            "Timeshift attempt failed (HTTP %d%s) on account %s for channel %s, "
            "trying next catch-up stream",
            response.status_code,
            ", decisive: skipping this account's other streams"
            if m3u_account.id in decisive_accounts else "",
            m3u_account.id, channel.name,
        )

    if last_response is not None:
        return _finalize_timeshift_response(last_response)
    if capacity_blocked:
        return _finalize_timeshift_response(
            HttpResponse("No available stream slot", status=503)
        )
    return _finalize_timeshift_response(
        HttpResponseBadRequest("Cannot build timeshift URL")
    )


def _authenticate_user(username, password):
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return None
    expected = (user.custom_properties or {}).get("xc_password")
    if not expected:
        return None
    if not hmac.compare_digest(str(expected), str(password)):
        return None
    return user


def _user_can_access_channel(user, channel):
    if user.user_level < channel.user_level:
        return False
    if user.user_level >= User.UserLevel.ADMIN:
        return True
    profile_count = user.channel_profiles.count()
    if profile_count == 0:
        return True
    return (
        type(channel).objects.filter(
            id=channel.id,
            channelprofilemembership__enabled=True,
            channelprofilemembership__channel_profile__in=user.channel_profiles.all(),
        )
        .exists()
    )


# Per-client pool (session_id from 301 redirect or inline adopt when ?session_id=
# is dropped on reconnect). Fingerprint-match when ?session_id= is absent.
_POOL_ENTRY_TTL = 10 * 60  # Refreshed on playback GET and active-stream heartbeats.
_STREAM_READ_INACTIVITY_SECONDS = CLIENT_TTL_SECONDS  # Shorter than pool TTL; data should flow.
_POOL_IDLE_TTL = CLIENT_TTL_SECONDS  # Must match CLIENT_TTL_SECONDS (stats + fingerprint agree).
_POOL_WAIT_SECONDS = 1.0
# Brief wait after scrub preempt before failover.
_POOL_SCRUB_WAIT_SECONDS = 2.0
_POOL_POLL_INTERVAL = 0.05
# Near-EOF duration probes (~10000 MPEG-TS packets / 1.88MB). Shared with stats.
_EOF_PROBE_TAIL_BYTES = EOF_PROBE_TAIL_BYTES
_EOF_PROBE_UNKNOWN_LENGTH_MIN = 100_000_000


def _pool_key(session_id):
    return TimeshiftRedisKeys.pool(session_id)


def _stats_disconnect_grace_key(stats_channel_id, client_id):
    return TimeshiftRedisKeys.stats_grace(stats_channel_id, client_id)


_STATS_GRACE_DEADLINE_FIELD = "stats_grace_deadline"
_STATS_GRACE_DISCONNECTED_AT_FIELD = "stats_grace_disconnected_at"


def _clear_stats_grace_schedule(redis_client, stats_channel_id, client_id):
    if redis_client is None:
        return
    try:
        redis_client.delete(_stats_disconnect_grace_key(stats_channel_id, client_id))
        client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
        redis_client.hdel(
            client_key,
            _STATS_GRACE_DEADLINE_FIELD,
            _STATS_GRACE_DISCONNECTED_AT_FIELD,
        )
    except Exception as exc:
        logger.debug("Timeshift stats grace cancel failed: %s", exc)


def _cancel_stats_disconnect_grace(redis_client, stats_channel_id, client_id):
    _clear_stats_grace_schedule(redis_client, stats_channel_id, client_id)


def _pool_session_exists(redis_client, session_id):
    if redis_client is None or not session_id:
        return False
    try:
        return bool(redis_client.exists(_pool_key(session_id)))
    except Exception:
        return False


def _pool_session_busy(redis_client, session_id):
    if redis_client is None or not session_id:
        return False
    try:
        busy = redis_client.hget(_pool_key(session_id), "busy")
    except Exception:
        return False
    if isinstance(busy, bytes):
        busy = busy.decode()
    return str(busy) == "1"


def _should_schedule_stats_disconnect_grace(
    total_yielded,
    elapsed_secs,
    *,
    stopped_for_reuse,
    redis_client=None,
    client_id=None,
):
    if stopped_for_reuse:
        return False
    if _is_timeshift_startup_probe(total_yielded, elapsed_secs):
        return False
    # XC duplicate requests often return 503 and reset the first connection
    # within ~1s while the idle pool entry waits for the retry.
    if (
        elapsed_secs < _STATS_GRACE_MIN_ELAPSED_SECONDS
        and redis_client is not None
        and client_id
        and _pool_session_exists(redis_client, client_id)
    ):
        return False
    return True


def _is_timeshift_startup_probe(total_yielded, elapsed_secs):
    """XC often probes several programme URLs in parallel; losers die quickly."""
    return (
        total_yielded < _STATS_GRACE_MIN_YIELDED_BYTES
        and elapsed_secs < _STATS_GRACE_MIN_ELAPSED_SECONDS
    )


def _stats_client_reconnected(
    redis_client, stats_channel_id, client_id, *, disconnected_at,
):
    """Return True when a new playback request superseded this disconnect."""
    if _pool_session_busy(redis_client, client_id):
        return True
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
    try:
        last_active = redis_client.hget(client_key, "last_active")
        if last_active:
            if isinstance(last_active, bytes):
                last_active = last_active.decode()
            # Strict ``>``: the disconnect path heartbeats stats immediately
            # before arming grace, so equality means no reconnect yet.
            if float(last_active) > float(disconnected_at):
                return True
    except (TypeError, ValueError):
        pass
    return False


def _grace_token_claimed(redis_client, grace_key, token):
    if redis_client is None:
        return False
    try:
        current = redis_client.get(grace_key)
        if isinstance(current, bytes):
            current = current.decode()
        return current == token
    except Exception:
        return False


def _complete_expired_stats_grace(redis_client, stats_channel_id, client_id):
    """Run disconnect cleanup when the grace deadline has already passed.

    uWSGI workers often cannot keep a daemon thread alive after the streaming
    response closes, so heartbeats and reconnect touches also drive this path.
    """
    if redis_client is None or not client_id:
        return
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
    try:
        deadline_raw = redis_client.hget(client_key, _STATS_GRACE_DEADLINE_FIELD)
        if not deadline_raw:
            return
        if isinstance(deadline_raw, bytes):
            deadline_raw = deadline_raw.decode()
        if time.time() < float(deadline_raw):
            return
        grace_key = _stats_disconnect_grace_key(stats_channel_id, client_id)
        token = redis_client.get(grace_key)
        if token is None:
            redis_client.hdel(
                client_key,
                _STATS_GRACE_DEADLINE_FIELD,
                _STATS_GRACE_DISCONNECTED_AT_FIELD,
            )
            return
        if isinstance(token, bytes):
            token = token.decode()
        disconnected_raw = redis_client.hget(
            client_key, _STATS_GRACE_DISCONNECTED_AT_FIELD,
        )
        if disconnected_raw is None:
            disconnected_at = (
                float(deadline_raw)
                - _STATS_RECONNECT_SETTLE_SECONDS
                - _STATS_DISCONNECT_GRACE_SECONDS
            )
        else:
            if isinstance(disconnected_raw, bytes):
                disconnected_raw = disconnected_raw.decode()
            disconnected_at = float(disconnected_raw)
        _run_stats_disconnect_grace(
            redis_client, stats_channel_id, client_id, token,
            disconnected_at=disconnected_at,
        )
    except Exception as exc:
        logger.debug("Timeshift stats grace finalize failed: %s", exc)


def _touch_stats_on_session_request(redis_client, channel_id, session_id):
    """Keep an in-flight stats card alive while XC reconnects the same session."""
    if redis_client is None or not session_id:
        return
    stats_channel_id = make_stats_channel_id(channel_id, session_id)
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, session_id)
    try:
        if not redis_client.exists(client_key):
            return
        _cancel_stats_disconnect_grace(redis_client, stats_channel_id, session_id)
        _complete_expired_stats_grace(redis_client, stats_channel_id, session_id)
        now = str(time.time())
        client_set_key = TimeshiftRedisKeys.clients(stats_channel_id)
        metadata_key = TimeshiftRedisKeys.channel_metadata(stats_channel_id)
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(client_key, "last_active", now)
        pipe.expire(client_key, CLIENT_TTL_SECONDS)
        pipe.expire(client_set_key, CLIENT_TTL_SECONDS)
        pipe.expire(metadata_key, CLIENT_TTL_SECONDS)
        pipe.execute()
        programme_vid = redis_client.hget(client_key, "programme_vid")
        if isinstance(programme_vid, bytes):
            programme_vid = programme_vid.decode()
        _refresh_active_session_redis_ttl(
            redis_client, session_id, programme_vid,
        )
    except Exception as exc:
        logger.debug("Timeshift stats touch failed: %s", exc)


def _run_stats_disconnect_grace(
    redis_client, stats_channel_id, client_id, token, *, disconnected_at,
):
    """Drop stats after the grace window unless a reconnect cancelled *token*."""
    if redis_client is None:
        return
    grace_key = _stats_disconnect_grace_key(stats_channel_id, client_id)
    try:
        claimed = redis_client.eval(
            _CLAIM_STATS_GRACE_LUA, 1, grace_key, token,
        )
        if not claimed:
            return
        if _pool_session_busy(redis_client, client_id):
            return
        if _stats_client_reconnected(
            redis_client, stats_channel_id, client_id,
            disconnected_at=disconnected_at,
        ):
            return
        client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
        programme_vid = redis_client.hget(client_key, "programme_vid")
        if isinstance(programme_vid, bytes):
            programme_vid = programme_vid.decode()
        _unregister_stats_client(redis_client, stats_channel_id, client_id)
        _cleanup_all_stream_generations(redis_client, client_id)
        api_session_ended = _finalize_playback_session_auth(redis_client, client_id)
        if api_session_ended:
            _discard_pool_session(redis_client, client_id, None)
        else:
            # Keep idle pool fingerprint for XC players that drop ?session_id=.
            key = _pool_key(client_id)
            try:
                if redis_client.exists(key):
                    redis_client.expire(key, _POOL_IDLE_TTL)
            except Exception as exc:
                logger.debug("Timeshift pool idle TTL refresh failed: %s", exc)
        try:
            redis_client.delete(_superseded_pool_key(client_id))
        except Exception:
            pass
        _trigger_timeshift_stats_update(redis_client)
    except Exception as exc:
        logger.warning("Timeshift delayed stats unregister failed: %s", exc)


def _finalize_playback_session_auth(redis_client, session_id):
    """Drop tokenless API session auth once viewing has genuinely ended.

    Returns ``True`` when an API session record existed and was deleted.
    """
    if redis_client is None or not session_id:
        return False
    if not catchup_session_exists(session_id, redis_client=redis_client):
        return False
    delete_catchup_session(session_id, redis_client=redis_client)
    return True


def _spawn_background_task(func):
    """Run *func* on a gevent greenlet (uWSGI) or a non-daemon thread.

    Gated on monkey-patching, not gevent importability: in unpatched
    processes (Celery prefork, tests) a spawned greenlet may never be
    scheduled because nothing yields to the hub.
    """
    if _is_gevent_monkey_patched():
        import gevent
        gevent.spawn(func)
        return
    thread = threading.Thread(target=func, daemon=False)
    thread.start()


def _schedule_stats_disconnect_grace(redis_client, stats_channel_id, client_id):
    if redis_client is None:
        return
    token = secrets.token_hex(8)
    grace_key = _stats_disconnect_grace_key(stats_channel_id, client_id)
    disconnected_at = time.time()
    grace_deadline = (
        disconnected_at
        + _STATS_RECONNECT_SETTLE_SECONDS
        + _STATS_DISCONNECT_GRACE_SECONDS
    )
    ttl = int(
        _STATS_RECONNECT_SETTLE_SECONDS + _STATS_DISCONNECT_GRACE_SECONDS + 2,
    )
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
    try:
        pipe = redis_client.pipeline(transaction=False)
        pipe.setex(grace_key, ttl, token)
        pipe.hset(
            client_key,
            mapping={
                _STATS_GRACE_DEADLINE_FIELD: str(grace_deadline),
                _STATS_GRACE_DISCONNECTED_AT_FIELD: str(disconnected_at),
            },
        )
        pipe.execute()
    except Exception as exc:
        logger.warning("Timeshift stats grace schedule failed: %s", exc)
        return

    def _delayed_unregister():
        time.sleep(_STATS_RECONNECT_SETTLE_SECONDS)
        if not _grace_token_claimed(redis_client, grace_key, token):
            return
        if _stats_client_reconnected(
            redis_client, stats_channel_id, client_id,
            disconnected_at=disconnected_at,
        ):
            try:
                redis_client.delete(grace_key)
            except Exception:
                pass
            return
        time.sleep(_STATS_DISCONNECT_GRACE_SECONDS)
        _run_stats_disconnect_grace(
            redis_client, stats_channel_id, client_id, token,
            disconnected_at=disconnected_at,
        )

    _spawn_background_task(_delayed_unregister)


def _trigger_timeshift_stats_update(redis_client):
    """Push catch-up stats to websocket listeners after real connection changes."""
    if redis_client is None:
        return

    def _send():
        try:
            from apps.timeshift.stats import build_timeshift_stats_data
            from core.utils import send_websocket_update

            stats = build_timeshift_stats_data(redis_client)
            send_websocket_update(
                "updates",
                "update",
                {
                    "success": True,
                    "type": "timeshift_stats",
                    "stats": json.dumps(stats),
                },
            )
        except Exception as exc:
            logger.debug("Failed to trigger timeshift stats update: %s", exc)

    _spawn_background_task(_send)


def _parse_range_start(range_header):
    """Return the byte offset from a ``Range: bytes=START-`` header, or None."""
    parsed = _parse_client_range(range_header)
    if parsed is None:
        return None
    return parsed[0]


def _parse_client_range(range_header):
    """Return ``(start, end)`` from a client Range header; ``end`` may be None."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    range_part = range_header[6:]
    if "-" not in range_part:
        return None
    start_str, end_str = range_part.split("-", 1)
    try:
        start = int(start_str) if start_str else 0
    except (TypeError, ValueError):
        return None
    if not end_str:
        return start, None
    try:
        return start, int(end_str)
    except (TypeError, ValueError):
        return None


def _parse_content_range_header(content_range):
    """Parse ``Content-Range: bytes START-END/TOTAL``."""
    if not content_range or not content_range.startswith("bytes "):
        return None
    body = content_range[6:]
    if "/" not in body:
        return None
    range_part, total_part = body.rsplit("/", 1)
    if "-" not in range_part:
        return None
    start_str, end_str = range_part.split("-", 1)
    try:
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else None
        total = None if total_part == "*" else int(total_part)
    except (TypeError, ValueError):
        return None
    return {"start": start, "end": end, "total": total}


def _extract_representation_length(upstream_response):
    """Return the full archived file size from upstream response headers."""
    if upstream_response is None:
        return None
    parsed = _parse_content_range_header(
        upstream_response.headers.get("Content-Range", ""),
    )
    if parsed and parsed.get("total") is not None:
        return parsed["total"]
    content_length = upstream_response.headers.get("Content-Length")
    if content_length:
        try:
            return int(content_length)
        except (TypeError, ValueError):
            return None
    return None


def _build_downstream_length_headers(
    *,
    range_header,
    status_code,
    representation_length,
    upstream_content_range,
    upstream_content_length,
    streaming=False,
):
    """Build RFC 7230/7233 length headers for the downstream IPTV client."""
    headers = {"Accept-Ranges": "bytes"}
    parsed_upstream = (
        _parse_content_range_header(upstream_content_range)
        if upstream_content_range else None
    )

    if representation_length is None and parsed_upstream:
        representation_length = parsed_upstream.get("total")

    if status_code == 206:
        # Trust upstream partial headers; peek bytes are forwarded verbatim.
        if upstream_content_range:
            headers["Content-Range"] = upstream_content_range
        elif range_header and representation_length is not None:
            client_range = _parse_client_range(range_header)
            if client_range:
                start, end = client_range
                if end is None:
                    end = representation_length - 1
                else:
                    end = min(end, representation_length - 1)
                headers["Content-Range"] = (
                    f"bytes {start}-{end}/{representation_length}"
                )
        if upstream_content_length:
            headers["Content-Length"] = str(upstream_content_length)
        elif parsed_upstream and parsed_upstream.get("end") is not None:
            up_start = parsed_upstream["start"]
            up_end = parsed_upstream["end"]
            headers["Content-Length"] = str(up_end - up_start + 1)
        return headers

    # Plain GET streaming 200: match provider/CDN Content-Length (clients use
    # it for archive duration; omitting it breaks FF reconnect playback).
    if streaming and status_code == 200 and not range_header:
        if representation_length is not None:
            headers["Content-Length"] = str(representation_length)
        elif upstream_content_length:
            headers["Content-Length"] = str(upstream_content_length)
        return headers

    # Omit Content-Length on other streaming full-file responses (seeks may preempt).
    if not streaming:
        if representation_length is not None:
            headers["Content-Length"] = str(representation_length)
        elif upstream_content_length:
            headers["Content-Length"] = str(upstream_content_length)

    return headers


def _is_near_eof_probe(range_header, content_length=None):
    """True for tail/duration probes IPTV clients fire during startup."""
    start = _parse_range_start(range_header)
    if start is None:
        return False
    if content_length is not None:
        try:
            total = int(content_length)
        except (TypeError, ValueError):
            total = None
        else:
            return start >= max(0, total - _EOF_PROBE_TAIL_BYTES)
    return start >= _EOF_PROBE_UNKNOWN_LENGTH_MIN


def _should_displace_busy_pool(
    range_header,
    content_length,
    busy_serving_range,
    *,
    pool_media_id,
    media_id,
):
    """True when a busy pooled slot should be recycled for this request."""
    if pool_media_id is not None and str(pool_media_id) != str(media_id):
        # Programme hops use _should_preempt_for_programme_change, not displacement.
        return False
    return _should_displace_busy_playback(
        range_header, content_length, busy_serving_range,
    )


def _should_preempt_for_programme_change(
    redis_client, session_id, pool_media_id, media_id, *, user=None,
):
    """True when the viewer moved to a different start on the same session.

    XC clients often rebuild the catch-up URL with a new ``start`` while keeping
    ``session_id``. During active playback that must always preempt the
    in-flight stream (heartbeats keep ``last_activity`` fresh, so the old ~2s
    startup-probe window was returning 503 on every seek).
    """
    if pool_media_id is None or str(pool_media_id) == str(media_id):
        return False
    if user is not None and _session_has_active_timeshift_stream(user, session_id):
        return True
    try:
        last_activity = float(
            _get_pool_entry(redis_client, session_id).get("last_activity") or 0
        )
    except (TypeError, ValueError):
        last_activity = 0
    # Parallel startup probes with no live stream yet: ignore brief media churn.
    return (time.time() - last_activity) >= _STATS_GRACE_MIN_ELAPSED_SECONDS


def _try_reacquire_idle_pool(
    redis_client, session_id, *, user_id, user,
    wait_seconds=_POOL_WAIT_SECONDS,
):
    """Stop the in-flight stream and wait to reuse the same provider slot."""
    _preempt_playback_streams(redis_client, session_id, user)
    acquired = _acquire_idle_pool_session(
        redis_client, session_id, user_id=user_id, handoff=True,
    )
    if acquired is not None:
        return acquired
    return _wait_for_idle_pool_session(
        redis_client, session_id, user_id=user_id, wait_seconds=wait_seconds,
        handoff=True,
    )


def _should_preempt_plain_reconnect(
    range_header, *, pool_exists, pool_busy, pool_media_id, media_id,
):
    """True when a plain GET should restart playback like the provider does.

    IPTV clients often close the HTTP connection and reopen the same programme
    URL without a Range header. Providers answer
    that with a full 200 from byte 0, not an internal byte-range resume.
    """
    if range_header:
        return False
    if not pool_exists or not pool_busy:
        return False
    if pool_media_id is not None and str(pool_media_id) != str(media_id):
        return False
    return True


def _should_displace_busy_playback(
    range_header, content_length=None, busy_serving_range=None,
):
    """True when this request should stop the in-flight stream (actual scrub)."""
    if not range_header:
        return False
    start = _parse_range_start(range_header)
    if start is None:
        return False
    if _is_near_eof_probe(range_header, content_length):
        return False
    if start == 0:
        # Only displace a known full-file probe; unknown busy context is not a scrub.
        return busy_serving_range == "none"
    return True


def _cap_open_ended_range(range_header, max_span_bytes):
    """Limit an open-ended ``bytes=START-`` Range to at most ``max_span_bytes``."""
    parsed = _parse_client_range(range_header)
    if parsed is None:
        return range_header
    start, end = parsed
    if end is not None or max_span_bytes is None or max_span_bytes <= 0:
        return range_header
    return f"bytes={start}-{start + int(max_span_bytes) - 1}"


def _try_serve_busy_eof_probe(
    *,
    redis_client,
    session_id,
    entry,
    range_header,
    probe_length,
    debug=False,
):
    """Serve a near-EOF duration probe via cached CDN without preempting playback.

    Returns a response, or ``None`` to fall through to busy ``503``.
    No pool/stats/profile side effects. Caps open-ended Ranges so a probe
    cannot pull the remainder of a multi-GB archive.
    """
    if not entry or not range_header:
        return None
    if not _is_near_eof_probe(range_header, probe_length):
        return None

    final_url = entry.get("final_url")
    if isinstance(final_url, bytes):
        final_url = final_url.decode()
    if not final_url:
        return None

    content_length = _pool_int_field(entry.get("content_length"))
    presentation_base = _pool_int_field(entry.get("presentation_byte_base"))
    presentation_length = _pool_int_field(entry.get("presentation_length"))
    effective_range = range_header
    relative_presentation = False
    if presentation_base and presentation_base > 0:
        mapped_range = _map_client_range_through_presentation(
            range_header, presentation_base,
        )
        mapped_start = _parse_range_start(mapped_range)
        client_start = _parse_range_start(range_header)
        # Stale scrub base: client Range is already archive-absolute.
        if (
            content_length is not None
            and mapped_start is not None
            and mapped_start >= content_length
            and client_start is not None
            and client_start < content_length
        ):
            effective_range = range_header
            relative_presentation = False
            presentation_length = content_length
        else:
            effective_range = mapped_range
            relative_presentation = True

    effective_range = _cap_open_ended_range(effective_range, _EOF_PROBE_TAIL_BYTES)

    user_agent = entry.get("provider_user_agent") or ""
    if isinstance(user_agent, bytes):
        user_agent = user_agent.decode()

    try:
        upstream = _open_upstream(
            final_url, user_agent, effective_range, allow_redirects=False,
        )
    except Exception as exc:
        logger.debug(
            "Timeshift EOF probe CDN open failed session=%s: %s",
            session_id, exc,
        )
        return None

    if upstream.status_code == 416:
        try:
            upstream.close()
        except Exception:
            pass
        total = (
            presentation_length
            if relative_presentation and presentation_length
            else content_length
        )
        if total is None:
            total = _pool_int_field(probe_length)
        response = HttpResponse(status=416)
        response["Accept-Ranges"] = "bytes"
        if total is not None:
            response["Content-Range"] = f"bytes */{int(total)}"
        if debug:
            logger.debug(
                "Timeshift EOF probe 416: session=%s client_range=%s cdn_range=%s",
                session_id, range_header, effective_range,
            )
        return _finalize_timeshift_response(response)

    if upstream.status_code not in (200, 206):
        try:
            upstream.close()
        except Exception:
            pass
        logger.debug(
            "Timeshift EOF probe CDN rejected session=%s status=%s",
            session_id, getattr(upstream, "status_code", None),
        )
        return None

    content_type = upstream.headers.get("Content-Type", "video/mp2t")
    status = upstream.status_code
    content_range = upstream.headers.get("Content-Range", "") or None
    if relative_presentation and content_range and presentation_length is not None:
        content_range = _presentation_relative_content_range(
            content_range,
            presentation_byte_base=presentation_base,
            presentation_length=presentation_length,
        )

    client_headers = _build_downstream_length_headers(
        range_header=None if relative_presentation else range_header,
        status_code=status,
        representation_length=(
            presentation_length
            if relative_presentation and presentation_length is not None
            else _extract_representation_length(upstream)
        ),
        upstream_content_range=content_range,
        upstream_content_length=upstream.headers.get("Content-Length"),
        streaming=True,
    )

    chunk_size = max(ConfigHelper.chunk_size(), 262144)
    closed = {"done": False}

    def _finish():
        if closed["done"]:
            return
        closed["done"] = True
        try:
            upstream.close()
        except Exception:
            pass

    def _generator():
        try:
            while True:
                try:
                    chunk = upstream.raw.read(chunk_size)
                except Exception:
                    break
                if not chunk:
                    break
                yield chunk
        except GeneratorExit:
            pass
        finally:
            _finish()

    if debug:
        logger.debug(
            "Timeshift EOF probe pass-through: session=%s client_range=%s "
            "cdn_range=%s status=%d",
            session_id, range_header, effective_range, status,
        )

    stream_iter = _SlotReleasingStream(_generator(), _finish)
    response = StreamingHttpResponse(
        stream_iter,
        content_type=content_type,
        status=status,
    )
    response["X-Accel-Buffering"] = "no"
    for header_name, header_value in client_headers.items():
        response[header_name] = header_value
    return _finalize_timeshift_response(response)


def _score_pool_fingerprint(entry, client_ip, client_user_agent):
    """Score IP/UA overlap for fingerprint adoption (user and media pre-filtered)."""
    score = 0
    if entry.get("client_ip") and entry.get("client_ip") == client_ip:
        score += 5
    if entry.get("client_user_agent") and entry.get("client_user_agent") == client_user_agent:
        score += 3
    return score


def _redirect_with_session(request, session_id):
    query_params = {k: request.GET.getlist(k) for k in request.GET}
    query_params["session_id"] = [session_id]
    redirect_url = f"{request.path}?{urlencode(query_params, doseq=True)}"
    return HttpResponse(status=301, headers={"Location": redirect_url})


def _redirect_with_new_session(request):
    return _redirect_with_session(request, mint_session_id())


def _pool_entry_owned_by_user(entry, user_id):
    """True when *entry* is unclaimed or owned by *user_id*."""
    if not entry or not entry.get("profile_id"):
        return True
    owner = entry.get("user_id")
    if owner is None or owner == "":
        return False
    return str(owner) == str(user_id)


def _find_matching_pool_session(
    redis_client, *, media_id, user_id, client_ip, client_user_agent,
    channel_id=None, include_busy=False, fresh_session=False,
):
    """Find a pooled session for the same viewer.

    Prefers an exact *media_id* match, then any in-flight or idle session on
    the same channel so XC programme hops can recover a dropped ``session_id``.

    When *fresh_session* is True (request carries a new ``session_id`` with no
    pool entry yet), skip idle exact-media matches so a spurious reconnect to
    the same programme slot does not revive a session the player abandoned.
    Busy exact-media matches are kept for in-programme scrub preemption.
    """
    if redis_client is None:
        return None
    channel_prefix = f"{channel_id}_" if channel_id is not None else None
    matches = []
    try:
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(
                cursor, match=TimeshiftRedisKeys.pool_scan_pattern(), count=100,
            )
            for key in keys:
                try:
                    data = redis_client.hgetall(key)
                    if not data:
                        continue
                    if not include_busy and data.get("busy") == "1":
                        continue
                    if str(data.get("user_id") or "") != str(user_id):
                        continue
                    stored_media = str(data.get("media_id") or "")
                    if stored_media == str(media_id):
                        exact_match = True
                    elif channel_prefix and stored_media.startswith(channel_prefix):
                        exact_match = False
                    else:
                        continue
                    if (
                        fresh_session
                        and exact_match
                        and data.get("busy") != "1"
                    ):
                        continue
                    session_id = key.rsplit(":", 1)[-1]
                    score = _score_pool_fingerprint(
                        data, client_ip, client_user_agent,
                    )
                    if score >= _MATCH_SCORE_THRESHOLD:
                        last_activity = float(data.get("last_activity") or "0")
                        matches.append(
                            (session_id, score, last_activity, exact_match),
                        )
                except Exception as exc:
                    logger.debug("Timeshift pool scan skip %s: %s", key, exc)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Timeshift idle session search failed: %s", exc)
        return None

    if not matches:
        return None
    matches.sort(key=lambda item: (item[3], item[1], item[2]), reverse=True)
    best = matches[0][0]
    logger.debug(
        "Timeshift %s match: session=%s score=%s media=%s exact=%s",
        "pool" if include_busy else "idle",
        best, matches[0][1], media_id, matches[0][3],
    )
    return best


def _get_pool_entry(redis_client, session_id):
    if redis_client is None or not session_id:
        return {}
    try:
        return redis_client.hgetall(_pool_key(session_id)) or {}
    except Exception:
        return {}


def _snapshot_from_entry(entry):
    if not entry:
        return None
    busy = entry.get("busy") == "1"
    return {
        "entry": entry,
        "busy": busy,
        "serving_range": (entry.get("serving_range") or "none") if busy else None,
        "content_length": entry.get("content_length"),
    }


def _pool_snapshot(redis_client, session_id):
    """Single HGETALL view of pool state for request handling."""
    return _snapshot_from_entry(_get_pool_entry(redis_client, session_id))


def _store_pool_serving_range(redis_client, session_id, range_header):
    if redis_client is None or not session_id:
        return
    start = _parse_range_start(range_header)
    if not range_header:
        serving_range = "none"
    elif start == 0:
        serving_range = "start"
    else:
        serving_range = "range"
    try:
        redis_client.hset(_pool_key(session_id), "serving_range", serving_range)
    except Exception as exc:
        logger.debug("Timeshift pool serving_range store failed: %s", exc)


def _update_pool_position(
    redis_client, session_id, *, media_id, provider_timestamp, keep_archive=False,
):
    """Move a reused session's descriptor to the position actually served.

    XC FF/RW rebuilds the catch-up URL with a new *start* timestamp (same
    session). That changes ``media_id`` but is still the same opened CDN
    archive; keep ``final_url`` / sizes when *keep_archive* is True.
    """
    if redis_client is None or not session_id:
        return
    key = _pool_key(session_id)
    try:
        with _pool_lock(redis_client, session_id):
            entry = redis_client.hgetall(key)
            if not entry:
                # Entry vanished (Redis restart/eviction): writing here would
                # resurrect a partial, TTL-less hash that wedges the session.
                return
            position_changed = entry.get("media_id") != str(media_id)
            redis_client.hset(key, mapping={
                "media_id": str(media_id),
                "provider_timestamp": str(provider_timestamp),
            })
            if position_changed and not keep_archive:
                # Left the opened archive window; drop file-specific state.
                redis_client.hdel(
                    key,
                    "content_length",
                    "serving_range",
                    "final_url",
                    "archive_anchor_ts",
                    "archive_duration_secs",
                    "presentation_length",
                    "presentation_byte_base",
                )
    except Exception as exc:
        logger.debug("Timeshift pool position update failed: %s", exc)


def _store_pool_content_length(redis_client, session_id, upstream_response):
    if redis_client is None or not session_id or upstream_response is None:
        return
    content_length = _extract_representation_length(upstream_response)
    if content_length is None:
        return
    try:
        redis_client.hset(
            _pool_key(session_id), "content_length", str(content_length),
        )
    except Exception as exc:
        logger.debug("Timeshift pool content_length store failed: %s", exc)


def _store_pool_final_url(redis_client, session_id, final_url):
    """Persist the post-redirect CDN URL for VOD-style reconnect reuse."""
    if redis_client is None or not session_id or not final_url:
        return
    try:
        redis_client.hset(_pool_key(session_id), "final_url", str(final_url))
    except Exception as exc:
        logger.debug("Timeshift pool final_url store failed: %s", exc)


def _store_pool_provider_user_agent(redis_client, session_id, user_agent):
    """Snapshot the resolved account User-Agent for this playback session."""
    if redis_client is None or not session_id:
        return
    key = _pool_key(session_id)
    try:
        if redis_client.exists(key):
            redis_client.hset(key, "provider_user_agent", str(user_agent or ""))
    except Exception as exc:
        logger.debug("Timeshift pool provider User-Agent store failed: %s", exc)


def _clear_pool_final_url(redis_client, session_id):
    if redis_client is None or not session_id:
        return
    try:
        redis_client.hdel(_pool_key(session_id), "final_url")
    except Exception as exc:
        logger.debug("Timeshift pool final_url clear failed: %s", exc)


def _store_pool_presentation_window(
    redis_client, session_id, length, *, byte_base=0,
):
    """Client-visible size/origin after a scrub rewrite (relative Ranges map here)."""
    if redis_client is None or not session_id or length is None:
        return
    try:
        redis_client.hset(
            _pool_key(session_id),
            mapping={
                "presentation_length": str(int(length)),
                "presentation_byte_base": str(int(byte_base or 0)),
            },
        )
    except Exception as exc:
        logger.debug("Timeshift pool presentation window store failed: %s", exc)


def _pool_int_field(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bytes):
            value = value.decode()
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_client_range_through_presentation(range_header, presentation_byte_base):
    """Translate presentation-relative Range into absolute CDN archive Range."""
    if presentation_byte_base is None or not range_header:
        return range_header
    parsed = _parse_client_range(range_header)
    if parsed is None:
        return range_header
    start, end = parsed
    base = int(presentation_byte_base)
    abs_start = base + start
    if end is None:
        return f"bytes={abs_start}-"
    return f"bytes={abs_start}-{base + end}"


def _presentation_relative_content_range(
    upstream_content_range, *, presentation_byte_base, presentation_length,
):
    """Rewrite absolute CDN Content-Range into presentation-relative coords."""
    if (
        not upstream_content_range
        or presentation_byte_base is None
        or presentation_length is None
    ):
        return upstream_content_range
    parsed = _parse_content_range_header(upstream_content_range)
    if not parsed or parsed.get("end") is None:
        return upstream_content_range
    base = int(presentation_byte_base)
    rel_start = parsed["start"] - base
    rel_end = parsed["end"] - base
    if rel_start < 0 or rel_end < rel_start:
        return upstream_content_range
    return f"bytes {rel_start}-{rel_end}/{int(presentation_length)}"


def _ensure_pool_archive_anchor(
    redis_client, session_id, *, timestamp, duration_minutes, force=False,
):
    """Remember the CDN archive window opened for this session (first portal hit)."""
    if redis_client is None or not session_id or not timestamp:
        return
    key = _pool_key(session_id)
    try:
        if not force and redis_client.hget(key, "archive_anchor_ts"):
            return
        duration_secs = max(int(float(duration_minutes or 0) * 60), 60)
        redis_client.hset(key, mapping={
            "archive_anchor_ts": str(timestamp),
            "archive_duration_secs": str(duration_secs),
        })
    except Exception as exc:
        logger.debug("Timeshift pool archive anchor store failed: %s", exc)


def _resolve_session_archive_scrub(descriptor, requested_timestamp):
    """Map an in-session timestamp rebuild onto the open CDN archive.

    XC clients often rebuild ``/timeshift/.../<new_start>/...`` while keeping
    ``session_id`` instead of Range-seeking. Same session + in-window start
    maps to a byte offset into the already-open CDN file (no portal).

    Returns ``None`` when the request is outside the opened window (new portal
    required), or a dict with ``kind`` ``same`` / ``scrub``, ``byte_offset``,
    and ``remaining``.
    """
    if not descriptor or not requested_timestamp:
        return None
    final_url = descriptor.get("final_url") or ""
    if isinstance(final_url, bytes):
        final_url = final_url.decode()
    if not final_url:
        return None
    try:
        content_length = int(descriptor.get("content_length"))
        duration_secs = float(descriptor.get("archive_duration_secs"))
    except (TypeError, ValueError):
        return None
    if content_length <= 0 or duration_secs <= 0:
        return None
    anchor_raw = descriptor.get("archive_anchor_ts")
    if isinstance(anchor_raw, bytes):
        anchor_raw = anchor_raw.decode()
    requested_dt = parse_catchup_timestamp(requested_timestamp)
    anchor_dt = parse_catchup_timestamp(anchor_raw) if anchor_raw else None
    if requested_dt is None or anchor_dt is None:
        return None
    offset_secs = (requested_dt - anchor_dt).total_seconds()
    if abs(offset_secs) < 1.0:
        return {
            "kind": "same",
            "byte_offset": 0,
            "remaining": content_length,
        }
    # Reverse seek before the opened CDN file: content is not on this URL.
    # Caller must portal/re-anchor (cannot Range-seek earlier than the open).
    if offset_secs < 0:
        return None
    if offset_secs >= duration_secs:
        return None
    byte_offset = int((offset_secs / duration_secs) * content_length)
    byte_offset = (byte_offset // 188) * 188
    remaining = content_length - byte_offset
    if remaining <= 0:
        return None
    return {
        "kind": "scrub",
        "byte_offset": byte_offset,
        "remaining": remaining,
    }


def _pool_lock(redis_client, session_id):
    return redis_client.lock(
        TimeshiftRedisKeys.pool_lock(session_id),
        timeout=10,
        blocking_timeout=5,
    )


def _acquire_idle_pool_session(
    redis_client, session_id, *, user_id=None, handoff=False,
):
    """Re-reserve an idle session's profile slot and mark it busy.

    When *handoff* is True the displaced stream kept its profile reservation;
    only flip the pool entry back to busy.
    """
    if redis_client is None or not session_id:
        return None
    key = _pool_key(session_id)
    try:
        with _pool_lock(redis_client, session_id):
            data = redis_client.hgetall(key)
            if not data or not data.get("profile_id"):
                return None
            if user_id is not None and not _pool_entry_owned_by_user(data, user_id):
                return None
            if data.get("busy") == "1" and not handoff:
                return None
            try:
                profile = M3UAccountProfile.objects.get(id=int(data["profile_id"]))
            except M3UAccountProfile.DoesNotExist:
                redis_client.delete(key)
                return None
            if not handoff:
                reserved, _count, _reason = reserve_profile_slot(profile, redis_client)
                if not reserved:
                    return None
            redis_client.hset(key, mapping={
                "busy": "1",
                "last_activity": str(time.time()),
            })
            redis_client.expire(key, _POOL_ENTRY_TTL)
            return dict(data), profile
    except Exception as exc:
        logger.warning("Timeshift pool acquire failed for %s: %s", session_id, exc)
    return None


def _wait_for_idle_pool_session(
    redis_client, session_id, *, user_id=None, wait_seconds=_POOL_WAIT_SECONDS,
    handoff=False,
):
    if redis_client is None or not session_id:
        return None
    deadline = time.time() + wait_seconds
    while True:
        acquired = _acquire_idle_pool_session(
            redis_client, session_id, user_id=user_id, handoff=handoff,
        )
        if acquired is not None:
            return acquired
        if not _get_pool_entry(redis_client, session_id):
            return None
        if time.time() >= deadline:
            return None
        time.sleep(_POOL_POLL_INTERVAL)


def _create_pool_session(
    redis_client,
    *,
    session_id,
    media_id,
    user_id,
    client_ip,
    client_user_agent,
    account_id,
    profile_id,
    stream_id,
    dispatcharr_stream_id,
    provider_timestamp,
    provider_tz_name=None,
):
    """Register an already-reserved slot for this client session."""
    if redis_client is None or not session_id:
        return False
    key = _pool_key(session_id)
    now = str(time.time())
    try:
        with _pool_lock(redis_client, session_id):
            if redis_client.exists(key):
                return False
            redis_client.hset(key, mapping={
                "media_id": str(media_id),
                "user_id": str(user_id),
                "client_ip": str(client_ip or ""),
                "client_user_agent": str(client_user_agent or ""),
                "account_id": str(account_id),
                "profile_id": str(profile_id),
                "stream_id": str(stream_id),
                "dispatcharr_stream_id": str(dispatcharr_stream_id),
                "provider_timestamp": str(provider_timestamp),
                "provider_tz_name": str(provider_tz_name or ""),
                "busy": "1",
                "last_activity": now,
            })
            redis_client.expire(key, _POOL_ENTRY_TTL)
        try:
            redis_client.delete(_superseded_pool_key(session_id))
        except Exception:
            pass
        return True
    except Exception as exc:
        logger.warning("Timeshift pool create failed for %s: %s", session_id, exc)
        return False


def _superseded_pool_key(session_id):
    return TimeshiftRedisKeys.pool_superseded(session_id)


_active_upstream_lock = threading.Lock()
_active_upstreams = {}


def _active_upstream_key(virtual_channel_id, client_id):
    return f"{virtual_channel_id}:{client_id}"


def _register_active_upstream(virtual_channel_id, client_id, upstream):
    if not virtual_channel_id or not client_id or upstream is None:
        return
    key = _active_upstream_key(virtual_channel_id, client_id)
    with _active_upstream_lock:
        _active_upstreams[key] = upstream


def _unregister_active_upstream(virtual_channel_id, client_id):
    if not virtual_channel_id or not client_id:
        return
    key = _active_upstream_key(virtual_channel_id, client_id)
    with _active_upstream_lock:
        _active_upstreams.pop(key, None)


def _close_active_upstream(virtual_channel_id, client_id):
    """Close an in-worker upstream socket so a scrub preempt unblocks immediately."""
    if not virtual_channel_id or not client_id:
        return
    key = _active_upstream_key(virtual_channel_id, client_id)
    with _active_upstream_lock:
        upstream = _active_upstreams.pop(key, None)
    if upstream is None:
        return
    try:
        upstream.close()
    except Exception:
        pass


def _force_abandon_busy_pool(redis_client, session_id, profile_id):
    """Drop a busy pool after a scrub preempt times out.

    The superseded marker prevents the displaced stream's ``release_cb`` from
    double-releasing the provider profile slot.
    """
    if redis_client is None or not session_id:
        return
    try:
        redis_client.setex(_superseded_pool_key(session_id), 120, "1")
    except Exception as exc:
        logger.warning("Timeshift supersede mark failed for %s: %s", session_id, exc)
    _discard_pool_session(redis_client, session_id, profile_id)


def _iter_upstream_with_stop(
    upstream,
    chunk_size,
    redis_client,
    stop_key,
    stream_generation,
    peek_data=None,
    *,
    inactivity_timeout=_STREAM_READ_INACTIVITY_SECONDS,
):
    """Yield upstream bytes, polling the stop key before each blocking read."""
    last_data_at = time.time()
    if peek_data:
        should_stop, _ = _stream_stop_requested(
            redis_client, stop_key, stream_generation,
        )
        if should_stop:
            try:
                upstream.close()
            except Exception:
                pass
            return
        last_data_at = time.time()
        yield peek_data
    raw = upstream.raw
    while True:
        if (
            inactivity_timeout is not None
            and time.time() - last_data_at >= inactivity_timeout
        ):
            logger.info(
                "Timeshift upstream inactive for %ss, closing stream",
                inactivity_timeout,
            )
            try:
                upstream.close()
            except Exception:
                pass
            break
        should_stop, _ = _stream_stop_requested(
            redis_client, stop_key, stream_generation,
        )
        if should_stop:
            try:
                upstream.close()
            except Exception:
                pass
            break
        try:
            chunk = raw.read(chunk_size)
        except requests.exceptions.ReadTimeout:
            # Per-chunk read timeout: loop back to check stop (live-proxy pattern).
            continue
        except Exception:
            break
        if not chunk:
            break
        last_data_at = time.time()
        yield chunk


def _release_pool_session(
    redis_client, session_id, profile_id, *,
    mark_pool_idle=True, release_profile=True,
):
    if redis_client is None:
        return
    superseded = False
    try:
        superseded = bool(redis_client.exists(_superseded_pool_key(session_id)))
    except Exception:
        pass
    if superseded and not release_profile:
        # Displaced stream after a scrub failover: abandon already released.
        return
    if superseded and release_profile:
        # Replacement stream is ending; stale marker must not block release.
        try:
            redis_client.delete(_superseded_pool_key(session_id))
        except Exception:
            pass
    if release_profile and profile_id is not None:
        try:
            release_profile_slot(int(profile_id), redis_client)
        except Exception as exc:
            logger.warning(
                "Timeshift slot release failed for profile %s: %s", profile_id, exc
            )
    if not mark_pool_idle or not session_id:
        return
    key = _pool_key(session_id)
    try:
        with _pool_lock(redis_client, session_id):
            if redis_client.exists(key):
                redis_client.hset(key, mapping={
                    "busy": "0",
                    "last_activity": str(time.time()),
                })
                redis_client.expire(key, _POOL_IDLE_TTL)
    except Exception as exc:
        logger.warning("Timeshift pool release failed for %s: %s", session_id, exc)


def _refresh_pool_session_ttl(redis_client, session_id):
    """Extend pool metadata TTL while a session is actively streaming."""
    if redis_client is None or not session_id:
        return
    key = _pool_key(session_id)
    try:
        if not redis_client.exists(key):
            return
        busy = redis_client.hget(key, "busy")
        if isinstance(busy, bytes):
            busy = busy.decode()
        ttl = _POOL_ENTRY_TTL if str(busy) == "1" else _POOL_IDLE_TTL
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(key, "last_activity", str(time.time()))
        pipe.expire(key, ttl)
        pipe.execute()
    except Exception as exc:
        logger.debug("Timeshift pool TTL refresh failed: %s", exc)


def _refresh_active_session_redis_ttl(
    redis_client, session_id, programme_vid=None,
):
    """Keep pool, stream generation, and API session auth alive during playback."""
    if redis_client is None or not session_id:
        return
    _refresh_pool_session_ttl(redis_client, session_id)
    if programme_vid:
        gen_key = _stream_generation_key(programme_vid, session_id)
        try:
            if redis_client.exists(gen_key):
                redis_client.expire(gen_key, _POOL_ENTRY_TTL)
        except Exception as exc:
            logger.debug("Timeshift stream generation TTL refresh failed: %s", exc)
    if catchup_session_exists(session_id, redis_client=redis_client):
        from .sessions import touch_catchup_session
        touch_catchup_session(session_id, redis_client=redis_client)


def _discard_pool_session(redis_client, session_id, profile_id):
    if redis_client is None:
        return
    if profile_id is not None:
        try:
            release_profile_slot(int(profile_id), redis_client)
        except Exception as exc:
            logger.warning(
                "Timeshift slot release failed for profile %s: %s", profile_id, exc
            )
    if not session_id:
        return
    try:
        with _pool_lock(redis_client, session_id):
            redis_client.delete(_pool_key(session_id))
    except Exception as exc:
        logger.warning("Timeshift pool discard failed for %s: %s", session_id, exc)


def _make_release_once(redis_client, session_id, profile_id):
    state = {"done": False}

    def _release(*, mark_pool_idle=True, release_profile=True):
        if state["done"]:
            return
        state["done"] = True
        _release_pool_session(
            redis_client, session_id, profile_id,
            mark_pool_idle=mark_pool_idle,
            release_profile=release_profile,
        )

    return _release


def _stream_generation_key(virtual_channel_id, client_id):
    return TimeshiftRedisKeys.stream_generation(virtual_channel_id, client_id)


def _current_stream_generation(redis_client, virtual_channel_id, client_id):
    if redis_client is None:
        return 0
    try:
        gen = redis_client.get(_stream_generation_key(virtual_channel_id, client_id))
        return int(gen) if gen else 0
    except (TypeError, ValueError):
        return 0


def _allocate_stream_generation(redis_client, virtual_channel_id, client_id):
    if redis_client is None:
        return 1
    key = _stream_generation_key(virtual_channel_id, client_id)
    try:
        generation = int(redis_client.incr(key))
        redis_client.expire(key, _POOL_ENTRY_TTL)  # Refreshed on each seek/new stream.
        try:
            redis_client.delete(
                TimeshiftRedisKeys.client_stop(virtual_channel_id, client_id),
            )
            redis_client.delete(_superseded_pool_key(client_id))
        except Exception:
            pass
        return generation
    except Exception:
        return 1


def _cleanup_stream_generation(redis_client, virtual_channel_id, client_id):
    """Delete the per-programme generation counter once a viewer is gone."""
    if redis_client is None or not virtual_channel_id or not client_id:
        return
    try:
        redis_client.delete(_stream_generation_key(virtual_channel_id, client_id))
    except Exception as exc:
        logger.debug("Timeshift stream generation cleanup failed: %s", exc)


def _cleanup_all_stream_generations(redis_client, client_id):
    """Drop every programme-scoped generation counter for one viewer."""
    if redis_client is None or not client_id:
        return
    pattern = TimeshiftRedisKeys.stream_generation_scan_pattern(client_id)
    try:
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
            if keys:
                redis_client.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        logger.debug("Timeshift stream generation scan cleanup failed: %s", exc)


def _set_client_stop(redis_client, virtual_channel_id, client_id, reason):
    if redis_client is None:
        return
    stop_key = TimeshiftRedisKeys.client_stop(virtual_channel_id, client_id)
    if reason == _STOP_REASON_REUSE:
        try:
            gen = redis_client.get(_stream_generation_key(virtual_channel_id, client_id))
            cancel_through = int(gen) if gen else 1
        except (TypeError, ValueError):
            cancel_through = 1
        redis_client.setex(stop_key, 60, str(cancel_through))
    else:
        redis_client.setex(stop_key, 60, reason)


def _stream_stop_requested(redis_client, stop_key, stream_generation):
    """Return ``(should_stop, stopped_for_reuse)`` for this stream generation."""
    if redis_client is None or not stop_key:
        return False, False
    try:
        value = redis_client.get(stop_key)
    except Exception:
        return False, False
    if value is None:
        return False, False
    if isinstance(value, bytes):
        value = value.decode()
    if value == _STOP_REASON_REUSE:
        return True, True
    if value.isdigit():
        cancel_through = int(value)
        return stream_generation <= cancel_through, True
    if value in _TERMINAL_STOP_REASONS:
        return True, False
    return False, False


def _session_has_active_timeshift_stream(user, session_id):
    """True when *session_id* still has a registered timeshift stats client."""
    if user is None or not session_id:
        return False
    try:
        for conn in get_user_active_connections(user.id):
            if conn.get("type") != "timeshift":
                continue
            if conn.get("client_id") == session_id:
                return True
    except Exception:
        return False
    return False


def _preempt_playback_streams(redis_client, session_id, user):
    """Stop in-flight streams for this client session only."""
    if redis_client is None or not session_id or user is None:
        return
    try:
        for conn in get_user_active_connections(user.id):
            if conn.get("type") != "timeshift":
                continue
            if conn.get("client_id") != session_id:
                continue
            conn_media_id = str(conn.get("media_id") or "")
            old_client_id = conn.get("client_id")
            stop_target = _timeshift_stop_channel_id(
                redis_client, conn_media_id, old_client_id,
            )
            logger.debug(
                "Timeshift preempt: stopping client %s on %s for reuse",
                old_client_id, stop_target,
            )
            _set_client_stop(
                redis_client, stop_target, old_client_id, _STOP_REASON_REUSE,
            )
            _close_active_upstream(stop_target, old_client_id)
    except Exception as exc:
        logger.warning("Timeshift preempt failed: %s", exc)


def _terminate_previous_timeshift_sessions(
    redis_client, user, channel_id, current_media_id, current_session_id,
):
    """Displace this user's other catch-up positions on the same channel."""
    if redis_client is None or user is None:
        return
    channel_prefix = f"{channel_id}_"
    displaced = False
    try:
        for conn in get_user_active_connections(user.id):
            if conn.get("type") != "timeshift":
                continue
            conn_media_id = str(conn.get("media_id") or "")
            old_client_id = conn.get("client_id")
            if conn.get("client_id") == current_session_id:
                # Programme hops for the same session are handled by pool
                # displacement; stats stay on the stable per-session channel id.
                continue
            if not conn_media_id.startswith(channel_prefix):
                continue
            if conn_media_id.startswith(f"{current_media_id}_") or conn_media_id == current_media_id:
                continue
            stats_channel_id = make_stats_channel_id(channel_id, old_client_id)
            logger.info(
                "Timeshift takeover: displacing session %s on %s",
                old_client_id, stats_channel_id,
            )
            stop_target = _timeshift_stop_channel_id(
                redis_client, stats_channel_id, old_client_id,
                fallback=conn_media_id,
            )
            _unregister_stats_client(redis_client, stats_channel_id, old_client_id)
            displaced = True
            _set_client_stop(
                redis_client, stop_target, old_client_id, _STOP_REASON_HOP,
            )
        if displaced:
            _trigger_timeshift_stats_update(redis_client)
    except Exception as exc:
        logger.warning("Timeshift takeover check failed: %s", exc)


def _attempt_timeshift_stream(
    *,
    m3u_account,
    profile,
    stream_id_value,
    provider_timestamp,
    provider_tz_name,
    duration_minutes,
    channel,
    safe_ts,
    timestamp,
    client_id,
    client_ip,
    client_user_agent,
    range_header,
    channel_logo_id,
    user,
    redis_client,
    debug,
    release_cb=None,
    pool_session_id=None,
    stats_stream_id=None,
    stream_stats=None,
    final_url=None,
    rewrite_plain_get=False,
    presentation_remaining=None,
    presentation_byte_base=None,
    relative_presentation_range=False,
):
    """Build the provider URL set for one (account, profile, stream) and stream it."""
    server_url, xc_username, xc_password = get_transformed_credentials(
        m3u_account, profile
    )
    creds = TimeshiftCredentials(server_url, xc_username, xc_password)
    candidate_urls = build_timeshift_candidate_urls(
        creds, stream_id_value, provider_timestamp, duration_minutes
    )

    try:
        user_agent = m3u_account.get_user_agent().user_agent
    except AttributeError:
        user_agent = ""
    _store_pool_provider_user_agent(
        redis_client, pool_session_id, user_agent,
    )

    virtual_channel_id = make_virtual_channel_id(
        channel.id, safe_ts, stream_id_value,
    )
    stats_channel_id = make_stats_channel_id(channel.id, client_id)

    if debug:
        logger.debug(
            "Timeshift attempt: channel=%s ts=%s (provider tz=%s -> %s) "
            "account=%s profile=%s provider_sid=%s vid=%s client=%s range=%s "
            "cdn=%s",
            channel.name, timestamp, provider_tz_name, provider_timestamp,
            m3u_account.id, profile.id, stream_id_value,
            virtual_channel_id, client_id, range_header or "(none)",
            "cached" if final_url else "portal",
        )

    return _stream_from_provider(
        candidate_urls=candidate_urls,
        user_agent=user_agent,
        range_header=range_header,
        virtual_channel_id=virtual_channel_id,
        stats_channel_id=stats_channel_id,
        client_id=client_id,
        client_ip=client_ip,
        client_user_agent=client_user_agent,
        user=user,
        channel_display_name=channel.name,
        timestamp_utc=timestamp,
        channel_logo_id=channel_logo_id,
        m3u_profile_id=profile.id,
        debug=debug,
        account_id=m3u_account.id,
        redis_client=redis_client,
        release_cb=release_cb,
        pool_session_id=pool_session_id,
        channel_id=channel.id,
        channel_uuid=channel.uuid,
        stats_stream_id=stats_stream_id,
        stream_stats=stream_stats,
        duration_minutes=duration_minutes,
        final_url=final_url,
        rewrite_plain_get=rewrite_plain_get,
        presentation_remaining=presentation_remaining,
        presentation_byte_base=presentation_byte_base,
        relative_presentation_range=relative_presentation_range,
    )


def _stream_reused_session(
    redis_client,
    *,
    session_id,
    descriptor,
    profile,
    channel,
    media_id,
    safe_ts,
    timestamp,
    duration_minutes,
    client_id,
    client_ip,
    client_user_agent,
    range_header,
    channel_logo_id,
    user,
    debug,
):
    """Stream an idle pooled session that was just re-reserved for this request."""
    try:
        m3u_account = M3UAccount.objects.get(id=int(descriptor["account_id"]))
    except (M3UAccount.DoesNotExist, ValueError, TypeError):
        _discard_pool_session(redis_client, session_id, profile.id)
        return None

    # Serve the requested position, not the pool entry's original anchor.
    provider_tz_name = descriptor.get("provider_tz_name") or None
    if provider_tz_name:
        provider_tz_name = str(provider_tz_name)
    if not provider_tz_name:
        server_info = (profile.custom_properties or {}).get("server_info") or {}
        if isinstance(server_info, dict):
            provider_tz_name = server_info.get("timezone")
    provider_timestamp = convert_timestamp_to_provider_tz(timestamp, provider_tz_name)

    prior_media_id = descriptor.get("media_id")
    if isinstance(prior_media_id, bytes):
        prior_media_id = prior_media_id.decode()
    media_changed = str(prior_media_id or "") != str(media_id)

    scrub_info = _resolve_session_archive_scrub(descriptor, timestamp)
    raw_final_url = descriptor.get("final_url")
    if isinstance(raw_final_url, bytes):
        raw_final_url = raw_final_url.decode()
    rewrite_plain_get = False
    presentation_remaining = None
    presentation_byte_base = None
    relative_presentation_range = False
    effective_range = range_header
    prior_presentation_base = _pool_int_field(
        descriptor.get("presentation_byte_base"),
    )
    prior_presentation_length = _pool_int_field(
        descriptor.get("presentation_length"),
    )

    if scrub_info is not None:
        # Same opened CDN archive: FF within the file opened for this session.
        keep_archive = True
        final_url = raw_final_url or None
        if scrub_info["kind"] == "scrub" and not range_header:
            effective_range = f"bytes={scrub_info['byte_offset']}-"
            rewrite_plain_get = True
            presentation_remaining = scrub_info["remaining"]
            presentation_byte_base = scrub_info["byte_offset"]
            if debug:
                logger.debug(
                    "Timeshift session scrub: session=%s offset=%d remaining=%d "
                    "(%s -> %s)",
                    session_id, scrub_info["byte_offset"], scrub_info["remaining"],
                    prior_media_id, media_id,
                )
        elif scrub_info["kind"] == "same":
            # Back at archive open: reset scrub window so Ranges stay absolute.
            presentation_remaining = scrub_info["remaining"]
            presentation_byte_base = 0
            if range_header:
                effective_range = range_header
                relative_presentation_range = False
        elif range_header and prior_presentation_base:
            # Post-scrub client Ranges are relative to the shorter presented file.
            effective_range = _map_client_range_through_presentation(
                range_header, prior_presentation_base,
            )
            relative_presentation_range = True
            presentation_byte_base = prior_presentation_base
            presentation_remaining = prior_presentation_length
            if debug:
                logger.debug(
                    "Timeshift presentation range map: session=%s %s -> %s "
                    "(base=%d)",
                    session_id, range_header, effective_range,
                    prior_presentation_base,
                )
    elif media_changed:
        # Outside the opened archive: mint a fresh portal/CDN URL. Retargeting
        # an old CDN token onto a new start path often still serves the prior
        # programme (token is bound to the archive that minted it).
        keep_archive = False
        final_url = None
        if debug:
            logger.debug(
                "Timeshift session re-anchor: session=%s %s -> %s "
                "(outside open archive window, portal)",
                session_id, prior_media_id, media_id,
            )
    else:
        keep_archive = True
        final_url = raw_final_url or None
        if range_header and prior_presentation_base:
            effective_range = _map_client_range_through_presentation(
                range_header, prior_presentation_base,
            )
            relative_presentation_range = True
            presentation_byte_base = prior_presentation_base
            presentation_remaining = prior_presentation_length
            if debug:
                logger.debug(
                    "Timeshift presentation range map: session=%s %s -> %s "
                    "(base=%d)",
                    session_id, range_header, effective_range,
                    prior_presentation_base,
                )

    _update_pool_position(
        redis_client, session_id,
        media_id=media_id, provider_timestamp=provider_timestamp,
        keep_archive=keep_archive,
    )

    release_cb = _make_release_once(redis_client, session_id, profile.id)
    raw_stream_id = descriptor.get("dispatcharr_stream_id")
    if isinstance(raw_stream_id, bytes):
        raw_stream_id = raw_stream_id.decode()
    stats_stream_id = None
    if raw_stream_id:
        try:
            stats_stream_id = int(raw_stream_id)
        except (TypeError, ValueError):
            stats_stream_id = None

    try:
        response = _attempt_timeshift_stream(
            m3u_account=m3u_account,
            profile=profile,
            stream_id_value=descriptor["stream_id"],
            provider_timestamp=provider_timestamp,
            provider_tz_name=provider_tz_name,
            duration_minutes=duration_minutes,
            channel=channel,
            safe_ts=safe_ts,
            timestamp=timestamp,
            client_id=client_id,
            client_ip=client_ip,
            client_user_agent=client_user_agent,
            range_header=effective_range,
            channel_logo_id=channel_logo_id,
            user=user,
            redis_client=redis_client,
            debug=debug,
            release_cb=release_cb,
            pool_session_id=session_id,
            stats_stream_id=stats_stream_id,
            final_url=final_url,
            rewrite_plain_get=rewrite_plain_get,
            presentation_remaining=presentation_remaining,
            presentation_byte_base=presentation_byte_base,
            relative_presentation_range=relative_presentation_range,
        )
    except Exception:
        _discard_pool_session(redis_client, session_id, profile.id)
        raise

    if response.status_code < 400:
        return response

    if getattr(response, "timeshift_passthrough", False) is True:
        release_cb()
        return response

    _discard_pool_session(redis_client, session_id, profile.id)
    return response


class _SlotReleasingStream:
    """Iterator wrapper that closes the generator when WSGI closes the response."""

    def __init__(self, generator, on_close):
        self._generator = generator
        self._on_close = on_close

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._generator)

    def close(self):
        try:
            self._generator.close()
        finally:
            self._on_close()  # Backup if generator finally never ran.


def _register_stats_client(
    redis_client,
    stats_channel_id,
    client_id,
    client_ip,
    client_user_agent,
    user,
    *,
    channel_display_name,
    timestamp_utc,
    primary_url,
    channel_logo_id=None,
    m3u_profile_id=None,
    programme_vid=None,
    channel_id,
    channel_uuid,
    stats_stream_id=None,
    stream_stats=None,
    range_start=None,
    representation_length=None,
    programme_duration_secs=None,
    emit_stats_update=False,
):
    """Write Redis keys so catch-up viewers appear on ``/stats``."""
    if redis_client is None:
        return
    _cancel_stats_disconnect_grace(redis_client, stats_channel_id, client_id)
    client_set_key = TimeshiftRedisKeys.clients(stats_channel_id)
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
    metadata_key = TimeshiftRedisKeys.channel_metadata(stats_channel_id)
    now = str(time.time())
    try:
        existing_connected_at = redis_client.hget(client_key, "connected_at")
        existing_init_time = redis_client.hget(
            metadata_key, ChannelMetadataField.INIT_TIME,
        )
        existing_programme_start = redis_client.hget(client_key, "programme_start")
        existing_position_anchor = redis_client.hget(client_key, "position_anchor_at")
        existing_playback_base = redis_client.hget(client_key, "playback_base_secs")
        existing_programme_vid = redis_client.hget(client_key, "programme_vid")
    except Exception:
        existing_connected_at = None
        existing_init_time = None
        existing_programme_start = None
        existing_position_anchor = None
        existing_playback_base = None
        existing_programme_vid = None
    if isinstance(existing_programme_vid, bytes):
        existing_programme_vid = existing_programme_vid.decode()
    notify_stats_update = existing_connected_at is None
    if (
        programme_vid
        and existing_programme_vid
        and programme_vid != existing_programme_vid
    ):
        notify_stats_update = True
        _cleanup_stream_generation(redis_client, existing_programme_vid, client_id)
    playback_base_secs, position_anchor_at = resolve_stats_playback_fields(
        timestamp_utc=timestamp_utc,
        existing_programme_start=existing_programme_start,
        existing_position_anchor=existing_position_anchor,
        existing_playback_base=existing_playback_base,
        range_start=range_start,
        representation_length=representation_length,
        programme_duration_secs=programme_duration_secs,
        now=now,
    )
    client_payload = {
        "user_agent": client_user_agent or "unknown",
        "ip_address": client_ip,
        "connected_at": existing_connected_at or now,
        "last_active": now,
        "user_id": str(user.id) if user is not None else "0",
        "username": user.username if user is not None else "unknown",
        "programme_start": timestamp_utc,
        "position_anchor_at": position_anchor_at,
    }
    if playback_base_secs is not None:
        client_payload["playback_base_secs"] = str(playback_base_secs)
    if programme_vid:
        client_payload["programme_vid"] = programme_vid
    metadata_payload = {
        ChannelMetadataField.STATE: ChannelState.ACTIVE,
        ChannelMetadataField.INIT_TIME: existing_init_time or now,
        ChannelMetadataField.CHANNEL_ID: str(channel_id),
        ChannelMetadataField.CHANNEL_UUID: str(channel_uuid),
        ChannelMetadataField.CHANNEL_NAME: channel_display_name or "Timeshift",
        ChannelMetadataField.STREAM_NAME: f"Catch-up @ {timestamp_utc} UTC" if timestamp_utc else "Catch-up",
        ChannelMetadataField.URL: _redact_url(primary_url) if primary_url else "",
    }
    if channel_logo_id is not None:
        metadata_payload[ChannelMetadataField.LOGO_ID] = str(channel_logo_id)
    if m3u_profile_id is not None:
        metadata_payload[ChannelMetadataField.M3U_PROFILE] = str(m3u_profile_id)
    seed_stream_stats_metadata(
        redis_client,
        metadata_key,
        metadata_payload,
        stats_stream_id=stats_stream_id,
        stream_stats=stream_stats,
    )
    try:
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(client_key, mapping=client_payload)
        if playback_base_secs is None:
            pipe.hdel(client_key, "playback_base_secs")
        pipe.expire(client_key, CLIENT_TTL_SECONDS)
        pipe.sadd(client_set_key, client_id)
        pipe.expire(client_set_key, CLIENT_TTL_SECONDS)
        pipe.hset(metadata_key, mapping=metadata_payload)
        pipe.expire(metadata_key, CLIENT_TTL_SECONDS)
        pipe.execute()
        if emit_stats_update and notify_stats_update:
            _trigger_timeshift_stats_update(redis_client)
    except Exception as exc:
        logger.warning("Timeshift stats register failed: %s", exc)


def _heartbeat_stats_client(
    redis_client, stats_channel_id, client_id, bytes_delta=0, *,
    pool_session_id=None, programme_vid=None,
):
    if redis_client is None:
        return
    client_set_key = TimeshiftRedisKeys.clients(stats_channel_id)
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
    metadata_key = TimeshiftRedisKeys.channel_metadata(stats_channel_id)
    try:
        if not redis_client.exists(client_key):
            return
        _complete_expired_stats_grace(redis_client, stats_channel_id, client_id)
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(client_key, "last_active", str(time.time()))
        pipe.expire(client_key, CLIENT_TTL_SECONDS)
        pipe.expire(client_set_key, CLIENT_TTL_SECONDS)
        if bytes_delta > 0:
            pipe.hincrby(metadata_key, ChannelMetadataField.TOTAL_BYTES, bytes_delta)
        pipe.expire(metadata_key, CLIENT_TTL_SECONDS)
        pipe.execute()
        if programme_vid is None:
            programme_vid = redis_client.hget(client_key, "programme_vid")
            if isinstance(programme_vid, bytes):
                programme_vid = programme_vid.decode()
        _refresh_active_session_redis_ttl(
            redis_client, pool_session_id or client_id, programme_vid,
        )
    except Exception as exc:
        logger.debug("Timeshift stats heartbeat failed: %s", exc)


def _unregister_stats_client(redis_client, stats_channel_id, client_id):
    if redis_client is None:
        return
    client_set_key = TimeshiftRedisKeys.clients(stats_channel_id)
    client_key = TimeshiftRedisKeys.client_metadata(stats_channel_id, client_id)
    metadata_key = TimeshiftRedisKeys.channel_metadata(stats_channel_id)
    try:
        redis_client.srem(client_set_key, client_id)
        redis_client.delete(client_key)
        if (redis_client.scard(client_set_key) or 0) == 0:
            redis_client.delete(client_set_key)
            redis_client.delete(metadata_key)
    except Exception as exc:
        logger.warning("Timeshift stats unregister failed: %s", exc)


def _open_upstream(url, user_agent, range_header, *, allow_redirects=True):
    """Open upstream HTTP.

    Portal URLs need ``allow_redirects=True`` (XC → CDN). Cached CDN
    ``final_url`` values use ``allow_redirects=False`` so reconnects do not
    mint a new provider timeshift lock/token.
    """
    # identity: raw peek bytes are not gzip-transparent.
    headers = {"Accept-Encoding": "identity"}
    if user_agent:
        headers["User-Agent"] = user_agent
    if range_header:
        headers["Range"] = range_header
    return requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=(
            ConfigHelper.connection_timeout(),
            ConfigHelper.chunk_timeout(),
        ),
        allow_redirects=allow_redirects,
    )


_FORMAT_CACHE_TTL = 3600  # 1 hour


def _get_cached_format_index(account_id):
    """Index of the URL shape that last worked for this account, or None."""
    if account_id is None:
        return None
    return cache.get(TimeshiftRedisKeys.format_cache(account_id))


def _set_cached_format_index(account_id, index):
    if account_id is None:
        return
    cache.set(TimeshiftRedisKeys.format_cache(account_id), index, _FORMAT_CACHE_TTL)


def _passthrough_response(status, content_range=None):
    """A terminal response handed straight to the client (no streaming).

    Marked so the failover loop and reuse path return it verbatim instead of
    cascading other URL shapes or failing over to another provider.
    """
    response = HttpResponse(status=status)
    if content_range:
        response["Content-Range"] = content_range
    response["Accept-Ranges"] = "bytes"
    response.timeshift_passthrough = True
    return response


def _stream_from_provider(
    *,
    candidate_urls,
    user_agent,
    range_header,
    virtual_channel_id,
    stats_channel_id=None,
    client_id,
    client_ip,
    client_user_agent,
    user,
    channel_display_name,
    timestamp_utc,
    channel_logo_id,
    m3u_profile_id,
    debug,
    account_id=None,
    redis_client=None,
    release_cb=None,
    pool_session_id=None,
    channel_id=None,
    channel_uuid=None,
    stats_stream_id=None,
    stream_stats=None,
    duration_minutes=None,
    final_url=None,
    rewrite_plain_get=False,
    presentation_remaining=None,
    presentation_byte_base=None,
    relative_presentation_range=False,
):
    """Try each upstream URL until one returns streamable MPEG-TS.

    When ``final_url`` is set (cached post-redirect CDN URL from a prior
    request in this session), try it first with redirects disabled (same
    pattern as VOD) so Range reconnects do not mint a new portal token.

    ``rewrite_plain_get`` maps an injected CDN Range (XC start-URL scrub) back
    to a plain ``200`` + remaining ``Content-Length`` so clients that rebuild
    the XC start URL (instead of sending ``Range``) still get provider-like
    headers. Subsequent client Ranges are relative to that window and must be
    remapped via ``relative_presentation_range``.

    Sets ``timeshift_decisive`` on auth/ban-class failures (401/403/406) so the
    failover loop skips the rest of that account's streams. ``release_cb`` frees
    the provider slot when the streaming response is closed.
    """
    chunk_size = max(ConfigHelper.chunk_size(), 262144)
    if release_cb is None:
        release_cb = lambda **_kwargs: None  # noqa: E731
    if stats_channel_id is None:
        stats_channel_id = virtual_channel_id

    cached_index = _get_cached_format_index(account_id)
    if cached_index is not None and 0 <= cached_index < len(candidate_urls):
        ordered_urls = [candidate_urls[cached_index]] + [
            u for i, u in enumerate(candidate_urls) if i != cached_index
        ]
        original_indices = [cached_index] + [
            i for i in range(len(candidate_urls)) if i != cached_index
        ]
    else:
        ordered_urls = list(candidate_urls)
        original_indices = list(range(len(candidate_urls)))

    # (url, allow_redirects, cached_final, format_index_or_None)
    attempts = []
    if final_url:
        attempts.append((final_url, False, True, None))
    for url, orig_idx in zip(ordered_urls, original_indices):
        attempts.append((url, True, False, orig_idx))

    # Peek for MPEG-TS sync; some providers return HTTP 200 with PHP/HTML errors.
    upstream = None
    last_status = None
    last_url = attempts[0][0] if attempts else ""
    winning_index = None
    used_cached_final = False
    decisive_failure = False
    for url, follow_redirects, cached_final, orig_idx in attempts:
        try:
            response = _open_upstream(
                url, user_agent, range_header, allow_redirects=follow_redirects,
            )
        except requests.exceptions.RequestException as exc:
            if cached_final:
                logger.warning(
                    "Timeshift cached CDN unreachable (%s): %s; falling back to portal",
                    _redact_url(url), type(exc).__name__,
                )
                _clear_pool_final_url(redis_client, pool_session_id)
                continue
            logger.error(
                "Timeshift provider unreachable (%s): %s",
                _redact_url(url), type(exc).__name__,
            )
            return _finalize_timeshift_response(
                HttpResponseBadRequest("Provider connection error")
            )
        last_status = response.status_code
        last_url = getattr(response, "url", None) or url
        cascade_label = "cdn" if cached_final else (orig_idx if orig_idx is not None else "?")
        if debug:
            logger.debug(
                "Timeshift cascade[%s]: status=%d type=%s url=%s",
                cascade_label, response.status_code,
                response.headers.get("Content-Type", "?"),
                _redact_url(url),
            )
        if response.status_code == 416:
            # Range Not Satisfiable: a seek/tail probe past EOF. Hand it back to
            # the client verbatim. Byte offsets are file-specific, so trying
            # other URL shapes or failing over to another provider is pointless
            # and only multiplies upstream connections.
            content_range = response.headers.get("Content-Range")
            response.close()
            return _finalize_timeshift_response(_passthrough_response(416, content_range))
        if response.status_code in (200, 206):
            peek = response.raw.read(1024)
            content_type = response.headers.get("Content-Type", "")
            # 206 may start mid-packet; accept before sync probe trims peek bytes.
            is_partial = response.status_code == 206 and bool(range_header)
            if is_partial and peek and "html" not in content_type and "json" not in content_type:
                response._peek_data = peek
                upstream = response
                winning_index = orig_idx
                used_cached_final = cached_final
                break
            sync_offset = find_ts_sync(peek) if peek else -1
            if sync_offset >= 0:
                response._peek_data = peek[sync_offset:]
                upstream = response
                winning_index = orig_idx
                used_cached_final = cached_final
                break
            snippet = peek[:200].decode("utf-8", errors="replace") if peek else "(empty)"
            logger.warning(
                "Timeshift upstream returned %d but no TS sync in first %d "
                "bytes (likely PHP error): %s, url=%s",
                response.status_code,
                len(peek) if peek else 0,
                snippet.replace("\n", " ")[:120],
                _redact_url(url),
            )
            response.close()
            if cached_final:
                _clear_pool_final_url(redis_client, pool_session_id)
            last_status = 404  # Treat as soft rejection for cascade
            continue
        response.close()
        if cached_final:
            # Expired/rotated CDN token; clear and retry portal shapes.
            logger.info(
                "Timeshift cached CDN returned %d, clearing final_url for session %s",
                response.status_code, pool_session_id,
            )
            _clear_pool_final_url(redis_client, pool_session_id)
            continue
        # Auth/ban-class statuses stop trying more shapes on this account; 5xx does not.
        code = response.status_code
        if code in (401, 403, 406) or 300 <= code < 400:
            decisive_failure = True
            break

    if winning_index is not None:
        _set_cached_format_index(account_id, winning_index)

    if upstream is None:
        logger.error("Timeshift upstream rejected: status=%s url=%s",
                     last_status, _redact_url(last_url))
        # Map 404/403 to meaningful client responses; other failures stay 400.
        if last_status == 404:
            failure = HttpResponseNotFound("Catch-up not available yet")
        elif last_status == 403:
            failure = HttpResponseForbidden("Provider denied access")
        else:
            failure = HttpResponseBadRequest("Provider error")
        failure.timeshift_decisive = decisive_failure
        return _finalize_timeshift_response(failure)

    content_type = upstream.headers.get("Content-Type", "video/mp2t")
    content_range = upstream.headers.get("Content-Range", "")
    status = upstream.status_code

    _store_pool_content_length(redis_client, pool_session_id, upstream)
    _store_pool_serving_range(redis_client, pool_session_id, range_header)
    # Capture post-redirect CDN URL for reconnects (VOD final_url pattern).
    resolved_url = getattr(upstream, "url", None) or last_url
    if resolved_url:
        _store_pool_final_url(redis_client, pool_session_id, resolved_url)
    # Portal opens define (or redefine) the session archive window; CDN scrubs reuse it.
    # force=False: after keep_archive=False clear, these keys are empty and get set;
    # after CDN→portal fallback mid-session, keep the original anchor.
    _ensure_pool_archive_anchor(
        redis_client,
        pool_session_id,
        timestamp=timestamp_utc,
        duration_minutes=duration_minutes,
        force=False,
    )

    representation_length = _extract_representation_length(upstream)
    if representation_length is None and redis_client and pool_session_id:
        cached_length = redis_client.hget(
            _pool_key(pool_session_id), "content_length",
        )
        if cached_length is not None:
            try:
                if isinstance(cached_length, bytes):
                    cached_length = cached_length.decode()
                representation_length = int(cached_length)
            except (TypeError, ValueError):
                representation_length = None

    if rewrite_plain_get and status == 206:
        # Client sent a plain GET with a new start; we injected CDN Range.
        # Present a provider-like 200 with remaining Content-Length.
        remaining = presentation_remaining
        if remaining is None and representation_length is not None:
            start = _parse_range_start(range_header) or 0
            remaining = max(int(representation_length) - int(start), 0)
        status = 200
        content_range = ""
        client_length_headers = {"Accept-Ranges": "bytes"}
        if remaining is not None:
            client_length_headers["Content-Length"] = str(remaining)
            byte_base = presentation_byte_base
            if byte_base is None:
                byte_base = _parse_range_start(range_header) or 0
            _store_pool_presentation_window(
                redis_client, pool_session_id, remaining, byte_base=byte_base,
            )
    else:
        outbound_content_range = content_range or None
        if relative_presentation_range and outbound_content_range:
            outbound_content_range = _presentation_relative_content_range(
                outbound_content_range,
                presentation_byte_base=presentation_byte_base,
                presentation_length=presentation_remaining,
            )
        client_length_headers = _build_downstream_length_headers(
            # Absolute CDN Range must not leak into Content-Range synthesis;
            # the client still thinks this file starts at presentation byte 0.
            range_header=None if relative_presentation_range else range_header,
            status_code=status,
            representation_length=(
                presentation_remaining
                if relative_presentation_range and presentation_remaining is not None
                else representation_length
            ),
            upstream_content_range=outbound_content_range,
            upstream_content_length=upstream.headers.get("Content-Length"),
            streaming=True,
        )
        if presentation_remaining is not None and presentation_byte_base is not None:
            _store_pool_presentation_window(
                redis_client, pool_session_id, presentation_remaining,
                byte_base=presentation_byte_base,
            )
        elif representation_length is not None and not range_header:
            _store_pool_presentation_window(
                redis_client, pool_session_id, representation_length, byte_base=0,
            )

    programme_duration_secs = None
    if duration_minutes:
        programme_duration_secs = float(duration_minutes) * 60.0

    # XC start-URL scrub injects a CDN Range for the provider only. Stats must
    # use the URL timestamp vs EPG; mapping archive bytes onto programme
    # duration falsely parks the card at an unrelated offset.
    stats_range_start = None if rewrite_plain_get else _parse_range_start(range_header)
    _register_stats_client(
        redis_client,
        stats_channel_id,
        client_id,
        client_ip,
        client_user_agent,
        user,
        channel_display_name=channel_display_name,
        timestamp_utc=timestamp_utc,
        primary_url=last_url,
        channel_logo_id=channel_logo_id,
        m3u_profile_id=m3u_profile_id,
        programme_vid=virtual_channel_id,
        channel_id=channel_id,
        channel_uuid=channel_uuid,
        stats_stream_id=stats_stream_id,
        stream_stats=stream_stats,
        range_start=stats_range_start,
        representation_length=representation_length,
        programme_duration_secs=programme_duration_secs,
        emit_stats_update=True,
    )

    peek_data = getattr(upstream, "_peek_data", None)
    _register_active_upstream(virtual_channel_id, client_id, upstream)

    session_closed = {"done": False}

    def _finish_session(
        *, close_upstream=False, release_slot=True,
        mark_pool_idle=True, release_profile=True,
    ):
        if session_closed["done"]:
            return
        session_closed["done"] = True
        _unregister_active_upstream(virtual_channel_id, client_id)
        if close_upstream:
            try:
                upstream.close()
            except Exception:
                pass
        if release_slot:
            release_cb(
                mark_pool_idle=mark_pool_idle,
                release_profile=release_profile,
            )

    def stream_generator():
        last_heartbeat = time.time()
        bytes_since_heartbeat = 0
        total_yielded = 0
        loop_start = time.time()
        stop_key = TimeshiftRedisKeys.client_stop(virtual_channel_id, client_id)
        stream_generation = _allocate_stream_generation(
            redis_client, virtual_channel_id, client_id,
        )
        stream_started_logged = False
        stopped_for_reuse = False
        try:
            for data in _iter_upstream_with_stop(
                upstream, chunk_size, redis_client, stop_key,
                stream_generation, peek_data=peek_data,
            ):
                if not data:
                    continue
                if debug and not stream_started_logged:
                    stream_started_logged = True
                    logger.debug(
                        "Timeshift stream started: client=%s vid=%s range=%s status=%d gen=%d",
                        client_id, virtual_channel_id, range_header or "(none)",
                        status, stream_generation,
                    )
                yield data
                bytes_since_heartbeat += len(data)
                total_yielded += len(data)

                now = time.time()
                should_stop, is_reuse = _stream_stop_requested(
                    redis_client, stop_key, stream_generation,
                )
                if should_stop:
                    logger.info("Timeshift client %s received stop signal", client_id)
                    stopped_for_reuse = is_reuse
                    if not is_reuse:
                        redis_client.delete(stop_key)
                    break
                # Refresh stats every 5 seconds.
                if now - last_heartbeat >= 5:
                    if debug and total_yielded > 0:
                        elapsed = now - loop_start
                        mbps = (total_yielded * 8) / elapsed / 1_000_000 if elapsed > 0 else 0
                        logger.debug(
                            "Timeshift streaming: client=%s range=%s total=%d bytes "
                            "in %.1fs (%.2f Mbps avg)",
                            client_id, range_header or "(none)",
                            total_yielded, elapsed, mbps,
                        )
                    _heartbeat_stats_client(
                        redis_client, stats_channel_id, client_id,
                        bytes_delta=bytes_since_heartbeat,
                        pool_session_id=pool_session_id or client_id,
                        programme_vid=virtual_channel_id,
                    )
                    last_heartbeat = now
                    bytes_since_heartbeat = 0
        except GeneratorExit:
            pass
        except Exception:
            logger.exception("Timeshift stream loop error")
        finally:
            elapsed = time.time() - loop_start
            if bytes_since_heartbeat > 0:
                _heartbeat_stats_client(
                    redis_client, stats_channel_id, client_id,
                    bytes_delta=bytes_since_heartbeat,
                    pool_session_id=pool_session_id or client_id,
                    programme_vid=virtual_channel_id,
                )
            if debug and total_yielded > 0:
                mbps = (total_yielded * 8) / elapsed / 1_000_000 if elapsed > 0 else 0
                logger.debug(
                    "Timeshift disconnect: vid=%s client=%s yielded=%d bytes in %.1fs (%.2f Mbps avg)",
                    virtual_channel_id, client_id, total_yielded, elapsed, mbps,
                )
            if redis_client and redis_client.exists(stop_key):
                should_stop, is_reuse = _stream_stop_requested(
                    redis_client, stop_key, stream_generation,
                )
                if should_stop:
                    if not stopped_for_reuse:
                        stopped_for_reuse = is_reuse
                    if not is_reuse:
                        redis_client.delete(stop_key)
            if (
                not stopped_for_reuse
                and redis_client
                and stream_generation
                < _current_stream_generation(
                    redis_client, virtual_channel_id, client_id,
                )
            ):
                # Newer stream generation took over (seek handoff).
                stopped_for_reuse = True
            if not stopped_for_reuse:
                if not _is_timeshift_startup_probe(total_yielded, elapsed):
                    _cleanup_stream_generation(
                        redis_client, virtual_channel_id, client_id,
                    )
                if _should_schedule_stats_disconnect_grace(
                    total_yielded,
                    elapsed,
                    stopped_for_reuse=stopped_for_reuse,
                    redis_client=redis_client,
                    client_id=client_id,
                ):
                    _schedule_stats_disconnect_grace(
                        redis_client, stats_channel_id, client_id,
                    )
                _finish_session(close_upstream=True, mark_pool_idle=True)
            else:
                # Seek handoff: replacement stream keeps pool busy and profile slot.
                _finish_session(
                    close_upstream=True,
                    mark_pool_idle=False,
                    release_profile=False,
                )

    def _finish_session_backup():
        _finish_session(close_upstream=True)

    stream_iter = _SlotReleasingStream(stream_generator(), _finish_session_backup)
    response = StreamingHttpResponse(
        stream_iter,
        content_type=content_type,
        status=status,
    )
    response["X-Accel-Buffering"] = "no"  # avoid nginx throttling the stream
    for header_name, header_value in client_length_headers.items():
        response[header_name] = header_value
    return _finalize_timeshift_response(response)


def _redact_url(url):
    """Truncate *url* to ``scheme://host/...`` for safe logging (drops credentials)."""
    if not url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/..."
