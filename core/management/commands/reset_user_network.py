from django.core.management.base import BaseCommand
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Reset per-user network access restrictions"

    def add_arguments(self, parser):
        parser.add_argument('--user', type=str, help='Username to reset (omit to reset all users)')

    def handle(self, *args, **options):
        username = options.get('user')
        qs = User.objects.filter(username=username) if username else User.objects.all()
        count = 0
        for user in qs:
            props = user.custom_properties or {}
            if 'allowed_networks' in props:
                del props['allowed_networks']
                user.custom_properties = props
                user.save(update_fields=['custom_properties'])
                count += 1
        self.stdout.write(f"Reset allowed_networks for {count} user(s).")
