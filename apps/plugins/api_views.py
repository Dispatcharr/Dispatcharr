import logging
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse
import os
import zipfile
import shutil
import tempfile
from urllib.parse import urlparse
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_method,
)
from dispatcharr.utils import network_access_allowed

from .loader import PluginManager
from .models import PluginConfig

logger = logging.getLogger(__name__)


MAX_PLUGIN_IMPORT_FILES = getattr(settings, "DISPATCHARR_PLUGIN_IMPORT_MAX_FILES", 2000)
MAX_PLUGIN_IMPORT_BYTES = getattr(settings, "DISPATCHARR_PLUGIN_IMPORT_MAX_BYTES", 200 * 1024 * 1024)
MAX_PLUGIN_IMPORT_FILE_BYTES = getattr(settings, "DISPATCHARR_PLUGIN_IMPORT_MAX_FILE_BYTES", 200 * 1024 * 1024)


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "y", "on"):
            return True
        if normalized in ("false", "0", "no", "n", "off"):
            return False
    return None


def _sanitize_plugin_key(value: str) -> str:
    base = os.path.basename(value or "")
    base = base.replace(" ", "_").lower()
    base = re.sub(r"[^a-z0-9_-]", "_", base)
    base = base.strip("._-")
    return base or "plugin"


def _absolutize_logo_url(request, url: str | None) -> str | None:
    if not url or not request:
        return url
    parsed = urlparse(url)
    if parsed.scheme:
        return url
    return request.build_absolute_uri(url)


class PluginsListAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def get(self, request):
        pm = PluginManager.get()
        # Prefer cached registry; reload explicitly via the reload endpoint
        pm.discover_plugins(sync_db=False, use_cache=True)
        plugins = pm.list_plugins()
        for plugin in plugins:
            plugin["logo_url"] = _absolutize_logo_url(request, plugin.get("logo_url"))
        return Response({"plugins": plugins})


class PluginReloadAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request):
        pm = PluginManager.get()
        pm.stop_all_plugins(reason="reload")
        pm.discover_plugins(force_reload=True)
        return Response({"success": True, "count": len(pm._registry)})


class PluginImportAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request):
        file: UploadedFile = request.FILES.get("file")
        if not file:
            return Response({"success": False, "error": "Missing 'file' upload"}, status=status.HTTP_400_BAD_REQUEST)

        pm = PluginManager.get()
        plugins_dir = pm.plugins_dir

        try:
            zf = zipfile.ZipFile(file)
        except zipfile.BadZipFile:
            return Response({"success": False, "error": "Invalid zip file"}, status=status.HTTP_400_BAD_REQUEST)

        # Extract to a temporary directory first to avoid server reload thrash
        tmp_root = tempfile.mkdtemp(prefix="plugin_import_")
        try:
            file_members = [m for m in zf.infolist() if not m.is_dir()]
            if not file_members:
                shutil.rmtree(tmp_root, ignore_errors=True)
                return Response({"success": False, "error": "Archive is empty"}, status=status.HTTP_400_BAD_REQUEST)
            if len(file_members) > MAX_PLUGIN_IMPORT_FILES:
                shutil.rmtree(tmp_root, ignore_errors=True)
                return Response({"success": False, "error": "Archive has too many files"}, status=status.HTTP_400_BAD_REQUEST)

            total_size = 0
            for member in file_members:
                total_size += member.file_size
                if member.file_size > MAX_PLUGIN_IMPORT_FILE_BYTES:
                    shutil.rmtree(tmp_root, ignore_errors=True)
                    return Response({"success": False, "error": "Archive contains a file that is too large"}, status=status.HTTP_400_BAD_REQUEST)
            if total_size > MAX_PLUGIN_IMPORT_BYTES:
                shutil.rmtree(tmp_root, ignore_errors=True)
                return Response({"success": False, "error": "Archive is too large"}, status=status.HTTP_400_BAD_REQUEST)

            for member in file_members:
                name = member.filename
                if not name or name.endswith("/"):
                    continue
                # Normalize and prevent path traversal
                norm = os.path.normpath(name)
                if norm.startswith("..") or os.path.isabs(norm):
                    shutil.rmtree(tmp_root, ignore_errors=True)
                    return Response({"success": False, "error": "Unsafe path in archive"}, status=status.HTTP_400_BAD_REQUEST)
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
            plugin_key = _sanitize_plugin_key(plugin_key)
            if len(plugin_key) > 128:
                plugin_key = plugin_key[:128]
            logo_bytes = None
            try:
                logo_candidates = []
                chosen_abs = os.path.abspath(chosen)
                for dirpath, _, filenames in os.walk(tmp_root):
                    for filename in filenames:
                        if filename.lower() != "logo.png":
                            continue
                        full_path = os.path.join(dirpath, filename)
                        full_abs = os.path.abspath(full_path)
                        try:
                            in_chosen = os.path.commonpath([chosen_abs, full_abs]) == chosen_abs
                        except Exception:
                            in_chosen = False
                        depth = len(os.path.relpath(dirpath, tmp_root).split(os.sep))
                        logo_candidates.append((0 if in_chosen else 1, depth, full_path))
                if logo_candidates:
                    logo_candidates.sort()
                    with open(logo_candidates[0][2], "rb") as fh:
                        logo_bytes = fh.read()
            except Exception:
                logo_bytes = None

            final_dir = os.path.join(plugins_dir, plugin_key)
            if os.path.exists(final_dir):
                # If final dir exists but contains a valid plugin, refuse; otherwise clear it
                if os.path.exists(os.path.join(final_dir, "plugin.py")) or os.path.exists(os.path.join(final_dir, "__init__.py")):
                    shutil.rmtree(tmp_root, ignore_errors=True)
                    return Response({"success": False, "error": f"Plugin '{plugin_key}' already exists"}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    shutil.rmtree(final_dir)
                except Exception:
                    pass

            # Move chosen directory into final location
            if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
                # Move all contents into final_dir
                os.makedirs(final_dir, exist_ok=True)
                for item in os.listdir(tmp_root):
                    shutil.move(os.path.join(tmp_root, item), os.path.join(final_dir, item))
            else:
                shutil.move(chosen, final_dir)
            if logo_bytes:
                try:
                    with open(os.path.join(final_dir, "logo.png"), "wb") as fh:
                        fh.write(logo_bytes)
                except Exception:
                    pass
            # Cleanup temp
            shutil.rmtree(tmp_root, ignore_errors=True)
            target_dir = final_dir
        finally:
            try:
                shutil.rmtree(tmp_root, ignore_errors=True)
            except Exception:
                pass

        # Ensure DB config exists (untrusted plugins are registered without loading)
        try:
            cfg, _ = PluginConfig.objects.get_or_create(
                key=plugin_key,
                defaults={
                    "name": plugin_key,
                    "version": "",
                    "description": "",
                    "settings": {},
                },
            )
        except Exception:
            cfg = None

        # Reload discovery to register the plugin (trusted plugins will load)
        pm.discover_plugins(force_reload=True)
        plugin_entry = None
        try:
            plugin_entry = next((p for p in pm.list_plugins() if p.get("key") == plugin_key), None)
        except Exception:
            plugin_entry = None

        if not plugin_entry:
            logo_path = os.path.join(plugins_dir, plugin_key, "logo.png")
            logo_url = f"/api/plugins/plugins/{plugin_key}/logo/" if os.path.isfile(logo_path) else None
            legacy = not os.path.isfile(os.path.join(plugins_dir, plugin_key, "plugin.json"))
            plugin_entry = {
                "key": plugin_key,
                "name": cfg.name if cfg else plugin_key,
                "version": cfg.version if cfg else "",
                "description": cfg.description if cfg else "",
                "enabled": cfg.enabled if cfg else False,
                "ever_enabled": getattr(cfg, "ever_enabled", False) if cfg else False,
                "fields": [],
                "actions": [],
                "trusted": bool(cfg and (cfg.ever_enabled or cfg.enabled)),
                "loaded": False,
                "missing": False,
                "legacy": legacy,
                "logo_url": logo_url,
            }

        plugin_entry["logo_url"] = _absolutize_logo_url(request, plugin_entry.get("logo_url"))
        return Response({"success": True, "plugin": plugin_entry})


class PluginSettingsAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request, key):
        pm = PluginManager.get()
        data = request.data or {}
        settings = data.get("settings", {})
        try:
            updated = pm.update_settings(key, settings)
            return Response({"success": True, "settings": updated})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PluginRunAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request, key):
        pm = PluginManager.get()
        action = request.data.get("action")
        params = request.data.get("params", {})
        if not action:
            return Response({"success": False, "error": "Missing 'action'"}, status=status.HTTP_400_BAD_REQUEST)

        # Respect plugin enabled flag
        try:
            cfg = PluginConfig.objects.get(key=key)
            if not cfg.enabled:
                return Response({"success": False, "error": "Plugin is disabled"}, status=status.HTTP_403_FORBIDDEN)
        except PluginConfig.DoesNotExist:
            return Response({"success": False, "error": "Plugin not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = pm.run_action(key, action, params)
            return Response({"success": True, "result": result})
        except PermissionError as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.exception("Plugin action failed")
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PluginEnabledAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def post(self, request, key):
        enabled_raw = request.data.get("enabled")
        if enabled_raw is None:
            return Response({"success": False, "error": "Missing 'enabled' boolean"}, status=status.HTTP_400_BAD_REQUEST)
        enabled = _parse_bool(enabled_raw)
        if enabled is None:
            return Response({"success": False, "error": "Invalid 'enabled' boolean"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            cfg = PluginConfig.objects.get(key=key)
            pm = PluginManager.get()
            if not enabled and cfg.enabled:
                try:
                    pm.stop_plugin(key, reason="disable")
                except Exception:
                    logger.exception("Failed to stop plugin '%s' on disable", key)
            cfg.enabled = enabled
            # Mark that this plugin has been enabled at least once
            if cfg.enabled and not cfg.ever_enabled:
                cfg.ever_enabled = True
            cfg.save(update_fields=["enabled", "ever_enabled", "updated_at"])
            pm.discover_plugins(force_reload=True)
            plugin_entry = None
            try:
                plugin_entry = next((p for p in pm.list_plugins() if p.get("key") == key), None)
            except Exception:
                plugin_entry = None
            response = {"success": True, "enabled": cfg.enabled, "ever_enabled": cfg.ever_enabled}
            if plugin_entry:
                plugin_entry["logo_url"] = _absolutize_logo_url(request, plugin_entry.get("logo_url"))
                response["plugin"] = plugin_entry
            return Response(response)
        except PluginConfig.DoesNotExist:
            return Response({"success": False, "error": "Plugin not found"}, status=status.HTTP_404_NOT_FOUND)


class PluginLogoAPIView(APIView):
    def get_permissions(self):
        return []

    def get(self, request, key):
        if not network_access_allowed(request, "UI"):
            return Response({"success": False, "error": "Network access denied"}, status=status.HTTP_403_FORBIDDEN)
        pm = PluginManager.get()
        pm.discover_plugins(use_cache=True)
        plugins_dir = pm.plugins_dir
        logo_path = os.path.join(plugins_dir, key, "logo.png")
        lp = pm.get_plugin(key)
        if lp and getattr(lp, "path", None):
            logo_path = os.path.join(lp.path, "logo.png")
        abs_plugins = os.path.abspath(plugins_dir) + os.sep
        abs_target = os.path.abspath(logo_path)
        if not abs_target.startswith(abs_plugins):
            return Response({"success": False, "error": "Invalid plugin path"}, status=status.HTTP_400_BAD_REQUEST)
        if not os.path.isfile(logo_path):
            return Response({"success": False, "error": "Logo not found"}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(open(logo_path, "rb"), content_type="image/png")


class PluginDeleteAPIView(APIView):
    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    def delete(self, request, key):
        pm = PluginManager.get()
        try:
            pm.stop_plugin(key, reason="delete")
        except Exception:
            logger.exception("Failed to stop plugin '%s' before delete", key)
        plugins_dir = pm.plugins_dir
        target_dir = os.path.join(plugins_dir, key)
        # Safety: ensure path inside plugins_dir
        abs_plugins = os.path.abspath(plugins_dir) + os.sep
        abs_target = os.path.abspath(target_dir)
        if not abs_target.startswith(abs_plugins):
            return Response({"success": False, "error": "Invalid plugin path"}, status=status.HTTP_400_BAD_REQUEST)

        # Remove files
        if os.path.isdir(target_dir):
            try:
                shutil.rmtree(target_dir)
            except Exception as e:
                return Response({"success": False, "error": f"Failed to delete plugin files: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Remove DB record
        try:
            PluginConfig.objects.filter(key=key).delete()
        except Exception:
            pass

        # Reload registry
        pm.discover_plugins(force_reload=True)
        return Response({"success": True})
