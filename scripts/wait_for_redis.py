#!/usr/bin/env python
"""
Helper script to wait for Redis to be available before starting the application.

This runs before Django (CI bootstrap, container entrypoint, uWSGI exec-pre).
It imports only core.redis_connection, which does not load the app.
"""

import os
import sys
import time
import logging

# Executing this file directly puts scripts/ on sys.path, not the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from redis.exceptions import ConnectionError, TimeoutError

from core.redis_connection import RedisUrlError, client_from_env

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Key prefixes used by Celery's broker (Kombu) and result backend.
# These must be preserved in modular mode where Celery runs independently.
_CELERY_KEY_PREFIXES = ('celery', '_kombu', 'unacked')


def _flush_non_celery_keys(client):
    """Delete all Redis keys except those belonging to Celery."""
    cursor = '0'
    deleted = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, count=500)
        to_delete = [
            k for k in keys
            if not k.decode('utf-8', errors='replace').startswith(_CELERY_KEY_PREFIXES)
        ]
        if to_delete:
            deleted += client.delete(*to_delete)
        if cursor == 0:
            break
    logger.info(f"Modular mode: selectively cleared {deleted} non-Celery Redis key(s)")


def wait_for_redis(max_retries=30, retry_interval=2):
    """Wait for Redis, using REDIS_URL when set and host/port/db otherwise."""
    redis_client = None
    location = None
    retry_count = 0

    while retry_count < max_retries:
        try:
            redis_client, location = client_from_env()
            redis_client.ping()
            break
        except RedisUrlError:
            logger.error("Ill-formatted REDIS_URL: Unable to parse connection string parameters")
            return False
        except (ConnectionError, TimeoutError) as exc:
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"Failed to connect to Redis after {max_retries} attempts: {exc}")
                return False
            logger.warning(
                f"Redis connection failed. Retrying in {retry_interval}s... ({retry_count}/{max_retries})"
            )
            time.sleep(retry_interval)
        except Exception as exc:
            logger.error(f"Unexpected error connecting to Redis: {exc}")
            return False

    if redis_client is None:
        logger.error("Redis turned out unavailable")
        return False

    # Clear stale state on startup. In AIO mode, every service restarts
    # together so a full flush is safe. In modular mode, Celery has its
    # own lifecycle: preserve its broker/result keys and only wipe
    # application state (stream locks, proxy metadata, etc.).
    if os.environ.get('DISPATCHARR_ENV') == 'modular':
        _flush_non_celery_keys(redis_client)
        logger.info("Flushed Non-Celery Redis keys")
    else:
        redis_client.flushdb()
        logger.info("Flushed Redis database")

    logger.info(f"Redis at {location} is now available!")
    return True


if __name__ == "__main__":

    sys.exit(0) if wait_for_redis() else sys.exit(1)
