# apps/m3u/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import M3UAccount
from .tasks import refresh_single_m3u_account, refresh_m3u_groups

@receiver(post_save, sender=M3UAccount)
def refresh_account_on_save(sender, instance, created, **kwargs):
    """
    When an M3UAccount is saved (created or updated),
    call a Celery task that fetches & parses that single account
    if it is active or newly created.
    """
    if created:
        refresh_m3u_groups(instance.id)
