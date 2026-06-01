"""XC catch-up (timeshift) HTTP view — proxies the provider's
`/streaming/timeshift.php` endpoint to clients like iPlayTV and TiviMate.

URL parameter quirk matching what iPlayTV / TiviMate emit:
    Position "stream_id"  -> EPG channel number, IGNORED here.
    Position "duration"   -> Dispatcharr's Channel.id (the XC API emits
                              channel.id as stream_id to clients).
"""

import hmac
import itertools
import logging
import time
import uuid

import requests
from django.core.cache import cache
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    StreamingHttpResponse,
)

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.channels.utils import get_channel_catchup_info
from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.utils import get_client_ip
from apps.proxy.live_proxy.input.http_streamer import find_ts_sync
from apps.proxy.utils import check_user_stream_limits
from core.models import CoreSettings
from core.utils import RedisClient

from .helpers import (
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    format_timestamp_as_sql_datetime,
    format_timestamp_as_underscore,
    get_programme_duration,
)

logger = logging.getLogger(__name__)

CLIENT_TTL_SECONDS = 60


def timeshift_proxy(request, username, password, stream_id, timestamp, duration):  # noqa: ARG001 stream_id
    # The "duration" URL slot carries Dispatcharr's internal Channel.id — the
    # XC API emits channel.id as the stream_id to clients, never the provider's
    # stream_id.  Resolve by Channel.id; 404 if it doesn't exist.
    raw_id = duration[:-3] if duration.endswith(".ts") else duration

    user = _authenticate_user(username, password)
    if user is None:
        return HttpResponseForbidden("Invalid credentials")

    try:
        channel = Channel.objects.get(id=int(raw_id))
    except (Channel.DoesNotExist, ValueError, TypeError):
        raise Http404("Channel not found") from None

    if not _user_can_access_channel(user, channel):
        return HttpResponseForbidden("Access denied")

    catchup = get_channel_catchup_info(channel)
    if catchup is None:
        return HttpResponseBadRequest("Timeshift not supported for this channel")

    catchup_stream = catchup["stream"]
    props = catchup["props"]
    m3u_account = catchup_stream.m3u_account
    if m3u_account is None or m3u_account.account_type != "XC":
        return HttpResponseBadRequest("Channel not from Xtream Codes provider")

    timeshift_settings = CoreSettings.get_timeshift_settings()
    debug = bool(timeshift_settings.get("debug_logging", False))

    # The client-supplied timestamp is already in UTC (derived from the
    # start_timestamp epoch in the EPG data). Pass it through to the
    # provider as-is — no timezone conversion. Converting here was the
    # root cause of the "wrong programme plays" bug: the provider indexes
    # archives in UTC, so shifting to Brussels meant requesting a programme
    # 1-2 hours later than intended.
    # Learned from plugin history v1.1.4 → v1.2.6: 6 iterations of timezone
    # bugs all converged on "never convert the provider URL timestamp".
    underscore_timestamp = format_timestamp_as_underscore(timestamp)
    sql_timestamp = format_timestamp_as_sql_datetime(timestamp)
    duration_minutes = get_programme_duration(channel, timestamp)
    stream_id_value = (props or {}).get("stream_id")
    if stream_id_value is None:
        return HttpResponseBadRequest("Cannot build timeshift URL")

    # Build a prioritised set of upstream candidates. Different XC servers (or
    # even different code paths inside the same server) accept different
    # timestamp shapes and URL layouts:
    #
    # • Underscore (YYYY-MM-DD_HH-MM): canonical format for many XC
    #   providers. Works for ALL archives — recent and old. Tried first.
    # • Colon-dash (YYYY-MM-DD:HH-MM): legacy shape used by older servers /
    #   the lenient parser. Resolves only finalised archives (> ~5–6 h old).
    # • SQL-datetime (YYYY-MM-DD HH:MM:SS): alternative modern shape accepted
    #   by some servers' strict parser for recently-indexed archives.
    # • Format B (path layout): the only shape some Stalker-style portals expose.
    #
    # We try them in order until one returns a 2xx — see `_stream_from_provider`.
    candidate_urls = [
        build_timeshift_url_format_a(m3u_account, stream_id_value, underscore_timestamp, duration_minutes),
        build_timeshift_url_format_b(m3u_account, stream_id_value, underscore_timestamp, duration_minutes),
        build_timeshift_url_format_a(m3u_account, stream_id_value, sql_timestamp, duration_minutes),
        build_timeshift_url_format_a(m3u_account, stream_id_value, timestamp, duration_minutes),
        build_timeshift_url_format_b(m3u_account, stream_id_value, timestamp, duration_minutes),
    ]

    try:
        user_agent = m3u_account.get_user_agent().user_agent
    except AttributeError:
        user_agent = ""

    safe_ts = timestamp.replace(":", "-").replace("/", "-")
    virtual_channel_id = f"timeshift_{channel.id}_{safe_ts}_{stream_id_value}"
    client_id = f"timeshift_{uuid.uuid4().hex[:16]}"
    client_ip = get_client_ip(request)
    range_header = request.META.get("HTTP_RANGE")

    # Resolve channel logo + M3U default profile so the Stats card can render
    # the same logo + M3U profile name as for live streams.
    channel_logo_id = getattr(channel, "logo_id", None)
    default_profile = m3u_account.profiles.filter(is_default=True).first()
    m3u_profile_id = default_profile.id if default_profile is not None else None

    # Free the provider slot before connecting upstream.
    # 1. Enforce user stream limits — this terminates the oldest active stream
    #    (live, timeshift, or VOD) via the Redis stop-key mechanism, same as
    #    the live and VOD proxy entry points.
    if not check_user_stream_limits(user, client_id, media_id=virtual_channel_id):
        return HttpResponseForbidden("Stream limit exceeded")

    # Note: no explicit ChannelService.stop_channel() here.  The
    # check_user_stream_limits() call above already terminates the oldest
    # active stream (live, timeshift, or VOD) via the Redis stop-key
    # mechanism — same pattern as the live and VOD proxy entry points.
    # Calling stop_channel() unconditionally would kill other users' live
    # streams on the same channel.

    if debug:
        logger.info(
            "Timeshift request: channel=%s ts=%s provider_sid=%s vid=%s client=%s range=%s",
            channel.name,
            timestamp,
            stream_id_value,
            virtual_channel_id,
            client_id,
            range_header or "(none)",
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
        m3u_profile_id=m3u_profile_id,
        debug=debug,
        account_id=m3u_account.id,
    )


# ---------------------------------------------------------------------------
# Authentication, lookup, access control
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Stats integration (direct Redis writes, no ClientManager instance)
# ---------------------------------------------------------------------------


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
    """Write the same Redis keys the live proxy's ClientManager writes so the
    catch-up viewer appears on `/stats`. `is_timeshift=1` toggles the badge."""
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


# ---------------------------------------------------------------------------
# Provider streaming
# ---------------------------------------------------------------------------


def _open_upstream(url, user_agent, range_header):
    """Open the upstream HTTP request (status + headers known synchronously)."""
    headers = {}
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
    """Return the index of the URL shape that last worked for this account,
    or None if we haven't seen one succeed yet.

    Uses ``django.core.cache`` (Redis-backed) so every uWSGI worker shares
    the same format discovery — the first worker that finds the winning URL
    shape caches it for all others.
    """
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
):
    # Use 256 KB chunks: amortises per-yield uWSGI/gevent overhead.
    chunk_size = max(ConfigHelper.chunk_size(), 262144)

    # Reorder the candidates so the cached winning shape is tried first.
    # The cache is per-account; within a single fast-forward session every
    # seek lands in the same archive entry and therefore the same parser
    # path, so the first attempt almost always succeeds.
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

    # Try each candidate URL until one returns a streamable MPEG-TS response.
    # Some XC servers return HTTP 200 with PHP error text instead of 404 when
    # the timestamp format doesn't match their parser.  We peek at the first
    # bytes to confirm TS sync before accepting the response.
    upstream = None
    last_status = None
    last_url = ordered_urls[0]
    winning_index = None
    for url, orig_idx in zip(ordered_urls, original_indices):
        try:
            response = _open_upstream(url, user_agent, range_header)
        except requests.exceptions.RequestException as exc:
            logger.error("Timeshift provider unreachable: %s", exc)
            return HttpResponseBadRequest("Provider connection error")
        last_status = response.status_code
        last_url = url
        if debug:
            logger.info(
                "Timeshift cascade[%d]: status=%d type=%s url=%s",
                orig_idx, response.status_code,
                response.headers.get("Content-Type", "?"),
                _redact_url(url),
            )
        if response.status_code in (200, 206):
            # Peek at the first bytes to confirm we're getting MPEG-TS, not
            # a PHP error page disguised as 200.  Read up to 1 KB — enough
            # to find a TS sync chain or detect HTML/PHP text.
            peek = response.raw.read(1024)
            sync_offset = find_ts_sync(peek) if peek else -1
            if sync_offset >= 0:
                # Valid TS — strip any pre-sync garbage (PHP warnings, BOM)
                # and prepend the clean bytes into the iter_content chain.
                response._peek_data = peek[sync_offset:]
                upstream = response
                winning_index = orig_idx
                break
            else:
                # No TS sync found — likely a PHP error.  Log and try next.
                snippet = peek[:200].decode("utf-8", errors="replace") if peek else "(empty)"
                logger.warning(
                    "Timeshift upstream returned 200 but no TS sync in first %d "
                    "bytes (likely PHP error): %s — url=%s",
                    len(peek) if peek else 0,
                    snippet.replace("\n", " ")[:120],
                    _redact_url(url),
                )
                response.close()
                last_status = 404  # Treat as soft rejection for cascade
                continue
        response.close()
        if response.status_code not in (400, 404):
            # Decisive failure (403, 5xx, …) — no point trying alternative URLs.
            break

    if winning_index is not None:
        _set_cached_format_index(account_id, winning_index)

    if upstream is None:
        logger.error("Timeshift upstream rejected: status=%s url=%s",
                     last_status, _redact_url(last_url))
        # Mirror semantically meaningful upstream statuses so clients react
        # correctly: 404 stops retry loops (catch-up not yet indexed), 403
        # surfaces auth problems. Everything else stays a generic 400.
        if last_status == 404:
            return HttpResponseNotFound("Catch-up not available yet")
        if last_status == 403:
            return HttpResponseForbidden("Provider denied access")
        return HttpResponseBadRequest("Provider error")

    content_type = upstream.headers.get("Content-Type", "video/mp2t")
    content_range = upstream.headers.get("Content-Range", "")
    status = upstream.status_code

    redis_client = RedisClient.get_client()
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

    # Stream directly via iter_content+yield (same pattern as VOD proxy).
    # The peek already validated TS sync and stripped any preamble.
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
        # Same stop-key pattern as live (generator.py:395) and VOD
        # (multi_worker_connection_manager.py:1095).
        stop_key = RedisKeys.client_stop(virtual_channel_id, client_id)
        try:
            for data in chunks_iter:
                if not data:
                    continue
                yield data
                bytes_since_heartbeat += len(data)
                total_yielded += len(data)
                chunk_count += 1

                # Check stop signal every 100 chunks (mirrors VOD pattern)
                if chunk_count % 100 == 0:
                    if redis_client and redis_client.exists(stop_key):
                        logger.info("Timeshift client %s received stop signal", client_id)
                        redis_client.delete(stop_key)
                        break

                now = time.time()
                if now - last_heartbeat >= 5:
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
                logger.info(
                    "Timeshift disconnect: vid=%s client=%s yielded=%d bytes in %.1fs (%.2f Mbps avg)",
                    virtual_channel_id, client_id, total_yielded, elapsed, mbps,
                )
            try:
                upstream.close()
            except Exception:
                pass
            _unregister_stats_client(redis_client, virtual_channel_id, client_id)

    response = StreamingHttpResponse(
        stream_generator(),
        content_type=content_type,
        status=status,
    )
    # Tell nginx not to buffer this streaming response. Without this, the
    # default uwsgi_buffering=on under `location /` throttles the response
    # roughly to half the upstream rate (back-pressure from buffer flushes
    # propagates back into the generator).
    response["X-Accel-Buffering"] = "no"
    # Forward Content-Range so iPlayTV / TiviMate seek cursor stays correct.
    # Content-Length is NOT forwarded: Django's StreamingHttpResponse uses
    # chunked transfer encoding, which is incompatible with Content-Length.
    # Sending both causes clients to wait for the full file instead of
    # playing progressively.
    if content_range:
        response["Content-Range"] = content_range
    response["Accept-Ranges"] = "bytes"
    return response


def _redact_url(url):
    """Strip credentials from a URL for safe logging.

    Handles both ``user:pass@host`` and XC path-based credentials
    (``/username/password/...``) by truncating to ``scheme://host/...``.
    Query-string parameters are always stripped.
    """
    if not url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/..."
