# apps/plugins/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import PluginConfig
from core import events
from core.signal_helpers import _get_instance_context, _set_context, _clear_context
import logging

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=PluginConfig)
def track_plugin_changes(sender, instance, **kwargs):
    """Track enabled/disabled and settings changes for plugin events."""
    if not instance.pk:
        return  # New instance

    try:
        old = PluginConfig.objects.get(pk=instance.pk)
        changes = {}

        # Track enabled/disabled change
        if old.enabled != instance.enabled:
            changes['enabled_changed'] = instance.enabled

        # Track settings change
        if old.settings != instance.settings:
            changes['settings_changed'] = True

        if changes:
            _set_context('PluginConfig', instance.pk, changes)
    except PluginConfig.DoesNotExist:
        pass


@receiver(post_save, sender=PluginConfig)
def emit_plugin_state_events(sender, instance, created, **kwargs):
    """Emit plugin enabled/disabled/configured events after save."""
    if created:
        return  # No events for initial plugin discovery

    ctx = _get_instance_context('PluginConfig', instance.pk)

    # Emit enabled/disabled event
    if 'enabled_changed' in ctx:
        if ctx['enabled_changed']:
            events.emit("plugin.enabled", instance)
        else:
            events.emit("plugin.disabled", instance)

    # Emit configured event
    if 'settings_changed' in ctx:
        events.emit("plugin.configured", instance)

    # Clear context after processing
    if ctx:
        _clear_context('PluginConfig', instance.pk)
