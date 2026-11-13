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
import os
import time

from redis.exceptions import WatchError

logger = logging.getLogger(__name__)

def _bounded_env(name, default, maximum):
    try:
        return max(1, min(int(os.environ.get(name, default)), maximum))
    except (TypeError, ValueError):
        logger.warning("Invalid %s; using %s", name, default)
        return default


HISTORY_MAX_ENTRIES = _bounded_env("PLUGIN_TASK_HISTORY_MAX_ENTRIES", 50, 5000)
HISTORY_TTL_SECONDS = _bounded_env("PLUGIN_TASK_HISTORY_TTL_SECONDS", 7 * 24 * 3600, 90 * 24 * 3600)


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
        for _ in range(5):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(data_key, zset_key)
                    raw = pipe.hget(data_key, task_id)
                    try:
                        record = json.loads(raw) if raw else {}
                    except (TypeError, ValueError):
                        record = {}
                    if not isinstance(record, dict):
                        record = {}
                    if record.get("status") not in (None, "running") and patch.get("status") in (None, "running"):
                        return
                    record.update(patch)
                    if record.get("startedAt") is None:
                        record["startedAt"] = patch.get("updatedAt") or _now_ms()
                    # Evict after including the new entry in the ordered set.
                    pipe.multi()
                    pipe.hset(data_key, task_id, json.dumps(record))
                    pipe.zadd(zset_key, {task_id: record["startedAt"]})
                    pipe.expire(zset_key, HISTORY_TTL_SECONDS)
                    pipe.expire(data_key, HISTORY_TTL_SECONDS)
                    pipe.execute()
                    break
            except WatchError:
                continue
        else:
            logger.warning("Plugin task history: concurrent write retries exhausted for '%s'/%s", plugin_key, task_id)
            return
        # Eviction removes only entries that remain outside the newest window.
        # Lua keeps the sorted-set and hash removals atomic with concurrent writes.
        client.eval("""
            local ids = redis.call('ZRANGE', KEYS[1], 0, -tonumber(ARGV[1]) - 1)
            for _, id in ipairs(ids) do
                redis.call('ZREM', KEYS[1], id)
                redis.call('HDEL', KEYS[2], id)
            end
        """, 2, zset_key, data_key, HISTORY_MAX_ENTRIES)
    except Exception:
        logger.warning("Plugin task history: write failed for '%s'/%s", plugin_key, task_id, exc_info=True)


def record_task_started(plugin_key: str, task_id: str, action_id: str, action_label: str, *, trigger: str = "manual") -> None:
    now = _now_ms()
    _write(plugin_key, task_id, {
        "action_id": action_id,
        "action_label": action_label,
        "trigger": trigger,
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


def get_task_history(plugin_key: str, trigger: str = None) -> list:
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
            if not isinstance(record, dict) or not (record.get("action_id") or record.get("action_label")):
                continue
            if trigger and (record.get("trigger") or "unknown") != trigger:
                continue
            record["task_id"] = task_id
            history.append(record)
        return history
    except Exception:
        logger.warning("Plugin task history: read failed for '%s'", plugin_key, exc_info=True)
        return []
