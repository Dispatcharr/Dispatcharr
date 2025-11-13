# Advanced Navigation Plugin - Example Plugin for Dispatcharr

## Overview

This is a comprehensive example plugin that demonstrates **ALL features** of the Dispatcharr plugin system using the **Navigation Page integration pattern**.

## Integration Pattern: Dedicated Navigation Page

- ✅ Plugin gets its own item in the **main navigation menu**
- ✅ Clicking it navigates to a **dedicated page** for this plugin
- ✅ Settings displayed on dedicated page with **more screen real estate**
- ✅ Best for plugins with **extensive configuration** or complex workflows
- ✅ Does NOT appear in Settings page accordion

## Key Difference from Simple Plugin

```python
# Simple Plugin (Settings Page Integration)
class Plugin:
    name = "Simple Plugin"
    # navigation field omitted or False
    # Settings appear in Settings page accordion

# Advanced Plugin (Navigation Page Integration)
class Plugin:
    name = "Advanced Plugin"
    navigation = True  # <-- This enables dedicated page
    # Plugin appears in navigation menu
    # Settings appear on dedicated page
```

## Features Demonstrated

This example plugin showcases every feature with extensive configuration:

### 1. **Navigation Integration**
- ✅ `navigation = True` enables dedicated page
- ✅ Plugin name appears in main navigation menu
- ✅ Dedicated page at `/plugin/{plugin_key}`
- ✅ More screen real estate for complex UIs

### 2. **All Field Types** (Same as Simple Plugin)
- ✅ `boolean` - Switches/toggles
- ✅ `number` - Numeric inputs
- ✅ `string` - Text inputs
- ✅ `select` - Dropdown menus

### 3. **Extensive Field Organization**
- ✅ **Unsectioned fields** - Master Enable, Operation Mode
- ✅ **7 Major Sections** with 50+ total fields:
  - **Connection Settings** - API endpoints, authentication, timeouts, proxy
  - **Processing Settings** - Data processing, validation, batch operations
  - **Caching & Performance** - Cache backends, compression, concurrency
  - **Retry & Error Handling** - Retry strategies, circuit breaker
  - **Logging & Monitoring** - Log levels, metrics collection
  - **Notifications** - Notification preferences, email alerts
  - **Advanced Features** - Webhooks, API, scheduling, experimental

### 4. **Complex Configuration Scenarios**
- ✅ Primary and fallback endpoints
- ✅ Multiple timeout settings
- ✅ Proxy configuration
- ✅ Circuit breaker pattern
- ✅ Multiple cache backends
- ✅ Retry strategies (fixed, linear, exponential)
- ✅ Webhook integration
- ✅ Email notifications
- ✅ Scheduled tasks

### 5. **Multiple Plugin Actions**
- ✅ **Test Connection** - Test all endpoints
- ✅ **Clear Cache** - Clear cached data
- ✅ **Reset Circuit Breaker** - Reset error handling
- ✅ **Generate Status Report** - Comprehensive metrics
- ✅ **Export Configuration** - Export settings as JSON
- ✅ **Run Diagnostics** - Full health check

## Installation

### Step 1: Copy Plugin to Dispatcharr

```bash
# Copy to Dispatcharr plugins directory
cp -r advanced_navigation_plugin /path/to/dispatcharr/data/plugins/
```

### Step 2: Restart or Refresh

- Restart Dispatcharr or use plugin refresh feature

### Step 3: Enable the Plugin

1. Go to **Plugins** page
2. Find "Advanced Navigation Plugin"
3. Toggle **On/Off** switch to enable

### Step 4: Access Dedicated Page

1. Look for **"Advanced Navigation Plugin"** in the main navigation menu
2. Click it to navigate to the dedicated plugin page
3. You'll see all settings organized in accordion sections
4. Settings save automatically when changed

### Step 5: Test Actions

1. Go to **Plugins** page
2. Find "Advanced Navigation Plugin" card
3. Click action buttons to test functionality

## File Structure

```
advanced_navigation_plugin/
├── plugin.py          # Main plugin file
└── README.md          # This documentation
```

## Code Structure

### Navigation Integration

```python
class Plugin:
    name = "Advanced Navigation Plugin"
    version = "2.0.0"
    description = "Example with extensive configuration"
    navigation = True  # <-- Enables dedicated page
```

### Extensive Settings

```python
fields = [
    # 50+ fields organized in 7 sections
    # Connection Settings (9 fields)
    # Processing Settings (6 fields)
    # Caching & Performance (7 fields)
    # Retry & Error Handling (7 fields)
    # Logging & Monitoring (6 fields)
    # Notifications (5 fields)
    # Advanced Features (7 fields)
]
```

### Multiple Actions

```python
actions = [
    {"id": "test_connection", "label": "Test Connection", ...},
    {"id": "clear_cache", "label": "Clear Cache", ...},
    {"id": "reset_circuit_breaker", "label": "Reset Circuit Breaker", ...},
    {"id": "generate_report", "label": "Generate Status Report", ...},
    {"id": "export_config", "label": "Export Configuration", ...},
    {"id": "run_diagnostics", "label": "Run Diagnostics", ...},
]
```

## When to Use This Pattern

Use the **Navigation Page integration** pattern when:

- ✅ Your plugin has **extensive configuration** (many fields)
- ✅ You need **more screen real estate** than Settings page provides
- ✅ Your plugin has **complex workflows** needing dedicated UI
- ✅ You want your plugin to be **prominently featured** in navigation
- ✅ Your plugin is a **major feature** of your Dispatcharr setup

## When NOT to Use This Pattern

Use the **Settings Page integration** pattern instead when:

- ❌ Your plugin has **simple configuration** (few fields)
- ❌ You don't need **dedicated page** real estate
- ❌ You want settings to appear **alongside core settings**
- ❌ Your plugin is a **minor utility** or helper

See the `simple_settings_plugin` example for the Settings Page pattern.

## Testing Checklist

### Navigation Integration
- [ ] Plugin appears in main navigation menu
- [ ] Clicking nav item navigates to `/plugin/{plugin_key}`
- [ ] Plugin does NOT appear in Settings page accordion
- [ ] Dedicated page displays correctly

### Dedicated Page
- [ ] Plugin name and description appear at top
- [ ] Unsectioned fields appear first
- [ ] All 7 sections render as accordions
- [ ] Fields within sections display correctly
- [ ] All field types work (boolean, number, string, select)
- [ ] Help text appears below fields
- [ ] Settings save automatically on change
- [ ] Settings persist after page refresh

### Actions
- [ ] All 6 action buttons appear on Plugins page
- [ ] Test Connection validates endpoints
- [ ] Clear Cache works
- [ ] Reset Circuit Breaker works
- [ ] Generate Report returns comprehensive data
- [ ] Export Configuration returns JSON
- [ ] Run Diagnostics performs health check

### Functionality
- [ ] Logger outputs appear in Dispatcharr logs
- [ ] Error handling works correctly
- [ ] All settings are accessible in run() method
- [ ] Context provides settings and logger

## Comparison: Simple vs Advanced

| Feature | Simple Plugin | Advanced Plugin |
|---------|--------------|-----------------|
| **Navigation** | No dedicated nav item | ✅ Own nav menu item |
| **Settings Location** | Settings page accordion | ✅ Dedicated page |
| **Screen Real Estate** | Limited (shared page) | ✅ Full page |
| **Number of Fields** | ~15 fields | ✅ 50+ fields |
| **Sections** | 4 sections | ✅ 7 sections |
| **Actions** | 3 actions | ✅ 6 actions |
| **Best For** | Simple plugins | ✅ Complex plugins |

## Support

This is an example plugin for educational purposes. For questions about the Dispatcharr plugin system, please refer to the main Dispatcharr documentation.

## License

This example plugin is provided as-is for educational purposes. Use it as a template for your own plugins.
