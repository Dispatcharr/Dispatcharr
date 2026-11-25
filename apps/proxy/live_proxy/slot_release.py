"""Single-winner release of an M3U profile slot from live-proxy Redis state.

Overlapping teardowns (API stop plus CHANNEL_STOP, or release_stream plus the
metadata fallback) must decrement profile_connections exactly once. The
m3u_profile field on the worker metadata hash is the shared token: whoever
removes it releases the slot. If release_profile_slot fails or abandons after
the claim, the token is restored so another teardown can finish the release.
"""

from __future__ import annotations

import logging

from redis.exceptions import ResponseError

from apps.m3u.connection_pool import release_profile_slot

from .constants import ChannelMetadataField

logger = logging.getLogger(__name__)

_getdel_unsupported = False


def redis_getdel(redis_client, key):
    """GETDEL when available; fall back to GET+DELETE once Redis is too old.

    Happy path is a single GETDEL with no version probe. The first unsupported
    response is logged and remembered for this process.
    """
    global _getdel_unsupported
    if _getdel_unsupported:
        value = redis_client.get(key)
        if value is not None:
            redis_client.delete(key)
        return value

    try:
        return redis_client.getdel(key)
    except AttributeError as exc:
        _getdel_unsupported = True
        logger.error(
            "Redis client has no GETDEL (%s). Falling back to GET+DELETE. "
            "Upgrade Redis to 6.2 or newer.",
            exc,
        )
    except ResponseError as exc:
        message = str(exc).lower()
        if "unknown command" not in message and "getdel" not in message:
            raise
        _getdel_unsupported = True
        logger.error(
            "Redis GETDEL is unavailable (%s). Falling back to GET+DELETE. "
            "Upgrade Redis to 6.2 or newer.",
            exc,
        )

    value = redis_client.get(key)
    if value is not None:
        redis_client.delete(key)
    return value


def _restore_claimed_profile(redis_client, metadata_key, claimed_token, log_label):
    try:
        redis_client.hset(
            metadata_key,
            mapping={ChannelMetadataField.M3U_PROFILE: claimed_token},
        )
    except Exception as restore_exc:
        logger.error(
            "%s: failed to restore m3u_profile after release error: %s",
            log_label,
            restore_exc,
        )


def claim_and_release_profile_slot(
    redis_client,
    metadata_key,
    meta_profile_id,
    profile_id,
    *,
    log_label,
) -> bool:
    """Claim m3u_profile (when present) and release the slot once.

    Returns False when another teardown already took the token, or when the
    counter update was abandoned after watch conflicts. Returns True after a
    successful release. Restores m3u_profile if release_profile_slot raises or
    returns False after a successful claim so the slot is not permanently leaked.
    """
    claimed_token = None
    if metadata_key is not None and meta_profile_id:
        if not redis_client.hdel(metadata_key, ChannelMetadataField.M3U_PROFILE):
            logger.debug(
                "%s: profile slot already released by a concurrent teardown",
                log_label,
            )
            return False
        claimed_token = meta_profile_id

    try:
        released = release_profile_slot(profile_id, redis_client)
    except Exception:
        if claimed_token is not None:
            _restore_claimed_profile(
                redis_client, metadata_key, claimed_token, log_label
            )
        raise

    if not released:
        if claimed_token is not None:
            _restore_claimed_profile(
                redis_client, metadata_key, claimed_token, log_label
            )
            logger.warning(
                "%s: profile slot release abandoned for profile %s; "
                "m3u_profile restored for a later teardown",
                log_label,
                profile_id,
            )
        else:
            logger.warning(
                "%s: profile slot release abandoned for profile %s; "
                "counters may be stale",
                log_label,
                profile_id,
            )
        return False

    if metadata_key is not None:
        redis_client.hdel(metadata_key, ChannelMetadataField.STREAM_ID)
    return True
