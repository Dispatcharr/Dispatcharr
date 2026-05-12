import sys
from django.apps import AppConfig

class ProxyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy'
    verbose_name = "Stream Proxies"

    def ready(self):
        """Initialize proxy servers when Django starts"""
        if 'manage.py' not in sys.argv:
            from .hls_proxy.server import ProxyServer as HLSProxyServer
            from .live_proxy.server import ProxyServer as LiveProxyServer

            # Initialize proxy servers (live uses singleton to prevent duplicate instances)
            self.hls_proxy = HLSProxyServer()
            self.live_proxy = LiveProxyServer.get_instance()
