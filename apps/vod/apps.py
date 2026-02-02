from django.apps import AppConfig


class VODConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.vod'
    verbose_name = 'Video on Demand'

    def ready(self):
        """Initialize VOD app when Django is ready"""
        # Import models to ensure they're registered
        from . import models
        # Import signals to register event handlers
        from . import signals
