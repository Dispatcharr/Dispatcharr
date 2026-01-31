"""Plugin registry - managing loaded plugins in memory.

This module provides the central registry for tracking loaded plugins
and synchronizing with the database.
"""

import logging
from typing import Any, Dict, List, Optional

from django.db import transaction

from .types import LoadedPlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Manages the in-memory registry of loaded plugins."""

    def __init__(self):
        """Initialize an empty registry."""
        self._plugins: Dict[str, LoadedPlugin] = {}

    def clear(self) -> None:
        """Clear all plugins from the registry."""
        self._plugins.clear()

    def register(self, plugin: LoadedPlugin) -> None:
        """Register a plugin in the registry.

        Args:
            plugin: The LoadedPlugin to register
        """
        self._plugins[plugin.key] = plugin
        logger.debug(f"Registered plugin: {plugin.key} ({plugin.name})")

    def unregister(self, key: str) -> Optional[LoadedPlugin]:
        """Remove a plugin from the registry.

        Args:
            key: The plugin key to remove

        Returns:
            The removed LoadedPlugin or None if not found
        """
        return self._plugins.pop(key, None)

    def get(self, key: str) -> Optional[LoadedPlugin]:
        """Get a plugin by key.

        Args:
            key: The plugin key

        Returns:
            LoadedPlugin or None if not found
        """
        return self._plugins.get(key)

    def get_all(self) -> Dict[str, LoadedPlugin]:
        """Get all registered plugins.

        Returns:
            Dictionary mapping keys to LoadedPlugin instances
        """
        return self._plugins.copy()

    def keys(self) -> List[str]:
        """Get all registered plugin keys.

        Returns:
            List of plugin keys
        """
        return list(self._plugins.keys())

    def __len__(self) -> int:
        """Get the number of registered plugins."""
        return len(self._plugins)

    def __contains__(self, key: str) -> bool:
        """Check if a plugin key is registered."""
        return key in self._plugins

    def update_from_discovery(self, discovered: Dict[str, LoadedPlugin]) -> None:
        """Update the registry with newly discovered plugins.

        Args:
            discovered: Dictionary of discovered plugins
        """
        self._plugins = discovered
        logger.info(f"Registry updated with {len(discovered)} plugin(s)")

    def sync_to_database(self) -> None:
        """Synchronize the registry with the database.

        Creates or updates PluginConfig records for all registered plugins.
        """
        from .models import PluginConfig

        try:
            with transaction.atomic():
                for key, plugin in self._plugins.items():
                    obj, created = PluginConfig.objects.get_or_create(
                        key=key,
                        defaults={
                            "name": plugin.name,
                            "version": plugin.version,
                            "description": plugin.description,
                            "settings": {},
                        },
                    )

                    # Update metadata if changed
                    if not created:
                        changed = False
                        if obj.name != plugin.name:
                            obj.name = plugin.name
                            changed = True
                        if obj.version != plugin.version:
                            obj.version = plugin.version
                            changed = True
                        if obj.description != plugin.description:
                            obj.description = plugin.description
                            changed = True
                        if changed:
                            obj.save()

            logger.debug(f"Synced {len(self._plugins)} plugins to database")
        except Exception:
            logger.exception("Failed to sync plugins to database")
            raise

    def list_plugins_with_config(self) -> List[Dict[str, Any]]:
        """Get a list of all plugins with their database configuration.

        Merges in-memory plugin data with database configuration (enabled, settings).
        Also includes plugins that exist in the database but failed to load (marked as missing).

        Returns:
            List of plugin dictionaries with full metadata and config
        """
        from .models import PluginConfig

        plugins: List[Dict[str, Any]] = []

        # Get database configs
        try:
            configs = {c.key: c for c in PluginConfig.objects.all()}
        except Exception as e:
            logger.warning("PluginConfig table unavailable: %s", e)
            configs = {}

        # Include all discovered plugins
        for key, plugin in self._plugins.items():
            conf = configs.get(key)
            plugins.append({
                "key": key,
                "name": plugin.name,
                "version": plugin.version,
                "description": plugin.description,
                "enabled": conf.enabled if conf else False,
                "ever_enabled": getattr(conf, "ever_enabled", False) if conf else False,
                "fields": plugin.fields or [],
                "settings": conf.settings if conf else {},
                "actions": plugin.actions or [],
                "missing": False,
            })

        # Include database-only configs (files missing or failed to load)
        discovered_keys = set(self._plugins.keys())
        for key, conf in configs.items():
            if key in discovered_keys:
                continue
            plugins.append({
                "key": key,
                "name": conf.name,
                "version": conf.version,
                "description": conf.description,
                "enabled": conf.enabled,
                "ever_enabled": getattr(conf, "ever_enabled", False),
                "fields": [],
                "settings": conf.settings or {},
                "actions": [],
                "missing": True,
            })

        return plugins
