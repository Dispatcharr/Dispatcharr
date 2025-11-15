# Dispatcharr Plugin System - Basic Plugin Development Guide

## Table of Contents

1. [Introduction](#introduction)
2. [What is a Basic Plugin?](#what-is-a-basic-plugin)
3. [Plugin Structure](#plugin-structure)
4. [Creating Your First Plugin](#creating-your-first-plugin)
5. [Plugin Class Reference](#plugin-class-reference)
6. [Settings Fields](#settings-fields)
7. [Organizing Settings with Sections](#organizing-settings-with-sections)
8. [Plugin Actions](#plugin-actions)
9. [Accessing Dispatcharr APIs](#accessing-dispatcharr-apis)
10. [Testing Your Plugin](#testing-your-plugin)
11. [Packaging and Distribution](#packaging-and-distribution)
12. [Best Practices](#best-practices)
13. [Examples](#examples)

---

## Introduction

This guide will teach you how to create **Basic Plugins** for Dispatcharr. Basic plugins are Python-based extensions that integrate into the Settings page and provide configurable settings and executable actions.

**Prerequisites:**

- Basic Python programming knowledge
- Understanding of the Dispatcharr application
- Access to a Dispatcharr development or test environment

**What You'll Learn:**

- How to structure a basic plugin
- How to define settings fields with different types
- How to organize settings into collapsible sections
- How to create executable actions
- How to access Dispatcharr's internal APIs and models
- How to package and distribute your plugin

---

## What is a Basic Plugin?

**Basic Plugins** are plugins that:

- Appear in the **Settings page accordion** when enabled
- Do **not** have a dedicated navigation menu item
- Are ideal for simple utilities, background tasks, and integrations
- Have settings and actions accessed from the Settings page

**Use Cases:**

- Data refresh utilities
- Batch processing tools
- Simple integrations with external services
- Background automation tasks
- Maintenance and cleanup utilities

**Comparison with Advanced Plugins:**

- Basic plugins use `navigation = False` (or omit the navigation attribute)
- Advanced plugins use `navigation = True` and get a dedicated page in the sidebar

---

## Plugin Structure

### Directory Structure

A basic plugin lives in a directory under `/app/data/plugins/` (inside the container):

```
/app/data/plugins/
└── my_plugin/
    ├── plugin.py          # Required: Main plugin file
    ├── __init__.py        # Optional: Makes it a Python package
    ├── helpers.py         # Optional: Helper functions
    └── README.md          # Optional: Plugin documentation
```

### Minimum Requirements

At minimum, your plugin needs:

1. A directory under `/app/data/plugins/`
2. A `plugin.py` file exporting a `Plugin` class

**Important Naming Rules:**

- Directory name becomes the plugin key (lowercased, spaces → underscores)
- Example: `My Plugin` directory → `my_plugin` key
- Avoid special characters in directory names

---

## Creating Your First Plugin

Let's create a simple "Hello World" plugin step by step.

### Step 1: Create the Plugin Directory

```bash
# Inside the Dispatcharr container or mounted volume
mkdir -p /app/data/plugins/hello_world
```

### Step 2: Create plugin.py

Create `/app/data/plugins/hello_world/plugin.py`:

```python
class Plugin:
    name = "Hello World"
    version = "1.0.0"
    description = "A simple example plugin"

    # Define settings fields
    fields = [
        {
            "id": "greeting",
            "label": "Greeting Message",
            "type": "string",
            "default": "Hello",
            "help_text": "The greeting to display"
        },
        {
            "id": "enabled",
            "label": "Enable Greeting",
            "type": "boolean",
            "default": True
        }
    ]

    # Define actions
    actions = [
        {
            "id": "say_hello",
            "label": "Say Hello",
            "description": "Prints a greeting message"
        }
    ]

    def run(self, action: str, params: dict, context: dict):
        """
        Called when a user clicks an action button

        Args:
            action: The action ID that was triggered
            params: Parameters passed from the UI (currently unused)
            context: Context object with settings, logger, etc.

        Returns:
            dict: Result object with status and message
        """
        settings = context.get("settings", {})
        logger = context.get("logger")

        if action == "say_hello":
            greeting = settings.get("greeting", "Hello")
            enabled = settings.get("enabled", True)

            if not enabled:
                return {
                    "status": "error",
                    "message": "Greeting is disabled in settings"
                }

            message = f"{greeting}, World!"
            logger.info(f"Hello World Plugin: {message}")

            return {
                "status": "success",
                "message": message
            }

        return {
            "status": "error",
            "message": f"Unknown action: {action}"
        }
```

### Step 3: Load the Plugin

1. Open the Dispatcharr UI
2. Navigate to the **Plugins** page
3. Click the **Reload** button (refresh icon)
4. Your "Hello World" plugin should appear
5. Enable the plugin using the toggle switch
6. Navigate to **Settings** page
7. Find the "Hello World" accordion section
8. Configure settings and click "Say Hello" action

---

## Plugin Class Reference

### Required Attributes

```python
class Plugin:
    name = "My Plugin Name"           # Required: Human-readable name
    version = "1.0.0"                 # Required: Semantic version string
    description = "What it does"      # Required: Short description
```

### Optional Attributes

```python
class Plugin:
    fields = []      # Optional: List of settings field definitions
    actions = []     # Optional: List of action definitions
    navigation = False  # Optional: Set to False for basic plugins (default)
```

### Required Methods

```python
def run(self, action: str, params: dict, context: dict) -> dict:
    """
    Called when a user triggers an action

    Args:
        action (str): The action ID that was triggered
        params (dict): Parameters from the UI (reserved for future use)
        context (dict): Context object containing:
            - settings (dict): Current plugin settings
            - logger (Logger): Pre-configured logger instance
            - actions (dict): Dictionary of action definitions

    Returns:
        dict: Result object with keys:
            - status (str): "success" or "error"
            - message (str): Human-readable message
            - file (str, optional): Path to output file
            - data (any, optional): Additional data to return
    """
    pass
```

---

## Settings Fields

Settings fields define the configuration UI for your plugin. Each field is a dictionary with specific keys.

### Field Structure

```python
{
    "id": "field_name",           # Required: Unique field identifier
    "label": "Field Label",       # Required: Display label
    "type": "string",             # Required: Field type
    "default": "default_value",   # Optional: Default value
    "help_text": "Helper text",   # Optional: Description shown below field
    "section": "Section Name",    # Optional: Group into collapsible section
    "options": []                 # Required for 'select' type only
}
```

### Supported Field Types

#### 1. String (Text Input)

```python
{
    "id": "api_key",
    "label": "API Key",
    "type": "string",
    "default": "",
    "help_text": "Enter your API key from the service provider"
}
```

**Renders as:** Text input field

#### 2. Number (Numeric Input)

```python
{
    "id": "max_items",
    "label": "Maximum Items",
    "type": "number",
    "default": 100,
    "help_text": "Maximum number of items to process"
}
```

**Renders as:** Number input field with increment/decrement buttons

#### 3. Boolean (Toggle Switch)

```python
{
    "id": "enabled",
    "label": "Enable Feature",
    "type": "boolean",
    "default": True,
    "help_text": "Enable or disable this feature"
}
```

**Renders as:** Toggle switch (on/off)

#### 4. Select (Dropdown)

```python
{
    "id": "mode",
    "label": "Processing Mode",
    "type": "select",
    "default": "normal",
    "help_text": "Select the processing mode",
    "options": [
        {"value": "fast", "label": "Fast Mode"},
        {"value": "normal", "label": "Normal Mode"},
        {"value": "thorough", "label": "Thorough Mode"}
    ]
}
```

**Renders as:** Dropdown menu with predefined options

**Note:** The `options` key is required for select fields. Each option must have `value` and `label` keys.

### Accessing Settings in Your Plugin

Settings are automatically saved when users change them. Access them in your `run` method:

```python
def run(self, action: str, params: dict, context: dict):
    settings = context.get("settings", {})

    # Access individual settings
    api_key = settings.get("api_key", "")
    max_items = settings.get("max_items", 100)
    enabled = settings.get("enabled", True)
    mode = settings.get("mode", "normal")

    # Use the settings
    if not enabled:
        return {"status": "error", "message": "Feature is disabled"}

    # ... rest of your logic
```

---

## Organizing Settings with Sections

For plugins with many settings, you can organize them into **collapsible sections** using the `section` attribute.

### Why Use Sections?

- **Better Organization:** Group related settings together
- **Improved UX:** Users can collapse sections they don't need
- **Cleaner Interface:** Reduces visual clutter for complex plugins

### How to Use Sections

Add a `section` attribute to your field definitions:

```python
fields = [
    # Unsectioned fields (appear at the top)
    {
        "id": "enabled",
        "label": "Enable Plugin",
        "type": "boolean",
        "default": True
    },

    # General section
    {
        "id": "api_key",
        "label": "API Key",
        "type": "string",
        "default": "",
        "section": "General"
    },
    {
        "id": "api_url",
        "label": "API URL",
        "type": "string",
        "default": "https://api.example.com",
        "section": "General"
    },

    # Advanced section
    {
        "id": "timeout",
        "label": "Request Timeout",
        "type": "number",
        "default": 30,
        "section": "Advanced"
    },
    {
        "id": "retry_count",
        "label": "Retry Count",
        "type": "number",
        "default": 3,
        "section": "Advanced"
    }
]
```

### Section Behavior

- **Unsectioned fields:** Displayed at the top of the settings form
- **Sectioned fields:** Grouped under collapsible accordion headers
- **First section:** Expanded by default
- **Other sections:** Collapsed by default
- **Backward compatible:** Plugins without sections render as a flat list

### Section Naming

- Use clear, descriptive section names
- Common section names: "General", "Advanced", "Authentication", "Output", "Performance"
- Sections are displayed in the order they first appear in the fields list

---

## Plugin Actions

Actions are operations that users can trigger manually by clicking a button in the UI.

### Action Structure

```python
{
    "id": "action_id",              # Required: Unique action identifier
    "label": "Action Label",        # Required: Button label
    "description": "What it does",  # Optional: Helper text shown below button
    "confirm": False                # Optional: Require confirmation before running
}
```

### Basic Action Example

```python
actions = [
    {
        "id": "refresh_data",
        "label": "Refresh Data",
        "description": "Fetches latest data from the external service"
    }
]

def run(self, action: str, params: dict, context: dict):
    if action == "refresh_data":
        # Perform the refresh operation
        return {
            "status": "success",
            "message": "Data refreshed successfully"
        }
```

### Action Confirmation

For potentially dangerous or long-running actions, you can require user confirmation:

#### Boolean Confirmation (Default Message)

```python
{
    "id": "delete_all",
    "label": "Delete All Data",
    "description": "Permanently deletes all cached data",
    "confirm": True  # Shows default confirmation modal
}
```

#### Custom Confirmation Message

```python
{
    "id": "delete_all",
    "label": "Delete All Data",
    "description": "Permanently deletes all cached data",
    "confirm": {
        "required": True,
        "title": "Delete All Data?",
        "message": "This will permanently delete all cached data. This action cannot be undone. Are you sure?"
    }
}
```

### Return Values

Your `run` method should return a dictionary with specific keys:

#### Success Response

```python
return {
    "status": "success",
    "message": "Operation completed successfully"
}
```

#### Error Response

```python
return {
    "status": "error",
    "message": "Failed to connect to API: Connection timeout"
}
```

#### Response with File Output

```python
return {
    "status": "success",
    "message": "Export completed",
    "file": "/app/data/exports/output.m3u"
}
```

#### Response with Additional Data

```python
return {
    "status": "success",
    "message": "Processed 150 items",
    "data": {
        "processed": 150,
        "skipped": 5,
        "errors": 0
    }
}
```

### Multiple Actions

You can define multiple actions in a single plugin:

```python
actions = [
    {
        "id": "quick_refresh",
        "label": "Quick Refresh",
        "description": "Fast refresh with minimal processing"
    },
    {
        "id": "full_refresh",
        "label": "Full Refresh",
        "description": "Complete refresh with full processing",
        "confirm": True
    },
    {
        "id": "export_data",
        "label": "Export Data",
        "description": "Export data to file"
    }
]

def run(self, action: str, params: dict, context: dict):
    settings = context.get("settings", {})
    logger = context.get("logger")

    if action == "quick_refresh":
        # Quick refresh logic
        return {"status": "success", "message": "Quick refresh completed"}

    elif action == "full_refresh":
        # Full refresh logic
        return {"status": "success", "message": "Full refresh completed"}

    elif action == "export_data":
        # Export logic
        output_path = "/app/data/exports/data.json"
        # ... export code ...
        return {
            "status": "success",
            "message": "Data exported",
            "file": output_path
        }

    else:
        return {"status": "error", "message": f"Unknown action: {action}"}
```

---

## Accessing Dispatcharr APIs

Plugins run server-side within the Django application and have full access to Dispatcharr's internal APIs.

### Importing Models

```python
# M3U models
from apps.m3u.models import M3UAccount, M3UStream

# EPG models
from apps.epg.models import EPGSource, EPGProgram

# Channel models
from apps.channels.models import Channel, ChannelGroup

# Core settings
from core.models import CoreSettings, StreamProfile, UserAgent
```

### Querying Data

```python
def run(self, action: str, params: dict, context: dict):
    if action == "count_channels":
        from apps.channels.models import Channel

        total_channels = Channel.objects.count()
        enabled_channels = Channel.objects.filter(enabled=True).count()

        return {
            "status": "success",
            "message": f"Total: {total_channels}, Enabled: {enabled_channels}"
        }
```

### Using Celery Tasks

For long-running operations, use Celery tasks to avoid blocking:

```python
def run(self, action: str, params: dict, context: dict):
    if action == "refresh_all":
        # Import Celery tasks
        from apps.m3u.tasks import refresh_m3u_accounts
        from apps.epg.tasks import refresh_all_epg_data

        # Queue tasks asynchronously
        refresh_m3u_accounts.delay()
        refresh_all_epg_data.delay()

        return {
            "status": "success",
            "message": "Refresh jobs queued in background"
        }
```

**Available Celery Tasks:**

- `apps.m3u.tasks.refresh_m3u_accounts` - Refresh all M3U accounts
- `apps.epg.tasks.refresh_all_epg_data` - Refresh all EPG sources
- `apps.epg.tasks.refresh_epg_source` - Refresh specific EPG source
- `apps.channels.tasks.*` - Channel-related tasks

### Sending WebSocket Updates

Send real-time updates to the UI:

```python
def run(self, action: str, params: dict, context: dict):
    from core.utils import send_websocket_update

    # Send update notification
    send_websocket_update('updates', 'update', {
        "type": "plugin",
        "plugin": "my_plugin",
        "message": "Processing started"
    })

    # ... do work ...

    send_websocket_update('updates', 'update', {
        "type": "plugin",
        "plugin": "my_plugin",
        "message": "Processing completed"
    })

    return {"status": "success", "message": "Done"}
```

### Using Database Transactions

For operations that modify multiple records:

```python
def run(self, action: str, params: dict, context: dict):
    from django.db import transaction
    from apps.channels.models import Channel

    if action == "bulk_update":
        try:
            with transaction.atomic():
                # All updates succeed or all fail together
                channels = Channel.objects.filter(group__name="Sports")
                for channel in channels:
                    channel.enabled = True
                    channel.save()

                return {
                    "status": "success",
                    "message": f"Updated {channels.count()} channels"
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Transaction failed: {str(e)}"
            }
```

### Logging

Use the provided logger for debugging and monitoring:

```python
def run(self, action: str, params: dict, context: dict):
    logger = context.get("logger")

    logger.info("Action started")
    logger.debug(f"Settings: {context.get('settings')}")

    try:
        # ... do work ...
        logger.info("Action completed successfully")
        return {"status": "success", "message": "Done"}
    except Exception as e:
        logger.error(f"Action failed: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}
```

---

## Testing Your Plugin

### Local Testing

1. **Create the plugin directory** in your development environment
2. **Write the plugin code** following the structure above
3. **Reload plugins** from the UI
4. **Enable the plugin** and accept the trust warning
5. **Navigate to Settings** to find your plugin
6. **Test settings** - Change values and verify they save
7. **Test actions** - Click action buttons and verify results
8. **Check logs** - Review server logs for errors or warnings

### Testing Checklist

- [ ] Plugin appears in the Plugins page after reload
- [ ] Plugin can be enabled without errors
- [ ] Plugin appears in Settings page accordion when enabled
- [ ] All settings fields render correctly
- [ ] Settings save automatically when changed
- [ ] Sections collapse/expand correctly (if using sections)
- [ ] Actions appear in the Actions section
- [ ] Action buttons trigger the correct operations
- [ ] Confirmation modals appear for actions with `confirm: true`
- [ ] Success/error notifications display correctly
- [ ] Server logs show expected messages
- [ ] Plugin can be disabled without errors
- [ ] Plugin can be deleted without errors

### Debugging Tips

**Plugin not appearing:**

- Check directory name (no special characters)
- Verify `plugin.py` exists and has a `Plugin` class
- Check server logs for import errors

**Settings not saving:**

- Verify field `id` values are unique
- Check browser console for API errors
- Ensure plugin is enabled

**Actions failing:**

- Check the `run` method signature is correct
- Verify action `id` matches the condition in `run`
- Review server logs for exceptions
- Ensure proper error handling in your code

---

## Packaging and Distribution

### Creating a ZIP Package

To distribute your plugin, package it as a ZIP file:

```bash
cd /app/data/plugins
zip -r my_plugin.zip my_plugin/
```

**ZIP Structure:**

```
my_plugin.zip
└── my_plugin/
    ├── plugin.py
    ├── __init__.py (optional)
    ├── helpers.py (optional)
    └── README.md (optional)
```

### Including a README

Add a `README.md` file to document your plugin:

```markdown
# My Plugin

## Description

Brief description of what your plugin does.

## Settings

- **API Key**: Your API key from the service
- **Max Items**: Maximum number of items to process

## Actions

- **Refresh Data**: Fetches latest data from the service

## Requirements

- Dispatcharr version 1.0+
- Internet connection for API access

## Installation

1. Download the plugin ZIP file
2. In Dispatcharr, go to Plugins page
3. Click "Import Plugin"
4. Upload the ZIP file
5. Enable the plugin

## Support

Contact: your@email.com
```

### Version Management

Use semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes

Update the `version` attribute when releasing updates:

```python
class Plugin:
    name = "My Plugin"
    version = "1.2.0"  # Increment for each release
    description = "..."
```

---

## Best Practices

### Code Quality

- **Use type hints** for better code clarity
- **Handle exceptions** gracefully
- **Validate user input** from settings
- **Keep `run` method fast** - use Celery for heavy work
- **Log important events** for debugging
- **Write clean, readable code** with comments

### Security

- **Validate and sanitize** all settings values
- **Use parameterized queries** to prevent SQL injection
- **Don't store sensitive data** in plain text
- **Limit file system access** to `/app/data/` paths
- **Be cautious with external APIs** - validate responses

### Performance

- **Use Celery tasks** for long-running operations
- **Batch database queries** when possible
- **Use database transactions** for multiple updates
- **Cache expensive computations** when appropriate
- **Avoid blocking operations** in the `run` method

### User Experience

- **Provide clear field labels** and help text
- **Use appropriate field types** for each setting
- **Group related settings** into sections
- **Write descriptive action labels** and descriptions
- **Return helpful error messages** to users
- **Use confirmation modals** for destructive actions

### Maintenance

- **Document your code** with comments and docstrings
- **Include a README** with installation and usage instructions
- **Test thoroughly** before releasing
- **Version your releases** using semantic versioning
- **Provide support** for users who encounter issues

---

## Examples

### Example 1: Data Export Plugin

```python
class Plugin:
    name = "Channel Exporter"
    version = "1.0.0"
    description = "Export channels to M3U format"

    fields = [
        {
            "id": "include_disabled",
            "label": "Include Disabled Channels",
            "type": "boolean",
            "default": False,
            "section": "Export Options"
        },
        {
            "id": "group_filter",
            "label": "Group Filter",
            "type": "string",
            "default": "",
            "help_text": "Only export channels from this group (leave empty for all)",
            "section": "Export Options"
        },
        {
            "id": "output_path",
            "label": "Output Path",
            "type": "string",
            "default": "/app/data/exports/channels.m3u",
            "section": "Advanced"
        }
    ]

    actions = [
        {
            "id": "export",
            "label": "Export Channels",
            "description": "Generate M3U file with current channels"
        }
    ]

    def run(self, action: str, params: dict, context: dict):
        if action == "export":
            from apps.channels.models import Channel
            import os

            settings = context.get("settings", {})
            logger = context.get("logger")

            include_disabled = settings.get("include_disabled", False)
            group_filter = settings.get("group_filter", "")
            output_path = settings.get("output_path", "/app/data/exports/channels.m3u")

            # Build query
            query = Channel.objects.all()
            if not include_disabled:
                query = query.filter(enabled=True)
            if group_filter:
                query = query.filter(group__name=group_filter)

            # Generate M3U
            try:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                with open(output_path, 'w') as f:
                    f.write("#EXTM3U\n")
                    for channel in query:
                        f.write(f'#EXTINF:-1,{channel.name}\n')
                        f.write(f'{channel.url}\n')

                count = query.count()
                logger.info(f"Exported {count} channels to {output_path}")

                return {
                    "status": "success",
                    "message": f"Exported {count} channels",
                    "file": output_path
                }
            except Exception as e:
                logger.error(f"Export failed: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Export failed: {str(e)}"
                }

        return {"status": "error", "message": f"Unknown action: {action}"}
```

### Example 2: Maintenance Plugin

```python
class Plugin:
    name = "Database Maintenance"
    version = "1.0.0"
    description = "Database cleanup and optimization utilities"

    fields = [
        {
            "id": "days_to_keep",
            "label": "Days to Keep Old Data",
            "type": "number",
            "default": 30,
            "help_text": "Delete data older than this many days",
            "section": "Cleanup Settings"
        }
    ]

    actions = [
        {
            "id": "cleanup_old_programs",
            "label": "Clean Up Old Programs",
            "description": "Delete EPG programs older than configured days",
            "confirm": {
                "required": True,
                "title": "Clean Up Old Programs?",
                "message": "This will permanently delete old EPG program data."
            }
        },
        {
            "id": "vacuum_database",
            "label": "Vacuum Database",
            "description": "Optimize database storage (may take a while)",
            "confirm": True
        }
    ]

    def run(self, action: str, params: dict, context: dict):
        from django.utils import timezone
        from datetime import timedelta

        settings = context.get("settings", {})
        logger = context.get("logger")

        if action == "cleanup_old_programs":
            from apps.epg.models import EPGProgram

            days = settings.get("days_to_keep", 30)
            cutoff_date = timezone.now() - timedelta(days=days)

            deleted_count, _ = EPGProgram.objects.filter(
                end_time__lt=cutoff_date
            ).delete()

            logger.info(f"Deleted {deleted_count} old EPG programs")

            return {
                "status": "success",
                "message": f"Deleted {deleted_count} old programs"
            }

        elif action == "vacuum_database":
            from django.db import connection

            try:
                with connection.cursor() as cursor:
                    cursor.execute("VACUUM")

                logger.info("Database vacuum completed")
                return {
                    "status": "success",
                    "message": "Database optimized successfully"
                }
            except Exception as e:
                logger.error(f"Vacuum failed: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Vacuum failed: {str(e)}"
                }

        return {"status": "error", "message": f"Unknown action: {action}"}
```

---

## Conclusion

You now have all the knowledge needed to create basic plugins for Dispatcharr! Remember to:

- Start simple and iterate
- Test thoroughly before distributing
- Follow best practices for security and performance
- Provide clear documentation for users
- Use sections to organize complex settings
- Leverage Celery for long-running tasks

For advanced plugins with dedicated pages and navigation integration, see the **Advanced Plugin Development Guide**.

---

**Last Updated:** November 2025
**Dispatcharr Version:** 1.0+
**Plugin System Version:** 2.0 (with navigation and sections support)
