import sys
import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class LiveProxyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy.live_proxy'
    verbose_name = "Live Stream Proxy"

    def ready(self):
        """Initialize proxy servers when Django starts"""
        if 'manage.py' not in sys.argv:
            from .server import ProxyServer
            ProxyServer.get_instance()
            _reconcile_profile_connections()


def _reconcile_profile_connections():
    """
    Reset profile_connections:* Redis counters to match the real number of
    active channels stored in live:channel:*:metadata.

    On a clean restart there are no active channels, so all counters become 0
    and any stale values left by a previous crash are cleared.  On a live
    reload (gunicorn SIGHUP / uWSGI chain-reload) the counters are rebuilt
    from actual metadata, preventing false "max connections reached" errors.
    """
    try:
        from core.utils import RedisClient
        from .constants import ChannelMetadataField

        redis_client = RedisClient.get_client()
        if not redis_client:
            return

        # Count active channels per profile from the metadata hashes.
        profile_counts: dict[str, int] = {}
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(
                cursor, match="live:channel:*:metadata", count=200
            )
            for key in keys:
                try:
                    profile_id = redis_client.hget(key, ChannelMetadataField.M3U_PROFILE)
                    if profile_id:
                        pk = str(profile_id)
                        profile_counts[pk] = profile_counts.get(pk, 0) + 1
                except Exception:
                    pass
            if cursor == 0:
                break

        # Delete all stale profile_connections:* keys first.
        stale_keys = []
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(
                cursor, match="profile_connections:*", count=200
            )
            stale_keys.extend(keys)
            if cursor == 0:
                break

        if stale_keys:
            redis_client.delete(*stale_keys)

        # Re-set counters from the actual channel counts.
        for profile_id, count in profile_counts.items():
            if count > 0:
                redis_client.set(f"profile_connections:{profile_id}", count)

        logger.info(
            "profile_connections reconciled on startup: "
            f"cleared {len(stale_keys)} stale key(s), "
            f"rebuilt {len(profile_counts)} active profile counter(s)"
        )

    except Exception as exc:
        logger.warning(f"profile_connections reconciliation failed (non-fatal): {exc}")
