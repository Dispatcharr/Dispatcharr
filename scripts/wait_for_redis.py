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

def wait_for_redis(host=None, port=6379, db=0, max_retries=30, retry_interval=2):
    """Wait for Redis to become available"""
    import os
    host = host or os.environ.get('REDIS_HOST', 'redis')
    redis_client = None
    retry_count = 0

    logger.info(f"Waiting for Redis at {host}:{port}/{db}...")

    while retry_count < max_retries:
        try:
            redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                socket_timeout=2,
                socket_connect_timeout=2
            )
            redis_client.ping()
            redis_client.flushdb()  # Flush the database to ensure it's clean
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
    max_retries = int(os.environ.get('REDIS_WAIT_RETRIES', 30))
    retry_interval = int(os.environ.get('REDIS_WAIT_INTERVAL', 2))

    logger.info(f"Starting Redis availability check at {host}:{port}/{db}")

    if wait_for_redis(host, port, db, max_retries, retry_interval):
        sys.exit(0)
    else:
        sys.exit(1)
