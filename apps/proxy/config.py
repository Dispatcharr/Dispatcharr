"""Shared configuration between proxy types"""
import time
from django.db import connection

class BaseConfig:
    DEFAULT_USER_AGENT = 'VLC/3.0.20 LibVLC/3.0.20' # Will only be used if connection to settings fail
    CHUNK_SIZE = 8192
    CLIENT_POLL_INTERVAL = 0.1
    MAX_RETRIES = 3
    RETRY_WAIT_INTERVAL = 0.5  # seconds to wait between retries
    CONNECTION_TIMEOUT = 10  # seconds to wait for initial connection
    MAX_STREAM_SWITCHES = 10  # Maximum number of stream switch attempts before giving up
    BUFFER_CHUNK_SIZE = 188 * 1361  # ~256KB
    BUFFERING_TIMEOUT = 15  # Seconds to wait for buffering before switching streams
    BUFFER_SPEED = 1 # What speed to condsider the stream buffering, 1x is normal speed, 2x is double speed, etc.

    # Cache for proxy settings (class-level, shared across all instances)
    _proxy_settings_cache = None
    _proxy_settings_cache_time = 0
    _proxy_settings_cache_ttl = 10  # Cache for 10 seconds

    @classmethod
    def get_proxy_settings(cls):
        """Get proxy settings from CoreSettings JSON data with fallback to defaults (cached)"""
        # Check if cache is still valid
        now = time.time()
        if cls._proxy_settings_cache is not None and (now - cls._proxy_settings_cache_time) < cls._proxy_settings_cache_ttl:
            return cls._proxy_settings_cache

        # Cache miss or expired - fetch from database
        try:
            from core.models import CoreSettings
            settings = CoreSettings.get_proxy_settings()
            cls._proxy_settings_cache = settings
            cls._proxy_settings_cache_time = now
            return settings

        except Exception:
            # Return defaults if database query fails
            return {
                "buffering_timeout": 15,
                "buffering_speed": 1.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 5,
                "new_client_behind_seconds": 5,
                "max_retries": 2,
                "url_switch_timeout": 20,
                "max_stream_switches": 200,
                "connection_timeout": 10,
                "failover_grace_period": 20,
                "chunk_timeout": 5,
                "initial_behind_chunks": 4,
                "chunk_batch_size": 5,
                "health_check_interval": 5,
            }

        finally:
            # Always close the connection after reading settings
            try:
                connection.close()
            except Exception:
                pass

    @classmethod
    def get_redis_chunk_ttl(cls):
        """Get Redis chunk TTL from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("redis_chunk_ttl", 60)

    @property
    def REDIS_CHUNK_TTL(self):
        return self.get_redis_chunk_ttl()

class HLSConfig(BaseConfig):
    MIN_SEGMENTS = 12
    MAX_SEGMENTS = 16
    WINDOW_SIZE = 12
    INITIAL_SEGMENTS = 3
    INITIAL_CONNECTION_WINDOW = 10
    CLIENT_TIMEOUT_FACTOR = 1.5
    CLIENT_CLEANUP_INTERVAL = 10
    FIRST_SEGMENT_TIMEOUT = 5.0
    INITIAL_BUFFER_SECONDS = 25.0
    MAX_INITIAL_SEGMENTS = 10
    BUFFER_READY_TIMEOUT = 30.0

class TSConfig(BaseConfig):
    """Configuration settings for TS proxy"""

    # Buffer settings
    INITIAL_BEHIND_CHUNKS = 4  # How many chunks behind to start a client (4 chunks = ~1MB)
    CHUNK_BATCH_SIZE = 5       # How many chunks to fetch in one batch
    NEW_CLIENT_BEHIND_SECONDS = 5  # Start new clients this many seconds behind live (0 = start at live)
    KEEPALIVE_INTERVAL = 0.5   # Seconds between keepalive packets when at buffer head
    # Chunk read timeout
    CHUNK_TIMEOUT = 5        # Seconds to wait for each chunk read

    # Streaming settings
    TARGET_BITRATE = 8000000   # Target bitrate (8 Mbps)
    STREAM_TIMEOUT = 20        # Disconnect after this many seconds of no data
    HEALTH_CHECK_INTERVAL = 5  # Check stream health every N seconds

    # Resource management
    CLEANUP_INTERVAL = 60  # Check for inactive channels every 60 seconds

    # Client tracking settings
    CLIENT_RECORD_TTL = 60  # How long client records persist in Redis (seconds). Client will be considered MIA after this time.
    CLEANUP_CHECK_INTERVAL = 1  # How often to check for disconnected clients (seconds)
    CLIENT_HEARTBEAT_INTERVAL = 5  # How often to send client heartbeats (seconds)
    GHOST_CLIENT_MULTIPLIER = 10.0  # How many heartbeat intervals before client considered ghost (10 = 50s, must exceed STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD = 40s)
    CLIENT_WAIT_TIMEOUT = 30  # Seconds to wait for client to connect

    # Stream health and recovery settings
    MAX_HEALTH_RECOVERY_ATTEMPTS = 2     # Maximum times to attempt recovery for a single stream
    MAX_RECONNECT_ATTEMPTS = 3           # Maximum reconnects to try before switching streams
    MIN_STABLE_TIME_BEFORE_RECONNECT = 30  # Minimum seconds a stream must be stable to try reconnect
    FAILOVER_GRACE_PERIOD = 20           # Extra time (seconds) to allow for stream switching before disconnecting clients
    URL_SWITCH_TIMEOUT = 20   # Max time allowed for a stream switch operation
    MAX_KEEPALIVE_DURATION = 300         # Keepalive packets prevent _is_timeout() from firing, so without this a permanently failed stream holds clients open indefinitely.



    # Database-dependent settings with fallbacks
    @classmethod
    def get_channel_shutdown_delay(cls):
        """Get channel shutdown delay from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("channel_shutdown_delay", 0)

    @classmethod
    def get_buffering_timeout(cls):
        """Get buffering timeout from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("buffering_timeout", 15)

    @classmethod
    def get_buffering_speed(cls):
        """Get buffering speed threshold from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("buffering_speed", 1.0)

    @classmethod
    def get_channel_init_grace_period(cls):
        """Get channel init grace period from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("channel_init_grace_period", 5)

    @classmethod
    def get_chunk_timeout(cls):
        """Get chunk timeout from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("chunk_timeout", 5)

    @classmethod
    def get_new_client_behind_seconds(cls):
        """Get new client behind seconds from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("new_client_behind_seconds", 5)

    @classmethod
    def get_initial_behind_chunks(cls):
        """Get initial behind chunks from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("initial_behind_chunks", 4)

    @classmethod
    def get_chunk_batch_size(cls):
        """Get chunk batch size from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("chunk_batch_size", 5)

    @classmethod
    def get_health_check_interval(cls):
        """Get health check interval from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("health_check_interval", 5)

    @classmethod
    def get_max_retries(cls):
        """Get max retries from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("max_retries", 2)

    @classmethod
    def get_url_switch_timeout(cls):
        """Get URL switch timeout from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("url_switch_timeout", 20)

    @classmethod
    def get_max_stream_switches(cls):
        """Get max stream switches from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("max_stream_switches", 200)

    @classmethod
    def get_connection_timeout(cls):
        """Get connection timeout from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("connection_timeout", 10)

    @classmethod
    def get_failover_grace_period(cls):
        """Get failover grace period from database or default"""
        settings = cls.get_proxy_settings()
        return settings.get("failover_grace_period", 20)

    # Dynamic property access for these settings
    @property
    def CHANNEL_SHUTDOWN_DELAY(self):
        return self.get_channel_shutdown_delay()

    @property
    def BUFFERING_TIMEOUT(self):
        return self.get_buffering_timeout()

    @property
    def BUFFERING_SPEED(self):
        return self.get_buffering_speed()

    @property
    def CHANNEL_INIT_GRACE_PERIOD(self):
        return self.get_channel_init_grace_period()

    @property
    def CHUNK_TIMEOUT(self):
        return self.get_chunk_timeout()

    @property
    def NEW_CLIENT_BEHIND_SECONDS(self):
        return self.get_new_client_behind_seconds()

    @property
    def INITIAL_BEHIND_CHUNKS(self):
        return self.get_initial_behind_chunks()

    @property
    def CHUNK_BATCH_SIZE(self):
        return self.get_chunk_batch_size()

    @property
    def HEALTH_CHECK_INTERVAL(self):
        return self.get_health_check_interval()



