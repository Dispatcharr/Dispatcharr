import hashlib
import logging
import os
import time
from typing import Dict, Optional

import redis
from django.conf import settings

from .utils import is_fuse_client_request

logger = logging.getLogger(__name__)

FUSE_CLIENTS_SET_KEY = "fuse:clients"
FUSE_CLIENT_KEY_PREFIX = "fuse:client"
FUSE_CLIENT_BLOCK_KEY_PREFIX = "fuse:client:block"

FUSE_CLIENT_PRESENCE_TTL_SECONDS = max(
    60, int(os.getenv("FUSE_CLIENT_PRESENCE_TTL_SECONDS", "900"))
)
FUSE_CLIENT_ACTIVE_WINDOW_SECONDS = max(
    60, int(os.getenv("FUSE_CLIENT_ACTIVE_WINDOW_SECONDS", "300"))
)
FUSE_FORCE_REMOVE_BLOCK_SECONDS = max(
    30, int(os.getenv("FUSE_FORCE_REMOVE_BLOCK_SECONDS", "300"))
)


def _get_redis_client() -> Optional[redis.StrictRedis]:
    try:
        return redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=int(getattr(settings, "REDIS_PORT", 6379)),
            db=int(getattr(settings, "REDIS_DB", 0)),
            password=getattr(settings, "REDIS_PASSWORD", "") or None,
            username=getattr(settings, "REDIS_USER", "") or None,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
            retry_on_timeout=True,
        )
    except Exception as exc:
        logger.warning("Failed to create Redis client for FUSE presence tracking: %s", exc)
        return None


def _get_client_key(client_id: str) -> str:
    return f"{FUSE_CLIENT_KEY_PREFIX}:{client_id}"


def _get_client_block_key(client_id: str) -> str:
    return f"{FUSE_CLIENT_BLOCK_KEY_PREFIX}:{client_id}"


def _safe_float(value, fallback=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _split_csv_values(raw_value: str):
    values = []
    for part in str(raw_value or "").split(","):
        normalized = part.strip()
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _merge_csv_values(
    existing_csv: str,
    incoming_value: str,
    preferred_order=None,
) -> str:
    values = _split_csv_values(existing_csv)
    normalized_incoming = str(incoming_value or "").strip()
    if normalized_incoming and normalized_incoming not in values:
        values.append(normalized_incoming)

    if preferred_order:
        index = {value: idx for idx, value in enumerate(preferred_order)}
        values.sort(key=lambda value: (index.get(value, len(index)), value))

    return ",".join(values)


def _get_request_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        parts = [part.strip() for part in str(forwarded_for).split(",") if part.strip()]
        if parts:
            return parts[0]
    return str(request.META.get("REMOTE_ADDR", "")).strip() or "unknown"


def _sanitize_identifier(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in ("-", "_", "."))
    return cleaned[:128].strip("._-")


def _derive_client_id(hostname: str, ip_address: str, user_agent: str) -> str:
    fingerprint = f"{hostname}|{ip_address}|{user_agent}"
    digest = hashlib.sha1(fingerprint.encode("utf-8", errors="ignore")).hexdigest()[:16]
    host_part = _sanitize_identifier(hostname.lower()) or "fuse"
    return f"{host_part}-{digest}"


def _extract_identity(request) -> Dict[str, str]:
    user_agent = str(request.META.get("HTTP_USER_AGENT", "")).strip()
    hostname = str(request.META.get("HTTP_X_DISPATCHARR_FUSE_HOSTNAME", "")).strip()
    client_id = str(request.META.get("HTTP_X_DISPATCHARR_FUSE_CLIENT_ID", "")).strip()
    mode = str(request.META.get("HTTP_X_DISPATCHARR_FUSE_MODE", "")).strip().lower()
    mountpoint = str(request.META.get("HTTP_X_DISPATCHARR_FUSE_MOUNTPOINT", "")).strip()
    build = str(request.META.get("HTTP_X_DISPATCHARR_FUSE_BUILD", "")).strip()
    ip_address = _get_request_ip(request)

    sanitized_hostname = _sanitize_identifier(hostname) or "unknown"
    sanitized_client_id = _sanitize_identifier(client_id)
    if not sanitized_client_id:
        sanitized_client_id = _derive_client_id(sanitized_hostname, ip_address, user_agent)

    return {
        "client_id": sanitized_client_id,
        "hostname": sanitized_hostname,
        "ip_address": ip_address[:128],
        "user_agent": user_agent[:512],
        "last_mode": _sanitize_identifier(mode)[:32],
        "last_mountpoint": mountpoint[:255],
        "build": build[:128],
    }


def _get_blocked_until(redis_client, client_id: str, now: Optional[float] = None) -> Optional[float]:
    if now is None:
        now = time.time()
    key = _get_client_block_key(client_id)
    raw = redis_client.get(key)
    if not raw:
        return None

    blocked_until = _safe_float(raw, 0.0)
    if blocked_until <= now:
        try:
            redis_client.delete(key)
        except Exception:
            pass
        return None
    return blocked_until


def touch_fuse_client_presence(request, endpoint: str = "") -> Dict[str, object]:
    user_agent = str(request.META.get("HTTP_USER_AGENT", "")).strip()
    if not is_fuse_client_request(client_user_agent=user_agent, request_meta=request.META):
        return {"tracked": False, "blocked": False}

    identity = _extract_identity(request)
    redis_client = _get_redis_client()
    if not redis_client:
        return {**identity, "tracked": False, "blocked": False}

    now = time.time()
    client_id = identity["client_id"]
    blocked_until = _get_blocked_until(redis_client, client_id, now=now)
    if blocked_until:
        return {
            **identity,
            "tracked": True,
            "blocked": True,
            "blocked_until": blocked_until,
        }

    key = _get_client_key(client_id)
    try:
        existing_data = redis_client.hgetall(key) or {}
    except Exception:
        existing_data = {}

    last_mode = identity["last_mode"] or str(existing_data.get("last_mode", "")).strip()
    last_mountpoint = (
        identity["last_mountpoint"] or str(existing_data.get("last_mountpoint", "")).strip()
    )

    movies_mountpoint = str(existing_data.get("movies_mountpoint", "")).strip()
    tv_mountpoint = str(existing_data.get("tv_mountpoint", "")).strip()
    if identity["last_mountpoint"]:
        if last_mode == "movies":
            movies_mountpoint = identity["last_mountpoint"]
        elif last_mode == "tv":
            tv_mountpoint = identity["last_mountpoint"]

    mapping = {
        "client_id": client_id,
        "hostname": identity["hostname"],
        "ip_address": identity["ip_address"],
        "user_agent": identity["user_agent"],
        "last_mode": last_mode,
        "last_mountpoint": last_mountpoint,
        "modes": _merge_csv_values(
            existing_data.get("modes", ""),
            last_mode,
            preferred_order=["movies", "tv"],
        ),
        "mountpoints": _merge_csv_values(
            existing_data.get("mountpoints", ""),
            last_mountpoint,
        ),
        "movies_mountpoint": movies_mountpoint,
        "tv_mountpoint": tv_mountpoint,
        "build": identity["build"],
        "last_endpoint": endpoint[:64],
        "last_seen": str(now),
    }

    try:
        pipe = redis_client.pipeline()
        pipe.hsetnx(key, "first_seen", str(now))
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, FUSE_CLIENT_PRESENCE_TTL_SECONDS)
        pipe.sadd(FUSE_CLIENTS_SET_KEY, client_id)
        pipe.expire(
            FUSE_CLIENTS_SET_KEY,
            max(FUSE_CLIENT_PRESENCE_TTL_SECONDS * 2, 1800),
        )
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed to update FUSE client presence for %s: %s", client_id, exc)
        return {**identity, "tracked": False, "blocked": False}

    return {
        **identity,
        "tracked": True,
        "blocked": False,
        "last_seen": now,
    }


def list_fuse_clients(include_inactive: bool = False) -> Dict[str, object]:
    redis_client = _get_redis_client()
    current_time = time.time()
    if not redis_client:
        return {
            "clients": [],
            "total_clients": 0,
            "active_window_seconds": FUSE_CLIENT_ACTIVE_WINDOW_SECONDS,
            "timestamp": current_time,
        }

    clients = []
    stale_client_ids = []
    try:
        client_ids = redis_client.smembers(FUSE_CLIENTS_SET_KEY) or set()
    except Exception as exc:
        logger.warning("Failed to load FUSE client ID set: %s", exc)
        client_ids = set()

    for raw_client_id in client_ids:
        client_id = str(raw_client_id).strip()
        if not client_id:
            continue
        key = _get_client_key(client_id)
        try:
            data = redis_client.hgetall(key) or {}
        except Exception as exc:
            logger.warning("Failed reading FUSE client key %s: %s", key, exc)
            data = {}

        if not data:
            stale_client_ids.append(client_id)
            continue

        last_seen = _safe_float(data.get("last_seen"), 0.0)
        first_seen = _safe_float(data.get("first_seen"), 0.0)
        idle_seconds = max(0, int(current_time - last_seen)) if last_seen > 0 else None
        active = bool(last_seen > 0 and idle_seconds is not None and idle_seconds <= FUSE_CLIENT_ACTIVE_WINDOW_SECONDS)
        if not include_inactive and not active:
            continue

        blocked_until = _get_blocked_until(redis_client, client_id, now=current_time)
        last_mode = str(data.get("last_mode", "")).strip()
        last_mountpoint = str(data.get("last_mountpoint", "")).strip()

        movies_mountpoint = str(data.get("movies_mountpoint", "")).strip()
        tv_mountpoint = str(data.get("tv_mountpoint", "")).strip()
        if not movies_mountpoint and last_mode == "movies":
            movies_mountpoint = last_mountpoint
        if not tv_mountpoint and last_mode == "tv":
            tv_mountpoint = last_mountpoint

        modes = str(data.get("modes", "")).strip()
        if not modes:
            derived_modes = []
            if movies_mountpoint:
                derived_modes.append("movies")
            if tv_mountpoint:
                derived_modes.append("tv")
            if last_mode and last_mode not in derived_modes:
                derived_modes.append(last_mode)
            modes = ",".join(derived_modes)

        mountpoints = str(data.get("mountpoints", "")).strip()
        if not mountpoints:
            derived_mountpoints = []
            if movies_mountpoint:
                derived_mountpoints.append(movies_mountpoint)
            if tv_mountpoint and tv_mountpoint not in derived_mountpoints:
                derived_mountpoints.append(tv_mountpoint)
            if last_mountpoint and last_mountpoint not in derived_mountpoints:
                derived_mountpoints.append(last_mountpoint)
            mountpoints = ",".join(derived_mountpoints)

        clients.append(
            {
                "client_id": client_id,
                "hostname": data.get("hostname", "unknown"),
                "ip_address": data.get("ip_address", "unknown"),
                "user_agent": data.get("user_agent", ""),
                "build": data.get("build", ""),
                "last_mode": last_mode,
                "last_mountpoint": last_mountpoint,
                "modes": modes,
                "mountpoints": mountpoints,
                "movies_mountpoint": movies_mountpoint,
                "tv_mountpoint": tv_mountpoint,
                "last_endpoint": data.get("last_endpoint", ""),
                "first_seen": first_seen or None,
                "last_seen": last_seen or None,
                "idle_seconds": idle_seconds,
                "is_active": active,
                "is_blocked": blocked_until is not None,
                "blocked_until": blocked_until,
            }
        )

    if stale_client_ids:
        try:
            redis_client.srem(FUSE_CLIENTS_SET_KEY, *stale_client_ids)
        except Exception:
            pass

    clients.sort(key=lambda item: _safe_float(item.get("last_seen"), 0.0), reverse=True)
    return {
        "clients": clients,
        "total_clients": len(clients),
        "active_window_seconds": FUSE_CLIENT_ACTIVE_WINDOW_SECONDS,
        "timestamp": current_time,
    }


def force_remove_fuse_client(
    client_id: str,
    block_seconds: Optional[int] = None,
    removed_by: str = "",
) -> Dict[str, object]:
    normalized_client_id = _sanitize_identifier(client_id)
    if not normalized_client_id:
        raise ValueError("Invalid client_id")

    redis_client = _get_redis_client()
    if not redis_client:
        raise RuntimeError("Redis unavailable")

    if block_seconds is None:
        effective_block_seconds = FUSE_FORCE_REMOVE_BLOCK_SECONDS
    else:
        effective_block_seconds = max(30, int(block_seconds))

    current_time = time.time()
    blocked_until = current_time + effective_block_seconds

    block_key = _get_client_block_key(normalized_client_id)
    client_key = _get_client_key(normalized_client_id)

    pipe = redis_client.pipeline()
    pipe.setex(block_key, effective_block_seconds, str(blocked_until))
    # Remove from active list immediately; if the process retries while blocked, requests will be denied.
    pipe.delete(client_key)
    pipe.srem(FUSE_CLIENTS_SET_KEY, normalized_client_id)
    pipe.execute()

    return {
        "client_id": normalized_client_id,
        "block_seconds": effective_block_seconds,
        "blocked_until": blocked_until,
        "removed_by": removed_by or "",
    }
