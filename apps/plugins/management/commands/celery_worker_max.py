from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Print the configured autoscale ceiling for the default Celery worker.

    Standalone rather than reading CoreSettings straight from the shell
    since uwsgi.ini/entrypoint.celery.sh have no other way to read a DB
    value before the worker process starts.
    """

    help = "Print CoreSettings.get_celery_max_workers()."

    def handle(self, *args, **options):
        from core.models import CoreSettings

        self.stdout.write(str(CoreSettings.get_celery_max_workers()))
