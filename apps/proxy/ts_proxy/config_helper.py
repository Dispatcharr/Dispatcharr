"""
Helper module to access configuration values with proper defaults.
"""

from apps.proxy.config import TSConfig as Config

class ConfigHelper:
    """
    Helper class for accessing configuration values with sensible defaults.
    This simplifies code and ensures consistent defaults across the application.
    """

    @staticmethod
    def get(name, default=None):
        """Get a configuration value with a default fallback"""
        return getattr(Config, name, default)

    # Commonly used configuration values
    @staticmethod
    def connection_timeout():
        """Get connection timeout in seconds"""
        return ConfigHelper.get('CONNECTION_TIMEOUT', 10)

    @staticmethod
    def client_wait_timeout():
        """Get client wait timeout in seconds"""
        return ConfigHelper.get('CLIENT_WAIT_TIMEOUT', 30)

    @staticmethod
    def stream_timeout():
        """Get stream timeout in seconds"""
        return ConfigHelper.get('STREAM_TIMEOUT', 60)

    @staticmethod
    def channel_shutdown_delay():
        """Get channel shutdown delay in seconds"""
        return Config.get_channel_shutdown_delay()

    @staticmethod
    def initial_behind_chunks():
        """Get number of chunks to start behind"""
        return ConfigHelper.get('INITIAL_BEHIND_CHUNKS', 4)

    @staticmethod
    def keepalive_interval():
        """Get keepalive interval in seconds"""
        return ConfigHelper.get('KEEPALIVE_INTERVAL', 0.5)

    @staticmethod
    def cleanup_check_interval():
        """Get cleanup check interval in seconds"""
        return ConfigHelper.get('CLEANUP_CHECK_INTERVAL', 3)

    @staticmethod
    def redis_chunk_ttl():
        """Get Redis chunk TTL in seconds"""
        return Config.get_redis_chunk_ttl()

    @staticmethod
    def chunk_size():
        """Get chunk size in bytes"""
        return ConfigHelper.get('CHUNK_SIZE', 8192)

    @staticmethod
    def max_retries():
        """Get maximum retry attempts"""
        return ConfigHelper.get('MAX_RETRIES', 3)

    @staticmethod
    def max_stream_switches():
        """Get maximum number of stream switch attempts"""
        return ConfigHelper.get('MAX_STREAM_SWITCHES', 10)

    @staticmethod
    def retry_wait_interval():
        """Get wait interval between connection retries in seconds"""
        return ConfigHelper.get('RETRY_WAIT_INTERVAL', 0.5)  # Default to 0.5 second

    @staticmethod
    def url_switch_timeout():
        """Get URL switch timeout in seconds (max time allowed for a stream switch operation)"""
        return ConfigHelper.get('URL_SWITCH_TIMEOUT', 20)  # Default to 20 seconds

    @staticmethod
    def failover_grace_period():
        """Get extra time (in seconds) to allow for stream switching before disconnecting clients"""
        return ConfigHelper.get('FAILOVER_GRACE_PERIOD', 20)  # Default to 20 seconds

    @staticmethod
    def buffering_timeout():
        """Get buffering timeout in seconds"""
        return Config.get_buffering_timeout()

    @staticmethod
    def buffering_speed():
        """Get buffering speed threshold"""
        return Config.get_buffering_speed()

    @staticmethod
    def channel_init_grace_period():
        """Get channel initialization grace period in seconds"""
        return Config.get_channel_init_grace_period()

    @staticmethod
    def chunk_timeout():
        """
        Get chunk timeout in seconds (used for both socket and HTTP read timeouts).
        This controls how long we wait for each chunk before timing out.
        Set this higher (e.g., 30s) for slow providers that may have intermittent delays.
        """
        return ConfigHelper.get('CHUNK_TIMEOUT', 5)  # Default 5 seconds
