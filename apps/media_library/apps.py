from django.apps import AppConfig


class MediaLibraryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.media_library'
    verbose_name = 'Media Library'
    label = 'media_library'

    def ready(self):
        import apps.media_library.signals
