"""
Shared connection pool enforcement for M3U accounts in the same ServerGroup.

Profile selection rotates across M3UAccountProfile rows using each profile's own
Redis counter (the pre-pool behavior). When an account belongs to a ServerGroup
with max_streams > 0, a credential-scoped counter is checked on reserve/release
so accounts sharing the same provider login share one limit without blocking
unrelated logins on the same group.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

PROFILE_CONNECTIONS_KEY = "profile_connections:{profile_id}"
SERVER_GROUP_CONNECTIONS_KEY = "server_group_connections:{group_id}:{fingerprint}"

_XC_URL_CREDENTIALS_RE = re.compile(
    r"/(?:live|movie|series)/([^/]+)/([^/]+)/",
    re.IGNORECASE,
)


def profile_connections_key(profile_id: int) -> str:
    return PROFILE_CONNECTIONS_KEY.format(profile_id=profile_id)


def server_group_connections_key(group_id: int, fingerprint: str) -> str:
    """Redis key for per-credential usage within a ServerGroup."""
    return SERVER_GROUP_CONNECTIONS_KEY.format(
        group_id=group_id,
        fingerprint=fingerprint[:16],
    )


def compute_credential_fingerprint(username: str, password: str) -> Optional[str]:
    """Return a stable hash for grouping accounts with the same IPTV login."""
    if not username or not password:
        return None
    normalized = f"{username.strip().lower()}\0{password.strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_credentials_from_stream_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse username/password embedded in an Xtream-style stream URL."""
    if not url:
        return None, None
    match = _XC_URL_CREDENTIALS_RE.search(url)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _fingerprint_from_profile_stream_url(profile) -> Optional[str]:
    """STD/M3U: fingerprint from a sample stream URL after profile rewrite."""
    from apps.channels.models import Stream

    sample_url = (
        Stream.objects.filter(m3u_account=profile.m3u_account)
        .exclude(url="")
        .values_list("url", flat=True)
        .first()
    )
    if not sample_url:
        return None

    try:
        from apps.proxy.live_proxy.url_utils import transform_url

        transformed = transform_url(
            sample_url,
            profile.search_pattern or "",
            profile.replace_pattern or "",
        )
        url_user, url_pass = extract_credentials_from_stream_url(
            transformed or sample_url
        )
        return compute_credential_fingerprint(url_user or "", url_pass or "")
    except Exception as exc:
        logger.debug(
            "Could not derive profile %s fingerprint from stream URL: %s",
            profile.pk,
            exc,
        )
        return None


def get_profile_credential_fingerprint(profile) -> Optional[str]:
    """Fingerprint for credentials this profile uses at playback time."""
    m3u_account = profile.m3u_account

    if m3u_account.account_type == "XC":
        try:
            from apps.m3u.tasks import get_transformed_credentials

            _url, username, password = get_transformed_credentials(m3u_account, profile)
            fingerprint = compute_credential_fingerprint(username or "", password or "")
            if fingerprint:
                return fingerprint
        except Exception as exc:
            logger.debug(
                "Could not resolve transformed credentials for profile %s: %s",
                profile.pk,
                exc,
            )

    fingerprint = _fingerprint_from_profile_stream_url(profile)
    if fingerprint:
        return fingerprint

    return compute_credential_fingerprint(
        m3u_account.username or "",
        m3u_account.password or "",
    )


def get_enforced_server_group_for_profile(profile):
    """Return the shared ServerGroup limit for this profile's account, if configured."""
    group = profile.m3u_account.server_group
    if group and group.max_streams > 0:
        return group
    return None


def _credential_counter_key(profile, group) -> Optional[str]:
    fingerprint = get_profile_credential_fingerprint(profile)
    if not fingerprint:
        return None
    return server_group_connections_key(group.id, fingerprint)


def get_profile_connection_count(profile, redis_client) -> int:
    return int(redis_client.get(profile_connections_key(profile.id)) or 0)


def get_credential_connection_count(profile, redis_client) -> int:
    group = get_enforced_server_group_for_profile(profile)
    if not group:
        return 0
    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return 0
    return int(redis_client.get(cred_key) or 0)


def get_group_connection_count(profile, redis_client) -> int:
    """Backwards-compatible alias for credential-scoped group usage."""
    return get_credential_connection_count(profile, redis_client)


def profile_has_capacity_for_selection(profile, redis_client) -> bool:
    """Per-profile capacity check used when rotating across profiles on one account."""
    if profile.max_streams == 0:
        return True
    return get_profile_connection_count(profile, redis_client) < profile.max_streams


def group_has_capacity_for_profile(profile, redis_client) -> bool:
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return True
    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return True
    return get_credential_connection_count(profile, redis_client) < profile.max_streams


def pool_has_capacity_for_profile(profile, redis_client) -> bool:
    """Non-mutating check before reserve: profile slot and credential slot if applicable."""
    return profile_has_capacity_for_selection(profile, redis_client) and group_has_capacity_for_profile(
        profile, redis_client
    )


def _safe_decr(redis_client, key: str) -> None:
    current = int(redis_client.get(key) or 0)
    if current <= 0:
        return
    new_count = redis_client.decr(key)
    if new_count < 0:
        redis_client.set(key, 0)


def _reserve_server_group_slot_for_profile(profile, redis_client) -> bool:
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return True

    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return True

    cred_count = redis_client.incr(cred_key)
    if cred_count <= profile.max_streams:
        return True

    redis_client.decr(cred_key)
    return False


def _release_server_group_slot_for_profile(profile, redis_client) -> None:
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return
    cred_key = _credential_counter_key(profile, group)
    if cred_key:
        _safe_decr(redis_client, cred_key)


def reserve_profile_slot(profile, redis_client) -> Tuple[bool, int]:
    """
    Atomically reserve profile + optional credential slots (INCR-first).

    Returns (reserved, profile_count_after_attempt).
    """
    profile_key = profile_connections_key(profile.id)
    profile_count = 0

    if profile.max_streams > 0:
        profile_count = redis_client.incr(profile_key)
        if profile_count > profile.max_streams:
            redis_client.decr(profile_key)
            return False, profile_count - 1

    if not _reserve_server_group_slot_for_profile(profile, redis_client):
        if profile.max_streams > 0:
            redis_client.decr(profile_key)
        return False, profile_count - 1 if profile.max_streams > 0 else 0

    return True, profile_count


def release_profile_slot(profile_id: int, redis_client) -> None:
    """Release profile and shared credential slots after a stream end."""
    from apps.m3u.models import M3UAccountProfile

    try:
        profile = M3UAccountProfile.objects.get(id=profile_id)
    except M3UAccountProfile.DoesNotExist:
        profile = None

    profile_key = profile_connections_key(profile_id)
    if profile is None or profile.max_streams > 0:
        current = int(redis_client.get(profile_key) or 0)
        if current > 0:
            redis_client.decr(profile_key)

    if profile:
        _release_server_group_slot_for_profile(profile, redis_client)
