# Dispatcharr Example Plugins

This repository contains comprehensive example plugins that demonstrate **ALL features** of the Dispatcharr plugin system.

## í³¦ Available Example Plugins

### 1. **Simple Settings Plugin** (`simple_settings_plugin/`)
**Integration Pattern:** Settings Page Accordion

A comprehensive example demonstrating the Settings Page integration pattern, where plugin settings appear in the main Settings page alongside core Dispatcharr settings.

**Best For:**
- Plugins with simple to moderate configuration needs
- Plugins that don't need dedicated UI space
- Utility plugins and helpers

**Features:**
- All field types (boolean, number, string, select)
- Sectioned and unsectioned fields
- 4 sections with ~15 total fields
- 3 plugin actions
- Auto-save settings
- Comprehensive documentation

[View Documentation â†’](simple_settings_plugin/README.md)

---

### 2. **Advanced Navigation Plugin** (`advanced_navigation_plugin/`)
**Integration Pattern:** Dedicated Navigation Page

A comprehensive example demonstrating the Navigation Page integration pattern, where the plugin gets its own navigation menu item and dedicated page.

**Best For:**
- Plugins with extensive configuration (many fields)
- Plugins needing more screen real estate
- Plugins with complex workflows
- Major features of your Dispatcharr setup

**Features:**
- Navigation menu integration (`navigation = True`)
- All field types (boolean, number, string, select)
- 7 major sections with 50+ total fields
- 6 plugin actions
- Complex configuration scenarios
- Comprehensive documentation

[View Documentation â†’](advanced_navigation_plugin/README.md)

---

## íº€ Quick Start

### Installation

1. **Choose a plugin** to test (or install both!)
2. **Copy the plugin folder** to your Dispatcharr plugins directory:
   ```bash
   # For Docker/Unraid installations
   cp -r simple_settings_plugin /path/to/dispatcharr/data/plugins/
   cp -r advanced_navigation_plugin /path/to/dispatcharr/data/plugins/
   ```
3. **Restart Dispatcharr** or use the plugin refresh feature
4. **Enable the plugin** from the Plugins page
5. **Configure settings:**
   - **Simple Plugin:** Go to Settings page, find plugin accordion
   - **Advanced Plugin:** Click plugin name in navigation menu

### Testing

Both plugins include:
- âœ… Comprehensive field examples
- âœ… Multiple actions to test
- âœ… Detailed logging
- âœ… Error handling examples
- âœ… Testing checklists in their READMEs

---

## í³š Plugin System Features

### Field Types

All example plugins demonstrate these field types:

| Type | Description | Example Use |
|------|-------------|-------------|
| `boolean` | Switch/toggle | Enable/disable features |
| `number` | Numeric input | Timeouts, limits, intervals |
| `string` | Text input | URLs, API keys, names |
| `select` | Dropdown menu | Modes, levels, strategies |

### Field Properties

```python
{
    "id": "field_name",              # Unique identifier
    "label": "Field Label",          # Display name
    "type": "boolean",               # Field type
    "default": True,                 # Default value
    "help_text": "Help text here",   # Description
    "section": "Section Name",       # Optional grouping
    "options": [...]                 # For select fields
}
```

### Field Organization

- **Unsectioned Fields:** Appear at the top, before any sections
- **Sectioned Fields:** Grouped in collapsible accordions
- **Sections:** Organize related fields together

### Plugin Actions

Actions appear as buttons in the plugin card:

```python
actions = [
    {
        "id": "action_id",
        "label": "Button Label",
        "description": "What this action does"
    }
]
```

### Run Method

The `run()` method handles action execution:

```python
def run(self, action: str, params: dict, context: dict):
    settings = context.get("settings", {})  # Current settings
    logger = context.get("logger")          # Logger instance
    
    # Your action logic here
    
    return {
        "status": "success",  # or "error", "warning"
        "message": "Action completed",
        "data": {...}  # Optional additional data
    }
```

---

## í¾¯ Choosing the Right Pattern

### Use **Settings Page Integration** when:

âœ… Simple to moderate configuration (< 20 fields)  
âœ… Standard field types are sufficient  
âœ… Don't need dedicated UI space  
âœ… Want settings alongside core Dispatcharr settings  
âœ… Plugin is a utility or helper  

**Example:** `simple_settings_plugin`

### Use **Navigation Page Integration** when:

âœ… Extensive configuration (20+ fields)  
âœ… Need more screen real estate  
âœ… Complex workflows or custom UI  
âœ… Want prominent navigation presence  
âœ… Plugin is a major feature  

**Example:** `advanced_navigation_plugin`

---

## í³– Comparison Table

| Feature | Simple Plugin | Advanced Plugin |
|---------|--------------|-----------------|
| **Integration** | Settings page accordion | Dedicated navigation page |
| **Navigation Item** | âŒ No | âœ… Yes |
| **Settings Location** | Settings page | Dedicated page |
| **Screen Space** | Shared with core settings | Full page |
| **Typical Fields** | 10-20 fields | 20-100+ fields |
| **Sections** | 2-5 sections | 5-10+ sections |
| **Best For** | Simple plugins | Complex plugins |
| **Code Difference** | `navigation` omitted | `navigation = True` |

---

## í» ï¸ Development Workflow

### 1. Choose Your Pattern

Decide between Settings Page or Navigation Page integration based on your plugin's complexity.

### 2. Start with Example

Copy the appropriate example plugin as your starting point:
- Simple plugin â†’ `simple_settings_plugin`
- Advanced plugin â†’ `advanced_navigation_plugin`

### 3. Customize

Modify the example to fit your needs:
- Update metadata (name, version, description)
- Define your fields
- Implement your actions
- Add your business logic to `run()` method

### 4. Test

Use the testing checklists in each example's README to verify all features work.

### 5. Deploy

Copy your plugin to `/data/plugins/` and enable it in Dispatcharr.

---

## í³ File Structure

```
Dispatcharr-Example-Plugins/
â”œâ”€â”€ README.md                          # This file
â”œâ”€â”€ simple_settings_plugin/
â”‚   â”œâ”€â”€ plugin.py                      # Simple plugin example
â”‚   â””â”€â”€ README.md                      # Simple plugin docs
â””â”€â”€ advanced_navigation_plugin/
    â”œâ”€â”€ plugin.py                      # Advanced plugin example
    â””â”€â”€ README.md                      # Advanced plugin docs
```

---

## í´ What's Demonstrated

Both example plugins demonstrate:

### Core Features
- âœ… All field types (boolean, number, string, select)
- âœ… Sectioned and unsectioned fields
- âœ… Field properties (id, label, type, default, help_text, section, options)
- âœ… Plugin actions (buttons that trigger methods)
- âœ… Settings persistence (auto-save)
- âœ… Settings retrieval in run() method
- âœ… Logging and error handling
- âœ… Return value structure (status, message, data)

### Integration Patterns
- âœ… **Simple:** Settings page accordion integration
- âœ… **Advanced:** Navigation page integration with `navigation = True`

### Best Practices
- âœ… Comprehensive inline documentation
- âœ… Clear field organization
- âœ… Descriptive help text
- âœ… Proper error handling
- âœ… Logging for debugging
- âœ… Meaningful return values

---

## í²¡ Tips for Plugin Developers

### Field Organization
- Put the most important fields as unsectioned (they appear first)
- Group related fields in sections
- Use descriptive section names
- Order sections from most to least important

### Help Text
- Write clear, concise help text for every field
- Explain what the field does and when to use it
- Include examples or valid ranges where helpful

### Actions
- Keep action IDs simple and descriptive
- Write clear labels and descriptions
- Return meaningful status messages
- Include relevant data in responses

### Logging
- Use appropriate log levels (debug, info, warning, error)
- Log important events and errors
- Include context in log messages
- Don't log sensitive data (API keys, passwords)

### Error Handling
- Validate settings before using them
- Return clear error messages
- Use appropriate status codes (success, error, warning)
- Handle edge cases gracefully

---

## í³ Plugin Metadata Reference

```python
class Plugin:
    # Required fields
    name = "Plugin Name"                    # Display name
    version = "1.0.0"                       # Version string
    description = "Plugin description"      # Short description
    
    # Optional fields
    navigation = False                      # True for dedicated page
    
    # Settings fields
    fields = [...]                          # List of field definitions
    
    # Actions
    actions = [...]                         # List of action definitions
    
    # Run method
    def run(self, action, params, context):
        # Action execution logic
        return {"status": "success", "message": "..."}
```

---

## í·ª Testing Your Plugin

### Basic Testing
1. Install plugin in `/data/plugins/`
2. Restart Dispatcharr
3. Enable plugin from Plugins page
4. Verify settings appear correctly
5. Test all actions
6. Check logs for errors

### Comprehensive Testing
Use the testing checklists in each example's README:
- [Simple Plugin Testing Checklist](simple_settings_plugin/README.md#testing-checklist)
- [Advanced Plugin Testing Checklist](advanced_navigation_plugin/README.md#testing-checklist)

---

## í³ž Support

These are example plugins for educational purposes. For questions about:
- **Dispatcharr Plugin System:** See main Dispatcharr documentation
- **Example Plugins:** Review the README files in each plugin folder
- **Plugin Development:** Study the heavily commented code in `plugin.py` files

---

## í³„ License

These example plugins are provided as-is for educational purposes. Feel free to use them as templates for your own plugins.

---

## í¾‰ Happy Plugin Development!

Start with the example that matches your needs:
- **Simple plugin?** â†’ Use `simple_settings_plugin` as your template
- **Complex plugin?** â†’ Use `advanced_navigation_plugin` as your template

Both examples are heavily documented and demonstrate every feature of the Dispatcharr plugin system. Good luck! íº€
