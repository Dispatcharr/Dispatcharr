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
        """Get connection timeout in seconds from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("connection_timeout", 10)

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
        """Get number of chunks to start behind from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("initial_behind_chunks", 4)

    @staticmethod
    def new_client_behind_seconds():
        """Get number of seconds behind live to start new clients.
        0 means start at live (buffer head).
        Loaded from DB proxy_settings so users can change it at runtime."""
        from apps.proxy.config import TSConfig
        settings = TSConfig.get_proxy_settings()
        return settings.get('new_client_behind_seconds', 5)

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
        """Get maximum retry attempts from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("max_retries", 2)

    @staticmethod
    def max_stream_switches():
        """Get maximum number of stream switch attempts from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("max_stream_switches", 200)

    @staticmethod
    def retry_wait_interval():
        """Get wait interval between connection retries in seconds"""
        return ConfigHelper.get('RETRY_WAIT_INTERVAL', 0.5)  # Default to 0.5 second

    @staticmethod
    def url_switch_timeout():
        """Get URL switch timeout in seconds from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("url_switch_timeout", 20)

    @staticmethod
    def failover_grace_period():
        """Get failover grace period in seconds from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("failover_grace_period", 20)

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
        """Get chunk timeout in seconds from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("chunk_timeout", 5)

    @staticmethod
    def health_check_interval():
        """Get health check interval in seconds from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("health_check_interval", 5)

    @staticmethod
    def chunk_batch_size():
        """Get chunk batch size from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("chunk_batch_size", 5)

    @staticmethod
    def stream_cooldown_enabled():
        """Get whether stream cooldown is enabled from database or default"""
        settings = Config.get_proxy_settings()
        return settings.get("stream_cooldown_enabled", False)

    @staticmethod
    def stream_cooldown_seconds():
        """Get stream cooldown duration in seconds (converted from minutes) from database or default"""
        settings = Config.get_proxy_settings()
        minutes = settings.get("stream_cooldown_minutes", 10)
        return int(minutes) * 60
