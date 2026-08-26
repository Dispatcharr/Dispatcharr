from django.db.models.signals import pre_delete, post_delete, post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.conf import settings
from dispatcharr.log_collector import apply_settings
from .models import (
    StreamProfile,
    CoreSettings,
    OutputProfile,
    UserAgent,
    NETWORK_ACCESS_KEY,
    SYSTEM_SETTINGS_KEY,
    scrub_output_profile_id,
)

@receiver(pre_delete, sender=StreamProfile)
def prevent_deletion_if_locked(sender, instance, **kwargs):
    if instance.locked:
        raise ValidationError("This profile is locked and cannot be deleted.")


@receiver(pre_delete, sender=OutputProfile)
def prevent_output_profile_deletion_if_locked(sender, instance, **kwargs):
    if instance.locked:
        raise ValidationError("This profile is locked and cannot be deleted.")


@receiver(post_delete, sender=OutputProfile)
def cleanup_output_profile_references(sender, instance, **kwargs):
    """Drop stale user and HDHR references when an output profile is deleted."""
    try:
        scrub_output_profile_id(instance.id)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Error scrubbing references for deleted OutputProfile %s",
            instance.id,
        )


@receiver(post_save, sender=CoreSettings)
def apply_log_collector_settings(sender, instance, **kwargs):
    if instance.key == SYSTEM_SETTINGS_KEY:
        # A user save that goes unapplied is worth a warning; boot is not, the collector may still be starting.
        apply_settings(
            getattr(settings, "LOG_FILE_DIR", None),
            instance.value,
            warn_if_absent=True,
        )

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
