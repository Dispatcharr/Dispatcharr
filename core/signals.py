from celery.signals import task_prerun
from django.core.signals import request_started
from django.db.models.signals import pre_delete, post_delete, post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from dispatcharr.display_timezone import refresh_display_zone, set_display_zone
from .models import StreamProfile, CoreSettings, UserAgent, NETWORK_ACCESS_KEY, SYSTEM_SETTINGS_KEY

@receiver(pre_delete, sender=StreamProfile)
def prevent_deletion_if_locked(sender, instance, **kwargs):
    if instance.locked:
        raise ValidationError("This profile is locked and cannot be deleted.")

@receiver(request_started, dispatch_uid="core_refresh_log_display_zone")
def refresh_log_display_zone_on_request(sender, **kwargs):
    refresh_display_zone()

@task_prerun.connect(weak=False)
def refresh_log_display_zone_on_task(**kwargs):
    refresh_display_zone()

@receiver(post_save, sender=CoreSettings)
def refresh_log_display_zone_on_settings_change(sender, instance, **kwargs):
    if instance.key == SYSTEM_SETTINGS_KEY:
        set_display_zone((instance.value or {}).get("time_zone"))

@receiver(post_save, sender=CoreSettings)
@receiver(post_delete, sender=CoreSettings)
def handle_coresettings_cache_invalidation(sender, instance, **kwargs):
    """Drop Redis group cache whenever a CoreSettings row is saved or deleted."""
    CoreSettings.invalidate_group_cache(instance.key)

@receiver(post_save, sender=UserAgent)
@receiver(post_delete, sender=UserAgent)
def handle_user_agent_cache_invalidation(sender, instance, **kwargs):
    """Drop cached default User-Agent string when any UserAgent row changes."""
    CoreSettings.invalidate_default_user_agent_cache()

@receiver(post_save, sender=CoreSettings)
def handle_network_access_update(sender, instance, **kwargs):
    """Sync developer notifications when network access settings change."""
    if instance.key != NETWORK_ACCESS_KEY:
        return

    from django.core.cache import cache
    from core.developer_notifications import sync_developer_notifications
    import logging

    logger = logging.getLogger(__name__)

    # Invalidate all notification condition caches
    try:
        cache.delete_pattern('dev_notif_condition_*')
        logger.info("Invalidated notification condition cache due to network access settings update")
    except Exception as e:
        logger.warning(f"Failed to delete cache pattern: {e}")
        # Fallback: try to clear entire cache (if delete_pattern not supported)
        try:
            cache.clear()
        except Exception:
            pass

    # Re-sync developer notifications to re-evaluate conditions
    # (websocket notification is sent by sync_developer_notifications)
    try:
        sync_developer_notifications()
        logger.info("Re-synced developer notifications after network access settings update")
    except Exception as e:
        logger.error(f"Failed to sync developer notifications: {e}")
