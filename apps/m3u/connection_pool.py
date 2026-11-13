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
from urllib.parse import unquote, urlparse

from redis.exceptions import WatchError

logger = logging.getLogger(__name__)

ReserveFailureReason = Literal["profile_full", "credential_full"]

PROFILE_CONNECTIONS_KEY = "profile_connections:{profile_id}"
PROFILE_CREDENTIAL_RELEASE_KEY = "profile_credential_release:{profile_id}"
SERVER_GROUP_CONNECTIONS_KEY = "server_group_connections:{group_id}:{fingerprint}"

RELEASE_MAX_ATTEMPTS = 10

# Typed Xtream paths: /live|movie|series/<user>/<pass>/...
_XC_URL_CREDENTIALS_RE = re.compile(
    r"/(?:live|movie|series)/([^/]+)/([^/]+)/",
    re.IGNORECASE,
)

# First path segment values that are XC API/path roots, not usernames.
_XC_SHORT_FORM_RESERVED_FIRST_SEGMENTS = frozenset(
    {
        "live",
        "movie",
        "series",
        "timeshift",
        "player_api.php",
        "panel_api.php",
        "xmltv.php",
    }
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


def extract_typed_xc_credentials(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse credentials from /live|movie|series/<user>/<pass>/ paths."""
    if not url:
        return None, None
    match = _XC_URL_CREDENTIALS_RE.search(url)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def extract_short_form_xc_credentials(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse credentials from short-form stream URLs: /<user>/<pass>/<id>.

    Requires exactly three non-empty path segments. The stream id may be numeric
    or not, and may include a media extension. Empty segments (trailing slash or
    "//") are rejected rather than collapsed. Reserved first segments are also
    rejected so incomplete typed paths are not treated as logins.
    """
    if not url:
        return None, None

    path = urlparse(url).path or ""
    if not path.startswith("/"):
        return None, None

    segments = path[1:].split("/")
    if len(segments) != 3 or not all(segments):
        return None, None

    username, password, _stream_part = (unquote(part) for part in segments)
    if username.lower() in _XC_SHORT_FORM_RESERVED_FIRST_SEGMENTS:
        return None, None
    return username, password


def _transformed_sample_stream_url(profile) -> Optional[str]:
    """Return one profile-rewritten stream URL for credential fingerprinting."""
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

        return transform_url(
            sample_url,
            profile.search_pattern or "",
            profile.replace_pattern or "",
        )
    except Exception as exc:
        logger.debug(
            "Could not transform sample stream URL for profile %s: %s",
            profile.pk,
            exc,
        )
        return None


def get_profile_credential_fingerprint(profile) -> Optional[str]:
    """Fingerprint for credentials this profile uses at playback time.

    Resolution order (after XC account credential transforms):
    1. Typed Xtream path credentials in a sample stream URL
    2. Account username/password
    3. Short-form Xtream path credentials in a sample stream URL

    Account credentials are preferred over short-form URL parsing so CDN-style
    three-segment paths cannot override an explicit login and break ServerGroup
    pairing with XC accounts. Short-form remains available for STD M3U accounts
    whose only login is embedded in /user/pass/id URLs.
    """
    m3u_account = profile.m3u_account

    if m3u_account.account_type == "XC":
        try:
            from apps.m3u.credentials import get_transformed_credentials

            _url, username, password = get_transformed_credentials(m3u_account, profile)
            if username and password:
                fingerprint = compute_credential_fingerprint(username, password)
                if fingerprint:
                    return fingerprint
            # Patterns configured but transform failed.
            if profile.search_pattern and profile.replace_pattern:
                return None
        except Exception as exc:
            logger.debug(
                "Could not resolve transformed credentials for profile %s: %s",
                profile.pk,
                exc,
            )
            if profile.search_pattern and profile.replace_pattern:
                return None

    transformed = _transformed_sample_stream_url(profile)
    if transformed:
        url_user, url_pass = extract_typed_xc_credentials(transformed)
        fingerprint = compute_credential_fingerprint(url_user or "", url_pass or "")
        if fingerprint:
            return fingerprint

    fingerprint = compute_credential_fingerprint(
        m3u_account.username or "",
        m3u_account.password or "",
    )
    if fingerprint:
        return fingerprint

    if transformed:
        url_user, url_pass = extract_short_form_xc_credentials(transformed)
        return compute_credential_fingerprint(url_user or "", url_pass or "")

    return None


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
        # Profile is in an enforced group but its login can't be fingerprinted
        return False
    return int(redis_client.get(cred_key) or 0) < profile.max_streams


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
    Move the shared credential counter when a stream switches profiles.

    Profile counters are managed separately by Channel.update_stream_profile().
    When both profiles hold a slot on the same credential counter, the slot stays
    where it is and only the new profile's release key is armed, so ending the
    stream on the new profile still frees it. Returns False when the new profile's
    credential pool is full.
    """
    old_slot_key = _held_credential_slot_key(old_profile)
    new_slot_key = _held_credential_slot_key(new_profile)
    if old_slot_key == new_slot_key:
        if new_slot_key:
            _remember_credential_release_key(new_profile.id, new_slot_key, redis_client)
        return True

    _release_credential_slot_by_profile_id(old_profile.id, redis_client)

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


def _held_credential_slot_key(profile) -> Optional[str]:
    """Credential counter key a reservation on this profile holds, or None if it holds none."""
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return None
    return _credential_counter_key(profile, group)


def _remember_credential_release_key(
    profile_id: int, cred_key: str, redis_client
) -> None:
    redis_client.set(profile_credential_release_key(profile_id), cred_key)


def _release_credential_slot_by_profile_id(
    profile_id: int, redis_client, *, release_profile: bool = False
) -> bool:
    """
    Release one credential slot for the profile, and its profile slot if requested.

    The stored credential key is kept until the profile's last reservation ends so
    every stream sharing the profile can still find it. Concurrent counter changes
    are retried; after RELEASE_MAX_ATTEMPTS conflicts the release is abandoned with
    a warning instead of blocking stream teardown.

    Returns True when the pipeline committed (including a no-op when counters
    were already zero). Returns False when every attempt hit WatchError.
    """
    release_key = profile_credential_release_key(profile_id)
    profile_key = profile_connections_key(profile_id)
    for _ in range(RELEASE_MAX_ATTEMPTS):
        with redis_client.pipeline() as pipe:
            try:
                pipe.watch(release_key, profile_key)
                profile_count = int(pipe.get(profile_key) or 0)
                cred_key = pipe.get(release_key)
                if isinstance(cred_key, bytes):
                    cred_key = cred_key.decode()
                if cred_key:
                    pipe.watch(cred_key)
                    cred_count = int(pipe.get(cred_key) or 0)

                # Watch the reads and commit both decrements together so concurrent
                # teardowns cannot consume the same final reservation.
                pipe.multi()
                if cred_key and profile_count > 0 and cred_count > 0:
                    pipe.decr(cred_key)
                if profile_count <= 1:
                    pipe.delete(release_key)
                if release_profile and profile_count > 0:
                    pipe.decr(profile_key)
                pipe.execute()
                return True
            except WatchError:
                continue

    logger.warning(
        "Gave up releasing connection slots for profile %s after %d conflicting "
        "updates; its counters may be stale",
        profile_id,
        RELEASE_MAX_ATTEMPTS,
    )
    return False


def _reserve_server_group_slot_for_profile(
    profile, redis_client
) -> Tuple[bool, Optional[str]]:
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return True, None

    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return False, None

    cred_count = redis_client.incr(cred_key)
    if cred_count <= profile.max_streams:
        return True, cred_key

    redis_client.decr(cred_key)
    return False, None


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


def release_profile_slot(profile_id: int, redis_client) -> bool:
    """Release profile and shared credential slots after a stream end.

    Returns True when the Redis update committed, False when concurrent
    updates exhausted the retry budget and the release was abandoned.
    """
    return _release_credential_slot_by_profile_id(
        profile_id, redis_client, release_profile=True
    )


# -- Per-connection User-Agent numbering ------------------------------------
#
# Some providers' middleware mishandles multiple concurrent connections
# from the same account that present an
# identical User-Agent string. Giving each concurrently-active stream on the
# account a distinct, reused-when-free slot number lets the resolved
# User-Agent vary per connection (M3UAccount.vary_user_agent, see
# apps/m3u/models.py) without touching the existing profile/credential
# reservation above. A free-list (not the profile_connections counter, which
# only tracks a count and can hand the same number to two connections that
# are simultaneously live -- see UA_SLOT_FREE_LIST_KEY below) guarantees two
# live connections never share a number.

UA_SLOT_FREE_LIST_KEY = "ua_slot_free:{profile_id}"
UA_SLOT_COUNTER_KEY = "ua_slot_counter:{profile_id}"


def reserve_ua_slot(profile_id: int, redis_client) -> int:
    """Hand out a per-connection slot number, reusing a released one first.

    Numbers start at 1 and are never reused by two simultaneously-held
    connections: a release pushes the number back onto a free list, and a
    reservation pops from that list before minting a new one.
    """
    free_list_key = UA_SLOT_FREE_LIST_KEY.format(profile_id=profile_id)
    popped = redis_client.lpop(free_list_key)
    if popped is not None:
        return int(popped)
    counter_key = UA_SLOT_COUNTER_KEY.format(profile_id=profile_id)
    return redis_client.incr(counter_key)


def release_ua_slot(profile_id: int, slot_index: Optional[int], redis_client) -> None:
    """Return a per-connection slot number to the free list for reuse."""
    if slot_index is None:
        return
    free_list_key = UA_SLOT_FREE_LIST_KEY.format(profile_id=profile_id)
    redis_client.rpush(free_list_key, slot_index)
