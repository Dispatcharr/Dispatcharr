from django.db.models.signals import post_migrate
from django.dispatch import receiver

from . import services


@receiver(post_migrate)
def sync_schedule_after_migrate(sender, **kwargs):  # pragma: no cover - startup hook
    try:
        services.sync_backup_schedule()
    except Exception:
        # Avoid breaking migrations if Celery beat tables are unavailable yet
        pass
