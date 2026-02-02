# apps/plugins/signals.py
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import PluginConfig
from core import events
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=PluginConfig)
def emit_plugin_installed_event(sender, instance, created, **kwargs):
    """Emit plugin.installed when a new plugin is discovered."""
    if created:
        events.emit("plugin.installed", instance)


@receiver(post_delete, sender=PluginConfig)
def emit_plugin_uninstalled_event(sender, instance, **kwargs):
    """Emit plugin.uninstalled when a plugin is removed."""
    events.emit("plugin.uninstalled", instance)


@receiver(pre_save, sender=PluginConfig)
def track_plugin_changes(sender, instance, **kwargs):
    """Track which fields changed for plugin events."""
    if not instance.pk:
        return  # New instance, will emit installed event

    try:
        old = PluginConfig.objects.get(pk=instance.pk)
        # Track enabled/disabled change
        if old.enabled != instance.enabled:
            instance._enabled_changed = instance.enabled
        # Track settings change
        if old.settings != instance.settings:
            instance._settings_changed = True
    except PluginConfig.DoesNotExist:
        pass


@receiver(post_save, sender=PluginConfig)
def emit_plugin_state_events(sender, instance, created, **kwargs):
    """Emit plugin enabled/disabled/configured events after save."""
    if created:
        return  # Handled by installed event

    # Emit enabled/disabled event
    if hasattr(instance, '_enabled_changed'):
        if instance._enabled_changed:
            events.emit("plugin.enabled", instance)
        else:
            events.emit("plugin.disabled", instance)
        del instance._enabled_changed

    # Emit configured event
    if hasattr(instance, '_settings_changed'):
        events.emit("plugin.configured", instance)
        del instance._settings_changed
