# your_app/management/commands/update_column.py

from django.core.management.base import BaseCommand
from core.models import CoreSettings, NETWORK_ACCESS_KEY


class Command(BaseCommand):
    help = "Reset network access settings"

    def handle(self, *args, **options):
        setting = CoreSettings.objects.get(key=NETWORK_ACCESS_KEY)
        setting.value = {}
        setting.save()
