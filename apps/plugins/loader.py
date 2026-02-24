import importlib
import importlib.util
import json
import logging
import os
import re
import sys
import threading
import types
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from django.db import transaction

from .models import PluginConfig

logger = logging.getLogger(__name__)


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
    trusted: bool = False
    loaded: bool = False
    path: Optional[str] = None
    folder_name: Optional[str] = None
    legacy: bool = False


class PluginManager:
    """Singleton manager that discovers and runs plugins from /data/plugins."""

    _instance: Optional["PluginManager"] = None

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
        self._lock = threading.RLock()

        # Ensure plugins directory exists
        os.makedirs(self.plugins_dir, exist_ok=True)
        if self.plugins_dir not in sys.path:
            sys.path.append(self.plugins_dir)

    def discover_plugins(
        self,
        *,
        sync_db: bool = True,
        force_reload: bool = False,
        use_cache: bool = False,
    ) -> Dict[str, LoadedPlugin]:
        token = self._get_reload_token()
        if use_cache and not force_reload:
            with self._lock:
                if self._registry and token <= self._last_reload_token:
                    return self._registry
        if token > self._last_reload_token:
            force_reload = True
        if force_reload:
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
                alias_name = self._resolve_alias_name(entry, path)

                if force_reload:
                    prev_alias = previous_aliases.get(plugin_key)
                    if prev_alias:
                        self._unload_alias(prev_alias)
                    prev_path = previous_paths.get(plugin_key)
                    if prev_path:
                        self._unload_path_modules(prev_path)

                cfg = configs.get(plugin_key) if configs else None
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
                if has_manifest and isinstance(manifest, dict):
                    manifest_name = manifest.get("name") if isinstance(manifest.get("name"), str) else None
                    manifest_version = manifest.get("version") if isinstance(manifest.get("version"), str) else None
                    manifest_description = manifest.get("description") if isinstance(manifest.get("description"), str) else None
                    manifest_author = manifest.get("author") if isinstance(manifest.get("author"), str) else None
                    manifest_help_url = manifest.get("help_url") if isinstance(manifest.get("help_url"), str) else None
                    manifest_fields = self._normalize_fields(manifest.get("fields", []))
                    manifest_actions = self._normalize_actions(manifest.get("actions", []))

                display_name = manifest_name or entry
                display_version = (
                    manifest_version if manifest_version is not None else (cfg.version if cfg else "")
                )
                display_description = (
                    manifest_description if manifest_description is not None else (cfg.description if cfg else "")
                )

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
                        trusted=trusted,
                        loaded=False,
                        path=path,
                        folder_name=entry,
                        legacy=legacy,
                    )

                if not enabled:
                    new_registry[plugin_key] = _make_placeholder()
                    continue

                try:
                    lp, package_name = self._load_plugin(
                        plugin_key,
                        path,
                        folder_name=entry,
                        force_reload=force_reload,
                        previous_package=previous_packages.get(plugin_key),
                    )
                    if lp:
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
                        lp.trusted = trusted
                        lp.loaded = True
                        lp.path = path
                        lp.folder_name = entry
                        lp.legacy = legacy
                        new_registry[plugin_key] = lp
                        if package_name:
                            new_packages[plugin_key] = package_name
                        if alias_name:
                            new_aliases[plugin_key] = alias_name
                    else:
                        new_registry[plugin_key] = _make_placeholder()
                except Exception:
                    logger.exception(f"Failed to load plugin '{plugin_key}' from {path}")
                    new_registry[plugin_key] = _make_placeholder()

            if force_reload:
                # Remove stale modules for plugins that no longer exist
                removed_keys = set(previous_packages.keys()) - set(new_packages.keys())
                for key in removed_keys:
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
        from .models import PluginConfig

        plugins: List[Dict[str, Any]] = []
        with self._lock:
            registry_snapshot = dict(self._registry)
        try:
            configs = {c.key: c for c in PluginConfig.objects.all()}
        except Exception as e:
            # Database might not be migrated yet; fall back to registry only
            logger.warning("PluginConfig table unavailable; listing registry only: %s", e)
            configs = {}

        # First, include all discovered plugins
        for key, lp in registry_snapshot.items():
            conf = configs.get(key)
            trusted = bool(conf and (conf.ever_enabled or conf.enabled))
            logo_url = self._get_logo_url(key, path=lp.path)
            plugins.append(
                {
                    "key": key,
                    "name": lp.name,
                    "version": lp.version,
                    "description": lp.description,
                    "author": getattr(lp, "author", "") or "",
                    "help_url": getattr(lp, "help_url", "") or "",
                    "enabled": conf.enabled if conf else False,
                    "ever_enabled": getattr(conf, "ever_enabled", False) if conf else False,
                    "fields": lp.fields or [],
                    "settings": (conf.settings if conf else {}),
                    "actions": lp.actions or [],
                    "missing": False,
                    "trusted": trusted,
                    "loaded": bool(lp.loaded),
                    "legacy": bool(getattr(lp, "legacy", False)),
                    "logo_url": logo_url,
                }
            )

        # Then, include any DB-only configs (files missing or failed to load)
        discovered_keys = set(registry_snapshot.keys())
        for key, conf in configs.items():
            if key in discovered_keys:
                continue
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
                    "fields": [],
                    "settings": conf.settings or {},
                    "actions": [],
                    "missing": True,
                    "trusted": bool(conf.ever_enabled or conf.enabled),
                    "loaded": False,
                    "legacy": False,
                    "logo_url": self._get_logo_url(key),
                }
            )

        return plugins

    def get_plugin(self, key: str) -> Optional[LoadedPlugin]:
        with self._lock:
            return self._registry.get(key)

    def update_settings(self, key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        cfg = PluginConfig.objects.get(key=key)
        cfg.settings = settings or {}
        cfg.save(update_fields=["settings", "updated_at"])
        return cfg.settings

    def run_action(self, key: str, action_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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

        context = self._build_context(lp, cfg)

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

    def stop_plugin(self, key: str, reason: Optional[str] = None) -> bool:
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

    def stop_all_plugins(self, reason: Optional[str] = None) -> int:
        stopped = 0
        with self._lock:
            registry_snapshot = dict(self._registry)
        for key in registry_snapshot.keys():
            if self.stop_plugin(key, reason=reason):
                stopped += 1
        return stopped

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

    def _build_context(self, lp: LoadedPlugin, cfg: PluginConfig) -> Dict[str, Any]:
        settings = self._merge_settings_with_defaults(cfg.settings or {}, lp.fields or [])
        return {
            "settings": settings,
            "logger": logger,
            "actions": {a.get("id"): a for a in (lp.actions or [])},
        }

    def _read_manifest(self, path: str) -> tuple[Optional[Dict[str, Any]], bool]:
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
