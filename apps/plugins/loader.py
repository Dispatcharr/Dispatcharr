import importlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import yaml
from django.db import transaction

from .manifest import extract_manifest_metadata, load_manifest, validate_manifest
from .models import PluginConfig
from .version import check_compatibility

logger = logging.getLogger(__name__)

# Default cache TTL for plugin discovery (seconds)
DEFAULT_DISCOVERY_CACHE_TTL = 60.0


@dataclass
class LoadedPlugin:
    """Represents a discovered plugin with its metadata."""
    key: str  # Directory-based key (used for registry and DB)
    name: str
    version: str = ""
    description: str = ""
    module: Any = None
    instance: Any = None
    fields: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    # Manifest-related fields
    compatible: bool = True
    compatibility_error: str = ""
    repository: str = ""
    authors: list[str] = field(default_factory=list)
    icon: str = ""
    has_manifest: bool = False
    manifest_key: str = ""  # Key declared in manifest (for uniqueness checking)


class PluginManager:
    """Singleton manager that discovers and runs plugins from /data/plugins."""

    _instance: "PluginManager | None" = None

    @classmethod
    def get(cls) -> "PluginManager":
        if not cls._instance:
            cls._instance = PluginManager()
        return cls._instance

    def __init__(self) -> None:
        """Initialize the plugin manager."""
        self.plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR", "/data/plugins")
        self._registry: dict[str, LoadedPlugin] = {}
        # Discovery caching
        self._discovery_timestamp: float = 0
        self._discovery_cache_ttl: float = float(
            os.environ.get("DISPATCHARR_PLUGIN_CACHE_TTL", DEFAULT_DISCOVERY_CACHE_TTL)
        )

        # Ensure plugins directory exists
        os.makedirs(self.plugins_dir, exist_ok=True)
        if self.plugins_dir not in sys.path:
            sys.path.append(self.plugins_dir)

    def _is_cache_valid(self) -> bool:
        """Check if the discovery cache is still valid."""
        if not self._registry:
            return False
        return (time.time() - self._discovery_timestamp) < self._discovery_cache_ttl

    def discover_plugins(
        self, *, sync_db: bool = True, force: bool = False
    ) -> dict[str, LoadedPlugin]:
        """Discover plugins from the plugins directory.

        Args:
            sync_db: Whether to sync discovered plugins with the database.
            force: Force rediscovery even if cache is valid.

        Returns:
            Dictionary mapping plugin keys to LoadedPlugin instances.
        """
        # Return cached results if valid and not forced
        if not force and self._is_cache_valid():
            logger.debug("Using cached plugin discovery results")
            return self._registry

        if sync_db:
            logger.info(f"Discovering plugins in {self.plugins_dir}")
        else:
            logger.debug(f"Discovering plugins (no DB sync) in {self.plugins_dir}")
        self._registry.clear()

        try:
            for entry in sorted(os.listdir(self.plugins_dir)):
                path = os.path.join(self.plugins_dir, entry)
                if not os.path.isdir(path):
                    continue
                # Skip symlinked directories (security)
                if os.path.islink(path):
                    logger.warning(f"Skipping symlinked plugin directory: {path}")
                    continue

                plugin_key = entry.replace(" ", "_").lower()

                try:
                    self._load_plugin(plugin_key, path)
                except Exception:
                    logger.exception(f"Failed to load plugin '{plugin_key}' from {path}")

            logger.info(f"Discovered {len(self._registry)} plugin(s)")
        except FileNotFoundError:
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")

        # Update cache timestamp
        self._discovery_timestamp = time.time()

        # Sync DB records (optional)
        if sync_db:
            try:
                self._sync_db_with_registry()
            except Exception:
                # Defer sync if database is not ready (e.g., first startup before migrate)
                logger.exception("Deferring plugin DB sync; database not ready yet")
        return self._registry

    def _make_loaded_plugin(
        self,
        key: str,
        manifest_meta: dict[str, Any] | None = None,
        *,
        module: Any = None,
        instance: Any = None,
        fields: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
        compatible: bool = True,
        compatibility_error: str = "",
    ) -> LoadedPlugin:
        """Create a LoadedPlugin from manifest metadata with optional overrides.

        Args:
            key: The plugin's directory-based key.
            manifest_meta: Metadata extracted from plugin.yaml (or None for legacy plugins).
            module: The loaded Python module (if any).
            instance: The Plugin class instance (if any).
            fields: Plugin configuration fields.
            actions: Plugin actions.
            compatible: Whether the plugin is compatible with this Dispatcharr version.
            compatibility_error: Error message if incompatible.

        Returns:
            A LoadedPlugin instance with all fields populated.
        """
        meta = manifest_meta or {}
        return LoadedPlugin(
            key=key,
            name=meta.get("name", key),
            version=meta.get("version", ""),
            description=meta.get("description", ""),
            module=module,
            instance=instance,
            fields=fields or [],
            actions=actions or [],
            compatible=compatible,
            compatibility_error=compatibility_error,
            repository=meta.get("repository", ""),
            authors=meta.get("authors", []),
            icon=meta.get("icon", ""),
            has_manifest=manifest_meta is not None,
            manifest_key=meta.get("key", ""),
        )

    def _load_plugin(self, key: str, path: str) -> None:
        """Load a single plugin from the given path."""
        # Check for plugin.yaml manifest first
        manifest_data = None
        manifest_meta = None
        compatible = True
        compatibility_error = ""

        try:
            manifest_data = load_manifest(path)
        except yaml.YAMLError as e:
            logger.error(f"Malformed plugin.yaml in {path}: {e}")
            # Register as incompatible with parse error
            # Use empty dict with has_manifest=True marker for error case
            self._registry[key] = self._make_loaded_plugin(
                key,
                {"name": key, "key": ""},  # Minimal meta to satisfy helper
                compatible=False,
                compatibility_error=f"Malformed plugin.yaml: {e}",
            )
            # Override has_manifest since we want it True for malformed manifests
            self._registry[key].has_manifest = True
            return

        if manifest_data is not None:
            is_valid, errors = validate_manifest(manifest_data)
            if not is_valid:
                logger.warning(f"Invalid manifest for {key}: {errors}")
                self._registry[key] = self._make_loaded_plugin(
                    key,
                    {"name": key, "key": ""},
                    compatible=False,
                    compatibility_error=f"Invalid manifest: {'; '.join(errors)}",
                )
                self._registry[key].has_manifest = True
                return

            manifest_meta = extract_manifest_metadata(manifest_data)

            # Check version compatibility if constraint is specified
            requires_dispatcharr = manifest_meta.get("requires_dispatcharr", "")
            if requires_dispatcharr:
                compatible, compatibility_error = check_compatibility(requires_dispatcharr)
                if not compatible:
                    logger.info(f"Plugin '{key}' is incompatible: {compatibility_error}")
                    # Register plugin with metadata but mark as incompatible
                    self._registry[key] = self._make_loaded_plugin(
                        key,
                        manifest_meta,
                        compatible=False,
                        compatibility_error=compatibility_error,
                    )
                    return

        # Plugin can be a package and/or contain plugin.py. Prefer plugin.py when present.
        has_pkg = os.path.exists(os.path.join(path, "__init__.py"))
        has_pluginpy = os.path.exists(os.path.join(path, "plugin.py"))
        if not (has_pkg or has_pluginpy):
            if manifest_meta:
                # Manifest exists but no Python code - valid for metadata-only plugins
                self._registry[key] = self._make_loaded_plugin(key, manifest_meta)
                logger.warning(f"Plugin '{key}' has manifest but no plugin.py or package")
            else:
                logger.debug(f"Skipping {path}: no plugin.py or package")
            return

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
            else:
                logger.warning(f"No Plugin class found for {key}; skipping")
                return

        instance = plugin_cls()
        fields = getattr(instance, "fields", [])
        actions = getattr(instance, "actions", [])

        # Use manifest metadata if available, otherwise build from Plugin class attributes
        if manifest_meta:
            self._registry[key] = self._make_loaded_plugin(
                key,
                manifest_meta,
                module=module,
                instance=instance,
                fields=fields,
                actions=actions,
                compatible=compatible,
                compatibility_error=compatibility_error,
            )
        else:
            # Legacy plugin without manifest - build metadata from class attributes
            legacy_meta = {
                "name": getattr(instance, "name", key),
                "version": getattr(instance, "version", ""),
                "description": getattr(instance, "description", ""),
            }
            self._registry[key] = self._make_loaded_plugin(
                key,
                None,  # Pass None to indicate no manifest
                module=module,
                instance=instance,
                fields=fields,
                actions=actions,
                compatible=compatible,
                compatibility_error=compatibility_error,
            )
            # Override fields from legacy meta
            self._registry[key].name = legacy_meta["name"]
            self._registry[key].version = legacy_meta["version"]
            self._registry[key].description = legacy_meta["description"]

    def _sync_db_with_registry(self):
        with transaction.atomic():
            for key, lp in self._registry.items():
                obj, _ = PluginConfig.objects.get_or_create(
                    key=key,
                    defaults={
                        "name": lp.name,
                        "version": lp.version,
                        "description": lp.description,
                        "settings": {},
                    },
                )
                # Update meta if changed
                changed = False
                if obj.name != lp.name:
                    obj.name = lp.name
                    changed = True
                if obj.version != lp.version:
                    obj.version = lp.version
                    changed = True
                if obj.description != lp.description:
                    obj.description = lp.description
                    changed = True
                if changed:
                    obj.save()

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return a list of all plugins (discovered + DB-only missing)."""
        plugins: list[dict[str, Any]] = []
        try:
            configs = {c.key: c for c in PluginConfig.objects.all()}
        except Exception as e:
            # Database might not be migrated yet; fall back to registry only
            logger.warning("PluginConfig table unavailable; listing registry only: %s", e)
            configs = {}

        # First, include all discovered plugins
        for key, lp in self._registry.items():
            conf = configs.get(key)
            plugins.append(
                {
                    "key": key,
                    "name": lp.name,
                    "version": lp.version,
                    "description": lp.description,
                    "enabled": conf.enabled if conf else False,
                    "ever_enabled": getattr(conf, "ever_enabled", False) if conf else False,
                    "fields": lp.fields or [],
                    "settings": (conf.settings if conf else {}),
                    "actions": lp.actions or [],
                    "missing": False,
                    # Manifest-related fields
                    "compatible": lp.compatible,
                    "compatibility_error": lp.compatibility_error,
                    "repository": lp.repository,
                    "authors": lp.authors,
                    "icon": lp.icon,
                    "has_manifest": lp.has_manifest,
                    "manifest_key": lp.manifest_key,
                }
            )

        # Then, include any DB-only configs (files missing or failed to load)
        discovered_keys = set(self._registry.keys())
        for key, conf in configs.items():
            if key in discovered_keys:
                continue
            plugins.append(
                {
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
                    # Defaults for missing plugins
                    "compatible": True,
                    "compatibility_error": "",
                    "repository": "",
                    "authors": [],
                    "icon": "",
                    "has_manifest": False,
                    "manifest_key": "",
                }
            )

        return plugins

    def get_plugin(self, key: str) -> LoadedPlugin | None:
        """Get a plugin by its key."""
        return self._registry.get(key)

    def get_plugins_by_manifest_key(self, manifest_key: str, exclude_key: str = "") -> list[str]:
        """Find all plugin keys that have the given manifest_key.

        Args:
            manifest_key: The manifest key to search for
            exclude_key: Optional plugin key to exclude from results

        Returns:
            List of plugin keys (directory names) with matching manifest_key
        """
        if not manifest_key:
            return []
        matches = []
        for key, lp in self._registry.items():
            if key == exclude_key:
                continue
            if lp.manifest_key == manifest_key:
                matches.append(key)
        return matches

    def update_settings(self, key: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Update settings for a plugin."""
        cfg = PluginConfig.objects.get(key=key)
        cfg.settings = settings or {}
        cfg.save(update_fields=["settings", "updated_at"])
        return cfg.settings

    def run_action(
        self, key: str, action_id: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        lp = self.get_plugin(key)
        if not lp or not lp.instance:
            raise ValueError(f"Plugin '{key}' not found")

        if not lp.compatible:
            raise PermissionError(f"Plugin '{key}' is incompatible: {lp.compatibility_error}")

        cfg = PluginConfig.objects.get(key=key)
        if not cfg.enabled:
            raise PermissionError(f"Plugin '{key}' is disabled")
        params = params or {}

        # Provide a context object to the plugin
        context = {
            "settings": cfg.settings or {},
            "logger": logger,
            "actions": {a.get("id"): a for a in (lp.actions or [])},
        }

        # Run either via Celery if plugin provides a delayed method, or inline
        run_method = getattr(lp.instance, "run", None)
        if not callable(run_method):
            raise ValueError(f"Plugin '{key}' has no runnable 'run' method")

        try:
            result = run_method(action_id, params, context)
        except Exception:
            logger.exception(f"Plugin '{key}' action '{action_id}' failed")
            raise

        # Normalize return
        if isinstance(result, dict):
            return result
        return {"status": "ok", "result": result}
