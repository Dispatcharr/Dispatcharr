# Dispatcharr Plugin System Documentation

Welcome to the Dispatcharr Plugin System documentation! This directory contains comprehensive guides for both users and developers.

---

## 📚 Documentation Overview

### For Users

**[User Guide](USER_GUIDE.md)** - Complete guide for installing, configuring, and using Dispatcharr plugins
- How to access the Plugins page
- Installing plugins (ZIP import and manual installation)
- Enabling and disabling plugins
- Configuring plugin settings
- Running plugin actions
- Managing plugins
- Troubleshooting common issues
- Security best practices

### For Developers

**[Basic Plugin Development Guide](BASIC_PLUGIN_DEVELOPMENT.md)** - Learn to create basic plugins
- Plugin structure and directory layout
- Creating your first plugin
- Plugin class reference
- Settings fields (string, number, boolean, select)
- Organizing settings with collapsible sections
- Plugin actions with confirmation modals
- Accessing Dispatcharr APIs
- Testing and packaging
- Best practices and examples

**[Advanced Plugin Development Guide](ADVANCED_PLUGIN_DEVELOPMENT.md)** - Learn to create advanced plugins with navigation
- What makes a plugin "advanced"
- Navigation integration
- Dedicated plugin pages
- Real-time WebSocket updates
- Complex examples
- Migration from basic to advanced
- Technical details and troubleshooting

---

## 🚀 Quick Start

### I'm a User - How do I use plugins?

1. Read the **[User Guide](USER_GUIDE.md)**
2. Navigate to the Plugins page in Dispatcharr
3. Import a plugin ZIP file or install manually
4. Enable the plugin and configure its settings
5. Use plugin actions as needed

### I'm a Developer - How do I create a plugin?

**For Simple Plugins:**
1. Read the **[Basic Plugin Development Guide](BASIC_PLUGIN_DEVELOPMENT.md)**
2. Create a plugin directory in `/app/data/plugins/`
3. Write a `plugin.py` file with a `Plugin` class
4. Define settings fields and actions
5. Implement the `run` method
6. Test and package your plugin

**For Complex Plugins:**
1. Start with the **[Basic Plugin Development Guide](BASIC_PLUGIN_DEVELOPMENT.md)**
2. Then read the **[Advanced Plugin Development Guide](ADVANCED_PLUGIN_DEVELOPMENT.md)**
3. Set `navigation = True` in your Plugin class
4. Organize settings into logical sections
5. Test on the dedicated plugin page

---

## 🔑 Key Concepts

### Plugin Types

**Basic Plugins** (`navigation = False` or omitted)
- Appear in the Settings page accordion
- Ideal for simple utilities and background tasks
- Limited UI space
- Quick access from Settings

**Advanced Plugins** (`navigation = True`)
- Appear in the sidebar navigation menu
- Have dedicated pages at `/plugin/{plugin_key}`
- Full page UI space
- Ideal for complex features

### Plugin System Features

✅ **Collapsible Sections** - Organize settings into accordion sections  
✅ **Auto-Save Settings** - Settings save automatically on change  
✅ **Plugin Actions** - Executable operations with confirmation modals  
✅ **Real-Time Updates** - WebSocket integration for instant UI updates  
✅ **Navigation Integration** - Advanced plugins appear in sidebar  
✅ **ZIP Import** - Easy plugin installation from ZIP files  
✅ **Trust Warnings** - Security prompts when enabling plugins  

---

## 📖 Documentation Structure

```
Plugin Docs/
├── README.md                           # This file - Documentation overview
├── USER_GUIDE.md                       # For end users
├── BASIC_PLUGIN_DEVELOPMENT.md         # For developers (basic plugins)
└── ADVANCED_PLUGIN_DEVELOPMENT.md      # For developers (advanced plugins)
```

---

## 🎯 Which Guide Should I Read?

**I want to...**

- **Use existing plugins** → [User Guide](USER_GUIDE.md)
- **Create a simple utility plugin** → [Basic Plugin Development Guide](BASIC_PLUGIN_DEVELOPMENT.md)
- **Create a complex feature plugin** → [Basic Plugin Development Guide](BASIC_PLUGIN_DEVELOPMENT.md) + [Advanced Plugin Development Guide](ADVANCED_PLUGIN_DEVELOPMENT.md)
- **Convert a basic plugin to advanced** → [Advanced Plugin Development Guide - Migration Section](ADVANCED_PLUGIN_DEVELOPMENT.md#migration-guide)
- **Understand the plugin system architecture** → [Advanced Plugin Development Guide - Technical Details](ADVANCED_PLUGIN_DEVELOPMENT.md#technical-details)

---

## 🛠️ Plugin System Version

**Current Version:** 2.0

**Features:**
- Collapsible sections support (`section` field attribute)
- Navigation integration (`navigation` plugin attribute)
- Real-time WebSocket updates
- Auto-save settings
- Confirmation modals for actions
- ZIP import/export

**Dispatcharr Compatibility:** 1.0+

---

## 📝 Additional Resources

- **Dispatcharr Main Documentation** - See project root for general Dispatcharr docs
- **Mantine UI Library** - https://mantine.dev/ (Frontend components)
- **Django Framework** - https://www.djangoproject.com/ (Backend framework)
- **Celery** - https://docs.celeryq.dev/ (Task queue for background jobs)

---

## 💡 Examples

Each guide includes complete, working examples:

**Basic Plugin Examples:**
- Hello World plugin
- Data export plugin
- Database maintenance plugin

**Advanced Plugin Examples:**
- Streaming output plugin with extensive codec settings
- Multi-section configuration interfaces

---

## 🤝 Contributing

If you create a plugin and want to share it with the community:

1. Package your plugin as a ZIP file
2. Include a README with installation and usage instructions
3. Test thoroughly across different environments
4. Share on the Dispatcharr community forums or GitHub

---

## 📞 Support

- **User Issues** - Check the [User Guide Troubleshooting Section](USER_GUIDE.md#troubleshooting)
- **Development Questions** - See the respective development guide's troubleshooting section
- **Bug Reports** - Submit to the Dispatcharr GitHub repository
- **Feature Requests** - Discuss in the Dispatcharr community

---

**Last Updated:** November 2025  
**Plugin System Version:** 2.0  
**Dispatcharr Version:** 1.0+

