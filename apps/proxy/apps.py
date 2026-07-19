import sys
from django.apps import AppConfig

class ProxyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy'
    verbose_name = "Stream Proxies"

    def ready(self):
        """Initialize proxy servers when Django starts"""
        if 'manage.py' not in sys.argv:
            from .live_proxy.server import ProxyServer as LiveProxyServer

            # HLS proxy retained in-tree but unused; live uses a singleton.
            self.live_proxy = LiveProxyServer.get_instance()
