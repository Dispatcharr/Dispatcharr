import importlib
import importlib.util
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import types
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from django.db import close_old_connections, transaction

from .capabilities import (
    compute_effective_capabilities,
    describe_capabilities,
    min_app_version_for_manifest_version,
    parse_manifest_version,
    manifest_version_supported,
)
from .models import PluginConfig
from .version_utils import get_plugin_status
from version import __version__

logger = logging.getLogger(__name__)


def read_plugin_manifest(path: str) -> tuple[Optional[Dict[str, Any]], bool]:
    """Read and parse <path>/plugin.json, if present.

    Module-level (no PluginManager instance needed) so lightweight tooling
    can read manifests without booting the full plugin discovery/leadership
    machinery.
    """
    manifest_path = os.path.join(path, "plugin.json")
    if not os.path.isfile(manifest_path):
        return None, False
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        logger.warning("Invalid plugin.json for plugin at %s", path)
        return None, False
    if not isinstance(data, dict):
        logger.warning("plugin.json must be an object for plugin at %s", path)
        return None, False
    return data, True


@dataclass
class LoadedPlugin:
    key: str
    name: str
    version: str = ""
    description: str = ""
    author: str = ""
    help_url: str = ""
    module: Any = None
    instance: Any = None
    fields: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    manifest_schema_version: int = 0
    trusted: bool = False
    loaded: bool = False
    path: Optional[str] = None
    folder_name: Optional[str] = None
    legacy: bool = False
    # Snapshot of merged settings taken at discovery time, used only to build
    # the lightweight context passed to on_leader_acquired/on_leader_lost --
    # the leadership tick loop must not hit the DB on every tick (see
    # PluginManager._leadership_tick), so it can't call _build_context()'s
    # live PluginConfig lookup like run_action()/stop_plugin() do.
    cached_settings: Dict[str, Any] = field(default_factory=dict)


class PluginManager:
    """Singleton manager that discovers and runs plugins from /data/plugins."""

    _instance: Optional["PluginManager"] = None

    # Leader-election tuning (see apps/plugins/loader.py leadership methods
    # below). 30s TTL / 10s renewal mirrors apps/proxy/live_proxy/server.py's
    # ProxyServer channel-ownership lease, which uses the same tradeoff.
    LEADER_LEASE_TTL = 30
    LEADER_RENEW_INTERVAL = 10

    # Minimum seconds between report_progress writes for a given task, unless
    # it's the completion call or percent jumped a lot, avoiding a plugin's
    # tight progress loop hammering the websocket + several Redis calls.
    PROGRESS_MIN_INTERVAL = 0.3
    PROGRESS_MIN_PERCENT_JUMP = 10

    @classmethod
    def get(cls) -> "PluginManager":
        if not cls._instance:
            cls._instance = PluginManager()
        return cls._instance

    def __init__(self) -> None:
        self.plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR", "/data/plugins")
        self._registry: Dict[str, LoadedPlugin] = {}
        self._package_names: Dict[str, str] = {}
        self._alias_names: Dict[str, str] = {}
        self._reload_token_path = os.path.join(self.plugins_dir, ".reload_token")
        self._last_reload_token = 0.0
        self._discovery_completed = False
        self._lock = threading.RLock()

        # Leader-election state, all process-local. `_leadership_state` maps
        # plugin_key -> "leader"/"follower"; only keys with a value are
        # tracked at all, and only plugins defining on_leader_acquired ever
        # get an entry. worker_id identifies this OS process for the Redis
        # lease, matching ProxyServer's `f"{hostname}:{pid}"` scheme.
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self._leadership_state: Dict[str, str] = {}
        self._leadership_lock = threading.RLock()
        self._leadership_thread_started = False
        # Keys already warned about missing the persistent_service capability,
        # so _leadership_tick logs once per plugin instead of every tick.
        self._leadership_capability_warned: set = set()

        # Ensure plugins directory exists
        os.makedirs(self.plugins_dir, exist_ok=True)
        if self.plugins_dir not in sys.path:
            sys.path.append(self.plugins_dir)

        self._ensure_leadership_loop_started()

    def discover_plugins(
        self,
        *,
        sync_db: bool = True,
        force_reload: bool = False,
        use_cache: bool = False,
        release_connections: bool = True,
    ) -> Dict[str, LoadedPlugin]:
        # Only an explicit caller force_reload broadcasts via the shared token.
        # Reacting to a newer token must reload locally without re-touching it;
        # otherwise every consumer becomes a producer and multi-worker setups
        # never converge.
        caller_force_reload = force_reload
        token = self._get_reload_token()
        if use_cache and not force_reload:
            with self._lock:
                if self._discovery_completed and token <= self._last_reload_token:
                    return self._registry
        if token > self._last_reload_token:
            force_reload = True
        if caller_force_reload:
            self._touch_reload_token()
            token = self._get_reload_token()

        if sync_db:
            logger.info(f"Discovering plugins in {self.plugins_dir}")
        else:
            logger.debug(f"Discovering plugins (no DB sync) in {self.plugins_dir}")

        with self._lock:
            previous_packages = dict(self._package_names)
            previous_aliases = dict(self._alias_names)
            previous_paths = {
                key: lp.path for key, lp in self._registry.items() if lp and lp.path
            }

        try:
            return self._discover_plugins_impl(
                sync_db=sync_db,
                force_reload=force_reload,
                previous_packages=previous_packages,
                previous_aliases=previous_aliases,
                previous_paths=previous_paths,
                token=token,
            )
        finally:
            # Discovery runs outside Django's request/task cycle (boot, worker_ready).
            if release_connections:
                close_old_connections()

    def _discover_plugins_impl(
        self,
        *,
        sync_db: bool,
        force_reload: bool,
        previous_packages: Dict[str, str],
        previous_aliases: Dict[str, str],
        previous_paths: Dict[str, str],
        token: int,
    ) -> Dict[str, LoadedPlugin]:
        try:
            configs: Optional[Dict[str, PluginConfig]] = None
            try:
                configs = {c.key: c for c in PluginConfig.objects.all()}
            except Exception:
                # DB might not be ready; treat all plugins as untrusted
                configs = None

            new_registry: Dict[str, LoadedPlugin] = {}
            new_packages: Dict[str, str] = {}
            new_aliases: Dict[str, str] = {}
            for entry in sorted(os.listdir(self.plugins_dir)):
                path = os.path.join(self.plugins_dir, entry)
                if not os.path.isdir(path):
                    continue

                has_pkg = os.path.exists(os.path.join(path, "__init__.py"))
                has_pluginpy = os.path.exists(os.path.join(path, "plugin.py"))
                if not (has_pkg or has_pluginpy):
                    continue

                plugin_key = entry.replace(" ", "_").lower()

                if force_reload:
                    prev_alias = previous_aliases.get(plugin_key)
                    if prev_alias:
                        self._unload_alias(prev_alias)
                    prev_path = previous_paths.get(plugin_key)
                    if prev_path:
                        self._unload_path_modules(prev_path)

                cfg = configs.get(plugin_key) if configs else None
                lp, package_name, alias_name = self._load_and_merge_plugin_entry(
                    plugin_key,
                    entry,
                    path,
                    cfg=cfg,
                    force_reload=force_reload,
                    previous_package=previous_packages.get(plugin_key),
                )
                new_registry[plugin_key] = lp
                if package_name:
                    new_packages[plugin_key] = package_name
                if alias_name:
                    new_aliases[plugin_key] = alias_name

            if force_reload:
                # Remove stale modules for plugins that no longer exist
                removed_keys = set(previous_packages.keys()) - set(new_packages.keys())
                for key in removed_keys:
                    # Release synchronously rather than waiting on TTL expiry --
                    # a plugin dropped from the registry mid-reload must not
                    # leave a dangling leadership lease held by a module that
                    # no longer exists in this process.
                    self._release_plugin_leadership(key)
                    self._unload_package(previous_packages[key])
                    prev_alias = previous_aliases.get(key)
                    if prev_alias:
                        self._unload_alias(prev_alias)
                    prev_path = previous_paths.get(key)
                    if prev_path:
                        self._unload_path_modules(prev_path)

            with self._lock:
                self._registry = new_registry
                self._package_names = new_packages
                self._alias_names = new_aliases
                if token > self._last_reload_token:
                    self._last_reload_token = token
                self._discovery_completed = True

            logger.info(f"Discovered {len(new_registry)} plugin(s)")
        except FileNotFoundError:
            logger.warning(f"Plugins directory not found: {self.plugins_dir}")

        # Sync DB records (optional)
        if sync_db:
            try:
                self._sync_db_with_registry(new_registry if 'new_registry' in locals() else None)
            except Exception:
                # Defer sync if database is not ready (e.g., first startup before migrate)
                logger.exception("Deferring plugin DB sync; database not ready yet")
        return self._registry

    def iter_actions_for_event(self, event_name: str) -> Iterator[Tuple[str, str]]:
        """Yield (plugin_key, action_id) pairs from the in-memory registry."""
        with self._lock:
            registry = list(self._registry.items())
        for key, lp in registry:
            for action in lp.actions or []:
                if not isinstance(action, dict):
                    continue
                action_id = action.get("id")
                events = action.get("events")
                if (
                    action_id
                    and isinstance(events, (list, tuple))
                    and event_name in events
                ):
                    yield key, action_id

    def _load_and_merge_plugin_entry(
        self,
        plugin_key: str,
        entry: str,
        path: str,
        *,
        cfg: Optional[PluginConfig],
        force_reload: bool,
        previous_package: Optional[str],
    ) -> Tuple[LoadedPlugin, Optional[str], Optional[str]]:
        """Load one plugin directory entry and merge in its plugin.json manifest.

        Shared by the full-directory scan in `_discover_plugins_impl` and by
        `reload_plugin` (single-plugin reload), so the two paths can't drift.
        Returns (loaded_plugin_or_placeholder, package_name, alias_name).
        """
        alias_name = self._resolve_alias_name(entry, path)
        enabled = bool(cfg and cfg.enabled)
        trusted = bool(cfg and (cfg.ever_enabled or cfg.enabled))

        manifest, has_manifest = self._read_manifest(path)
        legacy = not has_manifest
        manifest_name = None
        manifest_version = None
        manifest_description = None
        manifest_author = None
        manifest_help_url = None
        manifest_fields: List[Dict[str, Any]] = []
        manifest_actions: List[Dict[str, Any]] = []
        manifest_capabilities: List[str] = []
        manifest_schema_version = 0
        if has_manifest and isinstance(manifest, dict):
            manifest_name = manifest.get("name") if isinstance(manifest.get("name"), str) else None
            manifest_version = manifest.get("version") if isinstance(manifest.get("version"), str) else None
            manifest_description = manifest.get("description") if isinstance(manifest.get("description"), str) else None
            manifest_author = manifest.get("author") if isinstance(manifest.get("author"), str) else None
            manifest_help_url = manifest.get("help_url") if isinstance(manifest.get("help_url"), str) else None
            manifest_fields = self._normalize_fields(manifest.get("fields", []))
            manifest_actions = self._normalize_actions(manifest.get("actions", []))
            manifest_capabilities = compute_effective_capabilities(manifest)
            manifest_schema_version = parse_manifest_version(manifest)
            if not manifest_version_supported(manifest_schema_version, __version__):
                logger.warning(
                    "Plugin '%s' declares manifest_version=%s, which requires "
                    "Dispatcharr >= %s (running %s). Falling back to best-effort "
                    "parsing of manifest fields this build understands.",
                    plugin_key,
                    manifest_schema_version,
                    min_app_version_for_manifest_version(manifest_schema_version),
                    __version__,
                )

        display_name = manifest_name or entry
        display_version = manifest_version if manifest_version is not None else (cfg.version if cfg else "")
        display_description = manifest_description if manifest_description is not None else (cfg.description if cfg else "")

        def _make_placeholder() -> LoadedPlugin:
            return LoadedPlugin(
                key=plugin_key,
                name=display_name,
                version=display_version,
                description=display_description,
                author=manifest_author or "",
                help_url=manifest_help_url or "",
                fields=manifest_fields if has_manifest else [],
                actions=manifest_actions if has_manifest else [],
                capabilities=manifest_capabilities if has_manifest else [],
                manifest_schema_version=manifest_schema_version,
                trusted=trusted,
                loaded=False,
                path=path,
                folder_name=entry,
                legacy=legacy,
            )

        if not enabled:
            return _make_placeholder(), None, None

        try:
            lp, package_name = self._load_plugin(
                plugin_key,
                path,
                folder_name=entry,
                force_reload=force_reload,
                previous_package=previous_package,
            )
            if not lp:
                return _make_placeholder(), None, None

            if manifest_name and (not lp.name or lp.name == plugin_key):
                lp.name = manifest_name
            if manifest_version is not None and not lp.version:
                lp.version = manifest_version
            if manifest_description is not None and not lp.description:
                lp.description = manifest_description
            if manifest_author is not None and not lp.author:
                lp.author = manifest_author
            if manifest_help_url is not None and not lp.help_url:
                lp.help_url = manifest_help_url
            if manifest_fields and not lp.fields:
                lp.fields = manifest_fields
            if manifest_actions and not lp.actions:
                lp.actions = manifest_actions
            lp.capabilities = manifest_capabilities
            lp.manifest_schema_version = manifest_schema_version
            lp.trusted = trusted
            lp.loaded = True
            lp.path = path
            lp.folder_name = entry
            lp.legacy = legacy
            lp.cached_settings = self._merge_settings_with_defaults(
                cfg.settings if cfg else {}, lp.fields or []
            )
            return lp, package_name, alias_name
        except Exception:
            logger.exception(f"Failed to load plugin '{plugin_key}' from {path}")
            return _make_placeholder(), None, None

    def _load_plugin(
        self,
        key: str,
        path: str,
        *,
        folder_name: str,
        force_reload: bool,
        previous_package: Optional[str],
    ) -> tuple[Optional[LoadedPlugin], Optional[str]]:
        # Plugin can be a package and/or contain plugin.py. Prefer plugin.py when present.
        has_pkg = os.path.exists(os.path.join(path, "__init__.py"))
        has_pluginpy = os.path.exists(os.path.join(path, "plugin.py"))
        if not (has_pkg or has_pluginpy):
            logger.debug(f"Skipping {path}: no plugin.py or package")
            return None, None

        package_name = self._resolve_package_name(key)
        alias_name = self._resolve_alias_name(folder_name, path)

        if force_reload and previous_package:
            self._unload_package(previous_package)

        module = None
        plugin_cls = None
        last_error = None

        # Ensure a package context exists for plugin.py (even without __init__.py)
        if has_pluginpy:
            self._ensure_namespace_package(package_name, path, alias=alias_name)

            module_name = f"{package_name}.plugin"
            plugin_path = os.path.join(path, "plugin.py")
            try:
                logger.debug(f"Importing plugin module {module_name} from {plugin_path}")
                module = self._load_module_from_path(module_name, plugin_path, is_package=False)
                if alias_name:
                    self._register_alias_module(f"{alias_name}.plugin", module, path)
                plugin_cls = getattr(module, "Plugin", None)
                if plugin_cls is None:
                    logger.warning(f"Module {module_name} has no Plugin class")
            except Exception as e:
                last_error = e
                logger.exception(f"Error importing module {module_name}")

        if plugin_cls is None and has_pkg:
            module_name = package_name
            init_path = os.path.join(path, "__init__.py")
            try:
                logger.debug(f"Importing plugin package {module_name} from {init_path}")
                module = self._load_module_from_path(module_name, init_path, is_package=True)
                self._register_alias_module(alias_name, module, path)
                plugin_cls = getattr(module, "Plugin", None)
                if plugin_cls is None:
                    logger.warning(f"Module {module_name} has no Plugin class")
            except Exception as e:
                last_error = e
                logger.exception(f"Error importing module {module_name}")

        if plugin_cls is None:
            if last_error:
                raise last_error
            logger.warning(f"No Plugin class found for {key}; skipping")
            return None, package_name

        instance = plugin_cls()

        name = getattr(instance, "name", key)
        version = getattr(instance, "version", "")
        description = getattr(instance, "description", "")
        author = getattr(instance, "author", "")
        help_url = getattr(instance, "help_url", "")
        fields = getattr(instance, "fields", [])
        actions = getattr(instance, "actions", [])
        fields = self._normalize_fields(fields)
        actions = self._normalize_actions(actions)

        lp = LoadedPlugin(
            key=key,
            name=name,
            version=version,
            description=description,
            author=author or "",
            help_url=help_url or "",
            module=module,
            instance=instance,
            fields=fields,
            actions=actions,
            path=path,
            folder_name=folder_name,
        )
        return lp, package_name

    def _sync_db_with_registry(self, registry: Optional[Dict[str, LoadedPlugin]] = None):
        if registry is None:
            with self._lock:
                registry = dict(self._registry)
        with transaction.atomic():
            for key, lp in registry.items():
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

    def list_plugins(self) -> List[Dict[str, Any]]:
        from .models import PluginConfig, PluginRepo

        plugins: List[Dict[str, Any]] = []
        with self._lock:
            registry_snapshot = dict(self._registry)
        try:
            configs = {c.key: c for c in PluginConfig.objects.select_related("source_repo").all()}
        except Exception as e:
            # Database might not be migrated yet; fall back to registry only
            logger.warning("PluginConfig table unavailable; listing registry only: %s", e)
            configs = {}

        # Build repo latest-version lookup from cached manifests
        repo_latest = {}  # slug -> latest_version
        try:
            for repo in PluginRepo.objects.filter(enabled=True):
                manifest_data = repo.cached_manifest or {}
                manifest = manifest_data.get("manifest", manifest_data)
                for rp in manifest.get("plugins", []):
                    s = rp.get("slug", "")
                    if s:
                        repo_latest[s] = rp.get("latest_version", "")
        except Exception:
            pass

        # First, include all discovered plugins
        for key, lp in registry_snapshot.items():
            conf = configs.get(key)
            conf_slug = conf.slug if conf else ""
            trusted = bool(conf and (conf.ever_enabled or conf.enabled))
            logo_url = self._get_logo_url(key, path=lp.path)
            plugin_status = get_plugin_status(
                lp.version,
                repo_latest.get(conf_slug, ""),
                is_prerelease=bool(conf and conf.installed_version_is_prerelease),
                is_managed=bool(conf_slug and conf and conf.source_repo_id),
            )
            plugins.append(
                {
                    "key": key,
                    "name": lp.name,
                    "version": lp.version,
                    "description": lp.description,
                    "author": getattr(lp, "author", "") or "",
                    "help_url": getattr(lp, "help_url", "") or "",
                    "enabled": conf.enabled if conf else False,
                    "ever_enabled": conf.ever_enabled if conf else False,
                    "acknowledged_capabilities": conf.acknowledged_capabilities if conf else [],
                    "fields": lp.fields or [],
                    "settings": (conf.settings if conf else {}),
                    "actions": lp.actions or [],
                    "capabilities": describe_capabilities(lp.capabilities or []),
                    "manifest_version": lp.manifest_schema_version,
                    "missing": False,
                    "trusted": trusted,
                    "loaded": bool(lp.loaded),
                    "legacy": bool(getattr(lp, "legacy", False)),
                    "logo_url": logo_url,
                    "source_repo": conf.source_repo_id if conf else None,
                    "source_repo_name": conf.source_repo.name if conf and conf.source_repo else None,
                    "is_official_repo": bool(conf and conf.source_repo and conf.source_repo.is_official),
                    "slug": conf_slug,
                    "is_managed": bool(conf and conf.source_repo_id),
                    "installed_version_is_prerelease": bool(
                        conf and conf.installed_version_is_prerelease
                    ),
                    "install_status": plugin_status,
                    "update_available": plugin_status == "update_available",
                    "latest_version": repo_latest.get(conf_slug, ""),
                    "deprecated": conf.deprecated if conf else False,
                }
            )

        # Then, include any DB-only configs (files missing or failed to load)
        discovered_keys = set(registry_snapshot.keys())
        for key, conf in configs.items():
            if key in discovered_keys:
                continue
            plugin_status = get_plugin_status(
                conf.version,
                repo_latest.get(conf.slug or "", ""),
                is_prerelease=bool(conf.installed_version_is_prerelease),
                is_managed=bool(conf.slug and conf.source_repo_id),
            )
            plugins.append(
                {
                    "key": key,
                    "name": conf.name,
                    "version": conf.version,
                    "description": conf.description,
                    "author": "",
                    "help_url": "",
                    "enabled": conf.enabled,
                    "ever_enabled": getattr(conf, "ever_enabled", False),
                    "acknowledged_capabilities": getattr(conf, "acknowledged_capabilities", []) or [],
                    "fields": [],
                    "settings": conf.settings or {},
                    "actions": [],
                    "capabilities": [],
                    "manifest_version": 0,
                    "missing": True,
                    "trusted": bool(conf.ever_enabled or conf.enabled),
                    "loaded": False,
                    "legacy": False,
                    "logo_url": self._get_logo_url(key),
                    "source_repo": conf.source_repo_id,
                    "source_repo_name": conf.source_repo.name if conf.source_repo else None,
                    "is_official_repo": bool(conf.source_repo and conf.source_repo.is_official),
                    "slug": conf.slug,
                    "is_managed": bool(conf.source_repo_id),
                    "installed_version_is_prerelease": bool(
                        conf.installed_version_is_prerelease
                    ),
                    "install_status": plugin_status,
                    "update_available": plugin_status == "update_available",
                    "latest_version": repo_latest.get(conf.slug or "", ""),
                    "deprecated": conf.deprecated,
                }
            )

        return plugins

    def get_plugin(self, key: str) -> Optional[LoadedPlugin]:
        with self._lock:
            return self._registry.get(key)

    def update_settings(self, key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        settings = settings or {}
        lp = self.get_plugin(key)
        fields = (lp.fields if lp else None) or []
        # Drop (not reject) keys with no matching field. A plugin update can
        # legitimately remove a settings field, leaving an orphaned key in an
        # old saved settings blob, and rejecting would break that save.
        known_ids = {f.get("id") for f in fields if f.get("id")}
        if known_ids:
            settings = {k: v for k, v in settings.items() if k in known_ids}
        for field_def in fields:
            if field_def.get("type") == "table" and field_def.get("id") in settings:
                self._validate_table_value(field_def, settings[field_def["id"]])
            elif field_def.get("type") == "multiselect" and field_def.get("id") in settings:
                self._validate_multiselect_value(field_def, settings[field_def["id"]])

        cfg = PluginConfig.objects.get(key=key)
        cfg.settings = settings
        cfg.save(update_fields=["settings", "updated_at"])
        return cfg.settings

    def _validate_multiselect_value(self, field_def: Dict[str, Any], value: Any) -> None:
        """Validate a submitted 'multiselect' field value against declared options."""
        field_id = field_def.get("id")
        if not isinstance(value, list):
            raise ValueError(f"Field '{field_id}' must be a list of values")
        allowed = {o.get("value") for o in field_def.get("options") or []}
        for v in value:
            if str(v) not in allowed:
                raise ValueError(
                    f"Field '{field_id}' contains invalid option '{v}'; must be one of {sorted(allowed)}"
                )

    def run_action(
        self,
        key: str,
        action_id: str,
        params: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            lp = self.get_plugin(key)
            if not lp or not lp.instance:
                # Attempt a lightweight re-discovery in case the registry was rebuilt
                self.discover_plugins(sync_db=False, force_reload=False, use_cache=False)
                lp = self.get_plugin(key)
                if not lp or not lp.instance:
                    raise ValueError(f"Plugin '{key}' not found")

            cfg = PluginConfig.objects.get(key=key)
            if not cfg.enabled:
                raise PermissionError(f"Plugin '{key}' is disabled")
            params = params or {}

            context = self._build_context(lp, cfg, task_id=task_id)

            run_method = getattr(lp.instance, "run", None)
            if not callable(run_method):
                raise ValueError(f"Plugin '{key}' has no runnable 'run' method")

            try:
                result = run_method(action_id, params, context)
            except Exception:
                logger.exception(f"Plugin '{key}' action '{action_id}' failed")
                raise

            if isinstance(result, dict):
                return result
            return {"status": "ok", "result": result}
        finally:
            # Return geventpool checkouts for this greenlet/thread after every action,
            # including Connect event hooks and manual UI runs.
            close_old_connections()

    def stop_plugin(self, key: str, reason: Optional[str] = None) -> bool:
        try:
            # Tear down any persistent service this process leads for this
            # plugin synchronously: disable/reload must not leave a server
            # running headless under a lease the (about to be replaced or
            # disabled) instance no longer knows about, and must not wait on
            # TTL expiry for another process to notice.
            self._release_plugin_leadership(key)

            lp = self.get_plugin(key)
            if not lp or not lp.instance:
                return False
            try:
                cfg = PluginConfig.objects.get(key=key)
            except PluginConfig.DoesNotExist:
                return False
            if not cfg.enabled:
                return False

            context = self._build_context(lp, cfg)
            if reason:
                context["reason"] = reason

            stop_method = getattr(lp.instance, "stop", None)
            if callable(stop_method):
                try:
                    stop_method(context)
                    return True
                except TypeError:
                    try:
                        stop_method()
                        return True
                    except Exception:
                        logger.exception("Plugin '%s' stop() failed", key)
                        return False
                except Exception:
                    logger.exception("Plugin '%s' stop() failed", key)
                    return False

            run_method = getattr(lp.instance, "run", None)
            if callable(run_method):
                actions = {a.get("id") for a in (lp.actions or []) if isinstance(a, dict)}
                if "stop" in actions:
                    try:
                        run_method("stop", {}, context)
                        return True
                    except Exception:
                        logger.exception("Plugin '%s' stop action failed", key)
                        return False
            return False
        finally:
            close_old_connections()

    def stop_all_plugins(self, reason: Optional[str] = None) -> int:
        stopped = 0
        with self._lock:
            registry_snapshot = dict(self._registry)
        for key in registry_snapshot.keys():
            if self.stop_plugin(key, reason=reason):
                stopped += 1
        return stopped

    # ------------------------------------------------------------------
    # Leader election for persistent plugin services.
    #
    # discover_plugins() instantiates every enabled plugin in every process
    # that touches the app, so a plugin starting its own server in __init__
    # collides across processes. on_leader_acquired/on_leader_lost run in
    # exactly one process cluster-wide instead, via a Redis lease mirroring
    # ProxyServer's channel-ownership pattern in apps/proxy/live_proxy/server.py
    # (try_acquire_ownership/extend_ownership/release_ownership). Plugins
    # that don't define on_leader_acquired are never touched by this.
    # ------------------------------------------------------------------

    def _leader_redis_client(self):
        try:
            from core.utils import RedisClient
            return RedisClient.get_client()
        except Exception:
            logger.warning("Leader election: Redis unavailable", exc_info=True)
            return None

    @staticmethod
    def _leader_key(plugin_key: str) -> str:
        return f"plugin:{plugin_key}:leader"

    def try_acquire_leadership(self, plugin_key: str, ttl: Optional[int] = None) -> bool:
        """Try to become the leader for `plugin_key`. No Redis => always leader
        (degrades to today's every-process-runs-it behavior rather than
        hard-failing when Redis is down, matching ProxyServer's precedent)."""
        ttl = ttl or self.LEADER_LEASE_TTL
        client = self._leader_redis_client()
        if client is None:
            return True
        try:
            lock_key = self._leader_key(plugin_key)
            acquired = client.set(lock_key, self.worker_id, nx=True, ex=ttl)
            if acquired:
                return True
            current = client.get(lock_key)
            if current and current == self.worker_id:
                client.expire(lock_key, ttl)
                return True
            return False
        except Exception:
            logger.warning("Leader election: acquire failed for '%s'", plugin_key, exc_info=True)
            return False

    def extend_leadership(self, plugin_key: str, ttl: Optional[int] = None) -> bool:
        """Renew this process's lease. Returns False if leadership was lost
        (another process now holds the key) so the caller can transition."""
        ttl = ttl or self.LEADER_LEASE_TTL
        client = self._leader_redis_client()
        if client is None:
            return True
        try:
            lock_key = self._leader_key(plugin_key)
            current = client.get(lock_key)
            if current is None:
                # Lease expired outright (e.g. this process stalled past the
                # TTL). Try to reacquire rather than assume we still lead --
                # if someone else grabbed it first, this correctly reports
                # loss so on_leader_lost fires.
                return bool(client.set(lock_key, self.worker_id, nx=True, ex=ttl))
            if current == self.worker_id:
                client.expire(lock_key, ttl)
                return True
            return False
        except Exception:
            logger.warning("Leader election: renew failed for '%s'", plugin_key, exc_info=True)
            return False

    def release_leadership(self, plugin_key: str) -> None:
        client = self._leader_redis_client()
        if client is None:
            return
        try:
            lock_key = self._leader_key(plugin_key)
            current = client.get(lock_key)
            if current and current == self.worker_id:
                client.delete(lock_key)
        except Exception:
            logger.warning("Leader election: release failed for '%s'", plugin_key, exc_info=True)

    def _build_leadership_context(self, lp: LoadedPlugin) -> Dict[str, Any]:
        # Deliberately does not call _build_context()'s live PluginConfig
        # lookup, since the tick loop runs in every process and must not touch
        # the DB every LEADER_RENEW_INTERVAL seconds. Uses the settings
        # snapshot taken at discovery time instead (see LoadedPlugin.cached_settings).
        # report_progress is a no-op here (no task_id), since there's no active
        # task backing a persistent service's calls.
        return {
            "settings": lp.cached_settings,
            "logger": logger,
            "actions": {a.get("id"): a for a in (lp.actions or [])},
            "report_progress": self._make_progress_reporter(lp.key, task_id=None),
            "dispatch_task": self._make_task_dispatcher(lp),
        }

    def _transition_to_leader(self, key: str, lp: LoadedPlugin) -> None:
        hook = getattr(lp.instance, "on_leader_acquired", None)
        if not callable(hook):
            return
        with self._leadership_lock:
            self._leadership_state[key] = "leader"
        try:
            hook(self._build_leadership_context(lp))
        except Exception:
            logger.exception(
                "Plugin '%s' on_leader_acquired() failed; releasing leadership so "
                "another process can take over", key,
            )
            with self._leadership_lock:
                self._leadership_state[key] = "follower"
            self.release_leadership(key)

    def _transition_to_follower(self, key: str, lp: Optional[LoadedPlugin]) -> None:
        with self._leadership_lock:
            was_leader = self._leadership_state.get(key) == "leader"
            self._leadership_state[key] = "follower"
        if not was_leader:
            return
        if lp is not None and lp.instance is not None:
            hook = getattr(lp.instance, "on_leader_lost", None)
            if callable(hook):
                try:
                    hook(self._build_leadership_context(lp))
                except Exception:
                    logger.exception("Plugin '%s' on_leader_lost() failed", key)

    def _release_plugin_leadership(self, key: str) -> None:
        """Synchronous teardown for disable/reload/removal; do not wait for
        TTL expiry. Safe to call for a plugin that was never a leader."""
        lp = self.get_plugin(key)
        try:
            self._transition_to_follower(key, lp)
        finally:
            self.release_leadership(key)

    def release_all_leaderships(self) -> None:
        """Best-effort graceful teardown on process shutdown (see
        dispatcharr/celery.py worker_shutdown hook). Not the only safety net;
        lease TTL expiry covers hard kills where this never runs."""
        with self._leadership_lock:
            keys = [k for k, v in self._leadership_state.items() if v == "leader"]
        for key in keys:
            try:
                self._release_plugin_leadership(key)
            except Exception:
                logger.exception("Failed to release leadership for '%s' on shutdown", key)

    def _leadership_tick(self) -> None:
        with self._lock:
            pre_refresh_registry = dict(self._registry)

        # Cheap mtime check; only rescans if disable/reload bumped the token,
        # so the leader (often a different process than the one serving the
        # disable request) notices without waiting on lease TTL expiry.
        if self._get_reload_token() > self._last_reload_token:
            self.discover_plugins(sync_db=False, force_reload=False, use_cache=True)

        with self._lock:
            registry_snapshot = list(self._registry.items())

        live_keys = {key for key, lp in registry_snapshot if lp.instance}
        with self._leadership_lock:
            leader_keys = [k for k, v in self._leadership_state.items() if v == "leader"]
        for key in leader_keys:
            if key in live_keys:
                continue
            # Use the pre-refresh lp: a disabled/removed plugin's current
            # entry is an instance-less placeholder.
            try:
                self._transition_to_follower(key, pre_refresh_registry.get(key))
                self.release_leadership(key)
            except Exception:
                logger.exception("Leader election teardown failed for plugin '%s'", key)

        for key, lp in registry_snapshot:
            if not lp.instance:
                continue
            hook = getattr(lp.instance, "on_leader_acquired", None)
            if not callable(hook):
                continue
            if "persistent_service" not in (lp.capabilities or []):
                if key not in self._leadership_capability_warned:
                    self._leadership_capability_warned.add(key)
                    logger.warning(
                        "Plugin '%s' defines on_leader_acquired() without declaring the "
                        "'persistent_service' capability in plugin.json; skipping leader "
                        'election for it. Add "capabilities": ["persistent_service"] to '
                        "the manifest to allow this.",
                        key,
                    )
                continue
            try:
                with self._leadership_lock:
                    currently_leader = self._leadership_state.get(key) == "leader"
                if currently_leader:
                    if not self.extend_leadership(key):
                        self._transition_to_follower(key, lp)
                else:
                    if self.try_acquire_leadership(key):
                        self._transition_to_leader(key, lp)
            except Exception:
                # One plugin's bug must not stop leadership handling for
                # every other plugin on this tick.
                logger.exception("Leader election tick failed for plugin '%s'", key)

    def _leadership_loop(self) -> None:
        # Genuine OS thread regardless of gevent monkey-patching (see
        # _ensure_leadership_loop_started); time.sleep() here blocks only
        # this dedicated thread, never the gevent hub or any request/task.
        while True:
            try:
                self._leadership_tick()
            except Exception:
                logger.exception("Leader election tick loop iteration failed")
            time.sleep(self.LEADER_RENEW_INTERVAL)

    def _ensure_leadership_loop_started(self) -> None:
        with self._leadership_lock:
            if self._leadership_thread_started:
                return
            self._leadership_thread_started = True

        try:
            from django.conf import settings
            if getattr(settings, "TESTING", False):
                return
        except Exception:
            pass

        # Always use a genuine OS thread, never a greenlet: if gevent has
        # monkey-patched `threading`, grab the original pre-patch Thread
        # class via gevent.monkey.get_original(). This sidesteps needing to
        # detect whether a gevent hub is actively driving this process (a
        # known-hard problem here, see core/utils.py's
        # _should_use_sync_websocket_send() docstring for the same class of
        # issue with gevent.spawn in Celery prefork workers): a real OS
        # thread runs and sleeps on its own regardless of whether anything
        # else ever yields to a gevent hub in this process.
        thread_cls = threading.Thread
        try:
            import gevent.monkey
            if gevent.monkey.is_module_patched("threading"):
                thread_cls = gevent.monkey.get_original("threading", "Thread")
        except Exception:
            pass

        thread = thread_cls(target=self._leadership_loop, daemon=True)
        thread.name = "plugin-leader-election"
        thread.start()

    def reload_plugin(self, key: str) -> bool:
        """Reload a single plugin's Python code in isolation.

        Unlike `discover_plugins(force_reload=True)`, this does not stop or
        re-import any other plugin, and deliberately does not touch the
        shared `.reload_token` file used to broadcast full reloads to other
        worker processes (a single-plugin reload is process-local only).
        Concurrent reloads of the same key are rejected (returns False)
        rather than racing with an in-progress unload/re-import.
        """
        with self._lock:
            if not hasattr(self, "_reloading_keys"):
                self._reloading_keys = set()
            if key in self._reloading_keys:
                return False
            self._reloading_keys.add(key)

        try:
            self.stop_plugin(key, reason="reload")

            path = None
            entry_name = None
            for entry in sorted(os.listdir(self.plugins_dir)):
                candidate = os.path.join(self.plugins_dir, entry)
                if not os.path.isdir(candidate):
                    continue
                if entry.replace(" ", "_").lower() == key:
                    path = candidate
                    entry_name = entry
                    break
            if not path:
                logger.warning("reload_plugin: no directory found for '%s'", key)
                return False

            with self._lock:
                previous_package = self._package_names.get(key)
                previous_alias = self._alias_names.get(key)
                previous_lp = self._registry.get(key)
            previous_path = previous_lp.path if previous_lp else None

            if previous_alias:
                self._unload_alias(previous_alias)
            if previous_path:
                self._unload_path_modules(previous_path)

            try:
                configs = {c.key: c for c in PluginConfig.objects.all()}
            except Exception:
                configs = {}
            cfg = configs.get(key)

            lp, package_name, alias_name = self._load_and_merge_plugin_entry(
                key,
                entry_name,
                path,
                cfg=cfg,
                force_reload=True,
                previous_package=previous_package,
            )

            with self._lock:
                self._registry[key] = lp
                if package_name:
                    self._package_names[key] = package_name
                elif key in self._package_names:
                    del self._package_names[key]
                if alias_name:
                    self._alias_names[key] = alias_name
                elif key in self._alias_names:
                    del self._alias_names[key]

            try:
                self._sync_db_with_registry(dict(self._registry))
            except Exception:
                logger.exception("Deferring plugin DB sync after single-plugin reload")

            logger.info("Reloaded plugin '%s'", key)
            return True
        finally:
            close_old_connections()
            with self._lock:
                self._reloading_keys.discard(key)

    def _resolve_package_name(self, key: str) -> str:
        safe_key = self._safe_module_name(key)
        return f"_dispatcharr_plugin_{safe_key}"

    def _resolve_alias_name(self, folder_name: str, path: str) -> Optional[str]:
        if not self._is_valid_identifier(folder_name):
            return None
        if self._is_reserved_module_name(folder_name, path):
            return None
        return folder_name

    def _is_valid_identifier(self, name: str) -> bool:
        return re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) is not None

    def _safe_module_name(self, value: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z_]", "_", value)
        if not safe or safe[0].isdigit():
            safe = f"p_{safe}"
        return safe

    def _normalize_fields(self, fields: Any) -> List[Dict[str, Any]]:
        try:
            from .serializers import PluginFieldSerializer
        except Exception:
            return fields if isinstance(fields, list) else []
        if not isinstance(fields, list):
            return []
        serializer = PluginFieldSerializer(data=fields, many=True)
        if serializer.is_valid():
            return serializer.validated_data
        normalized: List[Dict[str, Any]] = []
        for item in fields:
            item_ser = PluginFieldSerializer(data=item)
            if item_ser.is_valid():
                normalized.append(item_ser.validated_data)
            else:
                logger.warning("Invalid plugin field entry ignored: %s", item_ser.errors)
        return normalized

    def _normalize_actions(self, actions: Any) -> List[Dict[str, Any]]:
        try:
            from .serializers import PluginActionSerializer
        except Exception:
            return actions if isinstance(actions, list) else []
        if not isinstance(actions, list):
            return []
        serializer = PluginActionSerializer(data=actions, many=True)
        if serializer.is_valid():
            return serializer.validated_data
        normalized: List[Dict[str, Any]] = []
        for item in actions:
            item_ser = PluginActionSerializer(data=item)
            if item_ser.is_valid():
                normalized.append(item_ser.validated_data)
            else:
                logger.warning("Invalid plugin action entry ignored: %s", item_ser.errors)
        return normalized

    def _merge_settings_with_defaults(self, settings: Dict[str, Any], fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        merged = dict(settings or {})
        for field_def in fields or []:
            field_id = field_def.get("id")
            if not field_id:
                continue
            if field_id not in merged and "default" in field_def:
                merged[field_id] = field_def.get("default")
        return merged

    def _validate_table_value(self, field_def: Dict[str, Any], value: Any) -> None:
        """Validate a submitted 'table' field value against its declared columns.

        Raises ValueError with a message naming the offending field/row/column.
        """
        field_id = field_def.get("id")
        if not isinstance(value, list):
            raise ValueError(f"Field '{field_id}' must be a list of rows")

        columns = {c.get("id"): c for c in field_def.get("columns") or []}
        type_checks = {
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
        }

        for i, row in enumerate(value):
            if not isinstance(row, dict):
                raise ValueError(f"Field '{field_id}' row {i} must be an object")
            for col_id, col_value in row.items():
                col = columns.get(col_id)
                if not col:
                    continue  # unknown/orphaned column key, ignored but not stripped
                col_type = col.get("type")
                if col_type == "select":
                    allowed = {o.get("value") for o in col.get("options") or []}
                    if col_value is not None and str(col_value) not in allowed:
                        raise ValueError(
                            f"Field '{field_id}' row {i} column '{col_id}' must be one of {sorted(allowed)}"
                        )
                else:
                    check = type_checks.get(col_type)
                    if check and not check(col_value):
                        raise ValueError(
                            f"Field '{field_id}' row {i} column '{col_id}' expects type '{col_type}'"
                        )

    def _build_context(
        self, lp: LoadedPlugin, cfg: PluginConfig, task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        settings = self._merge_settings_with_defaults(cfg.settings or {}, lp.fields or [])
        return {
            "settings": settings,
            "logger": logger,
            "actions": {a.get("id"): a for a in (lp.actions or [])},
            "report_progress": self._make_progress_reporter(lp.key, task_id),
            "dispatch_task": self._make_task_dispatcher(lp),
        }

    def _make_progress_reporter(self, plugin_key: str, task_id: Optional[str]):
        """No-op when task_id is None, so plugins can call it unconditionally.

        Throttled: at most one send per PROGRESS_MIN_INTERVAL seconds, unless
        this is the completion call (percent >= 100) or percent moved by at
        least PROGRESS_MIN_PERCENT_JUMP since the last sent update; either
        of those always goes through.
        """
        state = {"last_sent_at": 0.0, "last_percent": None}

        def report_progress(percent, message=None):
            if task_id is None:
                return
            now = time.time()
            is_complete = percent is not None and percent >= 100
            jumped = (
                state["last_percent"] is None
                or percent is None
                or abs(percent - state["last_percent"]) >= self.PROGRESS_MIN_PERCENT_JUMP
            )
            if not is_complete and not jumped and (now - state["last_sent_at"]) < self.PROGRESS_MIN_INTERVAL:
                return
            state["last_sent_at"] = now
            state["last_percent"] = percent

            from core.utils import send_websocket_update
            from .task_history import record_task_progress
            send_websocket_update("updates", "update", {
                "type": "plugin_task_progress",
                "plugin": plugin_key,
                "task_id": task_id,
                "percent": percent,
                "message": message,
                "updatedAt": int(time.time() * 1000),
            })
            record_task_progress(plugin_key, task_id, percent, message)
        return report_progress

    def _make_task_dispatcher(self, lp: LoadedPlugin):
        """Lets an action hand work off to the plugins queue at runtime,
        independent of the manifest 'async' flag.

        Enforced (unlike the rest of the capabilities model, which is
        advisory-only for backward compatibility, see apps/plugins/capabilities.py):
        a plugin must declare the background_tasks capability to use this.
        Manifest actions with "async": true don't need a separate check here,
        since compute_effective_capabilities() already infers background_tasks
        from those, so lp.capabilities is guaranteed to include it whenever an
        async action reaches this dispatcher via run_action(). This only
        actually blocks a plugin that calls dispatch_task() at runtime without
        declaring background_tasks (directly, or via any async action) at all.
        """
        def dispatch_task(action_id, params=None):
            if "background_tasks" not in (lp.capabilities or []):
                raise PermissionError(
                    f"Plugin '{lp.key}' called dispatch_task() without declaring the "
                    "'background_tasks' capability in plugin.json. Add "
                    '"capabilities": ["background_tasks"] to the manifest to allow this.'
                )
            action_def = next(
                (a for a in (lp.actions or []) if isinstance(a, dict) and a.get("id") == action_id), None
            )
            if action_def is None:
                raise ValueError(
                    f"Plugin '{lp.key}' called dispatch_task() with unknown action_id "
                    f"'{action_id}'. It must match an \"id\" declared in plugin.json's "
                    "\"actions\" list."
                )
            from .tasks import run_plugin_action_task
            from .task_history import record_task_started
            async_result = run_plugin_action_task.apply_async(
                args=[lp.key, action_id, params or {}], queue="plugins",
            )
            record_task_started(lp.key, async_result.id, action_id, action_def.get("label", action_id))
            return async_result.id
        return dispatch_task

    def _read_manifest(self, path: str) -> tuple[Optional[Dict[str, Any]], bool]:
        return read_plugin_manifest(path)

    def _get_logo_url(self, key: str, *, path: Optional[str] = None) -> Optional[str]:
        logo_path = os.path.join(self.plugins_dir, key, "logo.png")
        if path:
            logo_path = os.path.join(path, "logo.png")
        try:
            if os.path.isfile(logo_path):
                return f"/api/plugins/plugins/{key}/logo/"
        except Exception:
            return None
        return None

    def _ensure_namespace_package(self, package_name: str, path: str, *, alias: Optional[str] = None) -> None:
        existing = sys.modules.get(package_name)
        if existing and getattr(existing, "__path__", None):
            return
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [path]
        pkg.__package__ = package_name
        sys.modules[package_name] = pkg
        self._register_alias_module(alias, pkg, path)

    def _register_alias_module(
        self,
        alias_name: Optional[str],
        module: Any,
        path: str,
        *,
        force: bool = False,
    ) -> None:
        if not alias_name:
            return
        if self._is_reserved_module_name(alias_name, path):
            return
        if alias_name in sys.modules:
            if not force:
                return
            self._unload_alias(alias_name)
        sys.modules[alias_name] = module

    def _is_reserved_module_name(self, name: str, path: str) -> bool:
        if name in sys.builtin_module_names:
            return True
        if hasattr(sys, "stdlib_module_names") and name in sys.stdlib_module_names:
            return True
        existing = sys.modules.get(name)
        if existing:
            origin = getattr(existing, "__file__", None)
            if origin is None:
                return True
            try:
                if not os.path.abspath(origin).startswith(os.path.abspath(path)):
                    return True
            except Exception:
                return True
        try:
            spec = importlib.util.find_spec(name)
        except Exception:
            spec = None
        if spec:
            if spec.origin is None:
                return True
            try:
                if not os.path.abspath(spec.origin).startswith(os.path.abspath(path)):
                    return True
            except Exception:
                return True
        return False

    def _load_module_from_path(self, module_name: str, path: str, *, is_package: bool) -> Any:
        importlib.invalidate_caches()
        spec = importlib.util.spec_from_file_location(
            module_name,
            path,
            submodule_search_locations=[os.path.dirname(path)] if is_package else None,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for {module_name} from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _get_reload_token(self) -> float:
        try:
            return os.path.getmtime(self._reload_token_path)
        except FileNotFoundError:
            return 0.0
        except Exception:
            return 0.0

    def _touch_reload_token(self) -> None:
        try:
            os.makedirs(self.plugins_dir, exist_ok=True)
            with open(self._reload_token_path, "a", encoding="utf-8"):
                pass
            os.utime(self._reload_token_path, None)
        except Exception:
            logger.debug("Failed to update plugin reload token", exc_info=True)

    def _unload_package(self, package_name: str) -> None:
        if not package_name:
            return
        for name in list(sys.modules.keys()):
            if name == package_name or name.startswith(f"{package_name}."):
                sys.modules.pop(name, None)

    def _unload_alias(self, alias_name: str) -> None:
        if not alias_name:
            return
        for name in list(sys.modules.keys()):
            if name == alias_name or name.startswith(f"{alias_name}."):
                sys.modules.pop(name, None)

    def _unload_path_modules(self, path: str) -> None:
        if not path:
            return
        root = os.path.abspath(path)
        for name, module in list(sys.modules.items()):
            if not module:
                continue
            mod_path = getattr(module, "__file__", None)
            if mod_path:
                try:
                    abs_path = os.path.abspath(mod_path)
                    if abs_path == root or abs_path.startswith(f"{root}{os.sep}"):
                        sys.modules.pop(name, None)
                        continue
                except Exception:
                    pass
            mod_paths = getattr(module, "__path__", None)
            if mod_paths:
                try:
                    for pkg_path in mod_paths:
                        abs_pkg = os.path.abspath(pkg_path)
                        if abs_pkg == root or abs_pkg.startswith(f"{root}{os.sep}"):
                            sys.modules.pop(name, None)
                            break
                except Exception:
                    continue
