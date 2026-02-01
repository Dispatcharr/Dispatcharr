"""
Celery tasks for plugin event dispatch.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    bind=True
)
def dispatch_event(self, plugin_key: str, handler_name: str, event_name: str, data: dict):
    """
    Call a plugin's event handler.

    This task is dispatched by RedisPubSubManager.emit() when
    a system event occurs that plugins have subscribed to.

    Args:
        plugin_key: The plugin's unique key
        handler_name: The name of the handler method to call
        event_name: The event that triggered this dispatch
        data: The event data to pass to the handler
    """
    from apps.plugins.models import PluginConfig
    from apps.plugins.loader import PluginManager

    # Check if plugin is still enabled
    if not PluginConfig.objects.filter(key=plugin_key, enabled=True).exists():
        logger.debug(f"Plugin '{plugin_key}' is disabled, skipping event '{event_name}'")
        return

    # Get the plugin instance
    plugin = PluginManager.get().get_plugin(plugin_key)
    if not plugin or not plugin.instance:
        logger.warning(f"Plugin '{plugin_key}' not found or has no instance")
        return

    # Get the handler method
    handler = getattr(plugin.instance, handler_name, None)
    if not callable(handler):
        logger.warning(f"Plugin '{plugin_key}' has no callable handler '{handler_name}'")
        return

    # Call the handler
    try:
        handler(event_name, data)
        logger.info(f"Plugin '{plugin_key}' handled event '{event_name}' successfully")
    except Exception as e:
        logger.error(
            f"Plugin '{plugin_key}' handler '{handler_name}' failed for event '{event_name}': {e}",
            exc_info=True
        )
        # Re-raise to trigger Celery retry
        raise
