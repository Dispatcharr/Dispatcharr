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

Authz for playback: channel visibility is checked when the session is minted.
A valid ``session_id`` bound to the URL channel is enough to play; playback
loads that channel by the id stored at mint (no profile/level re-check) and
still loads the User row so stream limits, catch-up enablement, and
``is_active`` stay current. Because playback refreshes the idle TTL, a
permission change reaches an already-playing session only after the viewer
stops for ``SESSION_IDLE_TTL_SECONDS`` or the session is deleted.
"""

import logging
import time

from apps.accounts.models import User
from apps.channels.access import user_can_access_channel
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

    Channel visibility was already checked by the caller before minting. The
    session stores the channel id so playback can load that row without
    repeating the profile filter. Stream limits stay on the User row.
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
    """Resolve user, programme, and channel for a tokenless playback request.

    Returns:
        ``(user, start, duration, channel)`` on success, or ``None`` if the
        session is invalid, expired, bound to a different channel, or the
        channel row is gone. ``duration`` is the stored client programme
        length in minutes, or ``None`` when unset.

    Channel visibility is decided when the session is minted and is not
    re-checked for the user who minted it. That makes a session a capability:
    a permission change (profile, user level, hide-adult) applies to that
    user's next session, not to one that is already playing. The channel is
    loaded by the stored primary key and must still match *channel_uuid*. The
    User row is always loaded so deactivation, stream limits, and the
    catch-up flag stay current.
    """
    record = get_catchup_session(session_id)
    if not record:
        return None

    if str(record.get("channel_uuid") or "") != str(channel_uuid):
        return None

    # Validate the whole record before any database work.
    start = record.get("start")
    try:
        owner_id = int(record.get("user_id") or "")
        channel_pk = int(record.get("channel_id") or "")
    except (TypeError, ValueError):
        return None
    if not start:
        return None

    pool_user_id = _user_id_from_pool(session_id)
    user = User.objects.filter(
        id=owner_id if pool_user_id is None else pool_user_id,
        is_active=True,
    ).first()
    if user is None:
        return None

    # Plain PK + uuid fetch: no visibility subquery (authorized at mint).
    channel = Channel.objects.filter(pk=channel_pk, uuid=channel_uuid).first()
    if channel is None:
        return None

    if user.id != owner_id and not user_can_access_channel(user, channel):
        # The live pool entry names someone other than the minting user, so the
        # mint-time authorization does not cover them.
        return None

    # Refresh idle TTL only after the request is authorized to play. Touching
    # earlier would let a deactivated user keep a session alive by probing.
    touch_catchup_session(session_id)

    return user, str(start), record.get("duration"), channel


def user_owns_catchup_session(session_id, user_id):
    record = get_catchup_session(session_id)
    if not record:
        return False
    try:
        return int(record.get("user_id") or "") == int(user_id)
    except (TypeError, ValueError):
        return False
