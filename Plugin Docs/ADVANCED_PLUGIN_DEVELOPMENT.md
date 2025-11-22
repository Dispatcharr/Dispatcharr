# Dispatcharr Plugin System - Advanced Plugin Development Guide

## Table of Contents

1. [Introduction](#introduction)
2. [What is an Advanced Plugin?](#what-is-an-advanced-plugin)
3. [Key Differences from Basic Plugins](#key-differences-from-basic-plugins)
4. [Creating an Advanced Plugin](#creating-an-advanced-plugin)
5. [Navigation Integration](#navigation-integration)
6. [Dedicated Plugin Page](#dedicated-plugin-page)
7. [Real-Time Updates](#real-time-updates)
8. [Advanced Examples](#advanced-examples)
9. [Best Practices](#best-practices)
10. [Migration Guide](#migration-guide)

---

## Introduction

This guide covers **Advanced Plugins** - plugins that have dedicated pages in the Dispatcharr UI with full navigation integration. Advanced plugins are ideal for complex features that require more UI space and sophisticated user interactions.

**Prerequisites:**

- Completion of the Basic Plugin Development Guide
- Understanding of React and frontend development (helpful but not required)
- Familiarity with Dispatcharr's architecture

**What You'll Learn:**

- How to enable navigation integration for your plugin
- How the dedicated plugin page works
- How to leverage real-time WebSocket updates
- Best practices for advanced plugin development
- How to migrate a basic plugin to an advanced plugin

---

## What is an Advanced Plugin?

**Advanced Plugins** are plugins that:

- Set `navigation = True` in the Plugin class
- Appear in the **sidebar navigation menu** when enabled
- Have a **dedicated page** at `/plugin/{plugin_key}`
- Do **not** appear in the Settings page accordion
- Are ideal for complex features requiring more UI space

**Use Cases:**

- Complex configuration interfaces with many settings
- Data visualization and reporting dashboards
- Multi-step workflows and wizards
- Feature-rich integrations with external services
- Plugins that need custom UI components beyond standard settings

**Examples:**

- Streaming output plugins with extensive codec/quality settings
- Analytics dashboards showing channel statistics
- Advanced EPG management tools
- Custom content filtering and transformation tools

---

## Key Differences from Basic Plugins

| Feature                  | Basic Plugin                      | Advanced Plugin                       |
| ------------------------ | --------------------------------- | ------------------------------------- |
| **Navigation Attribute** | `navigation = False` (or omitted) | `navigation = True`                   |
| **UI Location**          | Settings page accordion           | Sidebar navigation menu               |
| **Page Route**           | N/A                               | `/plugin/{plugin_key}`                |
| **UI Space**             | Limited (accordion panel)         | Full page                             |
| **Complexity**           | Simple utilities                  | Complex features                      |
| **Settings Display**     | Flat or sectioned accordion       | Sectioned accordion on dedicated page |
| **Actions Display**      | Below settings in accordion       | Below settings on dedicated page      |

---

## Creating an Advanced Plugin

### Step 1: Set Navigation Attribute

The only code change required is adding `navigation = True` to your Plugin class:

```python
class Plugin:
    name = "My Advanced Plugin"
    version = "1.0.0"
    description = "A plugin with a dedicated page"
    navigation = True  # This enables navigation integration!

    fields = [
        # ... your settings fields ...
    ]

    actions = [
        # ... your actions ...
    ]

    def run(self, action: str, params: dict, context: dict):
        # ... your action logic ...
        pass
```

### Step 2: Enable the Plugin

1. Create your plugin directory and `plugin.py` file
2. Reload plugins from the Plugins page
3. Enable the plugin using the toggle switch
4. **The plugin will automatically appear in the sidebar navigation menu**

### Step 3: Access the Dedicated Page

1. Click on the plugin name in the sidebar
2. You'll be navigated to `/plugin/{plugin_key}`
3. The dedicated page displays:
   - Plugin name and description
   - Settings organized into accordion sections
   - Actions with run buttons
   - Real-time status updates

---

## Navigation Integration

### How Navigation Works

When you set `navigation = True`, Dispatcharr automatically:

1. **Adds the plugin to the sidebar** when enabled
2. **Creates a route** at `/plugin/{plugin_key}`
3. **Renders the PluginPage component** with your plugin's data
4. **Removes the plugin from Settings accordion** (to avoid duplication)
5. **Updates the sidebar in real-time** when the plugin is enabled/disabled

### Sidebar Appearance

Your plugin will appear in the sidebar navigation menu:

```
┌─────────────────────┐
│ Dispatcharr         │
├─────────────────────┤
│ 📊 Dashboard        │
│ 📺 Channels         │
│ 📡 Content Sources  │
│ 📅 TV Guide         │
│ 🔌 Plugins          │
│ ⚙️  Settings         │
│ 👥 Users            │
├─────────────────────┤
│ 🔧 My Advanced Plugin│  ← Your plugin appears here!
└─────────────────────┘
```

### Navigation Icon

Currently, plugins use a default wrench icon (🔧). Future versions may support custom icons.

### Real-Time Sidebar Updates

When you enable/disable a plugin:

- **WebSocket event** is broadcast: `plugin_enabled_changed`
- **Sidebar automatically updates** without page refresh
- **Plugin appears/disappears** from the navigation menu instantly

This is powered by the Zustand plugin store (`frontend/src/store/plugins.js`) and WebSocket integration.

---

## Dedicated Plugin Page

### Page Structure

The dedicated plugin page (`frontend/src/pages/PluginPage.jsx`) automatically renders:

#### 1. Header Section

```
┌────────────────────────────────────┐
│ My Advanced Plugin                 │
│ A plugin with a dedicated page     │
└────────────────────────────────────┘
```

#### 2. Settings Section (Accordion)

```
┌────────────────────────────────────┐
│ ▼ General Settings                 │
│   ├─ Enable Feature      [Toggle]  │
│   └─ API Key            [________] │
├────────────────────────────────────┤
│ ▶ Advanced Settings                │
├────────────────────────────────────┤
│ ▶ Output Settings                  │
└────────────────────────────────────┘
```

#### 3. Actions Section

```
┌────────────────────────────────────┐
│ Actions                            │
├────────────────────────────────────┤
│ Refresh Data                       │
│ Fetches latest data from service   │
│                          [Run]     │
├────────────────────────────────────┤
│ Export Data                        │
│ Exports data to file               │
│                          [Run]     │
└────────────────────────────────────┘
```

### Settings Organization

Settings are automatically organized using the `section` attribute:

```python
fields = [
    # Unsectioned fields → "General Settings" section
    {
        "id": "enabled",
        "label": "Enable Feature",
        "type": "boolean",
        "default": True
    },

    # Sectioned fields → Custom section names
    {
        "id": "video_codec",
        "label": "Video Codec",
        "type": "select",
        "options": [...],
        "section": "Video Settings"
    },
    {
        "id": "audio_codec",
        "label": "Audio Codec",
        "type": "select",
        "options": [...],
        "section": "Audio Settings"
    }
]
```

**Rendering Behavior:**

- **Unsectioned fields** → Grouped under "General Settings"
- **Sectioned fields** → Grouped under their section name
- **First section** → Expanded by default
- **Other sections** → Collapsed by default

### Auto-Save Functionality

Settings are automatically saved when changed:

- No "Save" button required
- Changes are sent to the backend immediately
- Uses `POST /api/plugins/plugins/{key}/settings/`
- Settings persist across page reloads

### Action Execution

Actions work the same as in basic plugins:

- Click "Run" button to execute
- Confirmation modal appears if `confirm: true`
- Button shows "Running…" during execution
- Success/error notifications display results
- Output files are shown below the action

---

## Real-Time Updates

Advanced plugins benefit from real-time WebSocket integration.

### WebSocket Events

When a plugin is enabled/disabled, a WebSocket event is broadcast:

```javascript
{
  "type": "plugin_enabled_changed",
  "plugin_key": "my_plugin",
  "plugin_name": "My Advanced Plugin",
  "enabled": true,
  "navigation": true
}
```

### Frontend Integration

The frontend automatically handles these events:

1. **WebSocket.jsx** receives the event
2. **Plugin store** (`usePluginsStore`) increments `pluginStateVersion`
3. **Sidebar.jsx** re-fetches enabled plugins with `navigation=true`
4. **Settings.jsx** re-fetches enabled plugins with `navigation=false`
5. **UI updates** without page refresh

### Sending Custom WebSocket Updates

You can send custom updates from your plugin:

```python
def run(self, action: str, params: dict, context: dict):
    from core.utils import send_websocket_update

    if action == "process_data":
        # Send progress update
        send_websocket_update('updates', 'update', {
            "type": "plugin_progress",
            "plugin": "my_plugin",
            "message": "Processing 50%",
            "progress": 50
        })

        # ... do work ...

        # Send completion update
        send_websocket_update('updates', 'update', {
            "type": "plugin_progress",
            "plugin": "my_plugin",
            "message": "Processing complete",
            "progress": 100
        })

        return {"status": "success", "message": "Done"}
```

**Note:** The frontend currently doesn't have a built-in handler for custom plugin events, but you can add one by modifying `WebSocket.jsx`.

---

## Advanced Examples

### Example 1: Streaming Output Plugin

A comprehensive example of an advanced plugin with extensive settings:

```python
class Plugin:
    name = "Advanced Stream Output"
    version = "2.0.0"
    description = "Advanced streaming output with full codec control"
    navigation = True  # Enable dedicated page

    fields = [
        # General Settings
        {
            "id": "enabled",
            "label": "Enable Output",
            "type": "boolean",
            "default": False,
            "help_text": "Enable or disable the streaming output"
        },
        {
            "id": "output_url",
            "label": "Output URL",
            "type": "string",
            "default": "http://localhost:8080/stream.m3u8",
            "help_text": "URL where the stream will be available"
        },

        # Video Settings Section
        {
            "id": "video_codec",
            "label": "Video Codec",
            "type": "select",
            "default": "h264",
            "options": [
                {"value": "h264", "label": "H.264 (AVC)"},
                {"value": "h265", "label": "H.265 (HEVC)"},
                {"value": "vp9", "label": "VP9"},
                {"value": "av1", "label": "AV1"}
            ],
            "section": "Video Settings"
        },
        {
            "id": "video_bitrate",
            "label": "Video Bitrate (kbps)",
            "type": "number",
            "default": 4000,
            "help_text": "Target video bitrate in kilobits per second",
            "section": "Video Settings"
        },
        {
            "id": "video_resolution",
            "label": "Resolution",
            "type": "select",
            "default": "1080p",
            "options": [
                {"value": "4k", "label": "4K (3840x2160)"},
                {"value": "1080p", "label": "1080p (1920x1080)"},
                {"value": "720p", "label": "720p (1280x720)"},
                {"value": "480p", "label": "480p (854x480)"}
            ],
            "section": "Video Settings"
        },
        {
            "id": "video_fps",
            "label": "Frame Rate",
            "type": "select",
            "default": "30",
            "options": [
                {"value": "60", "label": "60 FPS"},
                {"value": "30", "label": "30 FPS"},
                {"value": "24", "label": "24 FPS"}
            ],
            "section": "Video Settings"
        },

        # Audio Settings Section
        {
            "id": "audio_codec",
            "label": "Audio Codec",
            "type": "select",
            "default": "aac",
            "options": [
                {"value": "aac", "label": "AAC"},
                {"value": "mp3", "label": "MP3"},
                {"value": "opus", "label": "Opus"},
                {"value": "ac3", "label": "AC3"}
            ],
            "section": "Audio Settings"
        },
        {
            "id": "audio_bitrate",
            "label": "Audio Bitrate (kbps)",
            "type": "number",
            "default": 192,
            "help_text": "Target audio bitrate in kilobits per second",
            "section": "Audio Settings"
        },
        {
            "id": "audio_channels",
            "label": "Audio Channels",
            "type": "select",
            "default": "stereo",
            "options": [
                {"value": "mono", "label": "Mono (1.0)"},
                {"value": "stereo", "label": "Stereo (2.0)"},
                {"value": "5.1", "label": "5.1 Surround"}
            ],
            "section": "Audio Settings"
        },

        # Advanced Settings Section
        {
            "id": "segment_duration",
            "label": "Segment Duration (seconds)",
            "type": "number",
            "default": 6,
            "help_text": "Duration of each HLS segment",
            "section": "Advanced Settings"
        },
        {
            "id": "buffer_size",
            "label": "Buffer Size (MB)",
            "type": "number",
            "default": 10,
            "help_text": "Size of the encoding buffer",
            "section": "Advanced Settings"
        }
    ]

    actions = [
        {
            "id": "start_stream",
            "label": "Start Stream",
            "description": "Start the streaming output with current settings"
        },
        {
            "id": "stop_stream",
            "label": "Stop Stream",
            "description": "Stop the streaming output",
            "confirm": {
                "required": True,
                "title": "Stop Stream?",
                "message": "This will stop the active stream. Viewers will be disconnected."
            }
        },
        {
            "id": "test_config",
            "label": "Test Configuration",
            "description": "Validate the current configuration without starting the stream"
        }
    ]

    def run(self, action: str, params: dict, context: dict):
        settings = context.get("settings", {})
        logger = context.get("logger")

        if action == "start_stream":
            if not settings.get("enabled", False):
                return {
                    "status": "error",
                    "message": "Output is disabled. Enable it in settings first."
                }

            # Build ffmpeg command based on settings
            video_codec = settings.get("video_codec", "h264")
            audio_codec = settings.get("audio_codec", "aac")
            video_bitrate = settings.get("video_bitrate", 4000)
            audio_bitrate = settings.get("audio_bitrate", 192)

            logger.info(f"Starting stream with {video_codec}/{audio_codec}")

            # In a real plugin, you would start the actual streaming process here
            # For this example, we'll just simulate it

            return {
                "status": "success",
                "message": f"Stream started: {video_codec} @ {video_bitrate}kbps, {audio_codec} @ {audio_bitrate}kbps"
            }

        elif action == "stop_stream":
            logger.info("Stopping stream")
            # Stop the streaming process
            return {
                "status": "success",
                "message": "Stream stopped successfully"
            }

        elif action == "test_config":
            # Validate configuration
            errors = []

            if not settings.get("output_url"):
                errors.append("Output URL is required")

            video_bitrate = settings.get("video_bitrate", 0)
            if video_bitrate < 500 or video_bitrate > 50000:
                errors.append("Video bitrate must be between 500 and 50000 kbps")

            if errors:
                return {
                    "status": "error",
                    "message": "Configuration errors: " + ", ".join(errors)
                }

            return {
                "status": "success",
                "message": "Configuration is valid"
            }

        return {"status": "error", "message": f"Unknown action: {action}"}
```

This plugin demonstrates:

- **Extensive settings** organized into logical sections
- **Multiple actions** with different purposes
- **Confirmation modals** for destructive actions
- **Settings validation** in the test action
- **Clear user feedback** through messages

---

## Best Practices

### When to Use Advanced Plugins

**Use Advanced Plugins when:**

- You have 10+ settings that benefit from sectioning
- You need more UI space than an accordion provides
- Your plugin is a major feature deserving its own page
- You want prominent placement in the navigation menu
- You're building a complex workflow or dashboard

**Use Basic Plugins when:**

- You have simple utilities with few settings
- Your plugin is a background task or automation
- You don't need dedicated UI space
- You want to keep the plugin less prominent

### UI/UX Considerations

**Settings Organization:**

- Group related settings into logical sections
- Use clear, descriptive section names
- Put the most important settings in unsectioned fields or the first section
- Use help text to explain complex settings
- Provide sensible defaults

**Action Design:**

- Use clear, action-oriented labels ("Start Stream" not "Stream")
- Provide descriptions for non-obvious actions
- Use confirmation modals for destructive or long-running actions
- Return helpful success/error messages
- Consider adding a "Test Configuration" action

**Performance:**

- Keep the `run` method fast (< 5 seconds)
- Use Celery tasks for long-running operations
- Send WebSocket updates for progress tracking
- Validate settings before performing expensive operations

### Code Organization

For complex plugins, consider organizing your code:

```
/app/data/plugins/my_advanced_plugin/
├── __init__.py
├── plugin.py          # Main Plugin class
├── actions.py         # Action handlers
├── validators.py      # Settings validation
├── tasks.py           # Celery tasks
├── utils.py           # Helper functions
└── README.md          # Documentation
```

Example structure:

```python
# plugin.py
from .actions import handle_action
from .validators import validate_settings

class Plugin:
    name = "My Advanced Plugin"
    version = "1.0.0"
    description = "..."
    navigation = True

    fields = [...]
    actions = [...]

    def run(self, action: str, params: dict, context: dict):
        # Validate settings first
        validation_error = validate_settings(context.get("settings", {}))
        if validation_error:
            return {"status": "error", "message": validation_error}

        # Delegate to action handlers
        return handle_action(action, params, context)
```

```python
# actions.py
def handle_action(action: str, params: dict, context: dict):
    handlers = {
        "start_stream": start_stream,
        "stop_stream": stop_stream,
        "test_config": test_config
    }

    handler = handlers.get(action)
    if not handler:
        return {"status": "error", "message": f"Unknown action: {action}"}

    return handler(params, context)

def start_stream(params: dict, context: dict):
    # Implementation
    pass

def stop_stream(params: dict, context: dict):
    # Implementation
    pass

def test_config(params: dict, context: dict):
    # Implementation
    pass
```

### Testing Advanced Plugins

**Testing Checklist:**

- [ ] Plugin appears in sidebar when enabled
- [ ] Plugin disappears from sidebar when disabled
- [ ] Dedicated page loads without errors
- [ ] All settings sections render correctly
- [ ] Settings save automatically
- [ ] Actions execute correctly
- [ ] Confirmation modals appear when expected
- [ ] WebSocket updates work (enable/disable)
- [ ] Plugin doesn't appear in Settings accordion
- [ ] Navigation between pages works smoothly

**Cross-Browser Testing:**

- Test in Chrome, Firefox, Safari, Edge
- Verify WebSocket connections work
- Check for console errors
- Test on mobile devices (responsive design)

---

## Migration Guide

### Converting a Basic Plugin to Advanced

If you have an existing basic plugin and want to convert it to an advanced plugin:

#### Step 1: Add Navigation Attribute

```python
class Plugin:
    name = "My Plugin"
    version = "2.0.0"  # Increment version
    description = "..."
    navigation = True  # Add this line

    # ... rest of your plugin ...
```

#### Step 2: Update Version Number

Increment the version to indicate a major change:

- If currently `1.x.x`, change to `2.0.0`
- Update any documentation to reflect the change

#### Step 3: Test the Migration

1. Reload the plugin from the Plugins page
2. Verify it appears in the sidebar (not Settings)
3. Test all settings and actions on the dedicated page
4. Ensure existing settings are preserved

#### Step 4: Update Documentation

Update your plugin's README to reflect:

- New navigation integration
- Location change (sidebar instead of Settings)
- Any new features or improvements

### Backward Compatibility

**Settings Preservation:**

- Existing settings are automatically preserved
- No data migration needed
- Users won't lose their configuration

**User Impact:**

- Plugin moves from Settings to sidebar
- Users need to know where to find it
- Consider adding a notification or documentation

### Example Migration

**Before (Basic Plugin):**

```python
class Plugin:
    name = "Stream Exporter"
    version = "1.5.0"
    description = "Export streams to M3U format"
    # navigation attribute omitted (defaults to False)

    fields = [...]
    actions = [...]

    def run(self, action: str, params: dict, context: dict):
        # ... implementation ...
        pass
```

**After (Advanced Plugin):**

```python
class Plugin:
    name = "Stream Exporter"
    version = "2.0.0"  # Major version bump
    description = "Export streams to M3U format with advanced options"
    navigation = True  # Enable navigation integration

    fields = [...]  # Same fields, possibly reorganized into sections
    actions = [...]  # Same actions

    def run(self, action: str, params: dict, context: dict):
        # ... same implementation ...
        pass
```

**Changes:**

- Added `navigation = True`
- Bumped version from `1.5.0` to `2.0.0`
- Optionally updated description
- No changes to fields, actions, or run method required

---

## Technical Details

### Frontend Components

**PluginPage Component** (`frontend/src/pages/PluginPage.jsx`):

- Fetches plugin data from `/api/plugins/plugins/`
- Renders settings in accordion sections
- Handles auto-save for settings changes
- Executes actions and displays results
- Shows confirmation modals when needed

**Sidebar Component** (`frontend/src/components/Sidebar.jsx`):

- Fetches enabled plugins with `navigation=true`
- Renders plugin navigation items
- Updates in real-time via WebSocket events
- Uses `usePluginsStore` for state management

**Plugin Store** (`frontend/src/store/plugins.js`):

- Zustand store for plugin state
- Tracks `pluginStateVersion` for triggering re-fetches
- Provides `triggerPluginRefresh()` method
- Used by WebSocket handler and components

### Backend API Endpoints

**Plugin Endpoints:**

- `GET /api/plugins/plugins/` - List all plugins
- `GET /api/plugins/plugins/enabled/` - List enabled plugins only
- `POST /api/plugins/plugins/{key}/enabled/` - Enable/disable plugin
- `POST /api/plugins/plugins/{key}/settings/` - Update settings
- `POST /api/plugins/plugins/{key}/run/` - Run action

**WebSocket Events:**

- `plugin_enabled_changed` - Broadcast when plugin enabled/disabled
- Includes: `plugin_key`, `plugin_name`, `enabled`, `navigation`

### Routing

**Frontend Routes** (`frontend/src/App.jsx`):

```javascript
<Route path="/plugin/:pluginKey" element={<PluginPage />} />
```

**URL Pattern:**

- `/plugin/my_plugin` - Dedicated page for plugin with key `my_plugin`
- Plugin key is derived from directory name (lowercased, spaces → underscores)

---

## Troubleshooting

### Plugin Not Appearing in Sidebar

**Possible Causes:**

- `navigation` attribute not set to `True`
- Plugin is disabled
- WebSocket connection issues

**Solutions:**

1. Verify `navigation = True` in plugin.py
2. Enable the plugin from the Plugins page
3. Refresh the page to re-establish WebSocket connection
4. Check browser console for errors

### Dedicated Page Shows "Plugin Not Found"

**Possible Causes:**

- Plugin key doesn't match URL parameter
- Plugin is disabled
- Plugin was deleted

**Solutions:**

1. Verify the URL matches the plugin key
2. Enable the plugin from the Plugins page
3. Check that the plugin still exists in `/app/data/plugins/`

### Settings Not Saving on Dedicated Page

**Possible Causes:**

- Network errors
- Backend API errors
- Plugin is disabled

**Solutions:**

1. Check browser console for API errors
2. Verify plugin is enabled
3. Check server logs for backend errors
4. Test with browser dev tools network tab

### Plugin Appears in Both Sidebar and Settings

**Cause:** This should not happen - it's a bug

**Solution:**

1. Verify `navigation = True` is set correctly
2. Reload the plugin discovery
3. Refresh the browser page
4. Check for JavaScript errors in console

---

## Conclusion

Advanced plugins provide a powerful way to extend Dispatcharr with complex features that deserve dedicated UI space. By setting `navigation = True`, you automatically get:

- **Sidebar navigation integration**
- **Dedicated page** with full UI control
- **Real-time WebSocket updates**
- **Automatic settings organization**
- **Professional user experience**

**Key Takeaways:**

- Use advanced plugins for complex features with many settings
- Organize settings into logical sections for better UX
- Leverage real-time updates for responsive UI
- Follow best practices for code organization
- Test thoroughly across browsers and devices

For simpler utilities and background tasks, consider using **Basic Plugins** (see the Basic Plugin Development Guide).

---

**Last Updated:** November 2025
**Dispatcharr Version:** 1.0+
**Plugin System Version:** 2.0 (with navigation and sections support)

---

## Additional Resources

- **Basic Plugin Development Guide** - Learn about basic plugins
- **User Guide** - End-user documentation for using plugins
- **Dispatcharr API Documentation** - Reference for internal APIs
- **Mantine UI Documentation** - Frontend component library
- **Django Documentation** - Backend framework reference
- **Celery Documentation** - Task queue for background jobs

---

**Happy Plugin Development!** 🚀

---
