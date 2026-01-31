"""Plugin loader - main entry point and facade for the plugin system.

This module provides the PluginManager singleton that coordinates
plugin discovery, registration, and execution. It serves as the
primary interface for the rest of the application.

The implementation has been refactored into focused modules:
- discovery.py: Finding and loading plugins from disk
- registry.py: Managing loaded plugins in memory
- executor.py: Running plugin actions

This file maintains backwards compatibility while delegating to
the specialized modules.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from .discovery import PluginDiscovery
from .executor import PluginExecutor
from .registry import PluginRegistry
from .types import LoadedPlugin

logger = logging.getLogger(__name__)

# Re-export LoadedPlugin for backwards compatibility
__all__ = ["LoadedPlugin", "PluginManager"]


class PluginManager:
    """Singleton manager that discovers and runs plugins from /data/plugins.

    This is the main interface for the plugin system. It coordinates:
    - Plugin discovery from the filesystem
    - In-memory plugin registry
    - Database synchronization
    - Action execution

    Usage:
        pm = PluginManager.get()
        pm.discover_plugins()
        result = pm.run_action("my_plugin", "do_work", {"param": "value"})
    """

    _instance: Optional["PluginManager"] = None

    @classmethod
    def get(cls) -> "PluginManager":
        """Get the singleton PluginManager instance.

        Returns:
            The PluginManager singleton
        """
        if not cls._instance:
            cls._instance = PluginManager()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (mainly for testing).

        This clears the singleton, allowing a fresh instance to be created.
        """
        cls._instance = None

    def __init__(self) -> None:
        """Initialize the PluginManager.

        Sets up the plugins directory, discovery system, registry, and executor.
        """
        self.plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR", "/data/plugins")

        # Initialize subsystems
        self._discovery = PluginDiscovery(self.plugins_dir)
        self._registry = PluginRegistry()
        self._executor = PluginExecutor(self._registry)

    @property
    def _registry_dict(self) -> Dict[str, LoadedPlugin]:
        """Backwards compatibility: access to the internal registry dict.

        Deprecated: Use get_plugin() or list_plugins() instead.
        """
        return self._registry.get_all()

    def discover_plugins(self, *, sync_db: bool = True) -> Dict[str, LoadedPlugin]:
        """Discover all plugins in the plugins directory.

        This scans the plugins directory, loads all valid plugins,
        and optionally syncs with the database.

        Args:
            sync_db: Whether to sync discovered plugins to the database.
                    Set to False during early startup when DB isn't ready.

        Returns:
            Dictionary mapping plugin keys to LoadedPlugin instances
        """
        if sync_db:
            logger.info(f"Discovering plugins in {self.plugins_dir}")
        else:
            logger.debug(f"Discovering plugins (no DB sync) in {self.plugins_dir}")

        # Discover all plugins
        discovered = self._discovery.discover_all()

        # Update registry
        self._registry.update_from_discovery(discovered)

        logger.info(f"Discovered {len(self._registry)} plugin(s)")

        # Sync to database if requested
        if sync_db:
            try:
                self._registry.sync_to_database()
            except Exception:
                logger.exception("Deferring plugin DB sync; database not ready yet")

        return self._registry.get_all()

    def list_plugins(self) -> List[Dict[str, Any]]:
        """Get a list of all plugins with their configuration.

        Returns:
            List of plugin dictionaries with metadata and settings
        """
        return self._registry.list_plugins_with_config()

    def get_plugin(self, key: str) -> Optional[LoadedPlugin]:
        """Get a specific plugin by key.

        Args:
            key: The plugin key

        Returns:
            LoadedPlugin or None if not found
        """
        return self._registry.get(key)

    def update_settings(self, key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update settings for a plugin.

        Args:
            key: The plugin key
            settings: New settings dictionary

        Returns:
            The updated settings
        """
        return self._executor.update_settings(key, settings)

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
            params: Optional parameters for the action

        Returns:
            Result dictionary from the plugin

        Raises:
            ValueError: If plugin not found or has no run method
            PermissionError: If plugin is disabled
        """
        return self._executor.run_action(key, action_id, params)

    def set_enabled(self, key: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable a plugin.

        Args:
            key: The plugin key
            enabled: Whether to enable or disable

        Returns:
            Dictionary with enabled and ever_enabled flags
        """
        return self._executor.set_enabled(key, enabled)

    def reload_plugin(self, key: str) -> Optional[LoadedPlugin]:
        """Reload a single plugin.

        Args:
            key: The plugin key to reload

        Returns:
            Reloaded LoadedPlugin or None if not found
        """
        plugin = self._discovery.reload_plugin(key)
        if plugin:
            self._registry.register(plugin)
            try:
                self._registry.sync_to_database()
            except Exception:
                logger.exception(f"Failed to sync plugin {key} to database")
        return plugin
