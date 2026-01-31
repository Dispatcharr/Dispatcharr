"""Plugin executor - running plugin actions.

This module handles the execution of plugin actions, including
building the execution context and normalizing responses.
"""

import logging
from typing import Any, Dict, Optional

from .registry import PluginRegistry
from .types import LoadedPlugin

logger = logging.getLogger(__name__)


class PluginExecutor:
    """Handles executing plugin actions."""

    def __init__(self, registry: PluginRegistry):
        """Initialize the executor.

        Args:
            registry: The plugin registry to use for lookups
        """
        self.registry = registry

    def run_action(
        self,
        key: str,
        action_id: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a plugin action.

        Args:
            key: The plugin key
            action_id: The action ID to execute
            params: Optional parameters to pass to the action

        Returns:
            Result dictionary from the plugin

        Raises:
            ValueError: If the plugin is not found or has no run method
            PermissionError: If the plugin is disabled
        """
        from .models import PluginConfig

        # Get the plugin from registry
        plugin = self.registry.get(key)
        if not plugin or not plugin.instance:
            raise ValueError(f"Plugin '{key}' not found")

        # Check if plugin is enabled
        config = PluginConfig.objects.get(key=key)
        if not config.enabled:
            raise PermissionError(f"Plugin '{key}' is disabled")

        # Validate the run method exists
        run_method = getattr(plugin.instance, "run", None)
        if not callable(run_method):
            raise ValueError(f"Plugin '{key}' has no runnable 'run' method")

        # Build execution context
        context = self._build_context(plugin, config)

        # Execute the action
        params = params or {}
        try:
            result = run_method(action_id, params, context)
        except Exception:
            logger.exception(f"Plugin '{key}' action '{action_id}' failed")
            raise

        # Normalize the result
        return self._normalize_result(result)

    def _build_context(
        self,
        plugin: LoadedPlugin,
        config: Any,
    ) -> Dict[str, Any]:
        """Build the execution context for a plugin action.

        Args:
            plugin: The LoadedPlugin instance
            config: The PluginConfig database record

        Returns:
            Context dictionary for the plugin
        """
        return {
            "settings": config.settings or {},
            "logger": logger,
            "actions": {
                a.get("id"): a
                for a in (plugin.actions or [])
            },
        }

    def _normalize_result(self, result: Any) -> Dict[str, Any]:
        """Normalize a plugin result to a standard format.

        Args:
            result: The raw result from the plugin

        Returns:
            Normalized result dictionary
        """
        if isinstance(result, dict):
            return result
        return {"status": "ok", "result": result}

    def update_settings(
        self,
        key: str,
        settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update plugin settings.

        Args:
            key: The plugin key
            settings: New settings dictionary

        Returns:
            The updated settings
        """
        from .models import PluginConfig

        config = PluginConfig.objects.get(key=key)
        config.settings = settings or {}
        config.save(update_fields=["settings", "updated_at"])
        return config.settings

    def set_enabled(
        self,
        key: str,
        enabled: bool,
    ) -> Dict[str, Any]:
        """Enable or disable a plugin.

        Args:
            key: The plugin key
            enabled: Whether to enable or disable

        Returns:
            Dictionary with enabled and ever_enabled flags
        """
        from .models import PluginConfig

        config = PluginConfig.objects.get(key=key)
        config.enabled = enabled

        # Track if this plugin has ever been enabled (for trust warning)
        if enabled and not config.ever_enabled:
            config.ever_enabled = True

        config.save(update_fields=["enabled", "ever_enabled", "updated_at"])

        # Call lifecycle hooks if the plugin supports them
        plugin = self.registry.get(key)
        if plugin and plugin.instance:
            context = self._build_context(plugin, config)
            if enabled:
                hook = getattr(plugin.instance, "on_enable", None)
            else:
                hook = getattr(plugin.instance, "on_disable", None)

            if callable(hook):
                try:
                    hook(context)
                except Exception:
                    logger.exception(f"Plugin '{key}' lifecycle hook failed")

        return {
            "enabled": config.enabled,
            "ever_enabled": config.ever_enabled,
        }
