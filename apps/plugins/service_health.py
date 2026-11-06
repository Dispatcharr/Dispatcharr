"""Best-effort, lease-owned service health shared across processes."""
import json
import logging
import time

logger = logging.getLogger(__name__)


def publish_service_health(client, key, worker_id, state, failures, ttl):
    if client is None:
        return
    try:
        client.eval("""
            if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
            redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
            return 1
        """, 2, f"plugin:{key}:leader", f"plugin:{key}:service_health", worker_id,
            json.dumps({"state": state, "failures": failures, "updated_at": int(time.time() * 1000)}), ttl)
    except Exception:
        logger.warning("Could not publish plugin service health for '%s'", key, exc_info=True)


def get_service_health(key):
    try:
        from core.utils import RedisClient
        client = RedisClient.get_client()
        raw = client.get(f"plugin:{key}:service_health") if client else None
        data = json.loads(raw) if raw else None
        return data if isinstance(data, dict) else {"state": "unknown"}
    except Exception:
        logger.warning("Could not read plugin service health for '%s'", key, exc_info=True)
        return {"state": "unknown"}
