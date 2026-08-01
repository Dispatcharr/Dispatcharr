"""
Redis-backed history of async plugin task runs (dispatched via the manifest
`"async": true` flag or `context["dispatch_task"]`), keyed per plugin.

This is a read-mostly convenience layer on top of the existing websocket-driven
live UI (plugin_task_progress / plugin_task_complete in WebSocket.jsx): it lets
the frontend rehydrate a bounded task history on page load or in a second tab,
instead of only ever seeing tasks started in the current browser session.

Bounded and best-effort: capped to the newest N runs per plugin, TTL'd so an
abandoned plugin's history ages out, and every Redis call fails open (logs and
continues) so a Redis hiccup never breaks plugin execution or the live UI,
which do not depend on this module.
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

HISTORY_MAX_ENTRIES = 50
HISTORY_TTL_SECONDS = 7 * 24 * 3600


def _history_keys(plugin_key: str):
    return (
        f"plugin_task_history:{plugin_key}",
        f"plugin_task_history_data:{plugin_key}",
    )


def _client():
    try:
        from core.utils import RedisClient
        return RedisClient.get_client()
    except Exception:
        logger.warning("Plugin task history: Redis unavailable", exc_info=True)
        return None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _write(plugin_key: str, task_id: str, patch: dict) -> None:
    client = _client()
    if client is None:
        return
    try:
        zset_key, data_key = _history_keys(plugin_key)
        existing_raw = client.hget(data_key, task_id)
        record = json.loads(existing_raw) if existing_raw else {}
        record.update(patch)
        record.setdefault("startedAt", patch.get("updatedAt", _now_ms()))

        client.hset(data_key, task_id, json.dumps(record))
        client.zadd(zset_key, {task_id: record["startedAt"]})

        # Cap to newest HISTORY_MAX_ENTRIES, dropping the oldest overflow.
        evicted = client.zrange(zset_key, 0, -HISTORY_MAX_ENTRIES - 1)
        if evicted:
            client.zrem(zset_key, *evicted)
            client.hdel(data_key, *evicted)

        client.expire(zset_key, HISTORY_TTL_SECONDS)
        client.expire(data_key, HISTORY_TTL_SECONDS)
    except Exception:
        logger.warning("Plugin task history: write failed for '%s'/%s", plugin_key, task_id, exc_info=True)


def record_task_started(plugin_key: str, task_id: str, action_id: str, action_label: str) -> None:
    now = _now_ms()
    _write(plugin_key, task_id, {
        "action_id": action_id,
        "action_label": action_label,
        "status": "running",
        "percent": None,
        "message": None,
        "result": None,
        "error": None,
        "startedAt": now,
        "updatedAt": now,
    })


def record_task_progress(plugin_key: str, task_id: str, percent, message) -> None:
    _write(plugin_key, task_id, {
        "percent": percent,
        "message": message,
        "updatedAt": _now_ms(),
    })


def record_task_complete(plugin_key: str, task_id: str, status: str, result=None, error=None) -> None:
    _write(plugin_key, task_id, {
        "status": status,
        "result": result,
        "error": error,
        "updatedAt": _now_ms(),
    })


def get_task_history(plugin_key: str) -> list:
    client = _client()
    if client is None:
        return []
    try:
        zset_key, data_key = _history_keys(plugin_key)
        task_ids = client.zrevrange(zset_key, 0, HISTORY_MAX_ENTRIES - 1)
        if not task_ids:
            return []
        raw_records = client.hmget(data_key, task_ids)
        history = []
        for task_id, raw in zip(task_ids, raw_records):
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except (TypeError, ValueError):
                continue
            record["task_id"] = task_id
            history.append(record)
        return history
    except Exception:
        logger.warning("Plugin task history: read failed for '%s'", plugin_key, exc_info=True)
        return []
