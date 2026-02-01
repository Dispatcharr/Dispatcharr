import logging
import os
import re
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_method,
)

from .loader import PluginManager
from .models import PluginConfig

logger = logging.getLogger(__name__)

# Plugin key validation pattern (lowercase alphanumeric, underscores, hyphens)
PLUGIN_KEY_PATTERN = re.compile(r'^[a-z0-9_-]+$')


def validate_plugin_key(key: str) -> bool:
    """Validate plugin key format."""
    return bool(key and PLUGIN_KEY_PATTERN.match(key) and len(key) <= 128)


# Error codes for machine-parseable responses
class PluginErrorCode:
    PLUGIN_NOT_FOUND = "PLUGIN_NOT_FOUND"
    PLUGIN_DISABLED = "PLUGIN_DISABLED"
    PLUGIN_INCOMPATIBLE = "PLUGIN_INCOMPATIBLE"
    MANIFEST_KEY_CONFLICT = "MANIFEST_KEY_CONFLICT"
    INVALID_MANIFEST = "INVALID_MANIFEST"
    INVALID_PLUGIN_KEY = "INVALID_PLUGIN_KEY"
    UNSAFE_ARCHIVE = "UNSAFE_ARCHIVE"
    INVALID_PLUGIN = "INVALID_PLUGIN"
    MISSING_PARAMETER = "MISSING_PARAMETER"


class PluginPermissionMixin:
    """Mixin providing standard plugin permission handling."""

    def get_permissions(self):
        method_perms = permission_classes_by_method.get(self.request.method)
        if method_perms:
            return [perm() for perm in method_perms]
        return [Authenticated()]


class PluginsListAPIView(PluginPermissionMixin, APIView):
    def get(self, request):
        pm = PluginManager.get()
        # Use cached discovery (force=False) for normal requests
        pm.discover_plugins(force=False)
        return Response({"plugins": pm.list_plugins()})


class PluginReloadAPIView(PluginPermissionMixin, APIView):
    def post(self, request):
        pm = PluginManager.get()
        # Force rediscovery on explicit reload
        pm.discover_plugins(force=True)
        return Response({
            "success": True,
            "count": len(pm._registry),
            "plugins": pm.list_plugins()
        })


class PluginImportAPIView(PluginPermissionMixin, APIView):
    def post(self, request):
        file: UploadedFile = request.FILES.get("file")
        if not file:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.MISSING_PARAMETER,
                "error": "Missing 'file' upload"
            }, status=status.HTTP_400_BAD_REQUEST)

        pm = PluginManager.get()
        plugins_dir = pm.plugins_dir

        try:
            zf = zipfile.ZipFile(file)
        except zipfile.BadZipFile:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.UNSAFE_ARCHIVE,
                "error": "Invalid zip file"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Extract to a temporary directory first to avoid server reload thrash
        tmp_root = tempfile.mkdtemp(prefix="plugin_import_")
        try:
            file_members = [m for m in zf.infolist() if not m.is_dir()]
            if not file_members:
                shutil.rmtree(tmp_root, ignore_errors=True)
                return Response({
                    "success": False,
                    "error_code": PluginErrorCode.UNSAFE_ARCHIVE,
                    "error": "Archive is empty"
                }, status=status.HTTP_400_BAD_REQUEST)

            for member in file_members:
                name = member.filename
                if not name or name.endswith("/"):
                    continue

                # Check for symlinks (security: prevent symlink traversal)
                # ZipInfo external_attr: high 16 bits are Unix mode, symlinks have 0o120000
                unix_mode = (member.external_attr >> 16) & 0o170000
                if unix_mode == 0o120000:  # S_IFLNK
                    shutil.rmtree(tmp_root, ignore_errors=True)
                    return Response({
                        "success": False,
                        "error_code": PluginErrorCode.UNSAFE_ARCHIVE,
                        "error": "Symlinks not allowed in plugin archives"
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Normalize and prevent path traversal
                norm = os.path.normpath(name)
                if norm.startswith("..") or os.path.isabs(norm):
                    shutil.rmtree(tmp_root, ignore_errors=True)
                    return Response({
                        "success": False,
                        "error_code": PluginErrorCode.UNSAFE_ARCHIVE,
                        "error": "Unsafe path in archive"
                    }, status=status.HTTP_400_BAD_REQUEST)
                dest_path = os.path.join(tmp_root, norm)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with zf.open(member, 'r') as src, open(dest_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)

            # Find candidate directory containing plugin.py or __init__.py
            candidates = []
            for dirpath, dirnames, filenames in os.walk(tmp_root):
                has_pluginpy = "plugin.py" in filenames
                has_init = "__init__.py" in filenames
                if has_pluginpy or has_init:
                    depth = len(os.path.relpath(dirpath, tmp_root).split(os.sep))
                    candidates.append((0 if has_pluginpy else 1, depth, dirpath))
            if not candidates:
                shutil.rmtree(tmp_root, ignore_errors=True)
                return Response({"success": False, "error": "Invalid plugin: missing plugin.py or package __init__.py"}, status=status.HTTP_400_BAD_REQUEST)

            candidates.sort()
            chosen = candidates[0][2]
            # Determine plugin key: prefer chosen folder name; if chosen is tmp_root, use zip base name
            base_name = os.path.splitext(getattr(file, "name", "plugin"))[0]
            plugin_key = os.path.basename(chosen.rstrip(os.sep))
            if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
                plugin_key = base_name
            plugin_key = plugin_key.replace(" ", "_").lower()

            # Validate plugin key format
            if not validate_plugin_key(plugin_key):
                shutil.rmtree(tmp_root, ignore_errors=True)
                return Response({
                    "success": False,
                    "error_code": PluginErrorCode.INVALID_PLUGIN_KEY,
                    "error": f"Invalid plugin key format: '{plugin_key}'"
                }, status=status.HTTP_400_BAD_REQUEST)

            final_dir = os.path.join(plugins_dir, plugin_key)
            if os.path.exists(final_dir):
                # If final dir exists but contains a valid plugin, refuse; otherwise clear it
                if os.path.exists(os.path.join(final_dir, "plugin.py")) or os.path.exists(os.path.join(final_dir, "__init__.py")):
                    shutil.rmtree(tmp_root, ignore_errors=True)
                    return Response({
                        "success": False,
                        "error_code": PluginErrorCode.INVALID_PLUGIN,
                        "error": f"Plugin '{plugin_key}' already exists"
                    }, status=status.HTTP_400_BAD_REQUEST)
                try:
                    shutil.rmtree(final_dir)
                except Exception:
                    logger.debug(f"Failed to remove existing dir {final_dir}", exc_info=True)

            # Move chosen directory into final location
            if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
                # Move all contents into final_dir
                os.makedirs(final_dir, exist_ok=True)
                for item in os.listdir(tmp_root):
                    shutil.move(os.path.join(tmp_root, item), os.path.join(final_dir, item))
            else:
                shutil.move(chosen, final_dir)
            # Cleanup temp
            shutil.rmtree(tmp_root, ignore_errors=True)
            target_dir = final_dir
        finally:
            try:
                shutil.rmtree(tmp_root, ignore_errors=True)
            except Exception:
                logger.debug(f"Failed to cleanup temp dir {tmp_root}", exc_info=True)

        # Reload discovery and validate plugin entry
        pm.discover_plugins(force=True)
        plugin = pm._registry.get(plugin_key)
        if not plugin:
            # Cleanup the copied folder to avoid leaving invalid plugin behind
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
            except Exception:
                logger.debug(f"Failed to cleanup invalid plugin dir {target_dir}", exc_info=True)
            return Response({
                "success": False,
                "error_code": PluginErrorCode.INVALID_PLUGIN,
                "error": "Invalid plugin: missing Plugin class in plugin.py or __init__.py"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Extra validation: ensure Plugin.run exists
        instance = getattr(plugin, "instance", None)
        run_method = getattr(instance, "run", None)
        if not callable(run_method):
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
            except Exception:
                logger.debug(f"Failed to cleanup invalid plugin dir {target_dir}", exc_info=True)
            return Response({
                "success": False,
                "error_code": PluginErrorCode.INVALID_PLUGIN,
                "error": "Invalid plugin: Plugin class must define a callable run(action, params, context)"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Find DB config to return enabled/ever_enabled
        try:
            cfg = PluginConfig.objects.get(key=plugin_key)
            enabled = cfg.enabled
            ever_enabled = getattr(cfg, "ever_enabled", False)
        except PluginConfig.DoesNotExist:
            enabled = False
            ever_enabled = False

        return Response({
            "success": True,
            "plugin": {
                "key": plugin.key,
                "name": plugin.name,
                "version": plugin.version,
                "description": plugin.description,
                "enabled": enabled,
                "ever_enabled": ever_enabled,
                "fields": plugin.fields or [],
                "actions": plugin.actions or [],
                "compatible": plugin.compatible,
                "compatibility_error": plugin.compatibility_error,
                "repository": plugin.repository,
                "authors": plugin.authors,
                "icon": plugin.icon,
                "has_manifest": plugin.has_manifest,
                "manifest_key": plugin.manifest_key,
            }
        })


class PluginSettingsAPIView(PluginPermissionMixin, APIView):
    def post(self, request, key):
        # Validate key format
        if not validate_plugin_key(key):
            return Response({
                "success": False,
                "error_code": PluginErrorCode.INVALID_PLUGIN_KEY,
                "error": "Invalid plugin key format"
            }, status=status.HTTP_400_BAD_REQUEST)

        pm = PluginManager.get()
        data = request.data or {}
        settings = data.get("settings", {})
        try:
            updated = pm.update_settings(key, settings)
            return Response({"success": True, "settings": updated})
        except PluginConfig.DoesNotExist:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.PLUGIN_NOT_FOUND,
                "error": "Plugin not found"
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception(f"Failed to update settings for plugin {key}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class PluginRunAPIView(PluginPermissionMixin, APIView):
    def post(self, request, key):
        # Validate key format
        if not validate_plugin_key(key):
            return Response({
                "success": False,
                "error_code": PluginErrorCode.INVALID_PLUGIN_KEY,
                "error": "Invalid plugin key format"
            }, status=status.HTTP_400_BAD_REQUEST)

        pm = PluginManager.get()
        action = request.data.get("action")
        params = request.data.get("params", {})
        if not action:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.MISSING_PARAMETER,
                "error": "Missing 'action'"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Respect plugin enabled flag
        try:
            cfg = PluginConfig.objects.get(key=key)
            if not cfg.enabled:
                return Response({
                    "success": False,
                    "error_code": PluginErrorCode.PLUGIN_DISABLED,
                    "error": "Plugin is disabled"
                }, status=status.HTTP_403_FORBIDDEN)
        except PluginConfig.DoesNotExist:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.PLUGIN_NOT_FOUND,
                "error": "Plugin not found"
            }, status=status.HTTP_404_NOT_FOUND)

        try:
            result = pm.run_action(key, action, params)
            return Response({"success": True, "result": result})
        except PermissionError as e:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.PLUGIN_INCOMPATIBLE,
                "error": str(e)
            }, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.exception("Plugin action failed")
            return Response({
                "success": False,
                "error": "Plugin action failed"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PluginEnabledAPIView(PluginPermissionMixin, APIView):
    def post(self, request, key):
        # Validate key format
        if not validate_plugin_key(key):
            return Response({
                "success": False,
                "error_code": PluginErrorCode.INVALID_PLUGIN_KEY,
                "error": "Invalid plugin key format"
            }, status=status.HTTP_400_BAD_REQUEST)

        enabled = request.data.get("enabled")
        if enabled is None:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.MISSING_PARAMETER,
                "error": "Missing 'enabled' boolean"
            }, status=status.HTTP_400_BAD_REQUEST)

        pm = PluginManager.get()
        plugin = pm.get_plugin(key)

        # Check compatibility before enabling (outside transaction - read-only)
        if enabled:
            if plugin and not plugin.compatible:
                return Response({
                    "success": False,
                    "error_code": PluginErrorCode.PLUGIN_INCOMPATIBLE,
                    "error": f"Cannot enable incompatible plugin: {plugin.compatibility_error}",
                    "details": {
                        "compatibility_error": plugin.compatibility_error
                    }
                }, status=status.HTTP_400_BAD_REQUEST)

        # Use transaction with row locking to prevent race conditions
        try:
            with transaction.atomic():
                cfg = PluginConfig.objects.select_for_update().get(key=key)

                if enabled and plugin and plugin.manifest_key:
                    # Check for manifest_key conflicts with batch query (fixes N+1)
                    conflicting_keys = pm.get_plugins_by_manifest_key(plugin.manifest_key, exclude_key=key)
                    if conflicting_keys:
                        # Lock and check all potentially conflicting configs atomically
                        enabled_conflict = PluginConfig.objects.select_for_update().filter(
                            key__in=conflicting_keys,
                            enabled=True
                        ).first()

                        if enabled_conflict:
                            conflict_plugin = pm.get_plugin(enabled_conflict.key)
                            conflict_name = conflict_plugin.name if conflict_plugin else enabled_conflict.key
                            return Response({
                                "success": False,
                                "error_code": PluginErrorCode.MANIFEST_KEY_CONFLICT,
                                "error": f"Cannot enable: '{conflict_name}' is already enabled with the same plugin key '{plugin.manifest_key}'",
                                "details": {
                                    "conflicting_plugin_key": enabled_conflict.key,
                                    "conflicting_plugin_name": conflict_name,
                                    "manifest_key": plugin.manifest_key
                                }
                            }, status=status.HTTP_400_BAD_REQUEST)

                cfg.enabled = bool(enabled)
                # Mark that this plugin has been enabled at least once
                if cfg.enabled and not cfg.ever_enabled:
                    cfg.ever_enabled = True
                cfg.save(update_fields=["enabled", "ever_enabled", "updated_at"])

                return Response({
                    "success": True,
                    "enabled": cfg.enabled,
                    "ever_enabled": cfg.ever_enabled,
                })
        except PluginConfig.DoesNotExist:
            return Response({
                "success": False,
                "error_code": PluginErrorCode.PLUGIN_NOT_FOUND,
                "error": "Plugin not found"
            }, status=status.HTTP_404_NOT_FOUND)


class PluginDeleteAPIView(PluginPermissionMixin, APIView):
    def delete(self, request, key):
        # Validate key format
        if not validate_plugin_key(key):
            return Response({
                "success": False,
                "error_code": PluginErrorCode.INVALID_PLUGIN_KEY,
                "error": "Invalid plugin key format"
            }, status=status.HTTP_400_BAD_REQUEST)

        pm = PluginManager.get()
        plugins_dir = pm.plugins_dir
        target_dir = os.path.join(plugins_dir, key)
        # Safety: ensure path inside plugins_dir
        abs_plugins = os.path.abspath(plugins_dir) + os.sep
        abs_target = os.path.abspath(target_dir)
        if not abs_target.startswith(abs_plugins):
            return Response({
                "success": False,
                "error_code": PluginErrorCode.INVALID_PLUGIN_KEY,
                "error": "Invalid plugin path"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Remove files
        if os.path.isdir(target_dir):
            try:
                shutil.rmtree(target_dir)
            except Exception as e:
                logger.exception(f"Failed to delete plugin files for {key}")
                return Response({
                    "success": False,
                    "error": f"Failed to delete plugin files: {e}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Remove DB record
        try:
            PluginConfig.objects.filter(key=key).delete()
        except Exception:
            logger.exception(f"Failed to delete DB record for plugin {key}")

        # Reload registry
        pm.discover_plugins(force=True)
        return Response({"success": True})
