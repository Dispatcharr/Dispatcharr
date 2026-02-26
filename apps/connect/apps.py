from django.apps import AppConfig


class ConnectConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.connect'
    verbose_name = "Connect Integrations"
    label = 'dispatcharr_connect'
