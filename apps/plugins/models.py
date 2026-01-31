from typing import Any, Dict, List, Optional

from django.db import models


class PluginConfig(models.Model):
    """Stores discovered plugins and their persisted settings."""

    key = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)
    # Tracks whether this plugin has ever been enabled at least once
    ever_enabled = models.BooleanField(default=False)
    settings = models.JSONField(default=dict, blank=True)
    # Navigation item configuration (null if plugin doesn't add to nav)
    navigation = models.JSONField(
        null=True,
        blank=True,
        help_text="Navigation item config: {label, icon, path, badge, position}",
    )
    # UI schema for plugin pages (null if plugin uses legacy actions UI)
    pages = models.JSONField(
        null=True,
        blank=True,
        help_text="Page definitions for plugin UI",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


class PluginDataManager(models.Manager):
    """Custom manager for PluginData with collection-oriented methods."""

    def get_collection(
        self,
        plugin_key: str,
        collection: str,
    ) -> models.QuerySet:
        """Get all records in a collection for a plugin.

        Args:
            plugin_key: The plugin's unique key
            collection: The collection name

        Returns:
            QuerySet of PluginData records
        """
        return self.filter(plugin__key=plugin_key, collection=collection)

    def get_collection_data(
        self,
        plugin_key: str,
        collection: str,
    ) -> List[Dict[str, Any]]:
        """Get collection data as a list of dicts with IDs injected.

        Args:
            plugin_key: The plugin's unique key
            collection: The collection name

        Returns:
            List of data dicts, each with "_id" field added
        """
        records = self.get_collection(plugin_key, collection)
        result = []
        for record in records:
            data = record.data.copy()
            data["_id"] = record.id
            result.append(data)
        return result

    def set_collection(
        self,
        plugin_key: str,
        collection: str,
        data_list: List[Dict[str, Any]],
    ) -> List["PluginData"]:
        """Replace entire collection with new data.

        Args:
            plugin_key: The plugin's unique key
            collection: The collection name
            data_list: List of data dicts to store

        Returns:
            List of created PluginData records
        """
        plugin = PluginConfig.objects.get(key=plugin_key)

        # Delete existing collection
        self.filter(plugin=plugin, collection=collection).delete()

        # Create new records
        records = [
            PluginData(plugin=plugin, collection=collection, data=data)
            for data in data_list
        ]
        return self.bulk_create(records)

    def add_to_collection(
        self,
        plugin_key: str,
        collection: str,
        data: Dict[str, Any],
    ) -> "PluginData":
        """Add a single item to a collection.

        Args:
            plugin_key: The plugin's unique key
            collection: The collection name
            data: The data to store

        Returns:
            Created PluginData record
        """
        plugin = PluginConfig.objects.get(key=plugin_key)
        return self.create(plugin=plugin, collection=collection, data=data)

    def update_in_collection(
        self,
        plugin_key: str,
        collection: str,
        record_id: int,
        data: Dict[str, Any],
    ) -> Optional["PluginData"]:
        """Update a specific item in a collection.

        Args:
            plugin_key: The plugin's unique key
            collection: The collection name
            record_id: The record ID to update
            data: New data (replaces existing)

        Returns:
            Updated PluginData record or None if not found
        """
        try:
            record = self.get(
                plugin__key=plugin_key,
                collection=collection,
                id=record_id,
            )
            record.data = data
            record.save()
            return record
        except self.model.DoesNotExist:
            return None

    def remove_from_collection(
        self,
        plugin_key: str,
        collection: str,
        record_id: int,
    ) -> bool:
        """Remove a specific item from a collection.

        Args:
            plugin_key: The plugin's unique key
            collection: The collection name
            record_id: The record ID to remove

        Returns:
            True if deleted, False if not found
        """
        deleted, _ = self.filter(
            plugin__key=plugin_key,
            collection=collection,
            id=record_id,
        ).delete()
        return deleted > 0

    def clear_collection(
        self,
        plugin_key: str,
        collection: str,
    ) -> int:
        """Clear all items in a collection.

        Args:
            plugin_key: The plugin's unique key
            collection: The collection name

        Returns:
            Number of deleted records
        """
        deleted, _ = self.filter(
            plugin__key=plugin_key,
            collection=collection,
        ).delete()
        return deleted


class PluginData(models.Model):
    """Stores arbitrary data for plugins in a collection-based pattern.

    This allows plugins to persist structured data without needing to
    define their own database models. Data is organized by collections
    (e.g., "calendars", "events", "settings").

    Example usage from a plugin:
        from apps.plugins.models import PluginData

        # Add item to collection
        PluginData.objects.add_to_collection("my_plugin", "calendars", {
            "name": "Work Calendar",
            "url": "https://example.com/cal.ics"
        })

        # Get all items in collection
        calendars = PluginData.objects.get_collection_data("my_plugin", "calendars")

        # Update item
        PluginData.objects.update_in_collection("my_plugin", "calendars", item_id, new_data)

        # Delete item
        PluginData.objects.remove_from_collection("my_plugin", "calendars", item_id)
    """

    plugin = models.ForeignKey(
        PluginConfig,
        on_delete=models.CASCADE,
        related_name="data_records",
    )
    collection = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Collection name (e.g., 'calendars', 'events')",
    )
    data = models.JSONField(
        default=dict,
        help_text="Arbitrary JSON data for this record",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PluginDataManager()

    class Meta:
        verbose_name = "Plugin Data"
        verbose_name_plural = "Plugin Data"
        indexes = [
            models.Index(fields=["plugin", "collection"]),
        ]

    def __str__(self) -> str:
        return f"{self.plugin.key}:{self.collection}#{self.id}"
