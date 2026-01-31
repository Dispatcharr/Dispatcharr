"""Plugin API views.

This module provides REST API endpoints for managing plugins.
"""

import logging
import os
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import UploadedFile
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_method,
)

from .loader import PluginManager
from .models import PluginConfig, PluginData

logger = logging.getLogger(__name__)


class PluginPermissionMixin:
    """Mixin providing standardized permission handling for plugin views."""

    def get_permissions(self):
        """Get permission classes based on request method."""
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]


class PluginsListAPIView(PluginPermissionMixin, APIView):
    """List all plugins with their configuration."""

    def get(self, request):
        pm = PluginManager.get()
        pm.discover_plugins()
        return Response({"plugins": pm.list_plugins()})


class PluginReloadAPIView(PluginPermissionMixin, APIView):
    """Trigger plugin discovery refresh."""

    def post(self, request):
        pm = PluginManager.get()
        plugins = pm.discover_plugins()
        return Response({"success": True, "count": len(plugins)})


class PluginImportAPIView(PluginPermissionMixin, APIView):
    """Import a plugin from a ZIP file."""

    def post(self, request):
        file: UploadedFile = request.FILES.get("file")
        if not file:
            return Response(
                {"success": False, "error": "Missing 'file' upload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pm = PluginManager.get()
        plugins_dir = pm.plugins_dir

        try:
            zf = zipfile.ZipFile(file)
        except zipfile.BadZipFile:
            return Response(
                {"success": False, "error": "Invalid zip file"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tmp_root = tempfile.mkdtemp(prefix="plugin_import_")
        target_dir = None

        try:
            # Extract and validate the archive
            result = self._extract_and_validate(zf, tmp_root, plugins_dir)
            if isinstance(result, Response):
                return result

            plugin_key, target_dir = result

            # Reload discovery and validate plugin
            pm.discover_plugins()
            plugin = pm.get_plugin(plugin_key)

            if not plugin:
                self._cleanup_failed_import(target_dir)
                return Response(
                    {"success": False, "error": "Invalid plugin: missing Plugin class in plugin.py or __init__.py"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate run method exists
            if not plugin.is_valid:
                self._cleanup_failed_import(target_dir)
                return Response(
                    {"success": False, "error": "Invalid plugin: Plugin class must define a callable run(action, params, context)"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get DB config for response
            enabled, ever_enabled = self._get_plugin_config(plugin_key)

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
                },
            })

        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def _extract_and_validate(self, zf, tmp_root, plugins_dir):
        """Extract ZIP and validate structure.

        Returns:
            Tuple of (plugin_key, target_dir) on success, or Response on error.
        """
        file_members = [m for m in zf.infolist() if not m.is_dir()]
        if not file_members:
            return Response(
                {"success": False, "error": "Archive is empty"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract files with path traversal protection
        for member in file_members:
            name = member.filename
            if not name or name.endswith("/"):
                continue

            norm = os.path.normpath(name)
            if norm.startswith("..") or os.path.isabs(norm):
                return Response(
                    {"success": False, "error": "Unsafe path in archive"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            dest_path = os.path.join(tmp_root, norm)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with zf.open(member, 'r') as src, open(dest_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)

        # Find plugin directory
        candidates = []
        for dirpath, dirnames, filenames in os.walk(tmp_root):
            has_pluginpy = "plugin.py" in filenames
            has_init = "__init__.py" in filenames
            if has_pluginpy or has_init:
                depth = len(os.path.relpath(dirpath, tmp_root).split(os.sep))
                candidates.append((0 if has_pluginpy else 1, depth, dirpath))

        if not candidates:
            return Response(
                {"success": False, "error": "Invalid plugin: missing plugin.py or package __init__.py"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        candidates.sort()
        chosen = candidates[0][2]

        # Determine plugin key
        base_name = os.path.splitext(getattr(zf.fp, "name", "plugin"))[0]
        plugin_key = os.path.basename(chosen.rstrip(os.sep))
        if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
            plugin_key = os.path.basename(base_name)
        plugin_key = plugin_key.replace(" ", "_").lower()

        # Check for existing plugin
        final_dir = os.path.join(plugins_dir, plugin_key)
        if os.path.exists(final_dir):
            if os.path.exists(os.path.join(final_dir, "plugin.py")) or \
               os.path.exists(os.path.join(final_dir, "__init__.py")):
                return Response(
                    {"success": False, "error": f"Plugin '{plugin_key}' already exists"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            shutil.rmtree(final_dir, ignore_errors=True)

        # Move to final location
        if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
            os.makedirs(final_dir, exist_ok=True)
            for item in os.listdir(tmp_root):
                shutil.move(os.path.join(tmp_root, item), os.path.join(final_dir, item))
        else:
            shutil.move(chosen, final_dir)

        return plugin_key, final_dir

    def _cleanup_failed_import(self, target_dir):
        """Clean up plugin directory after failed import."""
        if target_dir:
            shutil.rmtree(target_dir, ignore_errors=True)

    def _get_plugin_config(self, plugin_key):
        """Get plugin enabled status from database."""
        try:
            cfg = PluginConfig.objects.get(key=plugin_key)
            return cfg.enabled, getattr(cfg, "ever_enabled", False)
        except PluginConfig.DoesNotExist:
            return False, False


class PluginSettingsAPIView(PluginPermissionMixin, APIView):
    """Update plugin settings."""

    def post(self, request, key):
        pm = PluginManager.get()
        data = request.data or {}
        settings = data.get("settings", {})

        try:
            updated = pm.update_settings(key, settings)
            return Response({"success": True, "settings": updated})
        except PluginConfig.DoesNotExist:
            return Response(
                {"success": False, "error": "Plugin not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )


class PluginRunAPIView(PluginPermissionMixin, APIView):
    """Execute a plugin action."""

    def post(self, request, key):
        pm = PluginManager.get()
        action = request.data.get("action")
        params = request.data.get("params", {})

        if not action:
            return Response(
                {"success": False, "error": "Missing 'action'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = pm.run_action(key, action, params)
            return Response({"success": True, "result": result})
        except PluginConfig.DoesNotExist:
            return Response(
                {"success": False, "error": "Plugin not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("Plugin action failed")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PluginEnabledAPIView(PluginPermissionMixin, APIView):
    """Enable or disable a plugin."""

    def post(self, request, key):
        enabled = request.data.get("enabled")

        if enabled is None:
            return Response(
                {"success": False, "error": "Missing 'enabled' boolean"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pm = PluginManager.get()

        try:
            result = pm.set_enabled(key, bool(enabled))
            return Response({
                "success": True,
                "enabled": result["enabled"],
                "ever_enabled": result["ever_enabled"],
            })
        except PluginConfig.DoesNotExist:
            return Response(
                {"success": False, "error": "Plugin not found"},
                status=status.HTTP_404_NOT_FOUND,
            )


class PluginDeleteAPIView(PluginPermissionMixin, APIView):
    """Delete a plugin."""

    def delete(self, request, key):
        pm = PluginManager.get()
        plugins_dir = pm.plugins_dir
        target_dir = os.path.join(plugins_dir, key)

        # Safety: ensure path is inside plugins_dir
        abs_plugins = os.path.abspath(plugins_dir) + os.sep
        abs_target = os.path.abspath(target_dir)
        if not abs_target.startswith(abs_plugins):
            return Response(
                {"success": False, "error": "Invalid plugin path"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Remove files
        if os.path.isdir(target_dir):
            try:
                shutil.rmtree(target_dir)
            except Exception as e:
                return Response(
                    {"success": False, "error": f"Failed to delete plugin files: {e}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Remove DB record
        try:
            PluginConfig.objects.filter(key=key).delete()
        except Exception:
            pass

        # Reload registry
        pm.discover_plugins()
        return Response({"success": True})


# =============================================================================
# Plugin Data API Views
# =============================================================================


class PluginDataListAPIView(PluginPermissionMixin, APIView):
    """List and create data in a plugin collection."""

    def get(self, request, key, collection):
        """Get all items in a collection."""
        try:
            PluginConfig.objects.get(key=key)
        except PluginConfig.DoesNotExist:
            return Response(
                {"success": False, "error": "Plugin not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = PluginData.objects.get_collection_data(key, collection)
        return Response({"success": True, "data": data})

    def post(self, request, key, collection):
        """Add a new item to a collection."""
        try:
            PluginConfig.objects.get(key=key)
        except PluginConfig.DoesNotExist:
            return Response(
                {"success": False, "error": "Plugin not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = request.data.get("data", {})
        if not isinstance(data, dict):
            return Response(
                {"success": False, "error": "'data' must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            record = PluginData.objects.add_to_collection(key, collection, data)
            return Response({
                "success": True,
                "data": {**record.data, "_id": record.id},
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.exception("Failed to add plugin data")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request, key, collection):
        """Clear all items in a collection."""
        try:
            PluginConfig.objects.get(key=key)
        except PluginConfig.DoesNotExist:
            return Response(
                {"success": False, "error": "Plugin not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        count = PluginData.objects.clear_collection(key, collection)
        return Response({"success": True, "deleted_count": count})


class PluginDataDetailAPIView(PluginPermissionMixin, APIView):
    """Get, update, or delete a specific data item."""

    def get(self, request, key, collection, record_id):
        """Get a specific item."""
        try:
            record = PluginData.objects.get(
                plugin__key=key,
                collection=collection,
                id=record_id,
            )
            return Response({
                "success": True,
                "data": {**record.data, "_id": record.id},
            })
        except PluginData.DoesNotExist:
            return Response(
                {"success": False, "error": "Record not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def put(self, request, key, collection, record_id):
        """Update a specific item (full replacement)."""
        data = request.data.get("data", {})
        if not isinstance(data, dict):
            return Response(
                {"success": False, "error": "'data' must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record = PluginData.objects.update_in_collection(
            key, collection, record_id, data
        )
        if record is None:
            return Response(
                {"success": False, "error": "Record not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({
            "success": True,
            "data": {**record.data, "_id": record.id},
        })

    def patch(self, request, key, collection, record_id):
        """Partially update a specific item (merge)."""
        try:
            record = PluginData.objects.get(
                plugin__key=key,
                collection=collection,
                id=record_id,
            )
        except PluginData.DoesNotExist:
            return Response(
                {"success": False, "error": "Record not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        updates = request.data.get("data", {})
        if not isinstance(updates, dict):
            return Response(
                {"success": False, "error": "'data' must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Merge updates into existing data
        record.data.update(updates)
        record.save()

        return Response({
            "success": True,
            "data": {**record.data, "_id": record.id},
        })

    def delete(self, request, key, collection, record_id):
        """Delete a specific item."""
        deleted = PluginData.objects.remove_from_collection(
            key, collection, record_id
        )
        if not deleted:
            return Response(
                {"success": False, "error": "Record not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"success": True})


class PluginDataBulkAPIView(PluginPermissionMixin, APIView):
    """Bulk operations on plugin data collections."""

    def put(self, request, key, collection):
        """Replace entire collection with new data."""
        try:
            PluginConfig.objects.get(key=key)
        except PluginConfig.DoesNotExist:
            return Response(
                {"success": False, "error": "Plugin not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        data_list = request.data.get("data", [])
        if not isinstance(data_list, list):
            return Response(
                {"success": False, "error": "'data' must be an array"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            records = PluginData.objects.set_collection(key, collection, data_list)
            result = [
                {**r.data, "_id": r.id}
                for r in records
            ]
            return Response({"success": True, "data": result})
        except Exception as e:
            logger.exception("Failed to set collection")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
