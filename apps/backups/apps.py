from django.apps import AppConfig


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backups"
    verbose_name = "Backups"

    def ready(self):
        # Import signals or schedule hooks lazily
        try:
            from . import signals  # noqa: F401
        except ImportError:
            pass
