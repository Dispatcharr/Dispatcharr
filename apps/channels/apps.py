from django.apps import AppConfig

class ChannelsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.channels'
    verbose_name = "Channel & Stream Management"
    label = 'dispatcharr_channels'

    def ready(self):
        # Import signals so they get registered.
        import apps.channels.signals
