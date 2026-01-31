"""Tests for plugin UI schema validation."""

import pytest

from apps.plugins.ui_schema import (
    PluginNavigation,
    PluginPage,
    PluginUISchema,
    validate_component,
    validate_navigation,
    validate_page,
    validate_ui_schema,
)


class TestPluginNavigation:
    """Tests for PluginNavigation dataclass."""

    def test_basic_navigation(self):
        """Navigation with minimal required fields."""
        nav = PluginNavigation(label="Test Plugin")
        assert nav.label == "Test Plugin"
        assert nav.icon == "puzzle"  # default
        assert nav.path is None
        assert nav.position == "bottom"

    def test_navigation_to_dict(self):
        """Navigation converts to dict correctly."""
        nav = PluginNavigation(
            label="Sports Calendar",
            icon="calendar",
            path="/plugins/sports-calendar",
            badge=5,
            position="top",
        )
        result = nav.to_dict()

        assert result["label"] == "Sports Calendar"
        assert result["icon"] == "calendar"
        assert result["path"] == "/plugins/sports-calendar"
        assert result["badge"] == 5
        assert result["position"] == "top"


class TestPluginPage:
    """Tests for PluginPage dataclass."""

    def test_basic_page(self):
        """Page with minimal fields."""
        page = PluginPage(title="Test Page")
        assert page.title == "Test Page"
        assert page.description is None
        assert page.components == []

    def test_page_with_components(self):
        """Page with components."""
        page = PluginPage(
            title="My Page",
            description="A test page",
            components=[
                {"type": "text", "content": "Hello"},
                {"type": "button", "label": "Click me"},
            ],
        )
        assert len(page.components) == 2
        assert page.components[0]["type"] == "text"

    def test_page_to_dict(self):
        """Page converts to dict correctly."""
        page = PluginPage(
            title="Test",
            components=[{"type": "text", "content": "Hi"}],
        )
        result = page.to_dict()

        assert result["title"] == "Test"
        assert len(result["components"]) == 1


class TestPluginUISchema:
    """Tests for PluginUISchema dataclass."""

    def test_empty_schema(self):
        """Empty UI schema."""
        schema = PluginUISchema()
        assert schema.navigation is None
        assert schema.pages == {}
        assert schema.data_models == {}

    def test_from_plugin_basic(self):
        """Extract schema from basic plugin."""
        class MockPlugin:
            name = "Test"

        schema = PluginUISchema.from_plugin(MockPlugin())
        assert schema.navigation is None
        assert schema.pages == {}

    def test_from_plugin_with_ui(self):
        """Extract schema from plugin with UI definition."""
        class MockPlugin:
            name = "Test"
            navigation = {"label": "Test", "icon": "test"}
            pages = {
                "main": {"title": "Main", "components": []},
            }
            data_models = {
                "items": {"fields": {"name": {"type": "string"}}},
            }

        schema = PluginUISchema.from_plugin(MockPlugin())
        assert schema.navigation["label"] == "Test"
        assert "main" in schema.pages
        assert "items" in schema.data_models


class TestValidateComponent:
    """Tests for component validation."""

    def test_missing_type(self):
        """Component without type is invalid."""
        errors = validate_component({})
        assert len(errors) == 1
        assert "missing 'type'" in errors[0]

    def test_text_component_valid(self):
        """Valid text component."""
        errors = validate_component({"type": "text", "content": "Hello"})
        assert errors == []

    def test_button_missing_label(self):
        """Button without label is invalid."""
        errors = validate_component({"type": "button"})
        assert len(errors) == 1
        assert "missing 'label'" in errors[0]

    def test_button_valid(self):
        """Valid button component."""
        errors = validate_component({"type": "button", "label": "Click"})
        assert errors == []

    def test_form_missing_fields(self):
        """Form without fields is invalid."""
        errors = validate_component({"type": "form"})
        assert len(errors) == 1
        assert "missing 'fields'" in errors[0]

    def test_form_fields_not_list(self):
        """Form fields must be a list."""
        errors = validate_component({"type": "form", "fields": "invalid"})
        assert len(errors) == 1
        assert "must be a list" in errors[0]

    def test_form_valid(self):
        """Valid form component."""
        errors = validate_component({
            "type": "form",
            "fields": [
                {"id": "name", "label": "Name", "type": "text"},
            ],
        })
        assert errors == []

    def test_table_missing_columns(self):
        """Table without columns is invalid."""
        errors = validate_component({"type": "table", "data_source": "items"})
        assert len(errors) == 1
        assert "missing 'columns'" in errors[0]

    def test_table_missing_data_source(self):
        """Table without data_source is invalid."""
        errors = validate_component({"type": "table", "columns": []})
        assert len(errors) == 1
        assert "missing 'data_source'" in errors[0]

    def test_table_valid(self):
        """Valid table component."""
        errors = validate_component({
            "type": "table",
            "data_source": "items",
            "columns": [{"id": "name", "label": "Name"}],
        })
        assert errors == []

    def test_tabs_missing_items(self):
        """Tabs without items is invalid."""
        errors = validate_component({"type": "tabs"})
        assert len(errors) == 1
        assert "missing 'items'" in errors[0]

    def test_tabs_valid(self):
        """Valid tabs component."""
        errors = validate_component({
            "type": "tabs",
            "items": [
                {"id": "tab1", "label": "Tab 1", "components": []},
            ],
        })
        assert errors == []

    def test_stack_missing_components(self):
        """Stack without components is invalid."""
        errors = validate_component({"type": "stack"})
        assert len(errors) == 1
        assert "missing 'components'" in errors[0]

    def test_card_missing_components(self):
        """Card without components is invalid."""
        errors = validate_component({"type": "card"})
        assert len(errors) == 1
        assert "missing 'components'" in errors[0]


class TestValidatePage:
    """Tests for page validation."""

    def test_missing_components(self):
        """Page without components is invalid."""
        errors = validate_page({})
        assert len(errors) == 1
        assert "missing 'components'" in errors[0]

    def test_components_not_list(self):
        """Page components must be a list."""
        errors = validate_page({"components": "invalid"})
        assert len(errors) == 1
        assert "must be a list" in errors[0]

    def test_valid_page(self):
        """Valid page with components."""
        errors = validate_page({
            "title": "Test",
            "components": [
                {"type": "text", "content": "Hello"},
            ],
        })
        assert errors == []

    def test_invalid_component_in_page(self):
        """Invalid component inside page is reported."""
        errors = validate_page({
            "components": [
                {"type": "button"},  # Missing label
            ],
        })
        assert len(errors) == 1
        assert "Component 0" in errors[0]


class TestValidateNavigation:
    """Tests for navigation validation."""

    def test_missing_label(self):
        """Navigation without label is invalid."""
        errors = validate_navigation({})
        assert len(errors) == 1
        assert "missing 'label'" in errors[0]

    def test_valid_navigation(self):
        """Valid navigation."""
        errors = validate_navigation({"label": "Test"})
        assert errors == []


class TestValidateUISchema:
    """Tests for full UI schema validation."""

    def test_empty_schema(self):
        """Empty schema is valid."""
        errors = validate_ui_schema({})
        assert errors == []

    def test_invalid_navigation(self):
        """Invalid navigation is reported."""
        errors = validate_ui_schema({"navigation": {}})
        assert len(errors) == 1
        assert "Navigation" in errors[0]

    def test_invalid_page(self):
        """Invalid page is reported."""
        errors = validate_ui_schema({
            "pages": {
                "main": {},  # Missing components
            },
        })
        assert len(errors) == 1
        assert "Page 'main'" in errors[0]

    def test_valid_full_schema(self):
        """Full valid schema."""
        errors = validate_ui_schema({
            "navigation": {
                "label": "Sports Calendar",
                "icon": "calendar",
            },
            "pages": {
                "main": {
                    "title": "Sports Calendar",
                    "components": [
                        {
                            "type": "tabs",
                            "items": [
                                {
                                    "id": "calendars",
                                    "label": "Calendars",
                                    "components": [
                                        {
                                            "type": "table",
                                            "data_source": "calendars",
                                            "columns": [
                                                {"id": "name", "label": "Name"},
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            },
        })
        assert errors == []
