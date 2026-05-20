"""
Shared connection pool enforcement for M3U accounts with identical credentials.

All Redis INCR/DECR for profile and server-group limits should go through this
module so live TV and VOD stay consistent.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

PROFILE_CONNECTIONS_KEY = "profile_connections:{profile_id}"
SERVER_GROUP_CONNECTIONS_KEY = "server_group_connections:{group_id}"
EXCLUDE_FROM_POOL_KEY = "exclude_from_credential_pool"

_XC_URL_CREDENTIALS_RE = re.compile(
    r"/(?:live|movie|series)/([^/]+)/([^/]+)/",
    re.IGNORECASE,
)


def profile_connections_key(profile_id: int) -> str:
    return PROFILE_CONNECTIONS_KEY.format(profile_id=profile_id)


def server_group_connections_key(group_id: int) -> str:
    return SERVER_GROUP_CONNECTIONS_KEY.format(group_id=group_id)


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


def account_excluded_from_pool(m3u_account) -> bool:
    props = m3u_account.custom_properties or {}
    return bool(props.get(EXCLUDE_FROM_POOL_KEY))


def _get_pool_for_fingerprint(fingerprint: str):
    """Return the auto credential pool ServerGroup for a fingerprint, if configured."""
    if not fingerprint:
        return None
    from apps.m3u.models import ServerGroup

    group = ServerGroup.objects.filter(credential_fingerprint=fingerprint).first()
    if not group or group.max_streams == 0:
        return None
    return group


def get_enforced_server_group_for_profile(profile):
    """Return the shared pool for this profile's effective provider login."""
    if account_excluded_from_pool(profile.m3u_account):
        return None

    group = _get_pool_for_fingerprint(get_profile_credential_fingerprint(profile))
    if group:
        return group

    manual = profile.m3u_account.server_group
    if manual and not manual.credential_fingerprint and manual.max_streams > 0:
        return manual
    return None


def pool_has_capacity_for_profile(profile, redis_client) -> bool:
    """Non-mutating check for the profile's credential pool."""
    group = get_enforced_server_group_for_profile(profile)
    if not group:
        return True
    key = server_group_connections_key(group.id)
    current = int(redis_client.get(key) or 0)
    return current < group.max_streams


def _reserve_server_group_slot_for_profile(profile, redis_client) -> bool:
    group = get_enforced_server_group_for_profile(profile)
    if not group:
        return True
    key = server_group_connections_key(group.id)
    group_count = redis_client.incr(key)
    if group_count <= group.max_streams:
        return True
    redis_client.decr(key)
    return False


def _release_server_group_slot_for_profile(profile, redis_client) -> None:
    group = get_enforced_server_group_for_profile(profile)
    if not group:
        return
    key = server_group_connections_key(group.id)
    new_count = redis_client.decr(key)
    if new_count < 0:
        redis_client.set(key, 0)


def reserve_profile_slot(profile, redis_client) -> Tuple[bool, int]:
    """
    Atomically reserve profile + shared pool slots (INCR-first).

    Returns (reserved, profile_count_after_attempt).
    """
    if profile.max_streams == 0:
        if _reserve_server_group_slot_for_profile(profile, redis_client):
            return True, 0
        return False, 0

    profile_key = profile_connections_key(profile.id)
    new_count = redis_client.incr(profile_key)

    if new_count <= profile.max_streams:
        if _reserve_server_group_slot_for_profile(profile, redis_client):
            return True, new_count
        redis_client.decr(profile_key)
        return False, new_count - 1

    redis_client.decr(profile_key)
    return False, new_count - 1


def release_profile_slot(profile_id: int, redis_client) -> None:
    """Release profile and shared pool slots after a stream ends."""
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


def recompute_pool_max_streams(server_group) -> None:
    """Set pool max_streams to the minimum positive limit across members and profiles."""
    from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup

    if not server_group.credential_fingerprint:
        return

    fp = server_group.credential_fingerprint
    limits = list(
        M3UAccount.objects.filter(
            server_group=server_group, max_streams__gt=0
        ).values_list("max_streams", flat=True)
    )

    for profile in M3UAccountProfile.objects.filter(is_active=True).select_related(
        "m3u_account"
    ):
        if account_excluded_from_pool(profile.m3u_account):
            continue
        if get_profile_credential_fingerprint(profile) != fp:
            continue
        if profile.max_streams > 0:
            limits.append(profile.max_streams)

    new_max = min(limits) if limits else 0
    if server_group.max_streams != new_max:
        ServerGroup.objects.filter(pk=server_group.pk).update(max_streams=new_max)


def _ensure_pool_for_fingerprint(fingerprint: str):
    from apps.m3u.models import ServerGroup

    group, _created = ServerGroup.objects.get_or_create(
        credential_fingerprint=fingerprint,
        defaults={
            "name": f"credential-pool-{fingerprint[:16]}",
            "max_streams": 0,
        },
    )
    recompute_pool_max_streams(group)
    return group


def sync_account_credential_pool(m3u_account) -> None:
    """
    Ensure auto credential pools exist for each distinct login on this account.

    Sets M3UAccount.server_group only when every active profile shares one login.
    """
    from apps.m3u.models import M3UAccount, M3UAccountProfile

    if account_excluded_from_pool(m3u_account):
        return

    if m3u_account.server_group_id:
        existing = m3u_account.server_group
        if existing and not existing.credential_fingerprint:
            return

    profile_fps = set()
    for profile in M3UAccountProfile.objects.filter(
        m3u_account=m3u_account, is_active=True
    ):
        fp = get_profile_credential_fingerprint(profile)
        if not fp:
            continue
        profile_fps.add(fp)
        _ensure_pool_for_fingerprint(fp)

    if len(profile_fps) == 1:
        group = _get_pool_for_fingerprint(next(iter(profile_fps)))
        if group and m3u_account.server_group_id != group.id:
            M3UAccount.objects.filter(pk=m3u_account.pk).update(server_group=group)
    elif m3u_account.server_group_id:
        existing = m3u_account.server_group
        if existing and existing.credential_fingerprint:
            M3UAccount.objects.filter(pk=m3u_account.pk).update(server_group=None)
