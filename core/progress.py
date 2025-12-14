"""
Progress tracking for distributed Celery tasks using Redis atomic counters.
"""
import time
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Module-level connection - one per process, thread-safe
_redis_client = None
_redis_lock = threading.Lock()


def get_redis_client():
    """Get shared Redis client. One per process, thread-safe."""
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    with _redis_lock:
        # Double-check after acquiring lock
        if _redis_client is not None:
            return _redis_client

        try:
            import redis
            from django.conf import settings

            _redis_client = redis.Redis(
                host=getattr(settings, 'REDIS_HOST', 'localhost'),
                port=6379,
                db=int(getattr(settings, 'REDIS_DB', '0')),
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                # Connection pool settings
                max_connections=10,
                health_check_interval=30,
            )
            # Test connection
            _redis_client.ping()
            logger.debug("Redis client initialized for progress tracking")
            return _redis_client
        except Exception as e:
            logger.warning(f"Redis unavailable for progress tracking: {e}")
            return None


class ProgressTracker:
    """Thread-safe progress tracker for distributed tasks using Redis atomic counters."""

    def __init__(
        self,
        key: str,
        total: int,
        on_progress: Optional[Callable[[int, int, int], None]] = None,
        update_interval: float = 0.5,
        ttl: int = 3600,
        max_progress: int = 95,  # Reserve 95-100 for finalization
    ):
        self.key = key
        self.total = total
        self.on_progress = on_progress
        self.update_interval = update_interval
        self.ttl = ttl
        self.max_progress = max_progress

        self._redis = get_redis_client()
        self._last_update_time = 0
        self._last_progress_sent = -1
        self._local_count = 0  # Fallback counter
        self._lock = threading.Lock()

    def increment(self, count: int = 1) -> int:
        """
        Atomically increment progress and optionally trigger callback.

        Returns:
            Current global count (or local estimate if Redis unavailable)
        """
        current = self._increment_counter(count)
        self._maybe_send_update(current)
        return current

    def _increment_counter(self, count: int) -> int:
        """Atomic increment with fallback."""
        if self._redis:
            try:
                # INCR is atomic - safe across all workers
                current = self._redis.incrby(self.key, count)

                # Set expiration on first increment (atomic operation)
                if current == count:  # First increment
                    self._redis.expire(self.key, self.ttl)

                return current
            except Exception as e:
                logger.debug(f"Redis increment failed, using local: {e}")

        # Fallback to local counter (inaccurate across workers but better than nothing)
        with self._lock:
            self._local_count += count
            return self._local_count

    def _maybe_send_update(self, current: int):
        """Rate-limited progress callback."""
        if not self.on_progress:
            return

        now = time.monotonic()
        progress = min(self.max_progress, int((current / self.total) * 100)) if self.total > 0 else 0

        # Send update if:
        # 1. Enough time has passed since last update, OR
        # 2. Progress percentage changed (ensures we don't miss milestones)
        should_send = (
            (now - self._last_update_time) >= self.update_interval
            or progress != self._last_progress_sent
        )

        if should_send:
            try:
                self.on_progress(progress, current, self.total)
                self._last_update_time = now
                self._last_progress_sent = progress
            except Exception as e:
                logger.debug(f"Progress callback failed: {e}")

    def get_count(self) -> int:
        """Get current count without incrementing."""
        if self._redis:
            try:
                val = self._redis.get(self.key)
                return int(val) if val else 0
            except Exception:
                pass
        return self._local_count

    def complete(self):
        """Clean up the progress key."""
        if self._redis:
            try:
                self._redis.delete(self.key)
            except Exception as e:
                logger.debug(f"Progress cleanup failed: {e}")

    @classmethod
    def reset(cls, key: str):
        """Reset/clear a progress key (e.g., before starting a new operation)."""
        redis_client = get_redis_client()
        if redis_client:
            try:
                redis_client.delete(key)
            except Exception:
                pass


def make_progress_key(namespace: str, identifier) -> str:
    """Generate a consistent progress key."""
    return f"{namespace}:progress:{identifier}"
