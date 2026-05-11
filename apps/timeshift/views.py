"""XC catch-up (timeshift) HTTP view.

Routes /timeshift/{user}/{pass}/{stream_id}/{timestamp}/{duration} → upstream
provider. The view opens an HTTP request to the provider's catch-up endpoint,
checks the status, and pipes the bytes back to the client via a dedicated
producer thread + `os.pipe` (the same pattern used by ts_proxy's live path
in `apps.proxy.ts_proxy.http_streamer.HTTPStreamReader`).

The producer-thread decoupling matters because uWSGI runs each request inside
a gevent greenlet — without a dedicated thread reading the upstream socket,
every `iter_content` recv yields to the gevent hub and competes with other
greenlets, dropping throughput below the FHD video bitrate.

Range / Content-Range / 206 handling: the request to the upstream forwards
the client's Range header (if any); the upstream's response status + headers
are propagated to the client's response so iPlayTV / TiviMate can seek.

Stats integration: the view writes the same Redis keys that ts_proxy's
`ClientManager` writes, so the catch-up viewer appears on `/stats` with the
violet `TIMESHIFT` badge. The `OWNER` is set to a constant `timeshift_*` form
so `ProxyServer._check_orphaned_metadata` can skip it.

URL parameter quirk preserved from the legacy plugin contract:
    Position "stream_id"  -> EPG channel number, IGNORED here.
    Position "duration"   -> actually the provider's stream_id.
This matches the URLs that the existing iPlayTV / TiviMate clients already
send and avoids a breaking change for downstream users.
"""

import fcntl
import hmac
import logging
import os
import threading
import time
import uuid

import redis
import requests
from django.conf import settings
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    StreamingHttpResponse,
)

from apps.accounts.models import User
from apps.channels.utils import (
    get_channel_catchup_info,
    resolve_channel_by_provider_stream_id,
)
from apps.proxy.ts_proxy.config_helper import ConfigHelper
from apps.proxy.ts_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.ts_proxy.redis_keys import RedisKeys
from apps.proxy.ts_proxy.utils import get_client_ip
from core.models import CoreSettings

from .helpers import (
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    convert_timestamp_to_local,
    get_programme_duration,
)

logger = logging.getLogger(__name__)

CLIENT_TTL_SECONDS = 60
ADMIN_LEVEL = 10


def timeshift_proxy(request, username, password, stream_id, timestamp, duration):
    # The "duration" URL slot is the provider's stream_id — see module docstring.
    provider_stream_id = duration[:-3] if duration.endswith(".ts") else duration

    user = _authenticate_user(username, password)
    if user is None:
        return HttpResponseForbidden("Invalid credentials")

    channel, _source_stream = resolve_channel_by_provider_stream_id(provider_stream_id)
    if channel is None:
        raise Http404("Channel not found")

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
    timezone_str = timeshift_settings.get("default_timezone", "UTC")
    debug = bool(timeshift_settings.get("debug_logging", False))

    local_timestamp = convert_timestamp_to_local(timestamp, timezone_str)
    duration_minutes = get_programme_duration(channel, local_timestamp)
    stream_id_value = (props or {}).get("stream_id")
    if stream_id_value is None:
        return HttpResponseBadRequest("Cannot build timeshift URL")
    primary_url = build_timeshift_url_format_a(m3u_account, stream_id_value, local_timestamp, duration_minutes)
    fallback_url = build_timeshift_url_format_b(m3u_account, stream_id_value, local_timestamp, duration_minutes)

    try:
        user_agent = m3u_account.get_user_agent().user_agent
    except AttributeError:
        user_agent = ""

    virtual_channel_id = _make_virtual_channel_id(channel.id, timestamp, provider_stream_id)
    client_id = f"timeshift_{uuid.uuid4().hex[:16]}"
    client_ip = get_client_ip(request)
    range_header = request.META.get("HTTP_RANGE")

    # Resolve channel logo + M3U default profile so the Stats card can render
    # the same logo + M3U profile name as for live streams.
    channel_logo_id = getattr(channel, "logo_id", None)
    default_profile = m3u_account.profiles.filter(is_default=True).first()
    m3u_profile_id = default_profile.id if default_profile is not None else None

    if debug:
        logger.info(
            "Timeshift request: channel=%s ts=%s provider_sid=%s vid=%s client=%s range=%s",
            channel.name,
            local_timestamp,
            provider_stream_id,
            virtual_channel_id,
            client_id,
            range_header or "(none)",
        )

    return _stream_from_provider(
        primary_url=primary_url,
        fallback_url=fallback_url,
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
    if user.user_level >= ADMIN_LEVEL:
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


def _make_virtual_channel_id(channel_id, timestamp, provider_stream_id):
    safe_ts = timestamp.replace(":", "-").replace("/", "-")
    return f"timeshift_{channel_id}_{safe_ts}_{provider_stream_id}"


def _get_redis_client():
    redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    ssl_params = getattr(settings, "REDIS_SSL_PARAMS", {}) or {}
    return redis.Redis.from_url(redis_url, decode_responses=True, **ssl_params)


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
    """Write the Redis keys that ts_proxy's status endpoint reads.

    The HTTP /proxy/ts/status endpoint scans `ts_proxy:channel:*:metadata` and
    drops entries for which `get_basic_channel_info()` returns None — which it
    does whenever the metadata hash is missing. So we MUST write a minimal
    metadata hash with the same TTL as the clients keys. The hash also carries
    `is_timeshift=1` so the front-end can render a distinct badge.
    """
    if redis_client is None:
        return
    client_set_key = RedisKeys.clients(virtual_channel_id)
    client_key = f"ts_proxy:channel:{virtual_channel_id}:clients:{client_id}"
    metadata_key = RedisKeys.channel_metadata(virtual_channel_id)
    now = str(time.time())
    client_payload = {
        "user_agent": user_agent or "unknown",
        "ip_address": client_ip,
        "connected_at": now,
        "last_active": now,
        "worker_id": "timeshift",
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
        redis_client.hset(client_key, mapping=client_payload)
        redis_client.expire(client_key, CLIENT_TTL_SECONDS)
        redis_client.sadd(client_set_key, client_id)
        redis_client.expire(client_set_key, CLIENT_TTL_SECONDS)
        redis_client.hset(metadata_key, mapping=metadata_payload)
        redis_client.expire(metadata_key, CLIENT_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Timeshift stats register failed: %s", exc)


def _heartbeat_stats_client(redis_client, virtual_channel_id, client_id, bytes_delta=0):
    if redis_client is None:
        return
    client_set_key = RedisKeys.clients(virtual_channel_id)
    client_key = f"ts_proxy:channel:{virtual_channel_id}:clients:{client_id}"
    metadata_key = RedisKeys.channel_metadata(virtual_channel_id)
    try:
        redis_client.hset(client_key, "last_active", str(time.time()))
        redis_client.expire(client_key, CLIENT_TTL_SECONDS)
        redis_client.expire(client_set_key, CLIENT_TTL_SECONDS)
        if bytes_delta > 0:
            redis_client.hincrby(metadata_key, ChannelMetadataField.TOTAL_BYTES, bytes_delta)
        redis_client.expire(metadata_key, CLIENT_TTL_SECONDS)
    except Exception:
        pass


def _unregister_stats_client(redis_client, virtual_channel_id, client_id):
    if redis_client is None:
        return
    client_set_key = RedisKeys.clients(virtual_channel_id)
    client_key = f"ts_proxy:channel:{virtual_channel_id}:clients:{client_id}"
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


F_SETPIPE_SZ = 1031  # fcntl op code, not exposed by the stdlib

# How much read-ahead the producer thread can buffer in the kernel pipe before
# blocking on write. 1 MB is the typical Linux default pipe-max-size cap.
PRODUCER_PIPE_BUFFER_BYTES = 1 << 20


class _UpstreamPipe:
    """Run an upstream `requests.iter_content` in a real OS thread, write the
    bytes to an `os.pipe`. The WSGI generator reads from the pipe.

    Mirrors the pattern used by ``apps.proxy.ts_proxy.http_streamer.HTTPStreamReader``
    for live streams. The producer thread decouples the socket read from the
    WSGI yield: while the WSGI greenlet is blocked sending a chunk to uWSGI,
    the producer keeps draining the upstream socket so the provider does not
    back-pressure.
    """

    def __init__(self, response, chunk_size):
        self.response = response
        self.chunk_size = chunk_size
        self._stop = threading.Event()
        self._thread = None
        self.pipe_read_fd = None
        self._pipe_write_fd = None

    def start(self):
        self.pipe_read_fd, self._pipe_write_fd = os.pipe()
        try:
            fcntl.fcntl(self._pipe_write_fd, F_SETPIPE_SZ, PRODUCER_PIPE_BUFFER_BYTES)
        except OSError:
            pass
        self._thread = threading.Thread(target=self._produce, daemon=True)
        self._thread.start()
        return self.pipe_read_fd

    def stop(self):
        self._stop.set()
        try:
            self.response.close()
        except Exception:
            pass
        try:
            if self._pipe_write_fd is not None:
                os.close(self._pipe_write_fd)
                self._pipe_write_fd = None
        except OSError:
            pass

    def _produce(self):
        try:
            for chunk in self.response.iter_content(chunk_size=self.chunk_size):
                if self._stop.is_set():
                    break
                if not chunk:
                    continue
                view = memoryview(chunk)
                while view:
                    try:
                        written = os.write(self._pipe_write_fd, view)
                    except (BrokenPipeError, OSError):
                        return
                    view = view[written:]
        except requests.exceptions.RequestException:
            pass
        except Exception:
            logger.exception("Timeshift upstream producer failed")
        finally:
            try:
                self.response.close()
            except Exception:
                pass
            if self._pipe_write_fd is not None:
                try:
                    os.close(self._pipe_write_fd)
                except OSError:
                    pass
                self._pipe_write_fd = None


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


def _stream_from_provider(
    *,
    primary_url,
    fallback_url,
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
):
    # Use 64 KB chunks: amortises per-yield gevent hub overhead across more
    # bytes than the live-path 8 KB baseline.
    chunk_size = max(ConfigHelper.chunk_size(), 65536)

    try:
        upstream = _open_upstream(primary_url, user_agent, range_header)
    except requests.exceptions.RequestException as exc:
        logger.error("Timeshift provider unreachable: %s", exc)
        return HttpResponseBadRequest("Provider connection error")

    if upstream.status_code == 400 and fallback_url:
        upstream.close()
        try:
            upstream = _open_upstream(fallback_url, user_agent, range_header)
        except requests.exceptions.RequestException as exc:
            logger.error("Timeshift fallback provider unreachable: %s", exc)
            return HttpResponseBadRequest("Provider connection error")

    if upstream.status_code not in (200, 206):
        upstream.close()
        logger.error("Timeshift upstream rejected: status=%s url=%s",
                     upstream.status_code, _redact_url(primary_url))
        return HttpResponseBadRequest(f"Provider error: {upstream.status_code}")

    content_type = upstream.headers.get("Content-Type", "video/mp2t")
    content_range = upstream.headers.get("Content-Range", "")
    status = upstream.status_code

    redis_client = _get_redis_client()
    _register_stats_client(
        redis_client,
        virtual_channel_id,
        client_id,
        client_ip,
        user_agent,
        user,
        channel_display_name=channel_display_name,
        timestamp_utc=timestamp_utc,
        primary_url=primary_url,
        channel_logo_id=channel_logo_id,
        m3u_profile_id=m3u_profile_id,
    )

    pipe = _UpstreamPipe(upstream, chunk_size)
    pipe_read_fd = pipe.start()
    pipe_reader = os.fdopen(pipe_read_fd, "rb", buffering=0)

    def stream_generator():
        last_heartbeat = time.time()
        bytes_since_heartbeat = 0
        total_yielded = 0
        loop_start = time.time()
        try:
            while True:
                data = pipe_reader.read(chunk_size)
                if not data:
                    break
                yield data
                bytes_since_heartbeat += len(data)
                total_yielded += len(data)

                now = time.time()
                if now - last_heartbeat >= 5:
                    interval = now - last_heartbeat
                    mbps = (bytes_since_heartbeat * 8) / interval / 1_000_000 if interval > 0 else 0
                    if debug:
                        logger.info(
                            "Timeshift heartbeat: vid=%s client=%s bytes=%d throughput=%.2fMbps",
                            virtual_channel_id, client_id, bytes_since_heartbeat, mbps,
                        )
                    _heartbeat_stats_client(
                        redis_client,
                        virtual_channel_id,
                        client_id,
                        bytes_delta=bytes_since_heartbeat,
                    )
                    last_heartbeat = now
                    bytes_since_heartbeat = 0
        except GeneratorExit:
            if debug:
                logger.info(
                    "Timeshift disconnect: vid=%s client=%s yielded=%d bytes in %.1fs",
                    virtual_channel_id, client_id, total_yielded, time.time() - loop_start,
                )
        except Exception:
            logger.exception("Timeshift stream loop error")
        finally:
            pipe.stop()
            try:
                pipe_reader.close()
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
    # Content-Length is intentionally NOT forwarded: chunked transfer is the
    # safer interchange format for long-lived streaming.
    if content_range:
        response["Content-Range"] = content_range
    response["Accept-Ranges"] = "bytes"
    return response


def _redact_url(url):
    """Strip credentials from a URL for safe logging."""
    if not url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    return f"{scheme}://{rest.split('?')[0]}/..."
