# dispatcharr/persistent_lock.py
import uuid
import redis
import os

class PersistentLock:
    """
    A persistent, auto-expiring lock that uses Redis.

    Usage:
      1. Instantiate with a Redis client, a unique lock key (e.g. "lock:account:123"),
         and an optional timeout (in seconds).
      2. Call acquire() to try to obtain the lock.
      3. Optionally, periodically call refresh() to extend the lock's lifetime.
      4. When finished, call release() to free the lock.
    """
    def __init__(self, redis_client: redis.Redis, lock_key: str, lock_timeout: int = 120):
        """
        Initialize the lock.

        :param redis_client: An instance of redis.Redis.
        :param lock_key: The unique key for the lock.
        :param lock_timeout: Time-to-live for the lock in seconds.
        """
        self.redis_client = redis_client
        self.lock_key = lock_key
        self.lock_timeout = lock_timeout
        self.lock_token = None
        self.has_lock = False

    def has_lock(self) -> bool:
        return self.has_lock

    def acquire(self) -> bool:
        """
        Attempt to acquire the lock. Returns True if successful.
        """
        self.lock_token = str(uuid.uuid4())
        # Set the lock with NX (only if not exists) and EX (expire time)
        result = self.redis_client.set(self.lock_key, self.lock_token, nx=True, ex=self.lock_timeout)
        if result is not None:
            self.has_lock = True

        return result is not None

    def refresh(self) -> bool:
        """
        Refresh the lock's expiration time if this instance owns the lock.
        Returns True if the expiration was successfully extended.
        """
        current_value = self.redis_client.get(self.lock_key)
        if current_value and current_value.decode("utf-8") == self.lock_token:
            self.redis_client.expire(self.lock_key, self.lock_timeout)
            self.has_lock = False
            return True
        return False

    def release(self) -> bool:
        """
        Release the lock only if owned by this instance.
        Returns True if the lock was successfully released.
        """
        # Use a Lua script for atomicity: only delete if the token matches.
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        release_lock = self.redis_client.register_script(lua_script)
        result = release_lock(keys=[self.lock_key], args=[self.lock_token])
        return result == 1

# Example usage (for testing purposes only):
if __name__ == "__main__":
    # Connect to Redis on localhost; adjust connection parameters as needed.
    client = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379, db=0)
    lock = PersistentLock(client, "lock:example_account", lock_timeout=120)

    if lock.acquire():
        print("Lock acquired successfully!")
        # Do work here...
        # Optionally refresh the lock periodically:
        if lock.refresh():
            print("Lock refreshed.")
        # Finally, release the lock:
        if lock.release():
            print("Lock released.")
        else:
            print("Failed to release lock.")
    else:
        print("Failed to acquire lock.")
