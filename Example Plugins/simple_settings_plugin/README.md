# Simple Settings Plugin - Example Plugin for Dispatcharr

## Overview

This is a comprehensive example plugin that demonstrates **ALL features** of the Dispatcharr plugin system using the **Settings Page integration pattern**.

## Integration Pattern: Settings Page Accordion

- ✅ Plugin settings appear in the main **Settings page**
- ✅ Settings are organized in **collapsible accordion sections**
- ✅ Best for plugins with **simple to moderate** configuration needs
- ✅ No dedicated navigation menu item

## Features Demonstrated

This example plugin showcases every feature available in the Dispatcharr plugin system:

### 1. **All Field Types**
- ✅ `boolean` - Switches/toggles (Enable Plugin, Debug Mode, etc.)
- ✅ `number` - Numeric inputs (Timeout, Max Retries, Cache TTL, etc.)
- ✅ `string` - Text inputs (API Endpoint, API Key, etc.)
- ✅ `select` - Dropdown menus (Plugin Mode, Log Level, Rate Limiting, etc.)

### 2. **Field Organization**
- ✅ **Unsectioned fields** - Appear at the top (Enable Plugin, Plugin Mode)
- ✅ **Sectioned fields** - Grouped in collapsible accordions:
  - **General** - Basic configuration (API settings, timeout, SSL)
  - **Advanced** - Power user options (debug, retries, logging)
  - **Performance** - Performance tuning (cache, concurrency, rate limiting)
  - **Notifications** - Notification preferences

### 3. **Field Properties**
- ✅ `id` - Unique identifier for the field
- ✅ `label` - Display name in the UI
- ✅ `type` - Field type (boolean, number, string, select)
- ✅ `default` - Default value when plugin is first enabled
- ✅ `help_text` - Descriptive help text shown below the field
- ✅ `section` - Optional section name for grouping
- ✅ `options` - Array of choices for select fields

### 4. **Plugin Actions**
- ✅ **Test Connection** - Validates API configuration
- ✅ **Clear Cache** - Clears cached data
- ✅ **Generate Report** - Creates a status report

Actions appear as buttons in the plugin card on the Plugins page.

### 5. **Settings Persistence**
- ✅ Settings are automatically saved when changed
- ✅ Settings are retrieved from context in the `run()` method
- ✅ No manual save button needed (auto-save on change)

### 6. **Logging and Error Handling**
- ✅ Logger instance provided in context
- ✅ Different log levels (debug, info, warning, error)
- ✅ Proper error handling with status responses

## Installation

### Step 1: Copy Plugin to Dispatcharr

Copy the entire `simple_settings_plugin` folder to `/data/plugins/` on your Dispatcharr server:

```bash
# If using Docker/Unraid
cp -r simple_settings_plugin /path/to/dispatcharr/data/plugins/

# Or use the Dispatcharr UI to upload the plugin ZIP
```

### Step 2: Restart or Refresh

- **Option A:** Restart Dispatcharr
- **Option B:** Use the plugin refresh feature (if available)

### Step 3: Enable the Plugin

1. Go to **Plugins** page in Dispatcharr
2. Find "Simple Settings Plugin" in the list
3. Toggle the **On/Off** switch to enable it

### Step 4: Configure Settings

1. Go to **Settings** page in Dispatcharr
2. Scroll down to find the "Simple Settings Plugin" accordion
3. Expand it to see all settings sections
4. Configure the plugin settings as needed
5. Settings are saved automatically when you change them

### Step 5: Test Actions

1. Go back to **Plugins** page
2. Find "Simple Settings Plugin" card
3. Click the action buttons to test:
   - **Test Connection** - Validates your API settings
   - **Clear Cache** - Clears cached data
   - **Generate Report** - Shows current plugin status

## File Structure

```
simple_settings_plugin/
├── plugin.py          # Main plugin file (this is all you need!)
└── README.md          # This documentation file
```

## Code Structure

### Plugin Metadata

```python
class Plugin:
    name = "Simple Settings Plugin"
    version = "1.0.0"
    description = "Example plugin demonstrating Settings page integration"
    # navigation is omitted (defaults to False)
```

### Settings Fields

```python
fields = [
    # Unsectioned field
    {
        "id": "enabled",
        "label": "Enable Plugin",
        "type": "boolean",
        "default": True,
        "help_text": "Master switch to enable/disable this plugin"
    },
    
    # Sectioned field
    {
        "id": "api_key",
        "label": "API Key",
        "type": "string",
        "default": "",
        "section": "General",
        "help_text": "Your API key for authentication"
    },
    
    # Select field with options
    {
        "id": "log_level",
        "label": "Log Level",
        "type": "select",
        "default": "info",
        "section": "Advanced",
        "options": [
            {"value": "debug", "label": "Debug (Most Verbose)"},
            {"value": "info", "label": "Info"},
            {"value": "warning", "label": "Warning"},
            {"value": "error", "label": "Error (Least Verbose)"},
        ],
        "help_text": "Set the logging verbosity level"
    },
]
```

### Actions

```python
actions = [
    {
        "id": "test_connection",
        "label": "Test Connection",
        "description": "Test the API connection with current settings"
    },
]
```

### Run Method

```python
def run(self, action: str, params: dict, context: dict):
    settings = context.get("settings", {})
    logger = context.get("logger")
    
    if action == "test_connection":
        # Your action logic here
        return {
            "status": "success",
            "message": "Connection successful!",
            "data": {...}
        }
```

## Developer Notes

### When to Use This Pattern

Use the **Settings Page integration** pattern when:

- ✅ Your plugin has **simple to moderate** configuration needs
- ✅ You don't need a **dedicated page** with custom UI
- ✅ Standard field types (boolean, number, string, select) are sufficient
- ✅ You want settings to appear alongside core Dispatcharr settings

### When NOT to Use This Pattern

Consider the **Navigation Page integration** pattern instead when:

- ❌ Your plugin needs **extensive configuration** with many fields
- ❌ You need **custom UI components** beyond standard fields
- ❌ You want a **dedicated page** with more screen real estate
- ❌ Your plugin has **complex workflows** that need their own interface

See the `advanced_navigation_plugin` example for the Navigation Page pattern.

## Testing Checklist

Use this checklist to verify all features work correctly:

### Settings Page
- [ ] Plugin accordion appears in Settings page
- [ ] Unsectioned fields appear at the top
- [ ] Sectioned fields are grouped in sub-accordions
- [ ] All field types render correctly (boolean, number, string, select)
- [ ] Help text appears below each field
- [ ] Default values are set correctly on first enable
- [ ] Settings save automatically when changed
- [ ] Settings persist after page refresh

### Plugins Page
- [ ] Plugin card displays correctly
- [ ] On/Off toggle works
- [ ] Action buttons appear
- [ ] Clicking actions triggers the run() method
- [ ] Action responses show in notifications

### Functionality
- [ ] Test Connection action validates settings
- [ ] Clear Cache action works
- [ ] Generate Report action returns data
- [ ] Logger outputs appear in Dispatcharr logs
- [ ] Error handling works correctly

## Support

This is an example plugin for educational purposes. For questions about the Dispatcharr plugin system, please refer to the main Dispatcharr documentation or GitHub repository.

## License

This example plugin is provided as-is for educational purposes. Feel free to use it as a template for your own plugins.
