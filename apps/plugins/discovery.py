"""Plugin discovery - finding and loading plugins from the filesystem.

This module handles scanning the plugins directory, importing plugin modules,
and extracting plugin metadata.
"""

import importlib
import logging
import os
import sys
from typing import Any, Dict, Optional, Tuple

from .types import LoadedPlugin

logger = logging.getLogger(__name__)


class PluginDiscovery:
    """Handles discovering and loading plugins from the filesystem."""

    def __init__(self, plugins_dir: str):
        """Initialize the discovery system.

        Args:
            plugins_dir: Path to the directory containing plugins
        """
        self.plugins_dir = plugins_dir
        self._ensure_plugins_dir()

    def _ensure_plugins_dir(self) -> None:
        """Ensure the plugins directory exists and is in sys.path."""
        os.makedirs(self.plugins_dir, exist_ok=True)
        if self.plugins_dir not in sys.path:
            sys.path.append(self.plugins_dir)

    def discover_all(self) -> Dict[str, LoadedPlugin]:
        """Discover all plugins in the plugins directory.

        Returns:
            Dictionary mapping plugin keys to LoadedPlugin instances
        """
        plugins: Dict[str, LoadedPlugin] = {}

        try:
            entries = sorted(os.listdir(self.plugins_dir))
        except FileNotFoundError:
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")
            return plugins

        for entry in entries:
            path = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(path):
                continue

            plugin_key = self._normalize_key(entry)

            try:
                loaded = self.load_plugin(plugin_key, path)
                if loaded:
                    plugins[plugin_key] = loaded
            except Exception:
                logger.exception(f"Failed to load plugin '{plugin_key}' from {path}")

        return plugins

    def load_plugin(self, key: str, path: str) -> Optional[LoadedPlugin]:
        """Load a single plugin from a directory.

        Args:
            key: The plugin key (normalized directory name)
            path: Full path to the plugin directory

        Returns:
            LoadedPlugin if successful, None if not a valid plugin
        """
        # Check for plugin.py or __init__.py
        has_pkg = os.path.exists(os.path.join(path, "__init__.py"))
        has_pluginpy = os.path.exists(os.path.join(path, "plugin.py"))

        if not (has_pkg or has_pluginpy):
            logger.debug(f"Skipping {path}: no plugin.py or package")
            return None

        # Try to import the plugin module
        module, plugin_cls = self._import_plugin_class(key, has_pluginpy, has_pkg)
        if plugin_cls is None:
            return None

        # Instantiate and extract metadata
        try:
            instance = plugin_cls()
        except Exception:
            logger.exception(f"Failed to instantiate Plugin class for '{key}'")
            return None

        return self._create_loaded_plugin(key, module, instance)

    def _import_plugin_class(
        self,
        key: str,
        has_pluginpy: bool,
        has_pkg: bool,
    ) -> Tuple[Any, Any]:
        """Import the Plugin class from a plugin module.

        Args:
            key: Plugin key for module naming
            has_pluginpy: Whether plugin.py exists
            has_pkg: Whether __init__.py exists

        Returns:
            Tuple of (module, plugin_class) or (None, None) if not found
        """
        # Build list of candidate module names to try
        candidate_modules = []
        if has_pluginpy:
            candidate_modules.append(f"{key}.plugin")
        if has_pkg:
            candidate_modules.append(key)

        module = None
        plugin_cls = None
        last_error = None

        for module_name in candidate_modules:
            try:
                logger.debug(f"Importing plugin module {module_name}")
                module = importlib.import_module(module_name)
                plugin_cls = getattr(module, "Plugin", None)
                if plugin_cls is not None:
                    break
                else:
                    logger.warning(f"Module {module_name} has no Plugin class")
            except Exception as e:
                last_error = e
                logger.exception(f"Error importing module {module_name}")

        if plugin_cls is None:
            if last_error:
                raise last_error
            logger.warning(f"No Plugin class found for {key}; skipping")

        return module, plugin_cls

    def _create_loaded_plugin(
        self,
        key: str,
        module: Any,
        instance: Any,
    ) -> LoadedPlugin:
        """Create a LoadedPlugin from an instantiated plugin.

        Args:
            key: Plugin key
            module: The imported module
            instance: The Plugin instance

        Returns:
            LoadedPlugin with extracted metadata
        """
        return LoadedPlugin(
            key=key,
            name=getattr(instance, "name", key),
            version=getattr(instance, "version", ""),
            description=getattr(instance, "description", ""),
            module=module,
            instance=instance,
            fields=getattr(instance, "fields", []),
            actions=getattr(instance, "actions", []),
        )

    def reload_plugin(self, key: str) -> Optional[LoadedPlugin]:
        """Reload a single plugin, refreshing its module.

        Args:
            key: The plugin key to reload

        Returns:
            Reloaded LoadedPlugin or None if not found
        """
        path = os.path.join(self.plugins_dir, key)
        if not os.path.isdir(path):
            return None

        # Invalidate cached modules
        modules_to_remove = [
            name for name in sys.modules
            if name == key or name.startswith(f"{key}.")
        ]
        for mod_name in modules_to_remove:
            del sys.modules[mod_name]

        return self.load_plugin(key, path)

    @staticmethod
    def _normalize_key(entry: str) -> str:
        """Normalize a directory name to a plugin key.

        Args:
            entry: Directory name

        Returns:
            Normalized plugin key (lowercase, spaces as underscores)
        """
        return entry.replace(" ", "_").lower()
