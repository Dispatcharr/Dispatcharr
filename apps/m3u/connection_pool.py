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
import json
import logging
import re
from typing import Any, Dict, Iterable, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

ReserveFailureReason = Literal["profile_full", "credential_full"]

PROFILE_CONNECTIONS_KEY = "profile_connections:{profile_id}"
PROFILE_CONNECTIONS_VERSION_KEY = "profile_connections_version:{profile_id}"
PROFILE_RECONCILE_LOCK_KEY = "profile_connections_reconcile:{profile_id}"
PROFILE_CREDENTIAL_RELEASE_KEY = "profile_credential_release:{profile_id}"
SERVER_GROUP_CONNECTIONS_KEY = "server_group_connections:{group_id}:{fingerprint}"
VOD_PROFILE_RESERVATION_KEY = "vod_profile_reservation:{session_id}"
VOD_PROFILE_RESERVATION_TTL = 3600
VOD_PROFILE_PENDING_RESERVATION_TTL = 30
PROFILE_RECONCILE_COOLDOWN = 5

_LUA_RESERVE_OWNED_PROFILE = """
-- reserve_owned_profile
local counter_key = KEYS[1]
local marker_key = KEYS[2]
local version_key = KEYS[3]
local credential_release_key = KEYS[4]
local profile_id = ARGV[1]
local max_streams = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local credential_key = ARGV[4]
local credential_payload = ARGV[5]
local existing = redis.call('GET', marker_key)
local current = tonumber(redis.call('GET', counter_key) or '0')
if existing == profile_id then
  redis.call('EXPIRE', marker_key, ttl)
  if credential_key ~= '' and redis.call('EXISTS', credential_release_key) == 0 then
    local credential_count = redis.call('INCR', credential_key)
    if credential_count > max_streams then
      redis.call('DECR', credential_key)
      redis.call('DEL', marker_key)
      if current > 0 then
        current = redis.call('DECR', counter_key)
        redis.call('INCR', version_key)
      end
      return {-2, current}
    end
    redis.call('SET', credential_release_key, credential_payload)
  end
  return {2, current}
end
if existing then
  return {-1, current}
end
local new_count = redis.call('INCR', counter_key)
redis.call('INCR', version_key)
if new_count > max_streams then
  redis.call('DECR', counter_key)
  redis.call('INCR', version_key)
  return {0, new_count - 1}
end
if credential_key ~= '' then
  local credential_count = redis.call('INCR', credential_key)
  if credential_count > max_streams then
    redis.call('DECR', credential_key)
    redis.call('DECR', counter_key)
    redis.call('INCR', version_key)
    return {-2, new_count - 1}
  end
  redis.call('SET', credential_release_key, credential_payload)
end
redis.call('SET', marker_key, profile_id, 'EX', ttl)
return {1, new_count}
"""

_LUA_RELEASE_OWNED_PROFILE = """
-- release_owned_profile
local counter_key = KEYS[1]
local marker_key = KEYS[2]
local version_key = KEYS[3]
local credential_release_key = KEYS[4]
local profile_id = ARGV[1]
local existing = redis.call('GET', marker_key)
local current = tonumber(redis.call('GET', counter_key) or '0')
if existing ~= profile_id then
  return {0, current}
end
redis.call('DEL', marker_key)
local credential_payload = redis.call('GET', credential_release_key)
if credential_payload then
  local ok, decoded = pcall(cjson.decode, credential_payload)
  if ok and decoded and decoded['credential_key'] then
    local credential_key = decoded['credential_key']
    local credential_count = tonumber(redis.call('GET', credential_key) or '0')
    if credential_count > 0 then
      redis.call('DECR', credential_key)
    end
  end
  redis.call('DEL', credential_release_key)
end
if current > 0 then
  current = redis.call('DECR', counter_key)
  redis.call('INCR', version_key)
end
return {1, current}
"""

_LUA_RECONCILE_PROFILE = """
-- reconcile_profile_counter
local counter_key = KEYS[1]
local version_key = KEYS[2]
local observed_count = tonumber(ARGV[1])
local observed_version = tonumber(ARGV[2])
local expected_count = tonumber(ARGV[3])
local current = tonumber(redis.call('GET', counter_key) or '0')
local version = tonumber(redis.call('GET', version_key) or '0')
if current == observed_count and version == observed_version and expected_count < current then
  redis.call('SET', counter_key, expected_count)
  redis.call('INCR', version_key)
  return {1, expected_count}
end
return {0, current}
"""

_LUA_RELEASE_CREDENTIAL = """
-- release_credential
local release_key = KEYS[1]
local expected_payload = ARGV[1]
local credential_key = ARGV[2]
if redis.call('GET', release_key) ~= expected_payload then
  return 0
end
redis.call('DEL', release_key)
local current = tonumber(redis.call('GET', credential_key) or '0')
if current > 0 then
  redis.call('DECR', credential_key)
end
return 1
"""

_LUA_RELEASE_ORPHANED_CREDENTIAL = """
-- release_orphaned_credential
local release_key = KEYS[1]
local owner_key = KEYS[2]
local expected_payload = ARGV[1]
local credential_key = ARGV[2]
local profile_id = ARGV[3]
if redis.call('GET', owner_key) == profile_id then
  return 0
end
if redis.call('GET', release_key) ~= expected_payload then
  return 0
end
redis.call('DEL', release_key)
local current = tonumber(redis.call('GET', credential_key) or '0')
if current > 0 then
  redis.call('DECR', credential_key)
end
return 1
"""

_profile_script_cache: Dict[int, Dict[str, Any]] = {}

_XC_URL_CREDENTIALS_RE = re.compile(
    r"/(?:live|movie|series)/([^/]+)/([^/]+)/",
    re.IGNORECASE,
)


def profile_connections_key(profile_id: int) -> str:
    return PROFILE_CONNECTIONS_KEY.format(profile_id=profile_id)


def profile_connections_version_key(profile_id: int) -> str:
    return PROFILE_CONNECTIONS_VERSION_KEY.format(profile_id=profile_id)


def profile_reconcile_lock_key(profile_id: int) -> str:
    return PROFILE_RECONCILE_LOCK_KEY.format(profile_id=profile_id)


def profile_credential_release_key(
    profile_id: int, reservation_key: Optional[str] = None
) -> str:
    """Redis key storing the credential counter for a profile or owned reservation."""
    key = PROFILE_CREDENTIAL_RELEASE_KEY.format(profile_id=profile_id)
    if reservation_key:
        owner_hash = hashlib.sha256(reservation_key.encode("utf-8")).hexdigest()[:16]
        return f"{key}:{owner_hash}"
    return key


def server_group_connections_key(group_id: int, fingerprint: str) -> str:
    """Redis key for per-credential usage within a ServerGroup."""
    return SERVER_GROUP_CONNECTIONS_KEY.format(
        group_id=group_id,
        fingerprint=fingerprint[:16],
    )


def vod_profile_reservation_key(session_id: str) -> str:
    return VOD_PROFILE_RESERVATION_KEY.format(session_id=session_id)


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
        if not transformed:
            return None
        url_user, url_pass = extract_credentials_from_stream_url(transformed)
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
    Move the shared credential counter when switching to a different provider login.

    Profile counters are managed separately by Channel.update_stream_profile().
    Returns False when the new profile's credential pool is full.
    """
    old_fp = get_profile_credential_fingerprint(old_profile)
    new_fp = get_profile_credential_fingerprint(new_profile)
    if old_fp == new_fp:
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


def _profile_scripts(redis_client) -> Dict[str, Any]:
    cache_key = id(redis_client)
    scripts = _profile_script_cache.get(cache_key)
    if scripts is None:
        scripts = {
            "reserve_owned": redis_client.register_script(
                _LUA_RESERVE_OWNED_PROFILE
            ),
            "release_owned": redis_client.register_script(
                _LUA_RELEASE_OWNED_PROFILE
            ),
            "reconcile": redis_client.register_script(_LUA_RECONCILE_PROFILE),
            "release_credential": redis_client.register_script(
                _LUA_RELEASE_CREDENTIAL
            ),
            "release_orphaned_credential": redis_client.register_script(
                _LUA_RELEASE_ORPHANED_CREDENTIAL
            ),
        }
        _profile_script_cache[cache_key] = scripts
    return scripts


def _decode(value):
    return value.decode() if isinstance(value, bytes) else value


def _scan_batches(redis_client, pattern: str, size: int = 200) -> Iterable[list]:
    batch = []
    for key in redis_client.scan_iter(match=pattern, count=size):
        batch.append(key)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _count_string_reservations(redis_client, pattern: str, profile_id: int):
    """Return matching value count and key suffixes using batched MGETs."""
    wanted = str(profile_id)
    count = 0
    suffixes = set()
    prefix = pattern[:-1]
    for keys in _scan_batches(redis_client, pattern):
        for key, value in zip(keys, redis_client.mget(keys)):
            if str(_decode(value)) != wanted:
                continue
            count += 1
            suffixes.add(str(_decode(key))[len(prefix):])
    return count, suffixes


def _matching_string_reservations(redis_client, pattern: str, profile_id: int):
    """Return ``{key_suffix: redis_key}`` for matching string values."""
    wanted = str(profile_id)
    matches = {}
    prefix = pattern[:-1]
    for keys in _scan_batches(redis_client, pattern):
        for key, value in zip(keys, redis_client.mget(keys)):
            if str(_decode(value)) == wanted:
                decoded_key = str(_decode(key))
                matches[decoded_key[len(prefix):]] = key
    return matches


def reconcile_profile_connection_count(profile_id: int, redis_client) -> int:
    """Repair a stale profile counter from active Redis ownership records.

    This intentionally performs scans only after a capacity rejection.  The
    versioned compare-and-set prevents a concurrent reservation/release from
    being overwritten while the active records are being inspected.
    """
    counter_key = profile_connections_key(profile_id)
    version_key = profile_connections_version_key(profile_id)
    observed_count = int(redis_client.get(counter_key) or 0)
    observed_version = int(redis_client.get(version_key) or 0)
    if observed_count <= 0:
        return 0
    if not redis_client.set(
        profile_reconcile_lock_key(profile_id),
        "1",
        nx=True,
        ex=PROFILE_RECONCILE_COOLDOWN,
    ):
        return observed_count

    live_count, _ = _count_string_reservations(
        redis_client, "stream_profile:*", profile_id
    )
    vod_markers = _matching_string_reservations(
        redis_client, "vod_profile_reservation:*", profile_id
    )

    active_vod_sessions = set()
    for keys in _scan_batches(redis_client, "vod_persistent_connection:*"):
        pipe = redis_client.pipeline(transaction=False)
        for key in keys:
            pipe.hmget(key, "m3u_profile_id", "active_streams")
        for key, values in zip(keys, pipe.execute()):
            if not values:
                continue
            stored_profile, active_streams = (_decode(v) for v in values)
            session_id = str(_decode(key)).split(":", 1)[1]
            if (
                str(stored_profile) == str(profile_id)
                and int(active_streams or 0) > 0
            ):
                active_vod_sessions.add(session_id)

    # Every existing marker is an owned VOD slot. New reservations get a short
    # setup TTL; creating/saving the session extends it to the active-session TTL.
    # Let Redis expire abandoned setup markers instead of guessing from their age.
    owned_vod_sessions = set(vod_markers)
    active_owned_vod_count = len(active_vod_sessions & owned_vod_sessions)
    pending_vod_count = len(owned_vod_sessions - active_vod_sessions)
    legacy_vod_count = len(active_vod_sessions - owned_vod_sessions)
    vod_marker_count = active_owned_vod_count + pending_vod_count

    _release_orphaned_owned_credential_slots(
        profile_id,
        redis_client,
    )

    timeshift_count = 0
    for keys in _scan_batches(redis_client, "timeshift:pool:*"):
        pool_keys = [
            key for key in keys
            if not str(_decode(key)).endswith((":lock", ":superseded"))
        ]
        if not pool_keys:
            continue
        pipe = redis_client.pipeline(transaction=False)
        for key in pool_keys:
            pipe.hmget(key, "profile_id", "busy")
        for values in pipe.execute():
            if not values:
                continue
            stored_profile, busy = (_decode(v) for v in values)
            if str(stored_profile) == str(profile_id) and str(busy) == "1":
                timeshift_count += 1

    expected_count = (
        live_count + vod_marker_count + legacy_vod_count + timeshift_count
    )
    if expected_count >= observed_count:
        return observed_count
    result = _profile_scripts(redis_client)["reconcile"](
        keys=[counter_key, version_key],
        args=[observed_count, observed_version, expected_count],
    )
    repaired = bool(int(result[0]))
    final_count = int(result[1])
    if repaired:
        logger.warning(
            "Reconciled stale profile %s connection counter from %s to %s "
            "(live=%s, vod=%s, legacy_vod=%s, timeshift=%s)",
            profile_id,
            observed_count,
            final_count,
            live_count,
            vod_marker_count,
            legacy_vod_count,
            timeshift_count,
        )
    return final_count


def _remember_credential_release_key(
    profile_id: int,
    cred_key: str,
    redis_client,
    reservation_key: Optional[str] = None,
) -> None:
    payload = cred_key
    if reservation_key:
        payload = json.dumps(
            {
                "credential_key": cred_key,
                "reservation_key": reservation_key,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    redis_client.set(
        profile_credential_release_key(profile_id, reservation_key), payload
    )


def _credential_release_payload(raw_payload):
    payload = str(_decode(raw_payload))
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError):
        return payload, None, payload
    if not isinstance(decoded, dict):
        return payload, None, payload
    return decoded.get("credential_key"), decoded.get("reservation_key"), payload


def _release_credential_slot_from_key(
    release_key,
    redis_client,
    *,
    only_if_owner_missing: bool = False,
    profile_id: Optional[int] = None,
) -> bool:
    raw_payload = redis_client.get(release_key)
    if not raw_payload:
        return False
    cred_key, reservation_key, expected_payload = _credential_release_payload(
        raw_payload
    )
    if not cred_key:
        return False

    if only_if_owner_missing:
        if not reservation_key or profile_id is None:
            return False
        result = _profile_scripts(redis_client)["release_orphaned_credential"](
            keys=[release_key, reservation_key],
            args=[expected_payload, cred_key, profile_id],
        )
    else:
        result = _profile_scripts(redis_client)["release_credential"](
            keys=[release_key],
            args=[expected_payload, cred_key],
        )
    return bool(int(result or 0))


def _release_orphaned_owned_credential_slots(profile_id: int, redis_client) -> int:
    """Release VOD credential slots whose session reservation has disappeared."""
    released = 0
    pattern = f"{profile_credential_release_key(profile_id)}:*"
    for keys in _scan_batches(redis_client, pattern):
        for release_key in keys:
            raw_payload = redis_client.get(release_key)
            if not raw_payload:
                continue
            _cred_key, reservation_key, _payload = _credential_release_payload(
                raw_payload
            )
            if not reservation_key:
                continue
            if str(_decode(redis_client.get(reservation_key))) == str(profile_id):
                continue
            if _release_credential_slot_from_key(
                release_key,
                redis_client,
                only_if_owner_missing=True,
                profile_id=profile_id,
            ):
                released += 1
    return released


def _release_credential_slot_by_profile_id(
    profile_id: int,
    redis_client,
    reservation_key: Optional[str] = None,
) -> bool:
    """Release a reserved credential counter using the key stored at reserve time."""
    release_key = profile_credential_release_key(profile_id, reservation_key)
    return _release_credential_slot_from_key(release_key, redis_client)


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
    profile,
    redis_client,
    *,
    reservation_key: Optional[str] = None,
    reservation_ttl: int = VOD_PROFILE_PENDING_RESERVATION_TTL,
) -> Tuple[bool, int, Optional[ReserveFailureReason]]:
    """
    Atomically reserve profile + optional credential slots (INCR-first).

    Returns (reserved, profile_count_after_attempt, failure_reason).
    failure_reason is set when reserved is False.
    """
    profile_key = profile_connections_key(profile.id)
    version_key = profile_connections_version_key(profile.id)
    profile_count = 0
    already_reserved = False

    if profile.max_streams > 0:
        if reservation_key:
            credential_key = ""
            group = get_enforced_server_group_for_profile(profile)
            if group:
                credential_key = _credential_counter_key(profile, group) or ""
            credential_release_key = profile_credential_release_key(
                profile.id, reservation_key
            )
            credential_payload = ""
            if credential_key:
                credential_payload = json.dumps(
                    {
                        "credential_key": credential_key,
                        "reservation_key": reservation_key,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            result = _profile_scripts(redis_client)["reserve_owned"](
                keys=[
                    profile_key,
                    reservation_key,
                    version_key,
                    credential_release_key,
                ],
                args=[
                    profile.id,
                    profile.max_streams,
                    reservation_ttl,
                    credential_key,
                    credential_payload,
                ],
            )
            status = int(result[0])
            profile_count = int(result[1])
            if status == 0:
                return False, profile_count, "profile_full"
            if status == -2:
                return False, profile_count, "credential_full"
            if status < 0:
                return False, profile_count, "profile_full"
            already_reserved = status == 2
        else:
            profile_count = redis_client.incr(profile_key)
            redis_client.incr(version_key)
            if profile_count > profile.max_streams:
                redis_client.decr(profile_key)
                redis_client.incr(version_key)
                return False, profile_count - 1, "profile_full"

    if already_reserved:
        return True, profile_count, None

    if reservation_key:
        return True, profile_count, None

    cred_reserved, cred_key = _reserve_server_group_slot_for_profile(
        profile, redis_client
    )
    if not cred_reserved:
        if profile.max_streams > 0:
            redis_client.decr(profile_key)
            redis_client.incr(version_key)
        return (
            False,
            profile_count - 1 if profile.max_streams > 0 else 0,
            "credential_full",
        )

    if cred_key:
        _remember_credential_release_key(profile.id, cred_key, redis_client)

    return True, profile_count, None


def release_profile_slot(
    profile_id: int,
    redis_client,
    *,
    reservation_key: Optional[str] = None,
) -> None:
    """Release profile and shared credential slots after a stream end."""
    profile_key = profile_connections_key(profile_id)
    version_key = profile_connections_version_key(profile_id)

    if reservation_key:
        credential_release_key = profile_credential_release_key(
            profile_id, reservation_key
        )
        result = _profile_scripts(redis_client)["release_owned"](
            keys=[
                profile_key,
                reservation_key,
                version_key,
                credential_release_key,
            ],
            args=[profile_id],
        )
        if not bool(int(result[0])):
            return
        return

    _release_credential_slot_by_profile_id(profile_id, redis_client)

    current = int(redis_client.get(profile_key) or 0)
    if current > 0:
        redis_client.decr(profile_key)
        redis_client.incr(version_key)
