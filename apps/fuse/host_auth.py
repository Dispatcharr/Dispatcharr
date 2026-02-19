import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from typing import Dict, Optional, Tuple

import redis
from django.conf import settings

from core.models import CoreSettings

logger = logging.getLogger(__name__)

FUSE_HOST_AUTH_SETTINGS_KEY = "fuse_host_auth"
FUSE_HOST_AUTH_SETTINGS_NAME = "FUSE Host Auth"

FUSE_HOST_TOKEN_HEADER_KEY = "HTTP_X_DISPATCHARR_FUSE_TOKEN"

FUSE_PAIRING_REDIS_PREFIX = "fuse:pairing"
FUSE_PAIRING_DEFAULT_TTL_SECONDS = max(
    60, int(os.getenv("FUSE_PAIRING_DEFAULT_TTL_SECONDS", "600"))
)
FUSE_PAIRING_MAX_TTL_SECONDS = max(
    FUSE_PAIRING_DEFAULT_TTL_SECONDS,
    int(os.getenv("FUSE_PAIRING_MAX_TTL_SECONDS", "3600")),
)

FUSE_HOST_TOKEN_CACHE_TTL_SECONDS = max(
    5, int(os.getenv("FUSE_HOST_TOKEN_CACHE_TTL_SECONDS", "30"))
)

_TOKEN_CACHE = {
    "loaded_at": 0.0,
    "entries": {},  # token_hash -> host metadata
}


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
        logger.warning("Failed to create Redis client for FUSE host auth: %s", exc)
        return None


def _sanitize_text(value: str, max_len: int = 255, fallback: str = "") -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return fallback
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    return cleaned[:max_len]


def _normalize_pairing_token(value: str) -> str:
    normalized = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    return normalized[:32]


def _format_pairing_token(value: str) -> str:
    normalized = _normalize_pairing_token(value)
    if not normalized:
        return ""
    return "-".join(
        normalized[i : i + 4] for i in range(0, len(normalized), 4) if normalized[i : i + 4]
    )


def _pairing_key(pairing_token: str) -> str:
    return f"{FUSE_PAIRING_REDIS_PREFIX}:{_normalize_pairing_token(pairing_token)}"


def _hash_host_token(host_token: str) -> str:
    return hashlib.sha256(str(host_token or "").encode("utf-8", errors="ignore")).hexdigest()


def _load_host_auth_state() -> Dict[str, object]:
    try:
        obj = CoreSettings.objects.get(key=FUSE_HOST_AUTH_SETTINGS_KEY)
        value = obj.value
    except CoreSettings.DoesNotExist:
        value = {}
    except Exception as exc:
        logger.warning("Failed loading FUSE host auth settings: %s", exc)
        value = {}

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}

    if not isinstance(value, dict):
        value = {}

    hosts = value.get("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}

    return {"hosts": hosts}


def _save_host_auth_state(state: Dict[str, object]) -> None:
    safe_state = state if isinstance(state, dict) else {}
    hosts = safe_state.get("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}
    safe_state = {"hosts": hosts}

    CoreSettings.objects.update_or_create(
        key=FUSE_HOST_AUTH_SETTINGS_KEY,
        defaults={"name": FUSE_HOST_AUTH_SETTINGS_NAME, "value": safe_state},
    )


def _build_token_cache_entries(state: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    hosts = state.get("hosts", {}) if isinstance(state, dict) else {}
    if not isinstance(hosts, dict):
        return {}

    entries: Dict[str, Dict[str, object]] = {}
    for host_id, metadata in hosts.items():
        if not isinstance(metadata, dict):
            continue
        if bool(metadata.get("revoked")):
            continue
        token_hash = _sanitize_text(metadata.get("token_hash", ""), max_len=128)
        if not token_hash:
            continue
        entries[token_hash] = {
            "host_id": _sanitize_text(host_id, max_len=64),
            "hostname": _sanitize_text(metadata.get("hostname", ""), max_len=128, fallback="unknown"),
            "created_by": _sanitize_text(metadata.get("created_by", ""), max_len=128),
            "created_at": float(metadata.get("created_at", 0.0) or 0.0),
            "last_register_ip": _sanitize_text(metadata.get("last_register_ip", ""), max_len=128),
            "client_id_hint": _sanitize_text(metadata.get("client_id_hint", ""), max_len=128),
            "mountpoint_hint": _sanitize_text(metadata.get("mountpoint_hint", ""), max_len=255),
            "revoked": False,
        }
    return entries


def _refresh_token_cache(force: bool = False) -> Dict[str, Dict[str, object]]:
    now = time.time()
    loaded_at = float(_TOKEN_CACHE.get("loaded_at", 0.0) or 0.0)
    if not force and (now - loaded_at) < FUSE_HOST_TOKEN_CACHE_TTL_SECONDS:
        entries = _TOKEN_CACHE.get("entries", {})
        if isinstance(entries, dict):
            return entries

    state = _load_host_auth_state()
    entries = _build_token_cache_entries(state)
    _TOKEN_CACHE["loaded_at"] = now
    _TOKEN_CACHE["entries"] = entries
    return entries


def extract_fuse_host_token_from_request(request) -> str:
    token = request.META.get(FUSE_HOST_TOKEN_HEADER_KEY, "")
    return _sanitize_text(token, max_len=512)


def validate_fuse_host_token(host_token: str) -> Optional[Dict[str, object]]:
    token = _sanitize_text(host_token, max_len=512)
    if not token:
        return None

    token_hash = _hash_host_token(token)
    entries = _refresh_token_cache(force=False)
    metadata = entries.get(token_hash)
    if metadata:
        return metadata

    # Retry once with a forced cache refresh in case another worker just rotated tokens.
    entries = _refresh_token_cache(force=True)
    return entries.get(token_hash)


def has_registered_fuse_host_tokens() -> bool:
    entries = _refresh_token_cache(force=False)
    return bool(entries)


def require_valid_fuse_host_token(request) -> Tuple[bool, str, Optional[Dict[str, object]]]:
    token = extract_fuse_host_token_from_request(request)
    if not token:
        return False, "Missing FUSE host token. Pair this host and retry.", None

    metadata = validate_fuse_host_token(token)
    if not metadata:
        return False, "Invalid FUSE host token. Re-pair this host and retry.", None

    return True, "", metadata


def _generate_pairing_token() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return _format_pairing_token(raw)


def create_fuse_pairing_token(
    *,
    created_by: str,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, object]:
    redis_client = _get_redis_client()
    if not redis_client:
        raise RuntimeError("Redis unavailable")

    if ttl_seconds is None:
        effective_ttl = FUSE_PAIRING_DEFAULT_TTL_SECONDS
    else:
        effective_ttl = max(60, min(int(ttl_seconds), FUSE_PAIRING_MAX_TTL_SECONDS))

    pairing_token = _generate_pairing_token()
    created_at = time.time()
    expires_at = created_at + effective_ttl
    payload = {
        "created_by": _sanitize_text(created_by, max_len=128),
        "created_at": created_at,
        "expires_at": expires_at,
    }

    redis_client.setex(
        _pairing_key(pairing_token),
        effective_ttl,
        json.dumps(payload),
    )

    return {
        "pairing_token": pairing_token,
        "ttl_seconds": effective_ttl,
        "created_at": created_at,
        "expires_at": expires_at,
    }


def register_fuse_host_with_pairing_token(
    *,
    pairing_token: str,
    hostname: str,
    request_ip: str,
    client_id_hint: str = "",
    mountpoint_hint: str = "",
) -> Dict[str, object]:
    redis_client = _get_redis_client()
    if not redis_client:
        raise RuntimeError("Redis unavailable")

    normalized_pairing_token = _normalize_pairing_token(pairing_token)
    if not normalized_pairing_token:
        raise ValueError("Invalid pairing token")

    pairing_key = _pairing_key(normalized_pairing_token)
    payload_raw = redis_client.get(pairing_key)
    if not payload_raw:
        raise ValueError("Pairing token is invalid or expired")

    # One-time use token.
    redis_client.delete(pairing_key)

    try:
        payload = json.loads(payload_raw)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    host_token = f"fht_{secrets.token_urlsafe(32)}"
    host_id = uuid.uuid4().hex
    now = time.time()

    state = _load_host_auth_state()
    hosts = state.get("hosts", {})
    if not isinstance(hosts, dict):
        hosts = {}

    hosts[host_id] = {
        "token_hash": _hash_host_token(host_token),
        "hostname": _sanitize_text(hostname, max_len=128, fallback="unknown"),
        "created_by": _sanitize_text(payload.get("created_by", ""), max_len=128),
        "created_at": now,
        "last_register_ip": _sanitize_text(request_ip, max_len=128),
        "client_id_hint": _sanitize_text(client_id_hint, max_len=128),
        "mountpoint_hint": _sanitize_text(mountpoint_hint, max_len=255),
        "revoked": False,
    }
    state["hosts"] = hosts
    _save_host_auth_state(state)
    _refresh_token_cache(force=True)

    return {
        "host_id": host_id,
        "host_token": host_token,
        "hostname": hosts[host_id]["hostname"],
        "created_at": now,
    }
