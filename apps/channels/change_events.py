"""
Coalesced ``channels_updated`` system event.

Channels change through many paths: single saves from the API, bulk edits,
EPG matching, and M3U auto channel sync, which can create or rewrite
thousands of rows at once. Integrations that mirror the channel list need to
know when it changed, but not one event per row. Changes are therefore
collected in Redis and announced together, at most once per
``DEBOUNCE_SECONDS``, as one event listing what was created, updated and
deleted.

Changes are recorded only once the transaction that made them commits, so a
rolled-back edit is never announced.
"""

import logging

from django.db import transaction

logger = logging.getLogger(__name__)

EVENT = "channels_updated"
DEBOUNCE_SECONDS = 2
# Channel UUIDs listed per kind; the counts are always complete.
MAX_IDS = 500

_SCHEDULED_KEY = f"{EVENT}:scheduled"
# An emit task that never ran (no worker) must not block the next one.
_SCHEDULED_TTL = 60


def _key(kind):
    return f"{EVENT}:{kind}"


def note_channels_changed(created=(), updated=(), deleted=()):
    """
    Record changed channels for the next ``channels_updated`` event.

    ``created`` and ``updated`` are channel primary keys. ``deleted`` are
    channel UUIDs, as the row is gone by the time the event is sent.
    Never raises: a lost notification must not fail the write that caused it.
    """
    created = [pk for pk in created if pk is not None]
    updated = [pk for pk in updated if pk is not None]
    deleted = [str(u) for u in deleted if u]
    if not (created or updated or deleted):
        return
    try:
        transaction.on_commit(lambda: _record(created, updated, deleted))
    except Exception:
        logger.debug("Could not queue channel change notification", exc_info=True)


def _record(created, updated, deleted):
    try:
        from core.utils import RedisClient

        redis = RedisClient.get_client()
        if redis is None:
            return
        pipe = redis.pipeline()
        for kind, ids in (("created", created), ("updated", updated), ("deleted", deleted)):
            if ids:
                pipe.sadd(_key(kind), *ids)
        pipe.set(_SCHEDULED_KEY, "1", nx=True, ex=_SCHEDULED_TTL)
        scheduled = pipe.execute()[-1]
        if scheduled:
            from apps.channels.tasks import send_channels_updated_event

            send_channels_updated_event.apply_async(countdown=DEBOUNCE_SECONDS)
    except Exception:
        logger.debug("Could not record channel change", exc_info=True)


def send_pending_changes():
    """
    Send one ``channels_updated`` event with the changes recorded so far.

    Returns the event's counts, or None when there was nothing to send.
    """
    from core.utils import RedisClient, log_system_event
    from apps.channels.models import Channel

    redis = RedisClient.get_client()
    if redis is None:
        return None
    # Clearing the schedule in the same transaction as the sets means a change
    # recorded afterwards schedules the next event instead of being lost.
    pipe = redis.pipeline()
    pipe.delete(_SCHEDULED_KEY)
    for kind in ("created", "updated", "deleted"):
        pipe.smembers(_key(kind))
        pipe.delete(_key(kind))
    _, created, _, updated, _, deleted, _ = pipe.execute()

    created = {int(pk) for pk in created}
    updated = {int(pk) for pk in updated} - created
    uuids = dict(
        Channel.objects.filter(pk__in=created | updated).values_list("pk", "uuid")
    )
    # A channel created or edited and then deleted within the window is only
    # reported as deleted.
    created_ids = sorted(str(uuids[pk]) for pk in created if pk in uuids)
    updated_ids = sorted(str(uuids[pk]) for pk in updated if pk in uuids)
    deleted_ids = sorted(deleted)
    if not (created_ids or updated_ids or deleted_ids):
        return None

    counts = {
        "created": len(created_ids),
        "updated": len(updated_ids),
        "deleted": len(deleted_ids),
    }
    log_system_event(
        EVENT,
        **counts,
        created_channel_ids=created_ids[:MAX_IDS],
        updated_channel_ids=updated_ids[:MAX_IDS],
        deleted_channel_ids=deleted_ids[:MAX_IDS],
        truncated=max(counts.values()) > MAX_IDS,
    )
    return counts
