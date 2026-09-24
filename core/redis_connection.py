"""Redis client construction with no Django imports.

The startup waiter runs before the app is loaded, so this module only uses
the environment and redis-py. RedisClient passes the same values from
Django settings when the app is up.
"""

import os
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit

import redis
from redis.connection import BlockingConnectionPool


class RedisUrlError(ValueError):
    """REDIS_URL was set but its query string could not be parsed."""


def build_redis_client(
    *,
    redis_url="",
    host="localhost",
    port=6379,
    db=0,
    username=None,
    password=None,
    ssl_params=None,
    socket_timeout=60,
    socket_connect_timeout=5,
    socket_keepalive=True,
    health_check_interval=15,
    retry_on_timeout=True,
    max_connections=50,
    pool_timeout=20,
    decode_responses=True,
):
    """Return (client, location). A blank redis_url uses host, port, and db.

    location is the socket path or host:port, for logs. Query keys that must
    stay under our control (timeouts, keepalive, decode_responses) are stripped
    from a URL so they cannot override the arguments above. socket_keepalive
    is omitted for unix sockets, which reject it.
    """
    ssl_params = ssl_params or {}
    sockargs = {
        "socket_timeout": socket_timeout,
        "socket_connect_timeout": socket_connect_timeout,
        "socket_keepalive": socket_keepalive,
    }
    pool_kwargs = {
        "max_connections": max_connections,
        "timeout": pool_timeout,
        "decode_responses": decode_responses,
        "health_check_interval": health_check_interval,
        "retry_on_timeout": retry_on_timeout,
    }
    immutable = (*sockargs.keys(), "health_check_interval", "retry_on_timeout", "decode_responses")

    url = (redis_url or "").strip()
    if url:
        parts = urlsplit(url, allow_fragments=False)
        try:
            query = dict(parse_qsl(parts.query, strict_parsing=True))
        except ValueError as exc:
            raise RedisUrlError("Unable to parse REDIS_URL query string") from exc
        for key in immutable:
            query.pop(key, None)
        encoded = urlencode(query)
        url = f"{parts.scheme}://{parts.netloc}{parts.path}{'?' + encoded if encoded else ''}"
        if parts.scheme == "unix":
            sockargs.pop("socket_keepalive", None)
        pool = BlockingConnectionPool.from_url(url, **pool_kwargs, **sockargs)
    else:
        pool = BlockingConnectionPool(
            host=host,
            port=int(port),
            db=int(db),
            username=username,
            password=password,
            **ssl_params,
            **sockargs,
            **pool_kwargs,
        )

    client = redis.Redis(connection_pool=pool)
    info = client.get_connection_kwargs()
    path = info.get("path")
    location = path if path else f"{info.get('host', '')}:{info.get('port', '')}"
    return client, location


def _ssl_params_from_env(redis_url):
    """TLS kwargs for a host/port connection. A URL carries its own TLS."""
    if (redis_url or "").strip():
        return {}
    if os.environ.get("REDIS_SSL", "false").lower() != "true":
        return {}
    params = {
        "ssl": True,
        "ssl_cert_reqs": (
            ssl.CERT_REQUIRED
            if os.environ.get("REDIS_SSL_VERIFY", "true").lower() == "true"
            else ssl.CERT_NONE
        ),
    }
    mapping = (
        ("REDIS_SSL_CA_CERT", "ssl_ca_certs"),
        ("REDIS_SSL_CERT", "ssl_certfile"),
        ("REDIS_SSL_KEY", "ssl_keyfile"),
    )
    for env_name, kwarg in mapping:
        path = os.environ.get(env_name, "")
        if path:
            params[kwarg] = path
    return params


def client_from_env(*, socket_timeout=2, socket_connect_timeout=2, decode_responses=False, max_connections=2):
    """Client for the startup waiter. Reads REDIS_* from the environment only."""
    redis_url = os.environ.get("REDIS_URL", "")
    password = os.environ.get("REDIS_PASSWORD", "")
    username = os.environ.get("REDIS_USER", "")
    return build_redis_client(
        redis_url=redis_url,
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        db=int(os.environ.get("REDIS_DB", 0)),
        username=username or None,
        password=password or None,
        ssl_params=_ssl_params_from_env(redis_url),
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
        decode_responses=decode_responses,
        max_connections=max_connections,
        pool_timeout=5,
    )
