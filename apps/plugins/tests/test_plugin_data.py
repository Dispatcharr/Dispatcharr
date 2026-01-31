"""Tests for PluginData model and data management."""

import pytest
from django.test import TestCase
from django.db import IntegrityError

from apps.plugins.models import PluginConfig, PluginData


class TestPluginDataModel(TestCase):
    """Tests for the PluginData model."""

    def setUp(self):
        """Create a plugin config for testing."""
        self.plugin_config = PluginConfig.objects.create(
            key="test_plugin",
            name="Test Plugin",
            version="1.0.0",
        )

    def test_create_plugin_data(self):
        """Can create a data record for a plugin."""
        data = PluginData.objects.create(
            plugin=self.plugin_config,
            collection="calendars",
            data={"name": "Test Calendar", "url": "https://example.com/cal.ics"},
        )
        assert data.id is not None
        assert data.plugin == self.plugin_config
        assert data.collection == "calendars"
        assert data.data["name"] == "Test Calendar"

    def test_data_auto_timestamps(self):
        """Data records have auto-generated timestamps."""
        data = PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={},
        )
        assert data.created_at is not None
        assert data.updated_at is not None

    def test_multiple_collections_per_plugin(self):
        """A plugin can have multiple collections."""
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="calendars",
            data={"name": "Cal 1"},
        )
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="events",
            data={"title": "Event 1"},
        )

        calendars = PluginData.objects.filter(
            plugin=self.plugin_config,
            collection="calendars",
        )
        events = PluginData.objects.filter(
            plugin=self.plugin_config,
            collection="events",
        )

        assert calendars.count() == 1
        assert events.count() == 1

    def test_plugin_data_deleted_with_plugin(self):
        """Plugin data is deleted when plugin config is deleted."""
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"test": True},
        )
        plugin_key = self.plugin_config.key

        # Delete the plugin
        self.plugin_config.delete()

        # Data should be gone
        assert PluginData.objects.filter(plugin__key=plugin_key).count() == 0

    def test_query_by_plugin_key(self):
        """Can query data by plugin key."""
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"value": 1},
        )

        data = PluginData.objects.filter(plugin__key="test_plugin")
        assert data.count() == 1

    def test_json_data_with_nested_structure(self):
        """Data can contain nested JSON structures."""
        nested_data = {
            "name": "Calendar",
            "events": [
                {"id": 1, "title": "Event 1"},
                {"id": 2, "title": "Event 2"},
            ],
            "settings": {
                "enabled": True,
                "refresh_interval": 3600,
            },
        }
        data = PluginData.objects.create(
            plugin=self.plugin_config,
            collection="complex",
            data=nested_data,
        )

        # Reload and verify
        data.refresh_from_db()
        assert data.data["name"] == "Calendar"
        assert len(data.data["events"]) == 2
        assert data.data["settings"]["enabled"] is True

    def test_update_data(self):
        """Can update data record."""
        data = PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"count": 1},
        )
        original_created = data.created_at

        # Update
        data.data["count"] = 2
        data.data["new_field"] = "value"
        data.save()

        data.refresh_from_db()
        assert data.data["count"] == 2
        assert data.data["new_field"] == "value"
        assert data.created_at == original_created
        assert data.updated_at > original_created

    def test_bulk_create(self):
        """Can bulk create data records."""
        records = [
            PluginData(
                plugin=self.plugin_config,
                collection="items",
                data={"name": f"Item {i}"},
            )
            for i in range(5)
        ]
        PluginData.objects.bulk_create(records)

        assert PluginData.objects.filter(
            plugin=self.plugin_config,
            collection="items",
        ).count() == 5

    def test_string_representation(self):
        """String representation is readable."""
        data = PluginData.objects.create(
            plugin=self.plugin_config,
            collection="calendars",
            data={"name": "Test"},
        )
        str_repr = str(data)
        assert "test_plugin" in str_repr
        assert "calendars" in str_repr


class TestPluginDataManager(TestCase):
    """Tests for custom PluginData manager methods."""

    def setUp(self):
        """Create test fixtures."""
        self.plugin_config = PluginConfig.objects.create(
            key="test_plugin",
            name="Test Plugin",
        )

    def test_get_collection(self):
        """Can get all records in a collection."""
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"name": "Item 1"},
        )
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"name": "Item 2"},
        )
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="other",
            data={"name": "Other"},
        )

        items = PluginData.objects.get_collection("test_plugin", "items")
        assert len(items) == 2

    def test_get_collection_as_list(self):
        """Can get collection data as a list of dicts."""
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"name": "Item 1", "value": 1},
        )
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"name": "Item 2", "value": 2},
        )

        items = PluginData.objects.get_collection_data("test_plugin", "items")
        assert len(items) == 2
        assert items[0]["name"] in ("Item 1", "Item 2")
        # Each item should have _id injected
        assert "_id" in items[0]

    def test_set_collection(self):
        """Can replace entire collection."""
        # Create initial data
        PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"name": "Old Item"},
        )

        # Replace collection
        new_data = [
            {"name": "New Item 1"},
            {"name": "New Item 2"},
        ]
        PluginData.objects.set_collection("test_plugin", "items", new_data)

        items = PluginData.objects.get_collection("test_plugin", "items")
        assert len(items) == 2
        names = [item.data["name"] for item in items]
        assert "Old Item" not in names
        assert "New Item 1" in names

    def test_add_to_collection(self):
        """Can add a single item to collection."""
        record = PluginData.objects.add_to_collection(
            "test_plugin",
            "items",
            {"name": "New Item"},
        )
        assert record.id is not None
        assert record.data["name"] == "New Item"

    def test_update_in_collection(self):
        """Can update a specific item in collection."""
        record = PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"name": "Original"},
        )

        updated = PluginData.objects.update_in_collection(
            "test_plugin",
            "items",
            record.id,
            {"name": "Updated", "extra": "field"},
        )

        assert updated.data["name"] == "Updated"
        assert updated.data["extra"] == "field"

    def test_remove_from_collection(self):
        """Can remove a specific item from collection."""
        record = PluginData.objects.create(
            plugin=self.plugin_config,
            collection="items",
            data={"name": "To Delete"},
        )

        deleted = PluginData.objects.remove_from_collection(
            "test_plugin",
            "items",
            record.id,
        )

        assert deleted is True
        assert PluginData.objects.filter(id=record.id).count() == 0

    def test_remove_nonexistent_returns_false(self):
        """Removing nonexistent item returns False."""
        deleted = PluginData.objects.remove_from_collection(
            "test_plugin",
            "items",
            99999,
        )
        assert deleted is False

    def test_clear_collection(self):
        """Can clear all items in a collection."""
        for i in range(3):
            PluginData.objects.create(
                plugin=self.plugin_config,
                collection="items",
                data={"name": f"Item {i}"},
            )

        count = PluginData.objects.clear_collection("test_plugin", "items")

        assert count == 3
        assert PluginData.objects.filter(
            plugin=self.plugin_config,
            collection="items",
        ).count() == 0
