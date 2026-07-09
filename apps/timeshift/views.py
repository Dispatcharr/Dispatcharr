"""XC catch-up (timeshift) proxy with multi-provider failover."""

import hmac
import itertools
import logging
import secrets
import time
from urllib.parse import urlencode

import requests
from django.core.cache import cache
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    StreamingHttpResponse,
)

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.channels.utils import get_channel_catchup_streams
from apps.m3u.connection_pool import release_profile_slot, reserve_profile_slot
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.tasks import get_transformed_credentials
from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.utils import get_client_ip
from apps.proxy.utils import (
    check_user_stream_limits,
    find_ts_sync,
    get_user_active_connections,
)
from core.utils import RedisClient
from dispatcharr.utils import network_access_allowed

from .helpers import (
    TimeshiftCredentials,
    build_timeshift_candidate_urls,
    convert_timestamp_to_provider_tz,
    get_programme_duration,
    parse_catchup_timestamp,
)

logger = logging.getLogger(__name__)

CLIENT_TTL_SECONDS = 60
_MATCH_SCORE_THRESHOLD = 8  # client_ip (5) + client_user_agent (3)


def timeshift_proxy(request, username, password, stream_id, timestamp, duration):  # noqa: ARG001 stream_id
    """Proxy an XC catch-up request to the provider with multi-stream failover.

    URL shape (iPlayTV / TiviMate):
        ``stream_id``: EPG channel number (ignored here).
        ``duration``: Dispatcharr ``Channel.id`` (XC API exposes channel.id as stream_id).
        ``timestamp``: UTC programme start (``YYYY-MM-DD:HH-MM`` or XC colon form
            ``YYYY-MM-DD:HH:MM:SS``).
    """
    raw_id = duration[:-3] if duration.endswith(".ts") else duration

    user = _authenticate_user(username, password)
    if user is None:
        return HttpResponseForbidden("Invalid credentials")

    if not network_access_allowed(request, "XC_API", user):
        return HttpResponseForbidden("Access denied")

    try:
        channel = Channel.objects.get(id=int(raw_id))
    except (Channel.DoesNotExist, ValueError, TypeError):
        raise Http404("Channel not found") from None

    if not _user_can_access_channel(user, channel):
        return HttpResponseForbidden("Access denied")

    # Shape helpers pass through on parse failure; reject bad input before upstream.
    if parse_catchup_timestamp(timestamp) is None:
        return HttpResponseBadRequest("Invalid timestamp")

    catchup_streams = get_channel_catchup_streams(channel)
    if not catchup_streams:
        return HttpResponseBadRequest("Timeshift not supported for this channel")

    debug = logger.isEnabledFor(logging.DEBUG)

    # EPG duration lookup stays in UTC; provider TZ conversion is per-attempt below.
    duration_minutes = get_programme_duration(channel, timestamp)

    safe_ts = timestamp.replace(":", "-").replace("/", "-")
    client_ip = get_client_ip(request)
    client_user_agent = request.META.get("HTTP_USER_AGENT", "") or ""
    range_header = request.META.get("HTTP_RANGE")
    channel_logo_id = getattr(channel, "logo_id", None)

    redis_client = RedisClient.get_client()

    # Content identity (channel + catch-up position). Provider slot sharing is
    # scoped per client session; never assume all requests for the same
    # programme belong to one viewer.
    media_id = f"timeshift_{channel.id}_{safe_ts}"

    session_id = request.GET.get("session_id")
    if not session_id:
        logger.debug("Timeshift session redirect: %s (new session)", request.path)
        return _redirect_with_new_session(request)

    session_entry = _get_pool_entry(redis_client, session_id)
    if session_entry and not _pool_entry_owned_by_user(session_entry, user.id):
        logger.info(
            "Timeshift: rejecting foreign session_id for user %s", user.id,
        )
        return _redirect_with_new_session(request)

    # Stable client identity for stats, stop keys, and the provider pool.
    effective_session_id = session_id
    client_id = session_id

    # Reuse an idle pool owned by this session, or fingerprint-match a prior
    # idle session from the same client (VOD-style) before opening upstream.
    if not session_entry:
        matched = _find_matching_idle_session(
            redis_client,
            media_id=media_id,
            user_id=user.id,
            client_ip=client_ip,
            client_user_agent=client_user_agent,
        )
        if matched:
            logger.info(
                "Timeshift fingerprint matched idle session %s for %s",
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
        return HttpResponseForbidden("Stream limit exceeded")

    if effective_session_id == session_id:
        pool = _snapshot_from_entry(session_entry)
    else:
        pool = _pool_snapshot(redis_client, effective_session_id)
    pool_exists = pool is not None
    pool_busy = pool["busy"] if pool else False
    pool_content_length = pool["content_length"] if pool else None
    busy_serving_range = pool["serving_range"] if pool else None

    acquired = None
    if pool_exists:
        if pool_busy:
            if _should_displace_busy_playback(
                range_header, pool_content_length, busy_serving_range,
            ):
                _preempt_playback_streams(redis_client, effective_session_id, user)
                acquired = _wait_for_idle_pool_session(
                    redis_client,
                    effective_session_id,
                    user_id=user.id,
                    wait_seconds=_POOL_PREEMPT_WAIT_SECONDS,
                )
        else:
            acquired = _acquire_idle_pool_session(
                redis_client, effective_session_id, user_id=user.id,
            )

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
            range_header=range_header,
            channel_logo_id=channel_logo_id,
            user=user,
            debug=debug,
        )
        if reuse_response is not None:
            if reuse_response.status_code < 400:
                return reuse_response
            if getattr(reuse_response, "timeshift_passthrough", False) is True:
                return reuse_response
            last_response = reuse_response
            if getattr(reuse_response, "timeshift_decisive", False):
                try:
                    decisive_accounts.add(int(descriptor["account_id"]))
                except (ValueError, TypeError):
                    pass

    if pool_exists and pool_busy and not _should_displace_busy_playback(
            range_header, pool_content_length, busy_serving_range,
        ):
        logger.debug(
            "Timeshift: deferring non-displacing request for session %s range=%s",
            effective_session_id, range_header or "(none)",
        )
        return HttpResponse("Stream slot busy", status=503)

    if pool_exists and pool_busy:
        logger.warning(
            "Timeshift: session %s did not become idle in time",
            effective_session_id,
        )
        return HttpResponse("Stream slot busy", status=503)

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
            provider_timestamp=provider_timestamp,
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
            return HttpResponse("Stream slot busy", status=503)
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
                range_header=range_header,
                channel_logo_id=channel_logo_id,
                user=user,
                redis_client=redis_client,
                debug=debug,
                release_cb=release_cb,
                pool_session_id=effective_session_id,
            )
        except Exception:
            _discard_pool_session(redis_client, effective_session_id, reserved_profile.id)
            raise
        if response.status_code < 400:
            # Streaming: the generator's close path frees the slot via release_cb.
            return response

        if getattr(response, "timeshift_passthrough", False) is True:
            # Terminal range answer (e.g. 416 past EOF): the upstream session is
            # healthy, so free the slot but keep the entry idle for the next
            # probe, and return verbatim without failing over to other accounts.
            release_cb()
            return response

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
        return last_response
    if capacity_blocked:
        return HttpResponse("No available stream slot", status=503)
    return HttpResponseBadRequest("Cannot build timeshift URL")


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


# Per-client session pool (keyed by session_id from the 301 redirect). Each
# viewer gets their own provider slot even when watching the same catch-up
# programme. Idle sessions can be fingerprint-matched (VOD-style) when a client
# returns without its prior session_id.
_POOL_KEY = "timeshift_pool:{session_id}"
_POOL_LOCK_KEY = "timeshift_pool_lock:{session_id}"
_POOL_ENTRY_TTL = 6 * 3600
_POOL_IDLE_TTL = 30
_POOL_WAIT_SECONDS = 1.0
_POOL_PREEMPT_WAIT_SECONDS = 5.0
_POOL_POLL_INTERVAL = 0.05
_EOF_PROBE_TAIL_BYTES = 512_000
_EOF_PROBE_UNKNOWN_LENGTH_MIN = 100_000_000


def _pool_key(session_id):
    return _POOL_KEY.format(session_id=session_id)


def _parse_range_start(range_header):
    """Return the byte offset from a ``Range: bytes=START-`` header, or None."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    start_part = range_header[6:].split("-", 1)[0]
    if not start_part:
        return None
    try:
        return int(start_part)
    except (TypeError, ValueError):
        return None


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


def _score_pool_fingerprint(entry, client_ip, client_user_agent):
    """Score IP/UA overlap for fingerprint adoption (user and media pre-filtered)."""
    score = 0
    if entry.get("client_ip") and entry.get("client_ip") == client_ip:
        score += 5
    if entry.get("client_user_agent") and entry.get("client_user_agent") == client_user_agent:
        score += 3
    return score


def _mint_timeshift_session_id():
    return f"timeshift_{secrets.token_urlsafe(16)}"


def _redirect_with_new_session(request):
    session_id = _mint_timeshift_session_id()
    query_params = {k: request.GET.getlist(k) for k in request.GET}
    query_params["session_id"] = [session_id]
    redirect_url = f"{request.path}?{urlencode(query_params, doseq=True)}"
    return HttpResponse(status=301, headers={"Location": redirect_url})


def _pool_entry_owned_by_user(entry, user_id):
    """True when *entry* is unclaimed or owned by *user_id*."""
    if not entry or not entry.get("profile_id"):
        return True
    owner = entry.get("user_id")
    if owner is None or owner == "":
        return False
    return str(owner) == str(user_id)


def _find_matching_idle_session(
    redis_client, *, media_id, user_id, client_ip, client_user_agent,
):
    """Find an idle pooled session that likely belongs to the same client."""
    if redis_client is None:
        return None
    matches = []
    try:
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(
                cursor, match="timeshift_pool:timeshift_*", count=100,
            )
            for key in keys:
                try:
                    data = redis_client.hgetall(key)
                    if not data or data.get("busy") == "1":
                        continue
                    if str(data.get("user_id") or "") != str(user_id):
                        continue
                    if str(data.get("media_id") or "") != str(media_id):
                        continue
                    session_id = key.rsplit(":", 1)[-1]
                    score = _score_pool_fingerprint(
                        data, client_ip, client_user_agent,
                    )
                    if score >= _MATCH_SCORE_THRESHOLD:
                        last_activity = float(data.get("last_activity") or "0")
                        matches.append((session_id, score, last_activity))
                except Exception as exc:
                    logger.debug("Timeshift pool scan skip %s: %s", key, exc)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Timeshift idle session search failed: %s", exc)
        return None

    if not matches:
        return None
    matches.sort(key=lambda item: (item[1], item[2]), reverse=True)
    best = matches[0][0]
    logger.debug(
        "Timeshift idle match: session=%s score=%s media=%s",
        best, matches[0][1], media_id,
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


def _update_pool_position(redis_client, session_id, *, media_id, provider_timestamp):
    """Move a reused session's descriptor to the position actually served.

    A seek keeps the session (provider-slot continuity) but changes the
    catch-up position; the descriptor must follow it so later fingerprint
    matches and same-channel displacement compare against the position the
    session is really on.
    """
    if redis_client is None or not session_id:
        return
    try:
        redis_client.hset(_pool_key(session_id), mapping={
            "media_id": str(media_id),
            "provider_timestamp": str(provider_timestamp),
        })
    except Exception as exc:
        logger.debug("Timeshift pool position update failed: %s", exc)


def _store_pool_content_length(redis_client, session_id, upstream_response):
    if redis_client is None or not session_id or upstream_response is None:
        return
    content_length = upstream_response.headers.get("Content-Length")
    content_range = upstream_response.headers.get("Content-Range", "")
    if content_range and "/" in content_range:
        total = content_range.rsplit("/", 1)[-1]
        if total != "*":
            content_length = total
    if not content_length:
        return
    try:
        redis_client.hset(
            _pool_key(session_id), "content_length", str(content_length),
        )
    except Exception as exc:
        logger.debug("Timeshift pool content_length store failed: %s", exc)


def _pool_lock(redis_client, session_id):
    return redis_client.lock(
        _POOL_LOCK_KEY.format(session_id=session_id),
        timeout=10,
        blocking_timeout=5,
    )


def _acquire_idle_pool_session(redis_client, session_id, *, user_id=None):
    """Re-reserve an idle session's profile slot and mark it busy."""
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
            if data.get("busy") == "1":
                return None
            try:
                profile = M3UAccountProfile.objects.get(id=int(data["profile_id"]))
            except M3UAccountProfile.DoesNotExist:
                redis_client.delete(key)
                return None
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
):
    if redis_client is None or not session_id:
        return None
    deadline = time.time() + wait_seconds
    while True:
        acquired = _acquire_idle_pool_session(
            redis_client, session_id, user_id=user_id,
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
    provider_timestamp,
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
                "provider_timestamp": str(provider_timestamp),
                "busy": "1",
                "last_activity": now,
            })
            redis_client.expire(key, _POOL_ENTRY_TTL)
        return True
    except Exception as exc:
        logger.warning("Timeshift pool create failed for %s: %s", session_id, exc)
        return False


def _release_pool_session(redis_client, session_id, profile_id):
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

    def _release():
        if state["done"]:
            return
        state["done"] = True
        _release_pool_session(redis_client, session_id, profile_id)

    return _release


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
            logger.debug(
                "Timeshift preempt: stopping client %s on %s for reuse",
                old_client_id, conn_media_id,
            )
            _unregister_stats_client(redis_client, conn_media_id, old_client_id)
            stop_key = RedisKeys.client_stop(conn_media_id, old_client_id)
            redis_client.setex(stop_key, 60, "true")
    except Exception as exc:
        logger.warning("Timeshift preempt failed: %s", exc)


def _terminate_previous_timeshift_sessions(
    redis_client, user, channel_id, current_media_id, current_session_id,
):
    """Displace this user's other catch-up positions on the same channel."""
    if redis_client is None or user is None:
        return
    prefix = f"timeshift_{channel_id}_"
    try:
        for conn in get_user_active_connections(user.id):
            if conn.get("type") != "timeshift":
                continue
            if conn.get("client_id") == current_session_id:
                continue
            conn_media_id = str(conn.get("media_id") or "")
            if not conn_media_id.startswith(prefix):
                continue
            if conn_media_id.startswith(f"{current_media_id}_") or conn_media_id == current_media_id:
                continue
            old_client_id = conn.get("client_id")
            logger.info(
                "Timeshift takeover: displacing session %s on %s",
                old_client_id, conn_media_id,
            )
            _unregister_stats_client(redis_client, conn_media_id, old_client_id)
            stop_key = RedisKeys.client_stop(conn_media_id, old_client_id)
            redis_client.setex(stop_key, 60, "true")
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
    range_header,
    channel_logo_id,
    user,
    redis_client,
    debug,
    release_cb=None,
    pool_session_id=None,
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

    virtual_channel_id = f"timeshift_{channel.id}_{safe_ts}_{stream_id_value}"

    if debug:
        logger.debug(
            "Timeshift attempt: channel=%s ts=%s (provider tz=%s -> %s) "
            "account=%s profile=%s provider_sid=%s vid=%s client=%s range=%s",
            channel.name, timestamp, provider_tz_name, provider_timestamp,
            m3u_account.id, profile.id, stream_id_value,
            virtual_channel_id, client_id, range_header or "(none)",
        )

    return _stream_from_provider(
        candidate_urls=candidate_urls,
        user_agent=user_agent,
        range_header=range_header,
        virtual_channel_id=virtual_channel_id,
        client_id=client_id,
        client_ip=client_ip,
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

    # The stored provider_timestamp is the position this session was CREATED
    # for. Clients (TiviMate) keep the ?session_id= query when they rebuild
    # the seek URL with a new start, so a reused session must serve the
    # REQUESTED position, never replay the stored one — otherwise every
    # timestamp-jump FF/RW snaps back to the session's original anchor. The
    # provider zone is a property of the account (server_info reported on
    # auth, stored on the default profile), so recomputing costs one trivial
    # conversion.
    provider_tz_name = None
    tz_profile = (
        m3u_account.profiles.filter(is_default=True).first() or profile
    )
    server_info = (tz_profile.custom_properties or {}).get("server_info") or {}
    if isinstance(server_info, dict):
        provider_tz_name = server_info.get("timezone")
    provider_timestamp = convert_timestamp_to_provider_tz(timestamp, provider_tz_name)

    # Move the descriptor to the position actually served so fingerprint
    # matching and same-channel displacement keep working after the seek.
    _update_pool_position(
        redis_client, session_id,
        media_id=media_id, provider_timestamp=provider_timestamp,
    )

    release_cb = _make_release_once(redis_client, session_id, profile.id)
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
            range_header=range_header,
            channel_logo_id=channel_logo_id,
            user=user,
            redis_client=redis_client,
            debug=debug,
            release_cb=release_cb,
            pool_session_id=session_id,
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
    """Iterator wrapper that releases the pool slot when WSGI closes the response."""

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
            self._on_close()


def _register_stats_client(
    redis_client,
    virtual_channel_id,
    client_id,
    client_ip,
    user_agent,
    user,
    *,
    channel_display_name,
    timestamp_utc,
    primary_url,
    channel_logo_id=None,
    m3u_profile_id=None,
):
    """Write Redis keys so catch-up viewers appear on ``/stats``."""
    if redis_client is None:
        return
    client_set_key = RedisKeys.clients(virtual_channel_id)
    client_key = RedisKeys.client_metadata(virtual_channel_id, client_id)
    metadata_key = RedisKeys.channel_metadata(virtual_channel_id)
    now = str(time.time())
    client_payload = {
        "user_agent": user_agent or "unknown",
        "ip_address": client_ip,
        "connected_at": now,
        "last_active": now,
        "user_id": str(user.id) if user is not None else "0",
        "username": user.username if user is not None else "unknown",
    }
    metadata_payload = {
        ChannelMetadataField.STATE: ChannelState.ACTIVE,
        ChannelMetadataField.INIT_TIME: now,
        ChannelMetadataField.OWNER: "timeshift",
        ChannelMetadataField.CHANNEL_NAME: channel_display_name or "Timeshift",
        ChannelMetadataField.STREAM_NAME: f"Catch-up @ {timestamp_utc} UTC" if timestamp_utc else "Catch-up",
        ChannelMetadataField.URL: _redact_url(primary_url) if primary_url else "",
        ChannelMetadataField.IS_TIMESHIFT: "1",
    }
    if channel_logo_id is not None:
        metadata_payload[ChannelMetadataField.LOGO_ID] = str(channel_logo_id)
    if m3u_profile_id is not None:
        metadata_payload[ChannelMetadataField.M3U_PROFILE] = str(m3u_profile_id)
    try:
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(client_key, mapping=client_payload)
        pipe.expire(client_key, CLIENT_TTL_SECONDS)
        pipe.sadd(client_set_key, client_id)
        pipe.expire(client_set_key, CLIENT_TTL_SECONDS)
        pipe.hset(metadata_key, mapping=metadata_payload)
        pipe.expire(metadata_key, CLIENT_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:
        logger.warning("Timeshift stats register failed: %s", exc)


def _heartbeat_stats_client(redis_client, virtual_channel_id, client_id, bytes_delta=0):
    if redis_client is None:
        return
    client_set_key = RedisKeys.clients(virtual_channel_id)
    client_key = RedisKeys.client_metadata(virtual_channel_id, client_id)
    metadata_key = RedisKeys.channel_metadata(virtual_channel_id)
    try:
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(client_key, "last_active", str(time.time()))
        pipe.expire(client_key, CLIENT_TTL_SECONDS)
        pipe.expire(client_set_key, CLIENT_TTL_SECONDS)
        if bytes_delta > 0:
            pipe.hincrby(metadata_key, ChannelMetadataField.TOTAL_BYTES, bytes_delta)
        pipe.expire(metadata_key, CLIENT_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:
        logger.debug("Timeshift stats heartbeat failed: %s", exc)


def _unregister_stats_client(redis_client, virtual_channel_id, client_id):
    if redis_client is None:
        return
    client_set_key = RedisKeys.clients(virtual_channel_id)
    client_key = RedisKeys.client_metadata(virtual_channel_id, client_id)
    metadata_key = RedisKeys.channel_metadata(virtual_channel_id)
    try:
        redis_client.srem(client_set_key, client_id)
        redis_client.delete(client_key)
        if (redis_client.scard(client_set_key) or 0) == 0:
            redis_client.delete(client_set_key)
            redis_client.delete(metadata_key)
    except Exception as exc:
        logger.warning("Timeshift stats unregister failed: %s", exc)


def _open_upstream(url, user_agent, range_header):
    """Open upstream HTTP; redirects are followed (XC load-balancer nodes)."""
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
        timeout=ConfigHelper.connection_timeout(),
    )


_FORMAT_CACHE_KEY = "timeshift:format_idx:{}"
_FORMAT_CACHE_TTL = 3600  # 1 hour


def _get_cached_format_index(account_id):
    """Index of the URL shape that last worked for this account, or None."""
    if account_id is None:
        return None
    return cache.get(_FORMAT_CACHE_KEY.format(account_id))


def _set_cached_format_index(account_id, index):
    if account_id is None:
        return
    cache.set(_FORMAT_CACHE_KEY.format(account_id), index, _FORMAT_CACHE_TTL)


def _passthrough_response(status, content_range=None):
    """A terminal response handed straight to the client (no streaming).

    Marked so the failover loop and reuse path return it verbatim instead of
    cascading other URL shapes or failing over to another provider.
    """
    response = HttpResponse(status=status)
    if content_range:
        response["Content-Range"] = content_range
    response.timeshift_passthrough = True
    return response


def _stream_from_provider(
    *,
    candidate_urls,
    user_agent,
    range_header,
    virtual_channel_id,
    client_id,
    client_ip,
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
):
    """Try each upstream URL until one returns streamable MPEG-TS.

    Sets ``timeshift_decisive`` on auth/ban-class failures (401/403/406) so the
    failover loop skips the rest of that account's streams. ``release_cb`` frees
    the provider slot when the streaming response is closed.
    """
    chunk_size = max(ConfigHelper.chunk_size(), 262144)
    if release_cb is None:
        release_cb = lambda: None  # noqa: E731

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

    # Peek for MPEG-TS sync; some providers return HTTP 200 with PHP/HTML errors.
    upstream = None
    last_status = None
    last_url = ordered_urls[0]
    winning_index = None
    decisive_failure = False
    for url, orig_idx in zip(ordered_urls, original_indices):
        try:
            response = _open_upstream(url, user_agent, range_header)
        except requests.exceptions.RequestException as exc:
            logger.error(
                "Timeshift provider unreachable (%s): %s",
                _redact_url(url), type(exc).__name__,
            )
            return HttpResponseBadRequest("Provider connection error")
        last_status = response.status_code
        last_url = url
        if debug:
            logger.debug(
                "Timeshift cascade[%d]: status=%d type=%s url=%s",
                orig_idx, response.status_code,
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
            return _passthrough_response(416, content_range)
        if response.status_code in (200, 206):
            peek = response.raw.read(1024)
            sync_offset = find_ts_sync(peek) if peek else -1
            if sync_offset >= 0:
                response._peek_data = peek[sync_offset:]
                upstream = response
                winning_index = orig_idx
                break
            # A 206 to a Range request legitimately starts mid-packet, so the
            # sync byte rarely lands at offset 0. Trust the partial status and
            # content type rather than the sync probe; only a full 200 carrying
            # a PHP/HTML error page must be rejected here.
            content_type = response.headers.get("Content-Type", "")
            is_partial = response.status_code == 206 and bool(range_header)
            if is_partial and peek and "html" not in content_type and "json" not in content_type:
                response._peek_data = peek
                upstream = response
                winning_index = orig_idx
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
            last_status = 404  # Treat as soft rejection for cascade
            continue
        response.close()
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
        return failure

    content_type = upstream.headers.get("Content-Type", "video/mp2t")
    content_range = upstream.headers.get("Content-Range", "")
    status = upstream.status_code

    _store_pool_content_length(redis_client, pool_session_id, upstream)
    _store_pool_serving_range(redis_client, pool_session_id, range_header)

    _register_stats_client(
        redis_client,
        virtual_channel_id,
        client_id,
        client_ip,
        user_agent,
        user,
        channel_display_name=channel_display_name,
        timestamp_utc=timestamp_utc,
        primary_url=last_url,
        channel_logo_id=channel_logo_id,
        m3u_profile_id=m3u_profile_id,
    )

    peek_data = getattr(upstream, "_peek_data", None)
    chunks_iter = upstream.iter_content(chunk_size=chunk_size)
    if peek_data:
        chunks_iter = itertools.chain([peek_data], chunks_iter)

    session_closed = {"done": False}

    def _finish_session(*, close_upstream=False):
        if session_closed["done"]:
            return
        session_closed["done"] = True
        if close_upstream:
            try:
                upstream.close()
            except Exception:
                pass
        _unregister_stats_client(redis_client, virtual_channel_id, client_id)
        release_cb()

    def stream_generator():
        last_heartbeat = time.time()
        bytes_since_heartbeat = 0
        total_yielded = 0
        loop_start = time.time()
        stop_key = RedisKeys.client_stop(virtual_channel_id, client_id)
        stream_started_logged = False
        try:
            for data in chunks_iter:
                if not data:
                    continue
                if debug and not stream_started_logged:
                    stream_started_logged = True
                    logger.debug(
                        "Timeshift stream started: client=%s vid=%s range=%s status=%d",
                        client_id, virtual_channel_id, range_header or "(none)", status,
                    )
                yield data
                bytes_since_heartbeat += len(data)
                total_yielded += len(data)

                now = time.time()
                if redis_client and redis_client.exists(stop_key):
                    logger.info("Timeshift client %s received stop signal", client_id)
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
                        redis_client, virtual_channel_id, client_id,
                        bytes_delta=bytes_since_heartbeat,
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
                    redis_client, virtual_channel_id, client_id,
                    bytes_delta=bytes_since_heartbeat,
                )
            if debug and total_yielded > 0:
                mbps = (total_yielded * 8) / elapsed / 1_000_000 if elapsed > 0 else 0
                logger.debug(
                    "Timeshift disconnect: vid=%s client=%s yielded=%d bytes in %.1fs (%.2f Mbps avg)",
                    virtual_channel_id, client_id, total_yielded, elapsed, mbps,
                )
            _finish_session(close_upstream=True)

    stream_iter = _SlotReleasingStream(stream_generator(), _finish_session)
    response = StreamingHttpResponse(
        stream_iter,
        content_type=content_type,
        status=status,
    )
    response["X-Accel-Buffering"] = "no"  # avoid nginx throttling the stream
    if content_range:
        response["Content-Range"] = content_range
    response["Accept-Ranges"] = "bytes"
    return response


def _redact_url(url):
    """Truncate *url* to ``scheme://host/...`` for safe logging (drops credentials)."""
    if not url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/..."
