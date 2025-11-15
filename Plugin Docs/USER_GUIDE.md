# Dispatcharr Plugin System - User Guide

## Table of Contents

1. [Introduction](#introduction)
2. [Accessing the Plugins Page](#accessing-the-plugins-page)
3. [Installing Plugins](#installing-plugins)
4. [Enabling and Disabling Plugins](#enabling-and-disabling-plugins)
5. [Configuring Plugin Settings](#configuring-plugin-settings)
6. [Running Plugin Actions](#running-plugin-actions)
7. [Managing Plugins](#managing-plugins)
8. [Understanding Plugin Types](#understanding-plugin-types)
9. [Troubleshooting](#troubleshooting)

---

## Introduction

The Dispatcharr Plugin System allows you to extend the functionality of your Dispatcharr instance with custom features and integrations. Plugins are Python-based extensions that can:

- Add new features and capabilities to Dispatcharr
- Integrate with external services and APIs
- Automate tasks and workflows
- Process and transform data
- Extend the user interface with dedicated pages

This guide will walk you through everything you need to know to install, configure, and use plugins as an end user.

---

## Accessing the Plugins Page

1. **Navigate to the Plugins page** by clicking the **"Plugins"** link in the left sidebar navigation menu
2. The Plugins page displays all discovered plugins in a card-based layout
3. Each plugin card shows:
   - Plugin logo or placeholder icon
   - Plugin name and version
   - Plugin description
   - Enable/Disable toggle switch
   - Settings button (when enabled and has settings)
   - Delete button (to remove the plugin)

---

## Installing Plugins

### Method 1: Import from ZIP File

1. **Obtain a plugin ZIP file** from a trusted source
2. On the Plugins page, click the **"Import Plugin"** button in the top-right corner
3. In the import modal:
   - Click the dropzone area or drag-and-drop your plugin ZIP file
   - The file will be uploaded and extracted automatically
4. After successful import:
   - The plugin information (name, version, description) will be displayed
   - You can choose to enable the plugin immediately or leave it disabled
5. Click **"Close"** to finish the import process

### Method 2: Manual Installation (Advanced)

If you have direct access to the Dispatcharr server:

1. Navigate to the plugins directory: `/app/data/plugins/` (inside the container)
2. Create a new folder for your plugin (e.g., `my_plugin`)
3. Place the plugin files inside this folder
4. On the Plugins page, click the **"Reload"** button (refresh icon) to discover the new plugin

**Note:** The plugin folder name will be used as the plugin key (lowercased, spaces replaced with underscores).

---

## Enabling and Disabling Plugins

### First-Time Enable (Trust Warning)

When you enable a plugin for the first time, Dispatcharr will display a **trust warning modal**:

- **Warning:** Plugins run server-side Python code with full application permissions
- **Security:** Only enable plugins from trusted sources
- **Confirmation:** You must acknowledge the warning to proceed

### Enabling a Plugin

1. Locate the plugin card on the Plugins page
2. Click the **toggle switch** in the top-right corner of the card
3. If this is the first time enabling the plugin, read and accept the trust warning
4. The plugin will be enabled and the card will appear at full opacity
5. **Real-time update:** The plugin will immediately appear in the appropriate location:
   - **Basic plugins:** Added to the Settings page accordion
   - **Advanced plugins:** Added to the sidebar navigation menu

### Disabling a Plugin

1. Click the **toggle switch** to turn it off
2. The plugin card will dim (reduced opacity)
3. **Real-time update:** The plugin will be removed from Settings/Sidebar immediately
4. **Note:** Disabled plugins cannot run actions (backend returns HTTP 403 error)

---

## Configuring Plugin Settings

Plugins can have configurable settings that control their behavior. There are two ways to access plugin settings depending on the plugin type:

### Basic Plugins (Settings Page Integration)

1. **Enable the plugin** first (if not already enabled)
2. Navigate to the **Settings** page from the sidebar
3. Scroll down to find the plugin's accordion section
4. Click on the plugin name to expand the accordion
5. Configure the settings:
   - Settings may be organized into **collapsible sections** for better organization
   - Each section can be expanded/collapsed independently
   - The first section is expanded by default
6. **Auto-save:** Settings are automatically saved when you change them (no save button needed)

### Advanced Plugins (Dedicated Page)

1. **Enable the plugin** first (if not already enabled)
2. The plugin will appear in the **sidebar navigation menu**
3. Click on the plugin name in the sidebar to open its dedicated page
4. Configure the settings:
   - Settings are organized into **accordion sections**
   - Unsectioned fields appear in a "General Settings" section
   - Sectioned fields are grouped under their respective section names
5. **Auto-save:** Settings are automatically saved when you change them

### Setting Types

Plugins can have different types of settings:

- **Boolean (Switch):** On/Off toggle switches
- **Number:** Numeric input fields
- **String (Text):** Text input fields
- **Select (Dropdown):** Dropdown menus with predefined options

Each setting may include:

- **Label:** The setting name
- **Description/Help Text:** Additional information about the setting
- **Default Value:** The initial value before any changes

---

## Running Plugin Actions

Plugins can define **actions** - operations that you can trigger manually by clicking a button. Actions might perform tasks like:

- Refreshing data from external sources
- Processing or transforming content
- Generating reports or exports
- Triggering background jobs
- Performing maintenance tasks

### How to Run Actions

#### From Settings Page (Basic Plugins)

1. Navigate to the **Settings** page
2. Expand the plugin's accordion section
3. Scroll down to the **"Actions"** section (below the settings fields)
4. Each action displays:
   - **Action name** (label)
   - **Description** (if provided)
   - **Run button**
5. Click the **"Run"** button to execute the action
6. If the action requires confirmation, a modal will appear:
   - Read the confirmation message carefully
   - Click **"Confirm"** to proceed or **"Cancel"** to abort
7. The button will show **"Running…"** while the action executes
8. After completion:
   - **Success:** A green notification appears with the result message
   - **Error:** A red notification appears with the error details
   - **Output files:** File paths are displayed below the action buttons

#### From Plugin Page (Advanced Plugins)

1. Navigate to the plugin's dedicated page from the sidebar
2. Scroll down to the **"Actions"** section
3. Follow the same process as above

### Action Results

After running an action, you may see:

- **Success message:** Displayed in a green notification
- **Error message:** Displayed in a red notification and below the action buttons
- **Output file path:** Displayed below the action buttons (e.g., "Output: /app/data/export.m3u")
- **Status updates:** Some actions may send real-time WebSocket updates

---

## Managing Plugins

### Reloading Plugin Discovery

If you manually add plugins to the server or make changes to plugin files:

1. Click the **"Reload"** button (refresh icon) in the top-right corner of the Plugins page
2. Dispatcharr will re-scan the plugins directory and update the plugin list
3. New plugins will appear as disabled by default

### Deleting Plugins

**Warning:** Deleting a plugin removes all its files from the server. This action cannot be undone.

1. Locate the plugin card on the Plugins page
2. Click the **"Delete"** button (trash icon) at the bottom of the card
3. Confirm the deletion in the modal dialog
4. The plugin files will be permanently removed from the server
5. The plugin card will disappear from the Plugins page

**Note:** You can delete both enabled and disabled plugins. If the plugin is enabled, it will be automatically disabled before deletion.

---

## Understanding Plugin Types

Dispatcharr supports two types of plugins, each with different integration patterns:

### Basic Plugins (Settings Page Integration)

**Characteristics:**

- Appear in the **Settings page** accordion when enabled
- Do not have a dedicated navigation menu item
- Ideal for simple utilities and background tasks
- Settings and actions are accessed from the Settings page

**Use Cases:**

- Data refresh utilities
- Batch processing tools
- Simple integrations
- Background automation tasks

**Example:** A "Refresh All Sources" plugin that triggers M3U and EPG refreshes

### Advanced Plugins (Dedicated Page with Navigation)

**Characteristics:**

- Appear in the **sidebar navigation menu** when enabled
- Have a dedicated page with full UI control
- Do not appear in the Settings page accordion
- Ideal for complex features requiring more UI space

**Use Cases:**

- Complex configuration interfaces
- Data visualization and reporting
- Multi-step workflows
- Feature-rich integrations

**Example:** A streaming output plugin with extensive codec and quality settings

### How to Identify Plugin Type

- **Basic Plugin:** After enabling, look for it in the Settings page accordion
- **Advanced Plugin:** After enabling, look for it in the sidebar navigation menu

---

## Troubleshooting

### Plugin Not Appearing After Import

**Possible Causes:**

- The ZIP file doesn't contain a valid plugin structure
- The plugin folder is missing `plugin.py` or `__init__.py`
- The plugin has import errors or syntax errors

**Solutions:**

1. Check the Dispatcharr server logs for error messages
2. Verify the ZIP file contains the correct structure
3. Click the "Reload" button to re-scan for plugins
4. Contact the plugin developer for support

### Plugin Won't Enable

**Possible Causes:**

- The plugin has initialization errors
- Required dependencies are missing
- Database connection issues

**Solutions:**

1. Check the server logs for detailed error messages
2. Ensure all plugin dependencies are installed
3. Try reloading the plugin discovery
4. Restart the Dispatcharr container if necessary

### Settings Not Saving

**Possible Causes:**

- Network connectivity issues
- Backend API errors
- Plugin is disabled

**Solutions:**

1. Check your browser's developer console for errors
2. Ensure the plugin is enabled
3. Verify network connectivity to the Dispatcharr server
4. Check server logs for API errors

### Actions Failing with HTTP 403 Error

**Cause:** The plugin is disabled

**Solution:** Enable the plugin using the toggle switch on the Plugins page

### Actions Not Completing

**Possible Causes:**

- Long-running operations timing out
- Backend errors during execution
- Missing permissions or resources

**Solutions:**

1. Check the notification messages for error details
2. Review server logs for detailed error information
3. Verify the plugin settings are correct
4. Ensure required resources (files, APIs, etc.) are accessible

### Real-Time Updates Not Working

**Possible Causes:**

- WebSocket connection issues
- Browser tab in background (some browsers throttle background tabs)

**Solutions:**

1. Refresh the page to re-establish WebSocket connection
2. Check browser console for WebSocket errors
3. Ensure the Dispatcharr server is running and accessible

---

## Best Practices

### Security

- **Only install plugins from trusted sources** - Plugins run with full server permissions
- **Review plugin descriptions and documentation** before enabling
- **Keep plugins updated** to the latest versions for security patches
- **Disable unused plugins** to reduce attack surface

### Performance

- **Disable plugins you don't use** to reduce resource consumption
- **Monitor server logs** for plugin errors or warnings
- **Use actions judiciously** - Some actions may be resource-intensive

### Maintenance

- **Regularly check for plugin updates** from plugin developers
- **Review plugin settings periodically** to ensure they're still appropriate
- **Clean up old or unused plugins** to keep your instance organized
- **Backup plugin settings** before making major changes

---

## Getting Help

If you encounter issues with plugins:

1. **Check this documentation** for common solutions
2. **Review server logs** for detailed error messages
3. **Contact the plugin developer** for plugin-specific issues
4. **Visit the Dispatcharr community forums** for general support
5. **Report bugs** to the plugin developer or Dispatcharr project

---

## Additional Resources

- **Developer Documentation:** See the developer guides for creating your own plugins
- **Plugin Repository:** Check the official Dispatcharr plugin repository for available plugins
- **Community Plugins:** Explore community-created plugins (use at your own risk)
- **API Documentation:** Review the Dispatcharr API docs for advanced integrations

---

**Last Updated:** November 2025
**Dispatcharr Version:** 1.0+
**Plugin System Version:** 2.0 (with navigation and sections support)
