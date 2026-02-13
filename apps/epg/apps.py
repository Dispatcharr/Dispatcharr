from django.apps import AppConfig


class EpgConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.epg'
    verbose_name = "EPG Management"

    def ready(self):
        # Import signals to ensure they get registered
        import apps.epg.signals
