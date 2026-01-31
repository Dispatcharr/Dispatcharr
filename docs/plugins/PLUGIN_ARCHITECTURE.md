# Dispatcharr Plugin Architecture

> **README-Driven Development**: This document describes the target plugin architecture. Features marked with checkboxes indicate implementation status.

## Overview

Dispatcharr's plugin system allows developers to extend the application with custom functionality. Plugins can:

- [x] Define configuration settings rendered in the UI
- [x] Provide action buttons that trigger backend code
- [x] Persist data in the database (new: `PluginData` model)
- [x] Add navigation items to the sidebar
- [x] Provide custom pages with rich UI components
- [x] Use forms, tables, drag-and-drop, and other interactive elements

## Compatibility

The new plugin system is **fully backwards compatible**. Existing plugins that use `fields`, `actions`, and `run()` will continue to work without modification. New features are opt-in.

## Quick Start

### Minimal Plugin (Legacy Style)

This is the simplest plugin, compatible with all versions:

```python
# /data/plugins/my_plugin/plugin.py

class Plugin:
    name = "My Plugin"
    version = "1.0.0"
    description = "A simple plugin"

    fields = [
        {"id": "enabled", "label": "Enabled", "type": "boolean", "default": True},
    ]

    actions = [
        {"id": "run_task", "label": "Run Task", "description": "Execute the main task"},
    ]

    def run(self, action: str, params: dict, context: dict) -> dict:
        if action == "run_task":
            return {"status": "ok", "message": "Task completed!"}
        return {"status": "error", "message": f"Unknown action: {action}"}
```

### Enhanced Plugin (With Custom UI)

Plugins can now define their own navigation items and rich UI pages:

```python
# /data/plugins/sports_calendar/plugin.py

class Plugin:
    name = "Sports Calendar"
    version = "2.0.0"
    description = "Automatic sports recording from ICS calendars"

    # Add a navigation item to the sidebar
    navigation = {
        "label": "Sports Calendar",
        "icon": "calendar",           # Tabler icon name
        "position": "bottom",         # "top", "bottom", or numeric order
    }

    # Define custom pages
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
                            "icon": "calendar",
                            "components": [
                                {
                                    "type": "card",
                                    "title": "Add Calendar",
                                    "components": [
                                        {
                                            "type": "form",
                                            "id": "add_calendar_form",
                                            "fields": [
                                                {"id": "name", "label": "Calendar Name", "type": "text", "required": True},
                                                {"id": "url", "label": "ICS URL", "type": "url", "required": True},
                                            ],
                                            "submit_action": "add_calendar",
                                            "submit_label": "Add Calendar",
                                        }
                                    ]
                                },
                                {
                                    "type": "table",
                                    "id": "calendars_table",
                                    "data_source": "calendars",  # Collection name
                                    "columns": [
                                        {"id": "name", "label": "Name"},
                                        {"id": "url", "label": "URL"},
                                        {"id": "last_synced", "label": "Last Synced", "render": "datetime"},
                                    ],
                                    "row_actions": [
                                        {"id": "sync", "label": "Sync", "icon": "refresh", "action": "sync_calendar"},
                                        {"id": "delete", "label": "Delete", "icon": "trash", "action": "delete_calendar", "color": "red", "confirm": True},
                                    ],
                                }
                            ]
                        },
                        {
                            "id": "events",
                            "label": "Events",
                            "icon": "list",
                            "components": [
                                {
                                    "type": "table",
                                    "data_source": "events",
                                    "columns": [
                                        {"id": "title", "label": "Event"},
                                        {"id": "calendar", "label": "Calendar"},
                                        {"id": "start", "label": "Start Time", "render": "datetime"},
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }

    def run(self, action: str, params: dict, context: dict) -> dict:
        if action == "add_calendar":
            return self._add_calendar(params, context)
        if action == "sync_calendar":
            return self._sync_calendar(params, context)
        # ... more actions
        return {"status": "error", "message": f"Unknown action: {action}"}
```

## Plugin Structure

### Required Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Human-readable plugin name |
| `run()` | `method` | Entry point for executing actions |

### Optional Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `version` | `str` | Semantic version (e.g., "1.0.0") |
| `description` | `str` | Brief description |
| `fields` | `list` | Settings fields for the legacy UI |
| `actions` | `list` | Action buttons for the legacy UI |
| `navigation` | `dict` | Sidebar navigation item |
| `pages` | `dict` | Custom page definitions |

## Settings Fields

Fields define configuration options rendered in the plugin UI:

```python
fields = [
    {
        "id": "api_key",           # Unique identifier (used in settings dict)
        "label": "API Key",         # Display label
        "type": "string",           # Field type
        "default": "",              # Default value
        "help_text": "Enter your API key",  # Help text shown below field
        "required": False,          # Whether field is required
    },
]
```

### Supported Field Types

| Type | Description | Extra Options |
|------|-------------|---------------|
| `boolean` | Toggle switch | - |
| `number` | Numeric input | `min`, `max`, `step` |
| `string` | Text input | `placeholder`, `max_length` |
| `select` | Dropdown | `options: [{value, label}]` |

## Actions

Actions appear as buttons that trigger backend code:

```python
actions = [
    {
        "id": "sync_all",
        "label": "Sync All",
        "description": "Sync all calendars",
        "confirm": {                          # Optional confirmation dialog
            "required": True,
            "title": "Confirm Sync",
            "message": "This will sync all calendars. Continue?",
        },
    },
]
```

## The `run()` Method

The `run()` method is called when an action is triggered:

```python
def run(self, action: str, params: dict, context: dict) -> dict:
    """
    Execute a plugin action.

    Args:
        action: The action ID (e.g., "sync_all")
        params: Parameters from the request (e.g., row data for table actions)
        context: Runtime context containing:
            - settings: Persisted plugin settings
            - logger: Configured logger instance
            - actions: Dict mapping action IDs to definitions

    Returns:
        Dict with at least a "status" key:
        - {"status": "ok", "message": "Success"}
        - {"status": "error", "message": "What went wrong"}
        - {"status": "queued", "message": "Background task started"}
    """
```

## Navigation Items

Plugins can add items to the sidebar:

```python
navigation = {
    "label": "My Plugin",           # Required: display text
    "icon": "puzzle",               # Optional: Tabler icon name (default: "puzzle")
    "path": "/plugins/my_plugin",   # Optional: auto-generated if not specified
    "badge": 5,                     # Optional: badge count/text
    "position": "bottom",           # Optional: "top", "bottom", or numeric
}
```

When a user clicks the navigation item, they're taken to the plugin's custom page.

## Custom Pages (UI Schema)

Pages are defined using a declarative JSON schema. The frontend renders Mantine components based on this schema.

### Page Structure

```python
pages = {
    "main": {                       # Page ID (currently only "main" is supported)
        "title": "Page Title",
        "description": "Optional description",
        "components": [             # List of UI components
            # ... component definitions
        ],
    }
}
```

### Available Components

#### Layout Components

**Stack** - Vertical layout
```python
{"type": "stack", "gap": "md", "components": [...]}
```

**Group** - Horizontal layout
```python
{"type": "group", "gap": "md", "justify": "space-between", "components": [...]}
```

**Card** - Container with optional title
```python
{"type": "card", "title": "Section Title", "components": [...]}
```

**Tabs** - Tabbed interface
```python
{
    "type": "tabs",
    "items": [
        {"id": "tab1", "label": "Tab 1", "icon": "home", "components": [...]},
        {"id": "tab2", "label": "Tab 2", "components": [...]},
    ]
}
```

#### Content Components

**Text** - Display text
```python
{"type": "text", "content": "Hello World", "size": "lg", "weight": "bold"}
```

**Title** - Heading
```python
{"type": "title", "content": "Section Title", "order": 2}  # h2
```

**Alert** - Notification banner
```python
{"type": "alert", "title": "Warning", "message": "Something happened", "color": "yellow"}
```

**Button** - Action trigger
```python
{
    "type": "button",
    "label": "Click Me",
    "action": "do_something",
    "color": "blue",
    "variant": "filled",
}
```

#### Data Components

**Form** - Input form
```python
{
    "type": "form",
    "id": "my_form",
    "fields": [
        {"id": "name", "label": "Name", "type": "text", "required": True},
        {"id": "email", "label": "Email", "type": "email"},
    ],
    "submit_action": "save_data",
    "submit_label": "Save",
}
```

**Table** - Data table with actions
```python
{
    "type": "table",
    "data_source": "items",         # Collection name in PluginData
    "columns": [
        {"id": "name", "label": "Name", "sortable": True},
        {"id": "created_at", "label": "Created", "render": "datetime"},
    ],
    "row_actions": [
        {"id": "edit", "label": "Edit", "icon": "edit", "action": "edit_item"},
        {"id": "delete", "label": "Delete", "icon": "trash", "action": "delete_item", "color": "red"},
    ],
    "searchable": True,
    "pagination": True,
}
```

**List** - Simple list display
```python
{
    "type": "list",
    "data_source": "events",
    "item_template": {
        "title": "{{title}}",
        "subtitle": "{{start}} - {{calendar}}",
    }
}
```

**DragDropList** - Reorderable list with drag-and-drop
```python
{
    "type": "drag_drop_list",
    "data_source": "priorities",
    "item_template": {
        "title": "{{name}}",
        "subtitle": "{{description}}",
        "badge": "{{status}}",
    },
    "on_reorder": "update_order",
    "order_field": "order",  # Default: "order" - field used for sorting
    "actions": [
        {"id": "edit", "label": "Edit", "icon": "edit", "action": "edit_item"},
        {"id": "delete", "label": "Delete", "icon": "trash", "action": "delete_item", "color": "red"},
    ],
    "empty_message": "No items to display",
}
```

When items are reordered via drag-and-drop, the `on_reorder` action is called with:
```python
params = {
    "items": [
        {"_id": "123", "order": 0},
        {"_id": "456", "order": 1},
        # ... new order for all items
    ],
    "moved_item_id": "123",
    "from_index": 2,
    "to_index": 0,
}
```

## Data Persistence

Plugins can store data in the database using the `PluginData` model:

### Using the Data API (Recommended)

From your plugin's `run()` method:

```python
from apps.plugins.models import PluginData

def run(self, action: str, params: dict, context: dict) -> dict:
    plugin_key = "my_plugin"

    # Add item to collection
    record = PluginData.objects.add_to_collection(
        plugin_key, "calendars",
        {"name": "Work Calendar", "url": "https://..."}
    )

    # Get all items
    calendars = PluginData.objects.get_collection_data(plugin_key, "calendars")
    # Returns: [{"_id": 1, "name": "Work Calendar", "url": "..."}, ...]

    # Update item
    PluginData.objects.update_in_collection(
        plugin_key, "calendars", record.id,
        {"name": "Updated Name", "url": "..."}
    )

    # Delete item
    PluginData.objects.remove_from_collection(plugin_key, "calendars", record.id)

    # Clear entire collection
    PluginData.objects.clear_collection(plugin_key, "calendars")
```

### REST API Endpoints

Data is also accessible via REST API:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/plugins/{key}/data/{collection}/` | List collection |
| POST | `/api/plugins/{key}/data/{collection}/` | Add to collection |
| DELETE | `/api/plugins/{key}/data/{collection}/` | Clear collection |
| GET | `/api/plugins/{key}/data/{collection}/{id}/` | Get item |
| PUT | `/api/plugins/{key}/data/{collection}/{id}/` | Replace item |
| PATCH | `/api/plugins/{key}/data/{collection}/{id}/` | Update item |
| DELETE | `/api/plugins/{key}/data/{collection}/{id}/` | Delete item |
| PUT | `/api/plugins/{key}/data/{collection}/bulk/` | Replace collection |

### Data Binding in UI

Tables and lists automatically fetch from `data_source`:

```python
{
    "type": "table",
    "data_source": "calendars",  # Fetches from PluginData collection
    ...
}
```

When a row action is triggered, the row's `_id` is passed in `params`:

```python
def run(self, action: str, params: dict, context: dict) -> dict:
    if action == "delete_calendar":
        calendar_id = params.get("_id")
        PluginData.objects.remove_from_collection(
            "sports_calendar", "calendars", calendar_id
        )
        return {"status": "ok", "message": "Calendar deleted"}
```

## Background Tasks

For long-running operations, use Celery tasks:

```python
from celery import shared_task

@shared_task
def sync_calendars_task(plugin_key: str):
    # Long-running work here
    pass

class Plugin:
    def run(self, action: str, params: dict, context: dict) -> dict:
        if action == "sync_all":
            task = sync_calendars_task.delay("sports_calendar")
            return {
                "status": "queued",
                "message": f"Sync started (task: {task.id[:8]}...)",
            }
```

## Accessing Django Models

Plugins have full access to Django models:

```python
from apps.channels.models import Channel, ChannelGroup
from apps.epg.models import EPGSource, Programme
from apps.m3u.models import M3UAccount
from core.models import StreamProfile

class Plugin:
    def run(self, action: str, params: dict, context: dict) -> dict:
        # Query channels
        channels = Channel.objects.filter(channel_group__name="Sports")

        # Create recordings
        from apps.channels.models import Recording
        Recording.objects.create(
            channel=channel,
            start_time=start,
            end_time=end,
            title="Game Recording",
        )
```

## WebSocket Updates

Send real-time updates to the frontend:

```python
from core.utils import send_websocket_update

def run(self, action: str, params: dict, context: dict) -> dict:
    # ... do work ...

    # Notify frontend
    send_websocket_update("updates", "update", {
        "type": "plugin",
        "plugin": "my_plugin",
        "message": "Sync completed",
    })

    return {"status": "ok"}
```

## Best Practices

### 1. Keep `run()` Fast

Dispatch heavy work to Celery tasks:

```python
def run(self, action: str, params: dict, context: dict) -> dict:
    if action == "heavy_task":
        my_task.delay()  # Return immediately
        return {"status": "queued", "message": "Task started"}
```

### 2. Use Transactions for Data Integrity

```python
from django.db import transaction

def run(self, action: str, params: dict, context: dict) -> dict:
    with transaction.atomic():
        # Multiple database operations
        pass
```

### 3. Validate Input

```python
def run(self, action: str, params: dict, context: dict) -> dict:
    url = params.get("url", "").strip()
    if not url:
        return {"status": "error", "message": "URL is required"}
    if not url.startswith(("http://", "https://")):
        return {"status": "error", "message": "Invalid URL format"}
```

### 4. Use the Logger

```python
def run(self, action: str, params: dict, context: dict) -> dict:
    logger = context.get("logger")
    logger.info("Starting sync for %s", calendar_name)
```

### 5. Handle Errors Gracefully

```python
def run(self, action: str, params: dict, context: dict) -> dict:
    try:
        result = self._do_work()
        return {"status": "ok", "data": result}
    except requests.RequestException as e:
        return {"status": "error", "message": f"Network error: {e}"}
    except Exception as e:
        context.get("logger").exception("Unexpected error")
        return {"status": "error", "message": str(e)}
```

## File Structure

```
/data/plugins/
└── my_plugin/
    ├── plugin.py          # Required: Plugin class
    ├── tasks.py           # Optional: Celery tasks
    ├── __init__.py        # Optional: Package init
    └── vendor/            # Optional: Vendored dependencies
```

## Installation

1. Create plugin directory: `/data/plugins/my_plugin/`
2. Add `plugin.py` with a `Plugin` class
3. In Dispatcharr UI, go to Plugins page
4. Click "Reload" to discover new plugin
5. Enable the plugin using the toggle

Or import via ZIP:
1. Create a ZIP file containing your plugin folder
2. Go to Plugins page → Import
3. Upload the ZIP file

## Implementation Status

### Completed
- [x] Plugin discovery and loading
- [x] Settings fields and persistence
- [x] Action buttons and execution
- [x] Plugin data persistence (`PluginData` model)
- [x] Data CRUD REST API
- [x] UI schema type definitions
- [x] Plugin system code refactoring (modular architecture)
- [x] Navigation item registration
- [x] Navigation API endpoint (`GET /api/plugins/navigation/`)
- [x] Plugin page routing (`/plugins/:key`, `/plugins/:key/:pageId`)
- [x] Page schema API endpoint (`GET /api/plugins/:key/page/`)
- [x] UI schema renderer (PluginRenderer component)
- [x] Layout components (Stack, Group, Card, Tabs)
- [x] Content components (Title, Text, Alert, Badge, Button, Divider)
- [x] Form component with validation and action submission
- [x] Table component with search, sort, pagination, row actions
- [x] List component with item templates
- [x] Modal support in renderer
- [x] Drag-and-drop list component with @dnd-kit

### TODO
- [ ] Example plugin using new UI system
- [ ] Frontend WebSocket integration for live data updates
- [ ] Additional field types (date, time, color pickers)

## API Reference

### Plugin Manager

```python
from apps.plugins.loader import PluginManager

pm = PluginManager.get()
pm.discover_plugins()
pm.run_action("my_plugin", "do_work", {"param": "value"})
pm.update_settings("my_plugin", {"key": "value"})
```

### Plugin Data Manager

```python
from apps.plugins.models import PluginData

# Collection operations
PluginData.objects.get_collection(plugin_key, collection)
PluginData.objects.get_collection_data(plugin_key, collection)
PluginData.objects.set_collection(plugin_key, collection, data_list)
PluginData.objects.add_to_collection(plugin_key, collection, data)
PluginData.objects.update_in_collection(plugin_key, collection, id, data)
PluginData.objects.remove_from_collection(plugin_key, collection, id)
PluginData.objects.clear_collection(plugin_key, collection)
```

---

*This document is maintained as part of the Dispatcharr project. For the latest version, see the repository.*
