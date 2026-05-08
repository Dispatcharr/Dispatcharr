import sys
from django.apps import AppConfig

class LiveProxyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy.live_proxy'
    verbose_name = "Live Stream Proxy"

    def ready(self):
        """Initialize proxy servers when Django starts"""
        if 'manage.py' not in sys.argv:
            from .server import ProxyServer
            ProxyServer.get_instance()
