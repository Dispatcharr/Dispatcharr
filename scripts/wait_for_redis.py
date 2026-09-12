#!/usr/bin/env python
"""
Helper script to wait for Redis to be available before starting the application.
"""

import os
import sys
import logging

from core.utils import RedisClient

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
    """Wait for Redis to become available, using universal environment variables as resolved by Django settings"""

    redis_cls = RedisClient()
    redis_client = redis_cls.get_test_client(max_retries = max_retries, retry_interval = retry_interval)

    if redis_client is None:

        logger.error("❌ Redis turned out unavailable, see stacktrace")
        return False

    # Clear stale state on startup. In AIO mode, every service restarts
    # together so a full flush is safe. In modular mode, Celery has its
    # own lifecycle — preserve its broker/result keys and only wipe
    # application state (stream locks, proxy metadata, etc.).
    if os.environ.get('DISPATCHARR_ENV') == 'modular':
        _flush_non_celery_keys(redis_client)
        logger.info("Flushed Non-Celery Redis keys")
    else:
        redis_client.flushdb()
        logger.info("Flushed Redis database")

    logger.info(f"✅ Redis at {redis_cls.get_net_location()} is now available!")
    return True


if __name__ == "__main__":

    os.environ["DJANGO_SETTINGS_MODULE"] = "dispatcharr"

    sys.exit(0) if wait_for_redis() else sys.exit(1)