from django.core.management.base import BaseCommand
from django.apps import apps
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Manage proxy servers'

    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            choices=['start', 'stop', 'restart'],
            help='Action to perform'
        )
        parser.add_argument(
            '--type',
            choices=['hls', 'ts', 'all'],
            default='all',
            help='Type of proxy to manage'
        )
        parser.add_argument(
            '--channel',
            help='Channel ID to manage'
        )
        parser.add_argument(
            '--url',
            help='Stream URL (required for start)'
        )

    def handle(self, *args, **options):
        proxy_app = apps.get_app_config('proxy')
        action = options['action']
        proxy_type = options['type']
        channel = options.get('channel')
        url = options.get('url')

        try:
            if action == 'start':
                if not url:
                    raise ValueError("URL is required for start action")
                if proxy_type in ('hls', 'all'):
                    proxy_app.hls_proxy.initialize_channel(url, channel or 'default')
                if proxy_type in ('ts', 'all'):
                    proxy_app.ts_proxy.initialize_channel(url, channel or 'default')
                self.stdout.write(self.style.SUCCESS('Started proxy servers'))

            elif action == 'stop':
                if proxy_type in ('hls', 'all'):
                    if channel:
                        proxy_app.hls_proxy.stop_channel(channel)
                    else:
                        proxy_app.hls_proxy.shutdown()
                if proxy_type in ('ts', 'all'):
                    if channel:
                        proxy_app.ts_proxy.stop_channel(channel)
                    else:
                        proxy_app.ts_proxy.shutdown()
                self.stdout.write(self.style.SUCCESS('Stopped proxy servers'))

            elif action == 'restart':
                self.handle(*args, **dict(options, action='stop'))
                self.handle(*args, **dict(options, action='start'))
                self.stdout.write(self.style.SUCCESS('Restarted proxy servers'))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error: {e}'))