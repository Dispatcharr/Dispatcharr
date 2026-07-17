"""Redis-backed catch-up playback sessions for native API clients.

A session is minted by ``POST /api/catchup/sessions/`` (JWT/API key). The
returned ``session_id`` lets a headerless video player call
``GET /proxy/catchup/{uuid}?session_id=...`` without embedding a JWT in the URL.

Lifecycle:
  * **Handshake**: unused sessions expire ``HANDSHAKE_TTL_SECONDS`` after POST.
  * **Playback**: the first GET extends TTL to ``SESSION_IDLE_TTL_SECONDS``;
    each subsequent GET (or active-stream heartbeat) refreshes that sliding
    window. Pausing longer than this without a new request requires minting
    a new session.
  * **End of viewing**: when the client disconnects for real (not a seek within
    the same session), the playback layer deletes the record after a short grace
    window so stale ``session_id`` values cannot be replayed until TTL expiry.
  * **User resolution**: prefer ``timeshift:pool:{session_id}.user_id`` while
    the provider pool entry exists; fall back to the API session record when the
    pool is idle/expired (pause gaps between HTTP range requests).
"""

import logging
import time

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.timeshift.redis_keys import TimeshiftRedisKeys, mint_session_id
from core.utils import RedisClient

logger = logging.getLogger(__name__)

HANDSHAKE_TTL_SECONDS = 60
# Max idle pause between range/seek requests (refreshed on each playback GET).
SESSION_IDLE_TTL_SECONDS = 10 * 60


def mint_catchup_session_id():
    """Backward-compatible alias for :func:`mint_session_id`."""
    return mint_session_id()


def create_catchup_session(*, user, channel, start, duration=None):
    """Persist a new playback session and return metadata for the API response.

    ``duration`` is an optional programme length in minutes. When supplied it is
    preferred over EPG at playback time (see ``resolve_catchup_duration``).
    """
    redis_client = RedisClient.get_client()
    if redis_client is None:
        raise RuntimeError("Redis unavailable")

    session_id = mint_session_id()
    now = int(time.time())
    key = TimeshiftRedisKeys.api_session(session_id)
    mapping = {
        "user_id": str(user.id),
        "channel_uuid": str(channel.uuid),
        "channel_id": str(channel.id),
        "start": str(start),
        "created_at": str(now),
    }
    if duration is not None:
        mapping["duration"] = str(duration)
    redis_client.hset(key, mapping=mapping)
    redis_client.expire(key, HANDSHAKE_TTL_SECONDS)

    handshake_expires_at = now + HANDSHAKE_TTL_SECONDS
    playback_url = f"/proxy/catchup/{channel.uuid}?session_id={session_id}"

    return {
        "session_id": session_id,
        "playback_url": playback_url,
        "expires_at": handshake_expires_at,
        "channel_uuid": str(channel.uuid),
        "start": str(start),
        "duration": duration,
    }


def get_catchup_session(session_id):
    """Return session fields as a dict, or None if missing."""
    redis_client = RedisClient.get_client()
    if redis_client is None or not session_id:
        return None
    try:
        data = redis_client.hgetall(TimeshiftRedisKeys.api_session(session_id))
    except Exception as exc:
        logger.warning("Catchup session read failed for %s: %s", session_id, exc)
        return None
    if not data:
        return None
    return data


def touch_catchup_session(session_id, *, redis_client=None):
    """Extend sliding idle TTL after a playback request uses the session."""
    if redis_client is None:
        redis_client = RedisClient.get_client()
    if redis_client is None or not session_id:
        return False
    key = TimeshiftRedisKeys.api_session(session_id)
    try:
        if not redis_client.exists(key):
            return False
        redis_client.expire(key, SESSION_IDLE_TTL_SECONDS)
        return True
    except Exception as exc:
        logger.warning("Catchup session touch failed for %s: %s", session_id, exc)
        return False


def delete_catchup_session(session_id, *, redis_client=None):
    if not session_id:
        return False
    if redis_client is None:
        redis_client = RedisClient.get_client()
    if redis_client is None:
        return False
    try:
        deleted = bool(redis_client.delete(TimeshiftRedisKeys.api_session(session_id)))
        if deleted:
            logger.debug("Catchup session deleted: %s", session_id)
        return deleted
    except Exception as exc:
        logger.warning("Catchup session delete failed for %s: %s", session_id, exc)
        return False


def catchup_session_exists(session_id, *, redis_client=None):
    """Return True when *session_id* has an API session record."""
    if not session_id:
        return False
    if redis_client is None:
        redis_client = RedisClient.get_client()
    if redis_client is None:
        return False
    try:
        return bool(redis_client.exists(TimeshiftRedisKeys.api_session(session_id)))
    except Exception:
        return False


def _user_id_from_pool(session_id):
    redis_client = RedisClient.get_client()
    if redis_client is None or not session_id:
        return None
    try:
        data = redis_client.hgetall(TimeshiftRedisKeys.pool(session_id))
    except Exception:
        return None
    if not data:
        return None
    uid = data.get("user_id")
    if not uid:
        return None
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


def resolve_catchup_playback(session_id, channel_uuid):
    """Resolve user and programme start for a tokenless playback request.

    Returns:
        ``(user, start, duration)`` on success, or ``None`` if the session is
        invalid, expired, or bound to a different channel. ``duration`` is the
        stored client programme length in minutes, or ``None`` when unset.
    """
    record = get_catchup_session(session_id)
    if not record:
        return None

    if str(record.get("channel_uuid") or "") != str(channel_uuid):
        return None

    touch_catchup_session(session_id)

    user_id = _user_id_from_pool(session_id)
    if user_id is None:
        try:
            user_id = int(record.get("user_id") or "")
        except (TypeError, ValueError):
            return None

    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        return None

    start = record.get("start")
    if not start:
        return None

    return user, str(start), record.get("duration")


def user_owns_catchup_session(session_id, user_id):
    record = get_catchup_session(session_id)
    if not record:
        return False
    try:
        return int(record.get("user_id") or "") == int(user_id)
    except (TypeError, ValueError):
        return False
