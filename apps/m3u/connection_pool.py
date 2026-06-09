"""
Shared connection pool enforcement for M3U accounts in the same ServerGroup.

Profile selection rotates across M3UAccountProfile rows using each profile's own
Redis counter (the pre-pool behavior). When an account belongs to a ServerGroup, a credential-scoped counter is checked on reserve/release
so accounts sharing the same provider login share one limit without blocking
unrelated logins on the same group. Account profiles with max_streams=0 skip
credential enforcement for that profile.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Literal, Optional, Tuple

logger = logging.getLogger(__name__)

ReserveFailureReason = Literal["profile_full", "credential_full"]

PROFILE_CONNECTIONS_KEY = "profile_connections:{profile_id}"
PROFILE_CREDENTIAL_RELEASE_KEY = "profile_credential_release:{profile_id}"
SERVER_GROUP_CONNECTIONS_KEY = "server_group_connections:{group_id}:{fingerprint}"

_XC_URL_CREDENTIALS_RE = re.compile(
    r"/(?:live|movie|series)/([^/]+)/([^/]+)/",
    re.IGNORECASE,
)


def profile_connections_key(profile_id: int) -> str:
    return PROFILE_CONNECTIONS_KEY.format(profile_id=profile_id)


def profile_credential_release_key(profile_id: int) -> str:
    """Redis key storing the credential counter to release when the profile row is gone."""
    return PROFILE_CREDENTIAL_RELEASE_KEY.format(profile_id=profile_id)


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
    """Return the ServerGroup for credential pooling when the account is assigned to one."""
    group = profile.m3u_account.server_group
    if group:
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


def profile_has_capacity_for_selection(profile, redis_client) -> bool:
    """Per-profile capacity check used when rotating across profiles on one account."""
    if profile.max_streams == 0:
        return True
    return get_profile_connection_count(profile, redis_client) < profile.max_streams


def group_has_capacity_for_profile(profile, redis_client) -> bool:
    # Profiles with max_streams=0 skip credential enforcement entirely. An unlimited
    # profile in a pooled group can still stream while other accounts share the login.
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


def profile_available_for_channel_switch(
    profile, redis_client, *, channel_already_on_profile: bool
) -> bool:
    """
    Non-mutating capacity check when selecting a profile for an in-flight channel.

    If the channel already holds this profile's slots, skip re-checking capacity.
    """
    if channel_already_on_profile:
        return True
    return pool_has_capacity_for_profile(profile, redis_client)


def move_credential_slot_on_profile_switch(
    old_profile, new_profile, redis_client
) -> bool:
    """
    Move the shared credential counter when switching to a different provider login.

    Profile counters are managed separately by Channel.update_stream_profile().
    Returns False when the new profile's credential pool is full.
    """
    old_fp = get_profile_credential_fingerprint(old_profile)
    new_fp = get_profile_credential_fingerprint(new_profile)
    if old_fp == new_fp:
        return True

    released = _release_credential_slot_by_profile_id(old_profile.id, redis_client)
    if not released:
        _release_server_group_slot_for_profile(old_profile, redis_client)

    cred_reserved, cred_key = _reserve_server_group_slot_for_profile(
        new_profile, redis_client
    )
    if not cred_reserved:
        restore_reserved, restore_key = _reserve_server_group_slot_for_profile(
            old_profile, redis_client
        )
        if restore_reserved and restore_key:
            _remember_credential_release_key(
                old_profile.id, restore_key, redis_client
            )
        return False

    if cred_key:
        _remember_credential_release_key(new_profile.id, cred_key, redis_client)
    return True


def _safe_decr(redis_client, key: str) -> None:
    current = int(redis_client.get(key) or 0)
    if current <= 0:
        return
    new_count = redis_client.decr(key)
    if new_count < 0:
        redis_client.set(key, 0)


def _remember_credential_release_key(
    profile_id: int, cred_key: str, redis_client
) -> None:
    redis_client.set(profile_credential_release_key(profile_id), cred_key)


def _release_credential_slot_by_profile_id(profile_id: int, redis_client) -> bool:
    """Release a reserved credential counter using the key stored at reserve time."""
    release_key = profile_credential_release_key(profile_id)
    cred_key = redis_client.get(release_key)
    if not cred_key:
        return False

    if isinstance(cred_key, bytes):
        cred_key = cred_key.decode()
    _safe_decr(redis_client, cred_key)
    redis_client.delete(release_key)
    return True


def _reserve_server_group_slot_for_profile(
    profile, redis_client
) -> Tuple[bool, Optional[str]]:
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return True, None

    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return True, None

    cred_count = redis_client.incr(cred_key)
    if cred_count <= profile.max_streams:
        return True, cred_key

    redis_client.decr(cred_key)
    return False, None


def _release_server_group_slot_for_profile(profile, redis_client) -> None:
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return
    cred_key = _credential_counter_key(profile, group)
    if cred_key:
        _safe_decr(redis_client, cred_key)


def reserve_profile_slot(
    profile, redis_client
) -> Tuple[bool, int, Optional[ReserveFailureReason]]:
    """
    Atomically reserve profile + optional credential slots (INCR-first).

    Returns (reserved, profile_count_after_attempt, failure_reason).
    failure_reason is set when reserved is False.
    """
    profile_key = profile_connections_key(profile.id)
    profile_count = 0

    if profile.max_streams > 0:
        profile_count = redis_client.incr(profile_key)
        if profile_count > profile.max_streams:
            redis_client.decr(profile_key)
            return False, profile_count - 1, "profile_full"

    cred_reserved, cred_key = _reserve_server_group_slot_for_profile(
        profile, redis_client
    )
    if not cred_reserved:
        if profile.max_streams > 0:
            redis_client.decr(profile_key)
        return (
            False,
            profile_count - 1 if profile.max_streams > 0 else 0,
            "credential_full",
        )

    if cred_key:
        _remember_credential_release_key(profile.id, cred_key, redis_client)

    return True, profile_count, None


def release_profile_slot(profile_id: int, redis_client) -> None:
    """Release profile and shared credential slots after a stream end."""
    from apps.m3u.models import M3UAccountProfile

    released_via_stored_key = _release_credential_slot_by_profile_id(
        profile_id, redis_client
    )

    try:
        profile = M3UAccountProfile.objects.get(id=profile_id)
    except M3UAccountProfile.DoesNotExist:
        profile = None

    profile_key = profile_connections_key(profile_id)
    if profile is None or profile.max_streams > 0:
        current = int(redis_client.get(profile_key) or 0)
        if current > 0:
            redis_client.decr(profile_key)

    if profile and not released_via_stored_key:
        _release_server_group_slot_for_profile(profile, redis_client)
