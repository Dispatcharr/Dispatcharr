import json
import redis
import logging
import time
import os
import threading
from pathlib import Path
import re
from django.conf import settings
from redis.exceptions import ConnectionError, TimeoutError
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
import gc

_REDIS_TLS_HINT = " (TLS is enabled — verify certificate paths and that Redis is configured for TLS)"

logger = logging.getLogger(__name__)

# Import the command detector
from .command_utils import is_management_command


def dispatcharr_user_agent():
    """Return the standard Dispatcharr User-Agent string (Dispatcharr/{version})."""
    from version import __version__
    return f'Dispatcharr/{__version__}'


def dispatcharr_dvr_user_agent(recording_id):
    """Return the User-Agent string used by DVR FFmpeg clients for a recording."""
    return f'Dispatcharr-DVR/recording-{recording_id}'


def dispatcharr_http_headers(*, token=None, content_type='application/json'):
    """
    Build HTTP headers for outbound Dispatcharr requests.

    content_type=None omits Content-Type (e.g. simple GET proxies).
    token is included when authenticating with Schedules Direct.
    """
    headers = {'User-Agent': dispatcharr_user_agent()}
    if content_type:
        headers['Content-Type'] = content_type
    if token:
        headers['token'] = token
    return headers


def natural_sort_key(text):
    """
    Convert a string into a list of string and number chunks for natural sorting.
    "PPV 10" becomes ['PPV ', 10] so it sorts correctly with "PPV 2".

    This function enables natural/alphanumeric sorting where numbers within strings
    are treated as actual numbers rather than strings.

    Args:
        text (str): The text to convert for sorting

    Returns:
        list: A list of strings and integers for proper sorting

    Example:
        >>> sorted(['PPV 1', 'PPV 10', 'PPV 2'], key=natural_sort_key)
        ['PPV 1', 'PPV 2', 'PPV 10']
    """
    def convert(chunk):
        return int(chunk) if chunk.isdigit() else chunk.lower()

    return [convert(c) for c in re.split('([0-9]+)', text)]


def custom_properties_as_dict(value):
    """
    Normalize a JSONField-backed custom_properties value into a dict.

    Historical rows (TextField era and early JSONField migration) may store a
    JSON-encoded string instead of an object. API clients can also submit a
    string value because JSONField accepts any JSON type. Call this before
    reading or merging custom_properties.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            logger.warning(
                "custom_properties stored as non-JSON string; ignoring: %r",
                value[:100],
            )
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if value is None:
        return {}
    return {}


def ensure_custom_properties_dict(value):
    """
    Return a dict for read/merge/bulk-write paths. Dict values pass through
    without re-parsing. Use model ``save()`` (not this) as the canonical
    normalizer for ORM writes that go through ``save()``.
    """
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return custom_properties_as_dict(value)


class RedisClient:
    _client = None
    _buffer = None
    _pubsub_client = None

    @classmethod
    def _init_client(cls, decode_responses=True, max_retries=5, retry_interval=1):
        retry_count = 0
        while retry_count < max_retries:
            try:
                # Get connection parameters from settings or environment
                redis_host = os.environ.get("REDIS_HOST", getattr(settings, 'REDIS_HOST', 'localhost'))
                redis_port = int(os.environ.get("REDIS_PORT", getattr(settings, 'REDIS_PORT', 6379)))
                redis_db = int(os.environ.get("REDIS_DB", getattr(settings, 'REDIS_DB', 0)))
                redis_password = os.environ.get("REDIS_PASSWORD", getattr(settings, 'REDIS_PASSWORD', ''))
                redis_user = os.environ.get("REDIS_USER", getattr(settings, 'REDIS_USER', ''))
                redis_url = getattr(settings, "REDIS_URL", "")

                # Use standardized settings
                socket_timeout = getattr(settings, 'REDIS_SOCKET_TIMEOUT', 5)
                socket_connect_timeout = getattr(settings, 'REDIS_SOCKET_CONNECT_TIMEOUT', 5)
                health_check_interval = getattr(settings, 'REDIS_HEALTH_CHECK_INTERVAL', 30)
                socket_keepalive = getattr(settings, 'REDIS_SOCKET_KEEPALIVE', True)
                retry_on_timeout = getattr(settings, 'REDIS_RETRY_ON_TIMEOUT', True)

                # TLS params from settings (empty dict when TLS is disabled)
                ssl_params = getattr(settings, 'REDIS_SSL_PARAMS', {})

                # Create Redis client with better defaults
                client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password if redis_password else None,
                    username=redis_user if redis_user else None,
                    socket_timeout=socket_timeout,
                    socket_connect_timeout=socket_connect_timeout,
                    socket_keepalive=socket_keepalive,
                    health_check_interval=health_check_interval,
                    retry_on_timeout=retry_on_timeout,
                    decode_responses=decode_responses,
                    **ssl_params
                ) if not redis_url else redis.Redis.from_url(
                    redis_url,
                    socket_timeout=socket_timeout,
                    socket_connect_timeout=socket_connect_timeout,
                    socket_keepalive=socket_keepalive,
                    health_check_interval=health_check_interval,
                    retry_on_timeout=retry_on_timeout,
                    decode_responses=decode_responses,
                    **ssl_params
                )

                # Validate connection with ping
                client.ping()

                # Disable persistence on first connection - improves performance
                # Only try to disable if not in a read-only environment
                try:
                    client.config_set('save', '')  # Disable RDB snapshots
                    client.config_set('appendonly', 'no')  # Disable AOF logging

                    # Disable protected mode when in debug mode
                    if os.environ.get('DISPATCHARR_DEBUG', '').lower() == 'true':
                        client.config_set('protected-mode', 'no')  # Disable protected mode in debug
                        logger.warning("Redis protected mode disabled for debug environment")

                    logger.trace("Redis persistence disabled for better performance")
                except redis.exceptions.ResponseError as e:
                    # Improve error handling for Redis configuration errors
                    if "OOM" in str(e):
                        logger.error(f"Redis OOM during configuration: {e}")
                        # Try to increase maxmemory as an emergency measure
                        try:
                            client.config_set('maxmemory', '768mb')
                            logger.warning("Applied emergency Redis memory increase to 768MB")
                        except:
                            pass
                    else:
                        logger.error(f"Redis configuration error: {e}")

                logger.info(f"Connected to Redis at {redis_host}:{redis_port}/{redis_db}")

                return client

            except (ConnectionError, TimeoutError) as e:
                retry_count += 1
                _tls_hint = _REDIS_TLS_HINT if ssl_params else ""
                if retry_count >= max_retries:
                    logger.error(f"Failed to connect to Redis after {max_retries} attempts: {e}{_tls_hint}")
                    return None
                else:
                    # Use exponential backoff for retries
                    wait_time = retry_interval * (2 ** (retry_count - 1))
                    logger.warning(f"Redis connection failed. Retrying in {wait_time}s... ({retry_count}/{max_retries})")
                    time.sleep(wait_time)

            except Exception as e:
                _tls_hint = ""
                try:
                    _tls_hint = _REDIS_TLS_HINT if ssl_params else ""
                except NameError:
                    pass
                logger.error(f"Unexpected error connecting to Redis: {e}{_tls_hint}")
                return None

        return None

    @classmethod
    def get_client(cls, max_retries=5, retry_interval=1):
        """Get Redis client optimized for non-binary data (decoded responses)"""
        if cls._client is None:
            cls._client = cls._init_client(decode_responses=True, max_retries=max_retries, retry_interval=retry_interval)
        return cls._client

    @classmethod
    def get_buffer(cls, max_retries=5, retry_interval=1):
        """Get Redis client optimized for binary data (no decoding)"""
        if cls._buffer is None:
            cls._buffer = cls._init_client(decode_responses=False, max_retries=max_retries, retry_interval=retry_interval)
        return cls._buffer

    @classmethod
    def get_pubsub_client(cls, max_retries=5, retry_interval=1):
        """Get Redis client optimized for PubSub operations"""
        if cls._pubsub_client is None:
            retry_count = 0
            while retry_count < max_retries:
                try:
                    # Get connection parameters from settings or environment
                    redis_host = os.environ.get("REDIS_HOST", getattr(settings, 'REDIS_HOST', 'localhost'))
                    redis_port = int(os.environ.get("REDIS_PORT", getattr(settings, 'REDIS_PORT', 6379)))
                    redis_db = int(os.environ.get("REDIS_DB", getattr(settings, 'REDIS_DB', 0)))
                    redis_password = os.environ.get("REDIS_PASSWORD", getattr(settings, 'REDIS_PASSWORD', ''))
                    redis_user = os.environ.get("REDIS_USER", getattr(settings, 'REDIS_USER', ''))
                    redis_url = getattr(settings, "REDIS_URL", "")

                    # Use standardized settings but without socket timeouts for PubSub
                    # Important: socket_timeout is None for PubSub operations
                    socket_connect_timeout = getattr(settings, 'REDIS_SOCKET_CONNECT_TIMEOUT', 5)
                    socket_keepalive = getattr(settings, 'REDIS_SOCKET_KEEPALIVE', True)
                    health_check_interval = getattr(settings, 'REDIS_HEALTH_CHECK_INTERVAL', 30)
                    retry_on_timeout = getattr(settings, 'REDIS_RETRY_ON_TIMEOUT', True)

                    ssl_params = getattr(settings, 'REDIS_SSL_PARAMS', {})

                    # Create Redis client with PubSub-optimized settings - no timeout
                    client = redis.Redis(
                        host=redis_host,
                        port=redis_port,
                        db=redis_db,
                        password=redis_password if redis_password else None,
                        username=redis_user if redis_user else None,
                        socket_timeout=None,  # Critical: No timeout for PubSub operations
                        socket_connect_timeout=socket_connect_timeout,
                        socket_keepalive=socket_keepalive,
                        health_check_interval=health_check_interval,
                        retry_on_timeout=retry_on_timeout,
                        decode_responses=True,
                        **ssl_params
                    ) if not redis_url else redis.Redis.from_url(
                        redis_url,
                        socket_timeout=None,  # Critical: No timeout for PubSub operations
                        socket_connect_timeout=socket_connect_timeout,
                        socket_keepalive=socket_keepalive,
                        health_check_interval=health_check_interval,
                        retry_on_timeout=retry_on_timeout,
                        decode_responses=True,
                        **ssl_params
                    )

                    # Validate connection with ping
                    client.ping()
                    logger.info(f"Connected to Redis for PubSub at {redis_host}:{redis_port}/{redis_db}")

                    # We don't need the keepalive thread anymore since we're using proper PubSub handling
                    cls._pubsub_client = client
                    break

                except (ConnectionError, TimeoutError) as e:
                    retry_count += 1
                    _tls_hint = _REDIS_TLS_HINT if ssl_params else ""
                    if retry_count >= max_retries:
                        logger.error(f"Failed to connect to Redis for PubSub after {max_retries} attempts: {e}{_tls_hint}")
                        return None
                    else:
                        # Use exponential backoff for retries
                        wait_time = retry_interval * (2 ** (retry_count - 1))
                        logger.warning(f"Redis PubSub connection failed. Retrying in {wait_time}s... ({retry_count}/{max_retries})")
                        time.sleep(wait_time)

                except Exception as e:
                    _tls_hint = _REDIS_TLS_HINT if ssl_params else ""
                    logger.error(f"Unexpected error connecting to Redis for PubSub: {e}{_tls_hint}")
                    return None

        return cls._pubsub_client

def acquire_task_lock(task_name, id):
    """Acquire a lock to prevent concurrent task execution."""
    redis_client = RedisClient.get_client()
    lock_id = f"task_lock_{task_name}_{id}"

    # Use the Redis SET command with NX (only set if not exists) and EX (set expiration)
    lock_acquired = redis_client.set(lock_id, "locked", ex=300, nx=True)

    if not lock_acquired:
        logger.warning(f"Lock for {task_name} and id={id} already acquired. Task will not proceed.")

    return lock_acquired

def release_task_lock(task_name, id):
    """Release the lock after task execution."""
    redis_client = RedisClient.get_client()
    lock_id = f"task_lock_{task_name}_{id}"

    # Remove the lock
    redis_client.delete(lock_id)


def is_task_lock_held(task_name, id):
    """Return True when another worker holds the task lock (read-only check)."""
    redis_client = RedisClient.get_client()
    if redis_client is None:
        return False
    lock_id = f"task_lock_{task_name}_{id}"
    return bool(redis_client.exists(lock_id))


class TaskLockRenewer:
    """Periodically renews a Redis task lock to prevent expiry during long-running tasks.

    Use as a context manager after acquiring a lock:

        if acquire_task_lock("my_task", task_id):
            with TaskLockRenewer("my_task", task_id):
                # ... long-running work ...
            release_task_lock("my_task", task_id)

    A daemon thread extends the lock TTL at regular intervals so that
    slow downloads or large parsing jobs don't lose their lock mid-operation.
    """

    def __init__(self, task_name, id, ttl=300, renewal_interval=120):
        self.task_name = task_name
        self.id = id
        self.ttl = ttl
        self.renewal_interval = renewal_interval
        self.lock_id = f"task_lock_{task_name}_{id}"
        self._stop_event = threading.Event()
        self._thread = None

    def _renew_loop(self):
        """Background loop that extends the lock TTL until stopped."""
        while not self._stop_event.wait(self.renewal_interval):
            try:
                redis_client = RedisClient.get_client()
                if redis_client.exists(self.lock_id):
                    redis_client.expire(self.lock_id, self.ttl)
                    logger.debug(
                        f"Renewed lock {self.lock_id} TTL to {self.ttl}s"
                    )
                else:
                    # Lock was deleted externally (e.g. manual release) — stop renewing
                    logger.warning(
                        f"Lock {self.lock_id} no longer exists, stopping renewal"
                    )
                    break
            except Exception as e:
                logger.error(f"Error renewing lock {self.lock_id}: {e}")

    def start(self):
        """Start the background renewal thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._renew_loop, daemon=True,
            name=f"lock-renew-{self.task_name}-{self.id}"
        )
        self._thread.start()
        return self

    def stop(self):
        """Stop the renewal thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


def _is_gevent_monkey_patched():
    try:
        import gevent.monkey
        return gevent.monkey.is_module_patched('threading')
    except Exception:
        return False


def _cooperative_yield():
    """Yield to the gevent hub during CPU-bound loops (no-op otherwise)."""
    if not _is_gevent_monkey_patched():
        return
    try:
        import gevent
        gevent.sleep(0)
    except ImportError:
        pass


def _is_celery_worker_context():
    """True when executing inside an active Celery task (prefork worker)."""
    try:
        from celery import current_task
        request = getattr(current_task, 'request', None)
        return bool(request and getattr(request, 'id', None))
    except Exception:
        return False


def _should_use_sync_websocket_send():
    """
    Use synchronous Redis delivery when gevent is monkey-patched but no gevent
    hub is driving the process — e.g. Celery prefork workers that inherit
    gevent patching from uWSGI imports. gevent.spawn in that context schedules
    coroutines that never run.
    """
    return _is_gevent_monkey_patched() and _is_celery_worker_context()


def _gevent_ws_send(group_name, message):
    """
    Publishes a WebSocket group message synchronously through Redis.

    gevent's monkey-patching removes select.epoll, which breaks asyncio event
    loop creation in threadpool threads. This function replicates channels_redis
    4.x group_send directly via a sync Redis client, avoiding asyncio entirely.

    Matches channels_redis 4.x defaults: prefix="asgi", expiry=60,
    group_expiry=86400, msgpack serializer with 12-byte random prefix.
    """
    try:
        import msgpack
        redis = RedisClient.get_buffer()  # decode_responses=False for binary values

        prefix = "asgi"
        group_expiry = 86400
        channel_expiry = 60
        rand_len = 12

        group_key = f"{prefix}:group:{group_name}"
        now = time.time()

        redis.zremrangebyscore(group_key, 0, now - group_expiry)
        raw = redis.zrange(group_key, 0, -1)
        if not raw:
            return

        channels = [m.decode('utf-8') if isinstance(m, bytes) else m for m in raw]

        # Group channels by non-local name (prefix up to and including "!") so
        # specific channels sharing a prefix share one Redis sorted-set key.
        nonlocal_map = {}
        for ch in channels:
            pos = ch.find("!")
            nl = ch[:pos + 1] if pos >= 0 else ch
            nonlocal_map.setdefault(nl, []).append(ch)

        pipe = redis.pipeline(transaction=False)
        for nl, chs in nonlocal_map.items():
            channel_key = prefix + nl
            msg = dict(message)
            msg["__asgi_channel__"] = chs
            serialized = os.urandom(rand_len) + msgpack.packb(msg)
            pipe.zadd(channel_key, {serialized: now})
            pipe.expire(channel_key, channel_expiry)
        pipe.execute()
    except Exception as e:
        logger.warning(f"Failed to send WebSocket update: {e}")


def send_websocket_update_sync(group_name, event_type, data):
    """Send a WebSocket group message synchronously via Redis (channels_redis wire format)."""
    message = {'type': event_type, 'data': data}
    _gevent_ws_send(group_name, message)


def send_websocket_update(group_name, event_type, data, collect_garbage=False):
    """
    Sends a WebSocket group message.

    In gevent-patched uWSGI workers, asyncio event loop creation fails because
    monkey-patching removes select.epoll. For those contexts a synchronous Redis
    path is used instead, matching the channels_redis 4.x wire format.

    Celery prefork workers may inherit gevent monkey-patching without a running
    gevent hub; in that case gevent.spawn would never execute, so delivery is
    synchronous via Redis instead.
    """
    message = {'type': event_type, 'data': data}

    if _should_use_sync_websocket_send():
        _gevent_ws_send(group_name, message)
    elif _is_gevent_monkey_patched():
        import gevent
        gevent.spawn(_gevent_ws_send, group_name, message)
    else:
        # Not gevent-patched (plain Celery, tests) — use asyncio channel layer
        try:
            async_to_sync(get_channel_layer().group_send)(group_name, message)
        except Exception as e:
            logger.warning(f"Failed to send WebSocket update: {e}")

    if collect_garbage:
        gc.collect()

def send_websocket_event(event, success, data):
    """Acquire a lock to prevent concurrent task execution."""
    data_payload = {"success": success, "type": event}
    if data:
        # Make a copy to avoid modifying the original
        data_payload.update(data)

    # Use the standardized function
    send_websocket_update('updates', 'update', data_payload)

    # Help garbage collection by clearing references
    data_payload = None

# Add memory monitoring utilities
def get_memory_usage():
    """Returns current memory usage in MB"""
    import psutil
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)

def monitor_memory_usage(func):
    """Decorator to monitor memory usage before and after function execution"""
    def wrapper(*args, **kwargs):
        import gc
        # Force garbage collection before measuring
        gc.collect()

        # Get initial memory usage
        start_mem = get_memory_usage()
        logger.debug(f"Memory usage before {func.__name__}: {start_mem:.2f} MB")

        # Call the original function
        result = func(*args, **kwargs)

        # Force garbage collection before measuring again
        gc.collect()

        # Get final memory usage
        end_mem = get_memory_usage()
        logger.debug(f"Memory usage after {func.__name__}: {end_mem:.2f} MB (Change: {end_mem - start_mem:.2f} MB)")

        return result
    return wrapper

def trim_c_allocator_heap():
    """Return unused C heap pages to the OS where supported (glibc malloc_trim)."""
    try:
        import ctypes
        import ctypes.util

        libc_name = ctypes.util.find_library("c")
        if not libc_name:
            return False
        libc = ctypes.CDLL(libc_name)
        if not hasattr(libc, "malloc_trim"):
            return False
        libc.malloc_trim(0)
        return True
    except Exception:
        logger.debug("malloc_trim unavailable or failed", exc_info=True)
        return False


def cleanup_memory(log_usage=False, force_collection=True, trim_heap=False):
    """
    Comprehensive memory cleanup function to reduce memory footprint

    Args:
        log_usage: Whether to log memory usage before and after cleanup
        force_collection: Whether to force garbage collection
        trim_heap: Return freed C heap pages to the OS. Only use after DB
            connections are closed (e.g. Celery task_postrun).
    """
    logger.trace("Starting memory cleanup django memory cleanup")
    # Skip logging if log level is not set to debug or more verbose (like trace)
    current_log_level = logger.getEffectiveLevel()
    if not current_log_level <= logging.DEBUG:
        log_usage = False
    if log_usage:
        try:
            import psutil
            process = psutil.Process()
            before_mem = process.memory_info().rss / (1024 * 1024)
            logger.debug(f"Memory before cleanup: {before_mem:.2f} MB")
        except (ImportError, Exception) as e:
            logger.debug(f"Error getting memory usage: {e}")

    # Clear any object caches from Django ORM
    from django.db import connection, reset_queries
    reset_queries()

    # Force garbage collection
    if force_collection:
        # Run full collection
        gc.collect(generation=2)
        # Clear cyclic references
        gc.collect(generation=0)

    if log_usage:
        try:
            import psutil
            process = psutil.Process()
            after_mem = process.memory_info().rss / (1024 * 1024)
            logger.debug(f"Memory after cleanup: {after_mem:.2f} MB (change: {after_mem-before_mem:.2f} MB)")
        except (ImportError, Exception):
            pass
    if trim_heap:
        trim_c_allocator_heap()
    logger.trace("Memory cleanup complete for django")


def spawn_memory_trim(close_connections=False):
    """Reclaim a request's heap pages: GC, then return freed C pages to the OS.

    On gevent uWSGI workers the trim runs in a spawned greenlet so it never
    blocks the caller; Celery prefork workers (no gevent hub) run it inline.
    Set close_connections=True when called from a streaming generator's teardown
    so the pooled DB connection is released first.
    """
    def _run():
        cleanup_memory(force_collection=True, trim_heap=True)

    if close_connections:
        from django.db import close_old_connections
        close_old_connections()

    if _is_gevent_monkey_patched():
        import gevent
        gevent.spawn(_run)
    else:
        _run()


def safe_upload_path(filename: str, base_dir) -> str:
    """Return a safe absolute path for an uploaded file within base_dir.

    Strips all directory components from *filename* and verifies the resolved
    path stays inside *base_dir*.  Raises ValueError on path traversal attempts.
    """
    safe_name = Path(filename).name
    base = Path(base_dir).resolve()
    file_path = (base / safe_name).resolve()
    if not file_path.is_relative_to(base):
        raise ValueError("Invalid filename.")
    return str(file_path)


def is_protected_path(file_path):
    """
    Determine if a file path is in a protected directory that shouldn't be deleted.

    Args:
        file_path (str): The file path to check

    Returns:
        bool: True if the path is protected, False otherwise
    """
    if not file_path:
        return False

    # List of protected directory prefixes
    protected_dirs = [
        '/data/epgs',     # EPG files mapped from host
        '/data/uploads',   # User uploaded files
        '/data/m3us'       # M3U files mapped from host
    ]

    # Check if the path starts with any protected directory
    for protected_dir in protected_dirs:
        if file_path.startswith(protected_dir):
            return True

    return False

def validate_flexible_url(value):
    """
    Custom URL validator that accepts URLs with hostnames that aren't FQDNs.
    This allows URLs like "http://hostname/" which
    Django's standard URLValidator rejects.
    """
    if not value:
        return  # Allow empty values since the field is nullable

    # Create a standard Django URL validator
    url_validator = URLValidator()

    try:
        # First try the standard validation
        url_validator(value)
    except ValidationError as e:
        # If standard validation fails, check if it's a non-FQDN hostname
        import re

        # More flexible pattern for non-FQDN hostnames with paths
        # Matches: http://hostname, https://hostname/, http://hostname:port/path/to/file.xml, rtp://192.168.2.1,  rtsp://192.168.178.1, udp://239.0.0.1:1234
        # Also matches FQDNs for rtsp/rtp/udp protocols: rtsp://FQDN/path?query=value
        # Also supports authentication: rtsp://user:pass@hostname/path
        non_fqdn_pattern = r'^(rts?p|https?|udp)://([a-zA-Z0-9_\-\.]+:[^\s@]+@)?([a-zA-Z0-9]([a-zA-Z0-9_\-\.]{0,61}[a-zA-Z0-9])?|[0-9.]+)?(\:[0-9]+)?(/[^\s]*)?$'
        non_fqdn_match = re.match(non_fqdn_pattern, value)

        if non_fqdn_match:
            return  # Accept non-FQDN hostnames and rtsp/rtp/udp URLs with optional authentication

        # If it doesn't match our flexible patterns, raise the original error
        raise ValidationError("Enter a valid URL.")

def dispatch_event_system(event_type, channel_id=None, channel_name=None, **details):
    from django.db import close_old_connections

    try:
        from apps.connect.utils import trigger_event
        from apps.channels.models import Channel, Stream
        from core.models import StreamProfile
        from core.utils import RedisClient

        payload = dict(details)

        channel_obj = None
        if channel_id:
            try:
                channel_obj = Channel.objects.get(uuid=channel_id)
                payload["channel_name"] = channel_obj.name
            except Exception:
                payload["channel_name"] = channel_name or None
        else:
            payload["channel_name"] = channel_name or None

        # Resolve current stream info
        stream_id = details.get("stream_id")
        stream_obj = None
        if not stream_id and channel_obj:
            try:
                redis = RedisClient.get_client()
                sid = redis.get(f"channel_stream:{channel_obj.id}")
                if sid:
                    stream_id = int(sid)
            except Exception:
                stream_id = None

        if stream_id:
            try:
                stream_obj = Stream.objects.get(id=stream_id)
            except Exception:
                stream_obj = None

        # Populate stream details
        payload["stream_name"] = getattr(stream_obj, "name", None)
        payload["stream_url"] = getattr(stream_obj, "url", None)

        # Channel URL: use stream URL as best-effort
        payload["channel_url"] = payload.get("stream_url")

        # Provider name from M3U account
        provider_name = None
        try:
            if stream_obj and stream_obj.m3u_account:
                provider_name = stream_obj.m3u_account.name
        except Exception:
            provider_name = None
        payload["provider_name"] = provider_name

        # Profile used
        profile_used = None
        try:
            if stream_id:
                redis = RedisClient.get_client()
                pid = redis.get(f"stream_profile:{stream_id}")
                if pid:
                    profile = StreamProfile.objects.filter(id=int(pid)).first()
                    profile_used = profile.name if profile else None
        except Exception:
            profile_used = None

        payload["profile_used"] = profile_used

        # remove empty keys
        for k in list(payload.keys()):
            if not payload[k]:
                del payload[k]

        trigger_event(event_type, payload)

    except Exception:
        # Don't fail main path if connect dispatch fails
        pass
    finally:
        if _should_use_sync_websocket_send() or _is_gevent_monkey_patched():
            close_old_connections()


def _dispatch_system_event_integrations(
    event_type, channel_id=None, channel_name=None, **details
):
    """
    Run Connect subscriptions and plugin event hooks without blocking the caller.

    On gevent uWSGI workers, dispatch runs in a spawned greenlet so slow webhooks,
    scripts, or plugin handlers cannot stall live-proxy teardown or streaming paths.
    Celery prefork workers (gevent patched but no hub) run synchronously instead.
    """

    def _run():
        try:
            dispatch_event_system(
                event_type,
                channel_id=channel_id,
                channel_name=channel_name,
                **details,
            )
        except Exception as e:
            logger.error(
                "Failed to dispatch Connect/plugin handlers for event %s: %s",
                event_type,
                e,
            )

    if _should_use_sync_websocket_send():
        _run()
    elif _is_gevent_monkey_patched():
        import gevent

        gevent.spawn(_run)
    else:
        _run()


def log_system_event(event_type, channel_id=None, channel_name=None, **details):
    """
    Log a system event and maintain the configured max history.

    Args:
        event_type: Type of event (e.g., 'channel_start', 'client_connect')
        channel_id: Optional UUID of the channel
        channel_name: Optional name of the channel
        **details: Additional details to store in the event (stored as JSON)

    Example:
        log_system_event('channel_start', channel_id=uuid, channel_name='CNN',
                        stream_url='http://...', user='admin')
    """
    from core.models import SystemEvent, CoreSettings
    from django.db import close_old_connections

    try:
        # Create the event
        SystemEvent.objects.create(
            event_type=event_type,
            channel_id=channel_id,
            channel_name=channel_name,
            details=details
        )

        # Connect integrations and plugin event hooks (non-blocking on gevent uWSGI)
        _dispatch_system_event_integrations(
            event_type,
            channel_id=channel_id,
            channel_name=channel_name,
            **details,
        )

        # Get max events from settings (default 100)
        try:
            from .models import CoreSettings
            max_events = int(
                CoreSettings.get_system_settings().get("max_system_events", 100) or 100
            )
        except Exception:
            max_events = 100

        # Delete old events beyond the limit (keep it efficient with a single query)
        total_count = SystemEvent.objects.count()
        if total_count > max_events:
            # Get the ID of the event at the cutoff point
            cutoff_event = SystemEvent.objects.values_list('id', flat=True)[max_events]
            # Delete all events with ID less than cutoff (older events)
            SystemEvent.objects.filter(id__lt=cutoff_event).delete()

    except Exception as e:
        # Don't let event logging break the main application
        logger.error(f"Failed to log system event {event_type}: {e}")
    finally:
        # geventpool keeps checked-out connections until close(); release promptly
        # when logging from proxy greenlets/threads outside a normal request cycle.
        if _is_gevent_monkey_patched():
            close_old_connections()


def _send_async(channel_layer, group, message):
    """Send a channel layer group message without blocking the gevent hub."""
    def _do():
        try:
            async_to_sync(channel_layer.group_send)(group, message)
        except Exception as e:
            logger.warning(f"Failed WebSocket group_send to '{group}': {e}")

    try:
        import gevent.monkey
        if gevent.monkey.is_module_patched("threading"):
            import gevent
            gevent.spawn(_gevent_ws_send, group, message)
            return
    except Exception:
        pass
    _do()


def send_websocket_notification(notification):
    """
    Send a system notification to all connected WebSocket clients.

    Args:
        notification: A SystemNotification model instance or dict with notification data

    Example:
        from core.models import SystemNotification
        notification = SystemNotification.create_version_notification('0.19.0', 'https://...')
        send_websocket_notification(notification)
    """
    try:
        channel_layer = get_channel_layer()

        # Convert model instance to dict if needed
        if hasattr(notification, 'id'):
            notification_data = {
                'id': notification.id,
                'notification_key': notification.notification_key,
                'notification_type': notification.notification_type,
                'priority': notification.priority,
                'title': notification.title,
                'message': notification.message,
                'action_data': notification.action_data,
                'is_active': notification.is_active,
                'admin_only': notification.admin_only,
                'created_at': notification.created_at.isoformat() if notification.created_at else None,
            }
        else:
            notification_data = notification

        _send_async(
            channel_layer,
            'updates',
            {
                'type': 'update',
                'data': {
                    'type': 'system_notification',
                    'notification': notification_data,
                }
            }
        )
        logger.debug(f"Sent WebSocket notification: {notification_data.get('title', 'Unknown')}")
    except Exception as e:
        logger.error(f"Failed to send WebSocket notification: {e}")


def get_host_and_port(request):
    """
    Returns (host, port) for building absolute URIs.
    - Prefers X-Forwarded-Host/X-Forwarded-Port (nginx).
    - Falls back to Host header.
    - Returns None for port if using standard ports (80/443) to omit from URLs.
    - In dev, uses 5656 as a guess if port cannot be determined.
    """
    scheme = request.META.get("HTTP_X_FORWARDED_PROTO", request.scheme)
    standard_port = "443" if scheme == "https" else "80"

    # 1. Try X-Forwarded-Host (may include port) - set by our nginx
    xfh = request.META.get("HTTP_X_FORWARDED_HOST")
    if xfh:
        if ":" in xfh:
            host, port = xfh.split(":", 1)
            if port == standard_port:
                return host, None
            return host, port
        else:
            host = xfh

        port = request.META.get("HTTP_X_FORWARDED_PORT")
        if port:
            return host, None if port == standard_port else port
        if request.META.get("HTTP_X_FORWARDED_PROTO"):
            return host, None

    # 2. Try Host header
    raw_host = request.get_host()
    if ":" in raw_host:
        host, port = raw_host.split(":", 1)
        return host, None if port == standard_port else port
    else:
        host = raw_host

    # 3. Check for X-Forwarded-Port (when Host header has no port but we're behind a reverse proxy)
    port = request.META.get("HTTP_X_FORWARDED_PORT")
    if port:
        return host, None if port == standard_port else port

    # 4. Behind a reverse proxy with no port info - assume standard port
    if request.META.get("HTTP_X_FORWARDED_PROTO") or request.META.get("HTTP_X_FORWARDED_FOR"):
        return host, None

    # 5. Try SERVER_PORT from META (only if NOT behind reverse proxy)
    port = request.META.get("SERVER_PORT")
    if port:
        return host, None if port == standard_port else port

    # 6. Dev fallback
    if os.environ.get("DISPATCHARR_ENV") == "dev" or host in ("localhost", "127.0.0.1"):
        return host, "5656"

    # 7. Final fallback: assume standard port for scheme
    return host, None


def build_absolute_uri_with_port(request, path):
    """
    Build an absolute URI with optional port.
    Port is omitted from URL if None (standard port for scheme).
    """
    host, port = get_host_and_port(request)
    scheme = request.META.get("HTTP_X_FORWARDED_PROTO", request.scheme)
    if port:
        return f"{scheme}://{host}:{port}{path}"
    return f"{scheme}://{host}{path}"


def send_notification_dismissed(notification_key):
    """
    Notify all connected clients that a notification was dismissed.
    Useful for syncing dismissal state across multiple browser tabs/sessions.

    Args:
        notification_key: The unique key of the dismissed notification
    """
    try:
        channel_layer = get_channel_layer()

        _send_async(
            channel_layer,
            'updates',
            {
                'type': 'update',
                'data': {
                    'type': 'notification_dismissed',
                    'notification_key': notification_key,
                }
            }
        )
    except Exception as e:
        logger.error(f"Failed to send notification dismissed event: {e}")
