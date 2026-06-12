"""XC catch-up (timeshift) HTTP view — proxies the provider's catch-up
archive (PATH `/timeshift/.../{id}.ts` form first, `/streaming/timeshift.php`
query form as fallback) to clients like iPlayTV and TiviMate, with
multi-provider failover across the channel's catch-up streams.

Provider capacity accounting follows the same contract as live and VOD: a
profile slot is reserved through ``apps.m3u.connection_pool`` before any
upstream connect and released exactly once when the session ends (one-shot
Redis token), so Dispatcharr's pool counters always match real upstream usage.
A user gets ONE active catch-up session per channel — a seek displaces the
previous one.

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
from apps.proxy.live_proxy.input.http_streamer import find_ts_sync
from apps.proxy.utils import check_user_stream_limits, get_user_active_connections
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
    # The "duration" URL slot carries Dispatcharr's internal Channel.id — the
    # XC API emits channel.id as the stream_id to clients, never the provider's
    # stream_id.  Resolve by Channel.id; 404 if it doesn't exist.
    raw_id = duration[:-3] if duration.endswith(".ts") else duration

    user = _authenticate_user(username, password)
    if user is None:
        return HttpResponseForbidden("Invalid credentials")

    # Same network-level gate as the live XC stream endpoint (stream_xc).
    if not network_access_allowed(request, "STREAMS", user):
        return HttpResponseForbidden("Access denied")

    try:
        channel = Channel.objects.get(id=int(raw_id))
    except (Channel.DoesNotExist, ValueError, TypeError):
        raise Http404("Channel not found") from None

    if not _user_can_access_channel(user, channel):
        return HttpResponseForbidden("Access denied")

    # Reject malformed timestamps up front: every shape helper falls back to
    # pass-through on parse failure, so an unvalidated value would be forwarded
    # verbatim into the upstream URL (query-injection vector + a pointless
    # provider request).
    if parse_catchup_timestamp(timestamp) is None:
        return HttpResponseBadRequest("Invalid timestamp")

    catchup_streams = get_channel_catchup_streams(channel)
    if not catchup_streams:
        return HttpResponseBadRequest("Timeshift not supported for this channel")

    # Verbose timeshift logging follows the standard logger level (set via
    # DISPATCHARR_LOG_LEVEL / the logging config), not a per-feature toggle.
    debug = logger.isEnabledFor(logging.DEBUG)

    # The client supplies the catch-up timestamp in UTC — Dispatcharr's XC API
    # surface is strictly UTC (server_info.timezone="UTC", EPG start/end in UTC),
    # and the client builds the URL from those UTC strings. The EPG duration
    # lookup therefore uses the original UTC value (programmes are stored in
    # UTC); the per-provider conversion happens inside the failover loop below.
    duration_minutes = get_programme_duration(channel, timestamp)

    safe_ts = timestamp.replace(":", "-").replace("/", "-")
    client_id = f"timeshift_{uuid.uuid4().hex[:16]}"
    client_ip = get_client_ip(request)
    range_header = request.META.get("HTTP_RANGE")
    channel_logo_id = getattr(channel, "logo_id", None)

    redis_client = RedisClient.get_client()

    # One active catch-up session per user+channel: a new request (programme
    # jump, or a seek re-request on the same programme) DISPLACES the user's
    # previous session on this channel. Its provider slot is released
    # synchronously — so the reservation below cannot collide with the dying
    # session on max_connections=1 providers — and its generator is stopped
    # via the same Redis stop-key the stream-limit path uses. Runs BEFORE the
    # stream-limit check so a seek displaces its own predecessor instead of
    # being denied when terminate_on_limit_exceeded is off.
    _terminate_previous_timeshift_sessions(redis_client, user, channel.id)

    # Enforce user stream limits once, before connecting upstream — this
    # terminates the oldest active stream (live, timeshift, or VOD) via the
    # Redis stop-key mechanism, same as the live and VOD proxy entry points.
    # (No explicit ChannelService.stop_channel(): that would kill other users'
    # live streams on the same channel. The media_id only matters for the
    # live same-channel exemption, so a channel-scoped id is enough.)
    if not check_user_stream_limits(
        user, client_id, media_id=f"timeshift_{channel.id}_{safe_ts}"
    ):
        return HttpResponseForbidden("Stream limit exceeded")

    # Failover: try each catch-up stream in channelstream order — mirroring how
    # live playback walks a channel's stream list. Every attempt carries ITS
    # OWN provider context (account, provider stream id, reported timezone,
    # user-agent, per-account format cache). Ban safety is per ACCOUNT: when an
    # account fails decisively (401/403/406 — auth or ban-class status), its
    # other catch-up streams (e.g. FHD/HD variants of the same channel) are
    # skipped too, so the cascade never hammers a banning provider; a DIFFERENT
    # account is a different host and remains safe to try.
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

        # Provider profile walk — same ordering as live's Channel.get_stream():
        # active profiles only, default first; an account without an active
        # default profile is skipped entirely, mirroring live dispatch.
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

        # Real XC providers index their archive in their OWN local zone (the
        # server_info.timezone they report on auth — stored on the default
        # profile). Convert the UTC instant to that zone for the upstream URL —
        # empirically a provider reads `17-00` as 17:00 LOCAL, not UTC, so
        # skipping this would seek 1-2h off. This is the ONLY timezone
        # conversion in the chain, and it is per-provider (account-level: all
        # profiles log into the same server, so the default profile's zone
        # applies to every profile of the walk).
        provider_tz_name = None
        _server_info = (default_profile.custom_properties or {}).get("server_info") or {}
        if isinstance(_server_info, dict):
            provider_tz_name = _server_info.get("timezone")
        provider_timestamp = convert_timestamp_to_provider_tz(timestamp, provider_tz_name)

        # Reserve a provider profile slot BEFORE connecting upstream — the
        # same accounting contract live (Channel.get_stream) and VOD follow,
        # so the Redis pool counters always match real upstream usage. Walk
        # to the next profile only on RESERVATION failure (profile_full /
        # credential_full — transient capacity, never ban-class); an upstream
        # failure instead moves to the next catch-up STREAM, because probing
        # the same server again through an alternate profile is wasteful and
        # ban-adjacent.
        reserved_profile = None
        for profile in profile_walk:
            if redis_client is None:
                # Without Redis no accounting is possible — proceed unpooled
                # rather than blocking playback (stats writes are equally
                # fail-open). Deployments always run Redis; this is a dev-only
                # path.
                reserved_profile = profile
                break
            reserved, _count, reason = reserve_profile_slot(profile, redis_client)
            if reserved:
                reserved_profile = profile
                break
            logger.info(
                "Timeshift: profile %s %s on account %s — trying next profile",
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
                # Redis hiccup right after the INCR: without a token no
                # release path could ever free this slot, so release it
                # directly NOW (race-free: the session is not yet visible to
                # the takeover scan) and report transient unavailability
                # instead of streaming unaccounted.
                try:
                    release_profile_slot(reserved_profile.id, redis_client)
                except Exception as exc:
                    logger.error(
                        "Timeshift: could not release slot for profile %s "
                        "after token-store failure: %s", reserved_profile.id, exc,
                    )
                capacity_blocked = True
                continue

        # From here until the streaming response owns the slot, ANY failure
        # must release the reservation before propagating — otherwise the
        # pool counter (which has no TTL) leaks until the next Redis flush.
        try:
            # Build the upstream URLs with the RESERVED profile's credentials,
            # resolved the same way live playback does (credential extraction
            # via the profile's URL transform). Using the raw account fields
            # for a non-default profile would consume that profile's slot
            # while authenticating with the default login — double-occupying
            # the provider connection the pool thinks is free.
            server_url, xc_username, xc_password = get_transformed_credentials(
                m3u_account, reserved_profile
            )
            creds = TimeshiftCredentials(server_url, xc_username, xc_password)

            # Ordered upstream candidates, PATH form first — see
            # build_timeshift_candidate_urls() for the full rationale (the
            # QUERY form is a last-resort fallback because some providers
            # return LIVE on it, ignoring the requested timestamp).
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
                # A False return here means someone else (a takeover) already
                # consumed the token and released the slot — nothing to do.
                _release_slot_token(redis_client, client_id)
            raise
        if response.status_code < 400:
            # The reserved slot is now owned by the streaming response: it is
            # released (exactly once, via the one-shot token) when the
            # generator finishes or the WSGI layer closes the response.
            return response

        # Failed attempt: free the slot before trying the next stream.
        _release_slot_token(redis_client, client_id)
        last_response = response
        if getattr(response, "timeshift_decisive", False):
            decisive_accounts.add(m3u_account.id)
        logger.warning(
            "Timeshift attempt failed (HTTP %d%s) on account %s for channel %s — "
            "trying next catch-up stream",
            response.status_code,
            ", decisive: skipping this account's other streams"
            if m3u_account.id in decisive_accounts else "",
            m3u_account.id, channel.name,
        )

    if last_response is not None:
        return last_response
    if capacity_blocked:
        # Every eligible stream failed on pool capacity alone (no upstream
        # attempt was made) — mirror the VOD proxy's pool-exhausted status so
        # clients back off instead of treating it as a permanent failure.
        return HttpResponse("No available stream slot", status=503)
    # Streams existed but none was usable (non-XC accounts / missing stream_id).
    return HttpResponseBadRequest("Cannot build timeshift URL")


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
# Provider pool slot ownership (one-shot release token) + session takeover
# ---------------------------------------------------------------------------

# Maps a timeshift client to the profile slot it reserved. Consumed (GET+DEL,
# atomically) by whichever release path runs first — the generator's finally,
# the response-close wrapper, a failed failover attempt, or a takeover by the
# user's next request on the same channel — so the slot is released exactly
# once even across uWSGI workers. Note the TTL does NOT recover the slot: if a
# worker dies mid-session the token eventually expires while the counter (no
# TTL) stays consumed — like the rest of the pool, the recovery for
# crash-leaked counters is the Redis flush at container start
# (scripts/wait_for_redis.py).
_SLOT_TOKEN_KEY = "timeshift_slot:{client_id}"
_SLOT_TOKEN_TTL = 24 * 3600


def _store_slot_token(redis_client, client_id, profile_id):
    """Record slot ownership; returns False when the token could not be
    written (the caller must then release the reservation itself — without a
    token no other path ever could)."""
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
    """Release the profile slot owned by *client_id*, exactly once.

    GET+DEL inside a MULTI/EXEC transaction: concurrent release attempts are
    serialized by Redis, so only the one that actually deletes a live token
    decrements the pool counters. Returns True when this call performed the
    release.
    """
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
    """Displace the user's previous catch-up session(s) on this channel.

    For each of the user's active timeshift sessions whose virtual channel id
    belongs to *channel_id*: release its provider slot NOW (synchronously —
    the dying generator's own release becomes a no-op thanks to the one-shot
    token), drop its stats keys so the stream-limit count no longer includes
    it, and set the stop key its generator polls on the 5-second heartbeat.
    The accounting is therefore correct immediately; only the old TCP socket
    closes lazily (≤ ~5 s).
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
    """Iterator wrapper whose close() always releases the reserved slot.

    Django registers ``streaming_content.close`` in the response's resource
    closers, and the WSGI layer guarantees close() runs — including when the
    client disconnects before the first chunk, in which case the generator
    never starts and its ``finally`` would never execute. The one-shot token
    makes the duplicate call from an already-finished generator a no-op.
    """

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
    """Open the upstream HTTP request (status + headers known synchronously).

    Redirects are followed on purpose: XC providers routinely 302 from the
    main host to a load-balanced streaming node carrying a session token, so
    disabling redirects would break normal catch-up. The cascade therefore
    observes the FINAL status; a ban-onset 302 that redirects somewhere
    non-streamable surfaces as a failed TS-sync peek (soft reject) or an
    error status.
    """
    # identity: the TS-sync peek reads raw bytes (response.raw), which are NOT
    # transparently decompressed — a gzip-encoded body would fail the sync check.
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
    redis_client=None,
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
    decisive_failure = False
    for url, orig_idx in zip(ordered_urls, original_indices):
        try:
            response = _open_upstream(url, user_agent, range_header)
        except requests.exceptions.RequestException as exc:
            # Log only the exception class and a redacted URL: requests
            # exceptions embed the full URL, which carries the XC credentials
            # (path segments in format B, query params in format A).
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
        # Decisive statuses where trying other URL shapes can't help and may
        # escalate an IP ban: auth failures (401/403) and IP-level block (406).
        # The 3xx case is defense-in-depth only: requests follows redirects
        # transparently (XC providers legitimately 302 to load-balanced
        # streaming nodes, so redirects MUST be followed), meaning a 3xx can
        # only surface here if that ever changes — but if one does, it is the
        # documented first sign of an IP ban and must stop the cascade.
        # A 5xx is different: it is usually format-specific — some XC servers run
        # PHP with display_errors off, so the "Undefined array key" warning that
        # another server emits as 200+text becomes a hard 500. The very next
        # candidate timestamp shape often succeeds, so keep trying instead of
        # giving up (this is why catch-up appeared broken on providers that 500).
        code = response.status_code
        if code in (401, 403, 406) or 300 <= code < 400:
            decisive_failure = True
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
            failure = HttpResponseNotFound("Catch-up not available yet")
        elif last_status == 403:
            failure = HttpResponseForbidden("Provider denied access")
        else:
            failure = HttpResponseBadRequest("Provider error")
        # Tell the failover loop whether this account failed DECISIVELY
        # (auth/ban-class status): its other catch-up streams must be skipped,
        # while a different provider remains safe to try.
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

                # Stop-signal + stats heartbeat on the same 5-second cadence.
                # Time-based (not chunk-modulo) so the provider slot is freed
                # within seconds of a stream-limit termination regardless of
                # bitrate — at 256 KB chunks a 100-chunk interval would mean
                # ~25 MB (~27 s at typical FHD rates) before noticing the stop.
                now = time.time()
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
            # Free the provider pool slot this session reserved. One-shot
            # token: a no-op if a takeover (the user's next request on this
            # channel) already released it.
            _release_slot_token(redis_client, client_id)

    # The wrapper guarantees session teardown even when the generator never
    # starts (client gone before the first chunk — its finally would then
    # never run): Django registers the iterator's close() as a resource
    # closer, which WSGI always invokes. Both calls are idempotent, so the
    # duplicate from a normally-finished generator is harmless.
    def _close_session():
        _unregister_stats_client(redis_client, virtual_channel_id, client_id)
        _release_slot_token(redis_client, client_id)

    stream_iter = _SlotReleasingStream(stream_generator(), _close_session)
    response = StreamingHttpResponse(
        stream_iter,
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
