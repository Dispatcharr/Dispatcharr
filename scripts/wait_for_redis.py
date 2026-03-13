#!/usr/bin/env python
"""
Helper script to wait for Redis to be available before starting the application.
"""

import redis
import time
import os
import sys
import logging

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


def wait_for_redis(host='localhost', port=6379, db=0, password='', username='', max_retries=30, retry_interval=2):
    """Wait for Redis to become available"""
    redis_client = None
    retry_count = 0

    logger.info(f"Waiting for Redis at {host}:{port}/{db}...")

    while retry_count < max_retries:
        try:
            redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password if password else None,
                username=username if username else None,
                socket_timeout=2,
                socket_connect_timeout=2
            )
            redis_client.ping()
            # Clear stale state on startup. In AIO mode, every service restarts
            # together so a full flush is safe. In modular mode, Celery has its
            # own lifecycle — preserve its broker/result keys and only wipe
            # application state (stream locks, proxy metadata, etc.).
            if os.environ.get('DISPATCHARR_ENV') == 'modular':
                _flush_non_celery_keys(redis_client)
            else:
                redis_client.flushdb()
                logger.info(f"Flushed Redis database")
            logger.info(f"✅ Redis at {host}:{port}/{db} is now available!")
            return True
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"❌ Failed to connect to Redis after {max_retries} attempts: {e}")
                return False

            logger.info(f"⏳ Redis not available yet, retrying in {retry_interval}s... ({retry_count}/{max_retries})")
            time.sleep(retry_interval)
        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to Redis: {e}")
            return False

    return False

if __name__ == "__main__":
    host = os.environ.get('REDIS_HOST', 'localhost')
    port = int(os.environ.get('REDIS_PORT', 6379))
    db = int(os.environ.get('REDIS_DB', 0))
    password = os.environ.get('REDIS_PASSWORD', '')
    username = os.environ.get('REDIS_USER', '')
    max_retries = int(os.environ.get('REDIS_WAIT_RETRIES', 30))
    retry_interval = int(os.environ.get('REDIS_WAIT_INTERVAL', 2))

    logger.info(f"Starting Redis availability check at {host}:{port}/{db}")

    if wait_for_redis(host, port, db, password, username, max_retries, retry_interval):
        sys.exit(0)
    else:
        sys.exit(1)
