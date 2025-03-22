import redis
import logging
import time
import os
import threading
from django.conf import settings
from redis.exceptions import ConnectionError, TimeoutError

logger = logging.getLogger(__name__)

# Import the command detector
from .command_utils import is_management_command

def get_redis_client(max_retries=5, retry_interval=1):
    """Get Redis client with connection validation and retry logic"""
    # Skip Redis connection for management commands like collectstatic
    if is_management_command():
        logger.info("Running as management command - skipping Redis initialization")
        return None

    retry_count = 0
    while retry_count < max_retries:
        try:
            # Get connection parameters from settings or environment
            redis_host = os.environ.get("REDIS_HOST", getattr(settings, 'REDIS_HOST', 'localhost'))
            redis_port = int(os.environ.get("REDIS_PORT", getattr(settings, 'REDIS_PORT', 6379)))
            redis_db = int(os.environ.get("REDIS_DB", getattr(settings, 'REDIS_DB', 0)))

            # Use standardized settings
            socket_timeout = getattr(settings, 'REDIS_SOCKET_TIMEOUT', 5)
            socket_connect_timeout = getattr(settings, 'REDIS_SOCKET_CONNECT_TIMEOUT', 5)
            health_check_interval = getattr(settings, 'REDIS_HEALTH_CHECK_INTERVAL', 30)
            socket_keepalive = getattr(settings, 'REDIS_SOCKET_KEEPALIVE', True)
            retry_on_timeout = getattr(settings, 'REDIS_RETRY_ON_TIMEOUT', True)

            # Create Redis client with better defaults
            client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
                socket_keepalive=socket_keepalive,
                health_check_interval=health_check_interval,
                retry_on_timeout=retry_on_timeout
            )

            # Validate connection with ping
            client.ping()
            logger.info(f"Connected to Redis at {redis_host}:{redis_port}/{redis_db}")
            return client

        except (ConnectionError, TimeoutError) as e:
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"Failed to connect to Redis after {max_retries} attempts: {e}")
                return None
            else:
                # Use exponential backoff for retries
                wait_time = retry_interval * (2 ** (retry_count - 1))
                logger.warning(f"Redis connection failed. Retrying in {wait_time}s... ({retry_count}/{max_retries})")
                time.sleep(wait_time)

        except Exception as e:
            logger.error(f"Unexpected error connecting to Redis: {e}")
            return None

def get_redis_pubsub_client(max_retries=5, retry_interval=1):
    """Get Redis client optimized for PubSub operations"""
    # Skip Redis connection for management commands like collectstatic
    if is_management_command():
        logger.info("Running as management command - skipping Redis PubSub initialization")
        return None

    retry_count = 0
    while retry_count < max_retries:
        try:
            # Get connection parameters from settings or environment
            redis_host = os.environ.get("REDIS_HOST", getattr(settings, 'REDIS_HOST', 'localhost'))
            redis_port = int(os.environ.get("REDIS_PORT", getattr(settings, 'REDIS_PORT', 6379)))
            redis_db = int(os.environ.get("REDIS_DB", getattr(settings, 'REDIS_DB', 0)))

            # Use standardized settings but without socket timeouts for PubSub
            # Important: socket_timeout is None for PubSub operations
            socket_connect_timeout = getattr(settings, 'REDIS_SOCKET_CONNECT_TIMEOUT', 5)
            socket_keepalive = getattr(settings, 'REDIS_SOCKET_KEEPALIVE', True)
            health_check_interval = getattr(settings, 'REDIS_HEALTH_CHECK_INTERVAL', 30)
            retry_on_timeout = getattr(settings, 'REDIS_RETRY_ON_TIMEOUT', True)

            # Create Redis client with PubSub-optimized settings - no timeout
            client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                socket_timeout=None,  # Critical: No timeout for PubSub operations
                socket_connect_timeout=socket_connect_timeout,
                socket_keepalive=socket_keepalive,
                health_check_interval=health_check_interval,
                retry_on_timeout=retry_on_timeout
            )

            # Validate connection with ping
            client.ping()
            logger.info(f"Connected to Redis for PubSub at {redis_host}:{redis_port}/{redis_db}")

            # We don't need the keepalive thread anymore since we're using proper PubSub handling
            return client

        except (ConnectionError, TimeoutError) as e:
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"Failed to connect to Redis for PubSub after {max_retries} attempts: {e}")
                return None
            else:
                # Use exponential backoff for retries
                wait_time = retry_interval * (2 ** (retry_count - 1))
                logger.warning(f"Redis PubSub connection failed. Retrying in {wait_time}s... ({retry_count}/{max_retries})")
                time.sleep(wait_time)

        except Exception as e:
            logger.error(f"Unexpected error connecting to Redis for PubSub: {e}")
            return None

def execute_redis_command(redis_client, command_func, default_return=None):
    """
    Execute a Redis command with proper error handling

    Args:
        redis_client: The Redis client instance
        command_func: Lambda function containing the Redis command to execute
        default_return: Value to return if command fails

    Returns:
        Command result or default_return on failure
    """
    if redis_client is None:
        return default_return

    try:
        return command_func()
    except (ConnectionError, TimeoutError) as e:
        logger.warning(f"Redis connection error: {e}")
        return default_return
    except Exception as e:
        logger.error(f"Redis command error: {e}")
        return default_return

# Initialize the global clients with retry logic
# Skip Redis initialization if running as a management command
if is_management_command():
    redis_client = None
    redis_pubsub_client = None
    logger.info("Running as management command - Redis clients set to None")
else:
    redis_client = get_redis_client()
    redis_pubsub_client = get_redis_pubsub_client()

# Import and initialize the PubSub manager
# Skip if running as management command or if Redis client is None
if not is_management_command() and redis_client is not None:
    from .redis_pubsub import get_pubsub_manager
    pubsub_manager = get_pubsub_manager(redis_client)
else:
    logger.info("PubSub manager not initialized (running as management command or Redis not available)")
    pubsub_manager = None