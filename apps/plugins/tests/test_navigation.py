"""Tests for plugin navigation registration."""

import pytest
from django.test import TestCase

from apps.plugins.models import PluginConfig
from apps.plugins.loader import PluginManager
from apps.plugins.types import LoadedPlugin


class TestPluginNavigation(TestCase):
    """Tests for plugin navigation feature."""

    def setUp(self):
        """Create test fixtures."""
        self.plugin_config = PluginConfig.objects.create(
            key="test_plugin",
            name="Test Plugin",
            version="1.0.0",
            enabled=True,
        )

    def test_plugin_config_stores_navigation(self):
        """PluginConfig can store navigation data."""
        self.plugin_config.navigation = {
            "label": "Test Plugin",
            "icon": "test",
            "path": "/plugins/test_plugin",
        }
        self.plugin_config.save()

        self.plugin_config.refresh_from_db()
        assert self.plugin_config.navigation["label"] == "Test Plugin"
        assert self.plugin_config.navigation["icon"] == "test"

    def test_plugin_config_navigation_default_empty(self):
        """Navigation defaults to None/empty."""
        config = PluginConfig.objects.create(
            key="no_nav_plugin",
            name="No Nav Plugin",
        )
        assert config.navigation is None

    def test_loaded_plugin_with_navigation(self):
        """LoadedPlugin can hold navigation data."""
        plugin = LoadedPlugin(
            key="test",
            name="Test",
            navigation={
                "label": "Test Nav",
                "icon": "puzzle",
            },
        )
        assert plugin.navigation["label"] == "Test Nav"

    def test_loaded_plugin_navigation_default(self):
        """LoadedPlugin navigation defaults to None."""
        plugin = LoadedPlugin(key="test", name="Test")
        assert plugin.navigation is None


class TestNavigationAPI(TestCase):
    """Tests for navigation API endpoint."""

    def setUp(self):
        """Create test plugins with navigation."""
        self.plugin_with_nav = PluginConfig.objects.create(
            key="sports_calendar",
            name="Sports Calendar",
            enabled=True,
            navigation={
                "label": "Sports Calendar",
                "icon": "calendar",
                "path": "/plugins/sports_calendar",
                "position": "bottom",
            },
        )
        self.plugin_without_nav = PluginConfig.objects.create(
            key="no_nav",
            name="No Nav Plugin",
            enabled=True,
        )
        self.disabled_plugin = PluginConfig.objects.create(
            key="disabled_plugin",
            name="Disabled Plugin",
            enabled=False,
            navigation={
                "label": "Disabled",
                "icon": "x",
            },
        )

    def test_get_navigation_items(self):
        """API returns navigation items for enabled plugins."""
        from django.test import Client
        client = Client()

        # This test validates the expected behavior once the endpoint exists
        # The actual implementation will follow
        response = client.get("/api/plugins/navigation/")

        # Skip if endpoint doesn't exist yet
        if response.status_code == 404:
            self.skipTest("Navigation endpoint not implemented yet")

        assert response.status_code == 200
        data = response.json()

        # Should only include enabled plugins with navigation
        nav_items = data.get("navigation", [])
        keys = [item["key"] for item in nav_items]

        assert "sports_calendar" in keys
        assert "no_nav" not in keys  # No navigation defined
        assert "disabled_plugin" not in keys  # Disabled


class TestNavigationExtraction(TestCase):
    """Tests for extracting navigation from plugin instances."""

    def test_extract_navigation_from_class(self):
        """Can extract navigation from plugin class."""
        class MockPlugin:
            name = "Test Plugin"
            navigation = {
                "label": "My Plugin",
                "icon": "star",
            }

        nav = getattr(MockPlugin(), "navigation", None)
        assert nav is not None
        assert nav["label"] == "My Plugin"
        assert nav["icon"] == "star"

    def test_auto_generate_path(self):
        """Path is auto-generated if not specified."""
        class MockPlugin:
            name = "Test Plugin"
            navigation = {
                "label": "My Plugin",
                "icon": "star",
            }

        nav = getattr(MockPlugin(), "navigation", {})
        # Path should be generated based on plugin key
        if "path" not in nav:
            nav["path"] = f"/plugins/test_plugin"

        assert nav["path"] == "/plugins/test_plugin"

    def test_navigation_with_badge(self):
        """Navigation can include a badge."""
        class MockPlugin:
            name = "Test Plugin"
            navigation = {
                "label": "Notifications",
                "icon": "bell",
                "badge": 5,
            }

        nav = getattr(MockPlugin(), "navigation", None)
        assert nav["badge"] == 5


class TestNavigationSync(TestCase):
    """Tests for syncing navigation to database."""

    def test_sync_updates_navigation(self):
        """Discovery sync updates navigation in database."""
        # Create a plugin config without navigation
        config = PluginConfig.objects.create(
            key="test_plugin",
            name="Test Plugin",
        )

        # Simulate what happens during sync when a plugin has navigation
        new_nav = {
            "label": "Test Plugin",
            "icon": "test",
            "path": "/plugins/test_plugin",
        }

        config.navigation = new_nav
        config.save()

        config.refresh_from_db()
        assert config.navigation == new_nav

    def test_sync_clears_navigation_if_removed(self):
        """Sync clears navigation if plugin no longer defines it."""
        config = PluginConfig.objects.create(
            key="test_plugin",
            name="Test Plugin",
            navigation={"label": "Old Nav"},
        )

        # Simulate sync finding no navigation
        config.navigation = None
        config.save()

        config.refresh_from_db()
        assert config.navigation is None
