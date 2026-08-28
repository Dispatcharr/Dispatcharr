from django.apps import AppConfig


class LiveProxyConfig(AppConfig):
    """Live stream proxy models/services.

    Eager ``ProxyServer`` startup lives in ``apps.proxy.apps.ProxyConfig`` and
    only runs in stream-serving processes. Celery/Daphne use lazy client-only
    ``ProxyServer.get_instance()`` when ``ChannelService`` needs Redis.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy.live_proxy'
    verbose_name = "Live Stream Proxy"
