import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
import io
import os
import zipfile
import shutil
import tempfile
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_method,
)

from .loader import PluginManager
from .models import PluginConfig

logger = logging.getLogger(__name__)


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
        # Ensure registry is up-to-date on each request
        pm.discover_plugins()
        return Response({"plugins": pm.list_plugins()})


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
        pm.discover_plugins()
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
            plugin_key = plugin_key.replace(" ", "_").lower()

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
            # Cleanup temp
            shutil.rmtree(tmp_root, ignore_errors=True)
            target_dir = final_dir
        finally:
            try:
                shutil.rmtree(tmp_root, ignore_errors=True)
            except Exception:
                pass

        # Reload discovery and validate plugin entry
        pm.discover_plugins()
        plugin = pm._registry.get(plugin_key)
        if not plugin:
            # Cleanup the copied folder to avoid leaving invalid plugin behind
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
            except Exception:
                pass
            return Response({"success": False, "error": "Invalid plugin: missing Plugin class in plugin.py or __init__.py"}, status=status.HTTP_400_BAD_REQUEST)

        # Extra validation: ensure Plugin.run exists
        instance = getattr(plugin, "instance", None)
        run_method = getattr(instance, "run", None)
        if not callable(run_method):
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
            except Exception:
                pass
            return Response({"success": False, "error": "Invalid plugin: Plugin class must define a callable run(action, params, context)"}, status=status.HTTP_400_BAD_REQUEST)

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
            }
        })


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
        enabled = request.data.get("enabled")
        if enabled is None:
            return Response({"success": False, "error": "Missing 'enabled' boolean"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            cfg = PluginConfig.objects.get(key=key)
            cfg.enabled = bool(enabled)
            # Mark that this plugin has been enabled at least once
            if cfg.enabled and not cfg.ever_enabled:
                cfg.ever_enabled = True
            cfg.save(update_fields=["enabled", "ever_enabled", "updated_at"])
            return Response({"success": True, "enabled": cfg.enabled, "ever_enabled": cfg.ever_enabled})
        except PluginConfig.DoesNotExist:
            return Response({"success": False, "error": "Plugin not found"}, status=status.HTTP_404_NOT_FOUND)


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
        pm.discover_plugins()
        return Response({"success": True})
