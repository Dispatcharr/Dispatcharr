from django.apps import AppConfig


class ProxyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy'
    verbose_name = "Stream Proxies"

    def ready(self):
        """Eager-start live proxy only in stream-serving processes (uWSGI)."""
        from apps.proxy.live_proxy.runtime import start_live_proxy_if_stream_worker

        # HLS proxy retained in-tree but unused; live uses a singleton.
        self.live_proxy = start_live_proxy_if_stream_worker()
