from django.apps import AppConfig


class HLSOutputConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy.hls_output'
    verbose_name = 'HLS Output'
    
    def ready(self):
        """Import signals when app is ready"""
        try:
            import apps.proxy.hls_output.signals  # noqa
        except ImportError:
            pass

