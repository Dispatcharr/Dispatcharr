from django.apps import AppConfig


class MediaLibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.media_library"
    verbose_name = "Media Library"

    def ready(self):
        # Import signals when needed without causing circular dependencies
        try:
            import apps.media_library.signals  # noqa: F401
        except ImportError:
            pass
