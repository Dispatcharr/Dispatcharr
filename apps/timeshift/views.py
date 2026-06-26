"""XC catch-up (timeshift) proxy with multi-provider failover."""

import hmac
import itertools
import logging
import time
import uuid

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
    client_id = f"timeshift_{uuid.uuid4().hex[:16]}"
    client_ip = get_client_ip(request)
    range_header = request.META.get("HTTP_RANGE")
    channel_logo_id = getattr(channel, "logo_id", None)

    redis_client = RedisClient.get_client()

    # Displace any prior catch-up session on this channel before reserving a slot.
    _terminate_previous_timeshift_sessions(redis_client, user, channel.id)

    if not check_user_stream_limits(
        user, client_id, media_id=f"timeshift_{channel.id}_{safe_ts}"
    ):
        return HttpResponseForbidden("Stream limit exceeded")

    last_response = None
    decisive_accounts = set()
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

        token_stored = False
        if redis_client is not None:
            token_stored = _store_slot_token(
                redis_client, client_id, reserved_profile.id
            )
            if not token_stored:
                # Release immediately if we cannot record ownership for later cleanup.
                try:
                    release_profile_slot(reserved_profile.id, redis_client)
                except Exception as exc:
                    logger.error(
                        "Timeshift: could not release slot for profile %s "
                        "after token-store failure: %s", reserved_profile.id, exc,
                    )
                capacity_blocked = True
                continue

        try:
            # Failures before streaming starts must release the reserved slot.
            # Use credentials for the profile whose slot was reserved.
            server_url, xc_username, xc_password = get_transformed_credentials(
                m3u_account, reserved_profile
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
                    m3u_account.id, reserved_profile.id, stream_id_value,
                    virtual_channel_id, client_id, range_header or "(none)",
                )

            response = _stream_from_provider(
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
                m3u_profile_id=reserved_profile.id,
                debug=debug,
                account_id=m3u_account.id,
                redis_client=redis_client,
            )
        except Exception:
            if token_stored:
                _release_slot_token(redis_client, client_id)
            raise
        if response.status_code < 400:
            return response

        _release_slot_token(redis_client, client_id)
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


# One-shot Redis token: whichever release path runs first frees the pool slot.
_SLOT_TOKEN_KEY = "timeshift_slot:{client_id}"
_SLOT_TOKEN_TTL = 24 * 3600


def _store_slot_token(redis_client, client_id, profile_id):
    """Store a one-shot Redis token mapping *client_id* to *profile_id*.

    Returns False if the token could not be written; the caller must release
    the reserved slot directly in that case.
    """
    if redis_client is None:
        return False
    try:
        redis_client.setex(
            _SLOT_TOKEN_KEY.format(client_id=client_id),
            _SLOT_TOKEN_TTL,
            str(profile_id),
        )
        return True
    except Exception as exc:
        logger.warning("Timeshift slot token store failed for %s: %s", client_id, exc)
        return False


def _release_slot_token(redis_client, client_id):
    """Release the profile slot owned by *client_id* (at most once via GET+DEL)."""
    if redis_client is None:
        return False
    key = _SLOT_TOKEN_KEY.format(client_id=client_id)
    try:
        pipe = redis_client.pipeline(transaction=True)
        pipe.get(key)
        pipe.delete(key)
        token_value, deleted = pipe.execute()
        if not token_value or not deleted:
            return False
        release_profile_slot(int(token_value), redis_client)
        return True
    except Exception as exc:
        logger.warning("Timeshift slot release failed for %s: %s", client_id, exc)
        return False


def _terminate_previous_timeshift_sessions(redis_client, user, channel_id):
    """Displace the user's prior catch-up session(s) on this channel.

    Releases the provider slot, unregisters stats keys, and sets the live
    stop key so the old generator exits on its next heartbeat.
    """
    if redis_client is None or user is None:
        return
    prefix = f"timeshift_{channel_id}_"
    try:
        for conn in get_user_active_connections(user.id):
            if conn.get("type") != "timeshift":
                continue
            media_id = str(conn.get("media_id") or "")
            if not media_id.startswith(prefix):
                continue
            old_client_id = conn.get("client_id")
            logger.info(
                "Timeshift takeover: displacing session %s on %s",
                old_client_id, media_id,
            )
            _release_slot_token(redis_client, old_client_id)
            _unregister_stats_client(redis_client, media_id, old_client_id)
            stop_key = RedisKeys.client_stop(media_id, old_client_id)
            redis_client.setex(stop_key, 60, "true")
    except Exception as exc:
        logger.warning("Timeshift takeover check failed: %s", exc)


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
):
    """Try each upstream URL until one returns streamable MPEG-TS.

    Sets ``timeshift_decisive`` on auth/ban-class failures (401/403/406) so the
    failover loop skips the rest of that account's streams.
    """
    chunk_size = max(ConfigHelper.chunk_size(), 262144)

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
        if response.status_code in (200, 206):
            peek = response.raw.read(1024)
            sync_offset = find_ts_sync(peek) if peek else -1
            if sync_offset >= 0:
                response._peek_data = peek[sync_offset:]
                upstream = response
                winning_index = orig_idx
                break
            else:
                snippet = peek[:200].decode("utf-8", errors="replace") if peek else "(empty)"
                logger.warning(
                    "Timeshift upstream returned 200 but no TS sync in first %d "
                    "bytes (likely PHP error): %s, url=%s",
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

    def stream_generator():
        last_heartbeat = time.time()
        bytes_since_heartbeat = 0
        total_yielded = 0
        chunk_count = 0
        loop_start = time.time()
        stop_key = RedisKeys.client_stop(virtual_channel_id, client_id)
        try:
            for data in chunks_iter:
                if not data:
                    continue
                yield data
                bytes_since_heartbeat += len(data)
                total_yielded += len(data)
                chunk_count += 1

                now = time.time()
                # Poll stop key and refresh stats every 5 seconds.
                if now - last_heartbeat >= 5:
                    if redis_client and redis_client.exists(stop_key):
                        logger.info("Timeshift client %s received stop signal", client_id)
                        redis_client.delete(stop_key)
                        break
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
            try:
                upstream.close()
            except Exception:
                pass
            _unregister_stats_client(redis_client, virtual_channel_id, client_id)
            _release_slot_token(redis_client, client_id)

    def _close_session():
        _unregister_stats_client(redis_client, virtual_channel_id, client_id)
        _release_slot_token(redis_client, client_id)

    stream_iter = _SlotReleasingStream(stream_generator(), _close_session)
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
