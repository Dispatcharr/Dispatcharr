"""Plugin UI Schema - Type definitions and validation for plugin UI components.

This module defines the schema that plugins use to declare their UI:
- Navigation items (sidebar entries)
- Pages with components (forms, tables, cards, etc.)
- Data bindings and actions

Example plugin with UI:

    class Plugin:
        name = "Sports Calendar"
        version = "1.0.0"

        # Navigation item in sidebar
        navigation = {
            "label": "Sports Calendar",
            "icon": "calendar",
            "path": "/plugins/sports-calendar",
        }

        # Page definitions
        pages = {
            "main": {
                "title": "Sports Calendar",
                "components": [
                    {
                        "type": "tabs",
                        "items": [
                            {
                                "id": "calendars",
                                "label": "Calendars",
                                "components": [...]
                            },
                            {
                                "id": "events",
                                "label": "Events",
                                "components": [...]
                            }
                        ]
                    }
                ]
            }
        }

        def run(self, action, params, context):
            # Handle actions from UI
            pass
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union


# =============================================================================
# Navigation Schema
# =============================================================================

@dataclass
class PluginNavigation:
    """Navigation item that appears in the sidebar.

    Attributes:
        label: Display text in the sidebar
        icon: Icon name (uses Tabler icons, e.g., "calendar", "settings")
        path: Route path (auto-generated as /plugins/{plugin_key} if not specified)
        badge: Optional badge text/number to show
        position: Where to place in sidebar ("top", "bottom", or numeric order)
    """
    label: str
    icon: str = "puzzle"
    path: Optional[str] = None
    badge: Optional[Union[str, int]] = None
    position: Union[str, int] = "bottom"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "icon": self.icon,
            "path": self.path,
            "badge": self.badge,
            "position": self.position,
        }


# =============================================================================
# Component Types
# =============================================================================

class ComponentType(str, Enum):
    """Available UI component types."""

    # Layout components
    STACK = "stack"  # Vertical stack
    GROUP = "group"  # Horizontal group
    GRID = "grid"  # Grid layout
    CARD = "card"  # Card container
    TABS = "tabs"  # Tabbed interface
    ACCORDION = "accordion"  # Collapsible sections

    # Content components
    TEXT = "text"  # Text display
    TITLE = "title"  # Heading
    ALERT = "alert"  # Alert/notification
    BADGE = "badge"  # Badge
    IMAGE = "image"  # Image display
    DIVIDER = "divider"  # Horizontal divider

    # Interactive components
    BUTTON = "button"  # Action button
    FORM = "form"  # Form with fields
    TABLE = "table"  # Data table
    LIST = "list"  # List of items
    DRAG_DROP_LIST = "drag_drop_list"  # Reorderable list

    # Feedback components
    LOADING = "loading"  # Loading spinner
    EMPTY = "empty"  # Empty state
    MODAL = "modal"  # Modal dialog

    # Data display
    STAT = "stat"  # Statistic display
    PROGRESS = "progress"  # Progress bar
    TIMELINE = "timeline"  # Timeline


# =============================================================================
# Field Types (for forms)
# =============================================================================

class FieldType(str, Enum):
    """Available form field types."""

    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    EMAIL = "email"
    URL = "url"
    PASSWORD = "password"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    CHECKBOX = "checkbox"
    SWITCH = "switch"
    RADIO = "radio"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    COLOR = "color"
    FILE = "file"
    HIDDEN = "hidden"


# =============================================================================
# Component Schemas
# =============================================================================

@dataclass
class BaseComponent:
    """Base for all UI components."""
    type: str
    id: Optional[str] = None
    visible: Optional[Union[bool, str]] = True  # Can be a data binding expression
    style: Optional[Dict[str, Any]] = None
    className: Optional[str] = None


@dataclass
class TextComponent(BaseComponent):
    """Display text content.

    Example:
        {"type": "text", "content": "Hello World", "size": "lg", "weight": "bold"}
    """
    type: Literal["text"] = "text"
    content: str = ""
    size: Optional[str] = None  # xs, sm, md, lg, xl
    weight: Optional[str] = None  # normal, bold, 500, 600, etc.
    color: Optional[str] = None  # Mantine color
    align: Optional[str] = None  # left, center, right


@dataclass
class TitleComponent(BaseComponent):
    """Display a heading.

    Example:
        {"type": "title", "content": "Page Title", "order": 1}
    """
    type: Literal["title"] = "title"
    content: str = ""
    order: int = 1  # 1-6 for h1-h6


@dataclass
class AlertComponent(BaseComponent):
    """Display an alert message.

    Example:
        {"type": "alert", "title": "Warning", "message": "...", "color": "yellow"}
    """
    type: Literal["alert"] = "alert"
    title: Optional[str] = None
    message: str = ""
    color: str = "blue"  # blue, green, yellow, red, etc.
    icon: Optional[str] = None
    closable: bool = False


@dataclass
class ButtonComponent(BaseComponent):
    """Interactive button.

    Example:
        {"type": "button", "label": "Save", "action": "save_data", "color": "blue"}
    """
    type: Literal["button"] = "button"
    label: str = ""
    action: Optional[str] = None  # Action ID to trigger
    params: Optional[Dict[str, Any]] = None  # Params to pass to action
    color: str = "blue"
    variant: str = "filled"  # filled, outline, light, subtle
    size: str = "sm"
    icon: Optional[str] = None
    loading: Optional[str] = None  # Data binding for loading state
    disabled: Optional[Union[bool, str]] = False
    confirm: Optional[Dict[str, Any]] = None  # Confirmation dialog


@dataclass
class FormField:
    """Field definition for forms.

    Example:
        {"id": "name", "label": "Name", "type": "text", "required": True}
    """
    id: str
    label: str
    type: str = "text"
    placeholder: Optional[str] = None
    help_text: Optional[str] = None
    required: bool = False
    default: Any = None
    options: Optional[List[Dict[str, str]]] = None  # For select/radio
    min: Optional[float] = None  # For number
    max: Optional[float] = None
    step: Optional[float] = None
    min_length: Optional[int] = None  # For text
    max_length: Optional[int] = None
    pattern: Optional[str] = None  # Regex validation
    disabled: Optional[Union[bool, str]] = False
    visible: Optional[Union[bool, str]] = True


@dataclass
class FormComponent(BaseComponent):
    """Form with fields and submit action.

    Example:
        {
            "type": "form",
            "id": "add_calendar",
            "fields": [
                {"id": "name", "label": "Name", "type": "text", "required": True},
                {"id": "url", "label": "URL", "type": "url", "required": True}
            ],
            "submit_action": "add_calendar",
            "submit_label": "Add Calendar"
        }
    """
    type: Literal["form"] = "form"
    fields: List[Dict[str, Any]] = field(default_factory=list)
    submit_action: Optional[str] = None
    submit_label: str = "Submit"
    reset_on_submit: bool = True
    layout: str = "vertical"  # vertical, horizontal, inline


@dataclass
class TableColumn:
    """Column definition for tables.

    Example:
        {"id": "name", "label": "Name", "sortable": True}
    """
    id: str
    label: str
    sortable: bool = False
    width: Optional[str] = None
    align: str = "left"
    render: Optional[str] = None  # Custom render type: "badge", "date", "link", etc.


@dataclass
class TableAction:
    """Row action for tables.

    Example:
        {"id": "edit", "label": "Edit", "icon": "edit", "action": "edit_item"}
    """
    id: str
    label: str
    icon: Optional[str] = None
    action: str = ""
    color: str = "blue"
    confirm: Optional[Dict[str, Any]] = None


@dataclass
class TableComponent(BaseComponent):
    """Data table component.

    Example:
        {
            "type": "table",
            "id": "calendars_table",
            "data_source": "calendars",
            "columns": [
                {"id": "name", "label": "Name", "sortable": True},
                {"id": "url", "label": "URL"},
                {"id": "last_synced", "label": "Last Synced", "render": "datetime"}
            ],
            "row_actions": [
                {"id": "edit", "label": "Edit", "icon": "edit", "action": "edit_calendar"},
                {"id": "delete", "label": "Delete", "icon": "trash", "action": "delete_calendar", "color": "red"}
            ],
            "empty_message": "No calendars configured"
        }
    """
    type: Literal["table"] = "table"
    data_source: str = ""  # Key in plugin data store
    columns: List[Dict[str, Any]] = field(default_factory=list)
    row_actions: List[Dict[str, Any]] = field(default_factory=list)
    empty_message: str = "No data"
    searchable: bool = False
    search_fields: List[str] = field(default_factory=list)
    pagination: bool = True
    page_size: int = 10


@dataclass
class ListItem:
    """Item template for lists."""
    title: str = ""
    subtitle: Optional[str] = None
    icon: Optional[str] = None
    badge: Optional[str] = None
    actions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ListComponent(BaseComponent):
    """List component for displaying items.

    Example:
        {
            "type": "list",
            "data_source": "events",
            "item_template": {
                "title": "{{title}}",
                "subtitle": "{{start}} - {{calendar}}",
                "icon": "calendar-event"
            }
        }
    """
    type: Literal["list"] = "list"
    data_source: str = ""
    item_template: Dict[str, Any] = field(default_factory=dict)
    empty_message: str = "No items"
    max_items: Optional[int] = None


@dataclass
class DragDropListComponent(BaseComponent):
    """Reorderable list with drag and drop.

    Example:
        {
            "type": "drag_drop_list",
            "data_source": "calendars",
            "item_template": {"title": "{{name}}", "subtitle": "{{url}}"},
            "on_reorder": "reorder_calendars"
        }
    """
    type: Literal["drag_drop_list"] = "drag_drop_list"
    data_source: str = ""
    item_template: Dict[str, Any] = field(default_factory=dict)
    on_reorder: Optional[str] = None  # Action to call with new order
    handle_position: str = "left"  # left, right


@dataclass
class TabItem:
    """Tab definition."""
    id: str
    label: str
    icon: Optional[str] = None
    badge: Optional[Union[str, int]] = None
    components: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TabsComponent(BaseComponent):
    """Tabbed interface.

    Example:
        {
            "type": "tabs",
            "items": [
                {"id": "calendars", "label": "Calendars", "icon": "calendar", "components": [...]},
                {"id": "events", "label": "Events", "icon": "list", "components": [...]}
            ]
        }
    """
    type: Literal["tabs"] = "tabs"
    items: List[Dict[str, Any]] = field(default_factory=list)
    default_tab: Optional[str] = None
    orientation: str = "horizontal"  # horizontal, vertical
    variant: str = "default"  # default, outline, pills


@dataclass
class CardComponent(BaseComponent):
    """Card container.

    Example:
        {
            "type": "card",
            "title": "Calendars",
            "components": [...]
        }
    """
    type: Literal["card"] = "card"
    title: Optional[str] = None
    subtitle: Optional[str] = None
    components: List[Dict[str, Any]] = field(default_factory=list)
    padding: str = "md"
    shadow: str = "sm"
    withBorder: bool = True


@dataclass
class StackComponent(BaseComponent):
    """Vertical stack layout.

    Example:
        {
            "type": "stack",
            "gap": "md",
            "components": [...]
        }
    """
    type: Literal["stack"] = "stack"
    components: List[Dict[str, Any]] = field(default_factory=list)
    gap: str = "md"
    align: str = "stretch"  # stretch, center, flex-start, flex-end


@dataclass
class GroupComponent(BaseComponent):
    """Horizontal group layout.

    Example:
        {
            "type": "group",
            "gap": "md",
            "components": [...]
        }
    """
    type: Literal["group"] = "group"
    components: List[Dict[str, Any]] = field(default_factory=list)
    gap: str = "md"
    justify: str = "flex-start"  # flex-start, center, flex-end, space-between
    wrap: bool = True


@dataclass
class ModalComponent(BaseComponent):
    """Modal dialog (triggered by button action).

    Example:
        {
            "type": "modal",
            "id": "edit_calendar_modal",
            "title": "Edit Calendar",
            "components": [...]
        }
    """
    type: Literal["modal"] = "modal"
    title: str = ""
    components: List[Dict[str, Any]] = field(default_factory=list)
    size: str = "md"  # xs, sm, md, lg, xl
    centered: bool = True


@dataclass
class StatComponent(BaseComponent):
    """Statistic display.

    Example:
        {
            "type": "stat",
            "label": "Total Events",
            "value": "{{stats.total_events}}",
            "icon": "calendar-event"
        }
    """
    type: Literal["stat"] = "stat"
    label: str = ""
    value: str = ""  # Can use data binding: {{data.count}}
    description: Optional[str] = None
    icon: Optional[str] = None
    color: str = "blue"


# =============================================================================
# Page Schema
# =============================================================================

@dataclass
class PluginPage:
    """Definition of a plugin page.

    Example:
        {
            "title": "Sports Calendar",
            "description": "Manage your sports calendars and recordings",
            "components": [...]
        }
    """
    title: str
    description: Optional[str] = None
    components: List[Dict[str, Any]] = field(default_factory=list)
    modals: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "components": self.components,
            "modals": self.modals,
        }


# =============================================================================
# Data Model Schema
# =============================================================================

@dataclass
class DataField:
    """Field definition for plugin data models."""
    type: str  # string, number, boolean, datetime, json, array
    required: bool = False
    default: Any = None


@dataclass
class PluginDataModel:
    """Data model definition for persistence.

    Plugins can define data models that get stored in the database.
    Each model creates a collection that can be queried and modified.

    Example:
        {
            "calendars": {
                "fields": {
                    "name": {"type": "string", "required": True},
                    "url": {"type": "string", "required": True},
                    "enabled": {"type": "boolean", "default": True},
                    "last_synced": {"type": "datetime"}
                }
            }
        }
    """
    fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# =============================================================================
# Full Plugin UI Schema
# =============================================================================

@dataclass
class PluginUISchema:
    """Complete UI schema for a plugin.

    This is the top-level schema that defines everything a plugin
    needs for its UI: navigation, pages, and data models.
    """
    navigation: Optional[Dict[str, Any]] = None
    pages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    data_models: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_plugin(cls, plugin_instance: Any) -> "PluginUISchema":
        """Extract UI schema from a plugin instance."""
        return cls(
            navigation=getattr(plugin_instance, "navigation", None),
            pages=getattr(plugin_instance, "pages", {}),
            data_models=getattr(plugin_instance, "data_models", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "navigation": self.navigation,
            "pages": self.pages,
            "data_models": self.data_models,
        }


# =============================================================================
# Validation Functions
# =============================================================================

def validate_component(component: Dict[str, Any]) -> List[str]:
    """Validate a component definition.

    Returns a list of error messages (empty if valid).
    """
    errors = []

    if "type" not in component:
        errors.append("Component missing 'type' field")
        return errors

    comp_type = component["type"]

    # Validate specific component types
    if comp_type == "form":
        if "fields" not in component:
            errors.append("Form component missing 'fields'")
        elif not isinstance(component["fields"], list):
            errors.append("Form 'fields' must be a list")

    elif comp_type == "table":
        if "columns" not in component:
            errors.append("Table component missing 'columns'")
        if "data_source" not in component:
            errors.append("Table component missing 'data_source'")

    elif comp_type == "tabs":
        if "items" not in component:
            errors.append("Tabs component missing 'items'")
        elif not isinstance(component["items"], list):
            errors.append("Tabs 'items' must be a list")

    elif comp_type in ("stack", "group", "card"):
        if "components" not in component:
            errors.append(f"{comp_type.title()} component missing 'components'")

    elif comp_type == "button":
        if "label" not in component:
            errors.append("Button component missing 'label'")

    return errors


def validate_page(page: Dict[str, Any]) -> List[str]:
    """Validate a page definition."""
    errors = []

    if "components" not in page:
        errors.append("Page missing 'components'")
    elif not isinstance(page["components"], list):
        errors.append("Page 'components' must be a list")
    else:
        for i, comp in enumerate(page["components"]):
            comp_errors = validate_component(comp)
            for err in comp_errors:
                errors.append(f"Component {i}: {err}")

    return errors


def validate_navigation(nav: Dict[str, Any]) -> List[str]:
    """Validate navigation definition."""
    errors = []

    if "label" not in nav:
        errors.append("Navigation missing 'label'")

    return errors


def validate_ui_schema(schema: Dict[str, Any]) -> List[str]:
    """Validate a complete plugin UI schema."""
    errors = []

    if "navigation" in schema and schema["navigation"]:
        nav_errors = validate_navigation(schema["navigation"])
        for err in nav_errors:
            errors.append(f"Navigation: {err}")

    if "pages" in schema:
        for page_id, page in schema["pages"].items():
            page_errors = validate_page(page)
            for err in page_errors:
                errors.append(f"Page '{page_id}': {err}")

    return errors
