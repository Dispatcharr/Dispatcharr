"""
Celery tasks for plugin event dispatch.
"""
import logging
import re
from celery import shared_task

logger = logging.getLogger(__name__)

# Security: Only allow handler names matching this pattern
# Handlers must start with 'on_' followed by lowercase letters, numbers, or underscores
ALLOWED_HANDLER_PATTERN = re.compile(r'^on_[a-z][a-z0-9_]*$')


def is_valid_handler_name(handler_name: str) -> bool:
    """
    Validate that a handler name is safe to invoke.

    Security: Prevents arbitrary method invocation by requiring handlers to:
    - Start with 'on_' prefix (convention for event handlers)
    - Not start with underscore (blocks private/dunder methods)
    - Match a strict alphanumeric pattern
    """
    if not handler_name or not isinstance(handler_name, str):
        return False

    # Block any attempt to access private or dunder methods
    if handler_name.startswith('_'):
        return False

    # Require the on_ prefix and alphanumeric pattern
    return bool(ALLOWED_HANDLER_PATTERN.match(handler_name))


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

    # Security: Validate handler name before any getattr call
    if not is_valid_handler_name(handler_name):
        logger.error(
            f"Blocked invalid handler name '{handler_name}' for plugin '{plugin_key}'. "
            "Handler names must start with 'on_' and contain only lowercase alphanumeric characters."
        )
        return

    # Check if plugin is still enabled
    if not PluginConfig.objects.filter(key=plugin_key, enabled=True).exists():
        logger.debug(f"Plugin '{plugin_key}' is disabled, skipping event '{event_name}'")
        return

    # Get the plugin instance
    plugin = PluginManager.get().get_plugin(plugin_key)
    if not plugin or not plugin.instance:
        logger.warning(f"Plugin '{plugin_key}' not found or has no instance")
        return

    # Get the handler method (safe after validation)
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
