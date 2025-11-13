"""
Simple Settings Plugin - Example Plugin for Dispatcharr
========================================================

This is a comprehensive example plugin that demonstrates ALL features of the
Dispatcharr plugin system using the Settings Page integration pattern.

INTEGRATION PATTERN: Settings Page Accordion
- This plugin's settings appear in the main Settings page
- Settings are organized in collapsible accordion sections
- Best for plugins with simple to moderate configuration needs

FEATURES DEMONSTRATED:
1. All field types (boolean, number, string, select)
2. Sectioned and unsectioned fields
3. Field help text and descriptions
4. Default values
5. Select field with options
6. Plugin actions (buttons that trigger plugin methods)
7. Settings persistence and retrieval
8. Logging and error handling

INSTALLATION:
1. Copy this entire folder to /data/plugins/ on your Dispatcharr server
2. Restart Dispatcharr or use the plugin refresh feature
3. Go to Plugins page and enable "Simple Settings Plugin"
4. Go to Settings page to configure the plugin
5. Plugin settings will appear in their own accordion section

DEVELOPER NOTES:
- navigation field is omitted (defaults to False)
- This means settings appear in Settings page, not as a separate nav item
- Use this pattern for plugins that don't need a dedicated page
"""

class Plugin:
    # ============================================================================
    # PLUGIN METADATA
    # ============================================================================
    
    # Plugin name - appears in UI
    name = "Simple Settings Plugin"
    
    # Version string - displayed in plugin card
    version = "1.0.0"
    
    # Description - shown in plugin card and settings page
    description = "Example plugin demonstrating Settings page integration with all field types and features"
    
    # Navigation integration - OMITTED (defaults to False)
    # When False or omitted, plugin settings appear in Settings page accordion
    # navigation = False  # <-- This is the default, no need to specify
    
    # ============================================================================
    # SETTINGS FIELDS
    # ============================================================================
    
    fields = [
        # ------------------------------------------------------------------------
        # UNSECTIONED FIELDS
        # These appear at the top of the plugin's accordion, before any sections
        # ------------------------------------------------------------------------
        
        {
            "id": "enabled",
            "label": "Enable Plugin",
            "type": "boolean",
            "default": True,
            "help_text": "Master switch to enable/disable this plugin. This is an unsectioned field."
        },
        
        {
            "id": "plugin_mode",
            "label": "Plugin Mode",
            "type": "select",
            "default": "automatic",
            "options": [
                {"value": "automatic", "label": "Automatic Mode"},
                {"value": "manual", "label": "Manual Mode"},
                {"value": "disabled", "label": "Disabled"},
            ],
            "help_text": "Select the operating mode for this plugin. This is also unsectioned."
        },
        
        # ------------------------------------------------------------------------
        # GENERAL SECTION
        # Basic configuration options grouped together
        # ------------------------------------------------------------------------
        
        {
            "id": "api_endpoint",
            "label": "API Endpoint URL",
            "type": "string",
            "default": "https://api.example.com",
            "section": "General",
            "help_text": "The base URL for the external API this plugin connects to"
        },
        
        {
            "id": "api_key",
            "label": "API Key",
            "type": "string",
            "default": "",
            "section": "General",
            "help_text": "Your API key for authentication. Leave blank if not required."
        },
        
        {
            "id": "timeout",
            "label": "Request Timeout (seconds)",
            "type": "number",
            "default": 30,
            "section": "General",
            "help_text": "How long to wait for API responses before timing out"
        },
        
        {
            "id": "verify_ssl",
            "label": "Verify SSL Certificates",
            "type": "boolean",
            "default": True,
            "section": "General",
            "help_text": "Enable SSL certificate verification for secure connections"
        },
        
        # ------------------------------------------------------------------------
        # ADVANCED SECTION
        # Advanced options for power users
        # ------------------------------------------------------------------------
        
        {
            "id": "debug_mode",
            "label": "Debug Mode",
            "type": "boolean",
            "default": False,
            "section": "Advanced",
            "help_text": "Enable verbose logging for troubleshooting"
        },
        
        {
            "id": "max_retries",
            "label": "Maximum Retries",
            "type": "number",
            "default": 3,
            "section": "Advanced",
            "help_text": "Number of times to retry failed requests"
        },
        
        {
            "id": "retry_delay",
            "label": "Retry Delay (seconds)",
            "type": "number",
            "default": 5,
            "section": "Advanced",
            "help_text": "Time to wait between retry attempts"
        },
        
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
        
        # ------------------------------------------------------------------------
        # PERFORMANCE SECTION
        # Performance tuning options
        # ------------------------------------------------------------------------
        
        {
            "id": "enable_cache",
            "label": "Enable Caching",
            "type": "boolean",
            "default": True,
            "section": "Performance",
            "help_text": "Cache API responses to improve performance"
        },
        
        {
            "id": "cache_ttl",
            "label": "Cache TTL (seconds)",
            "type": "number",
            "default": 300,
            "section": "Performance",
            "help_text": "How long to keep cached data before refreshing"
        },
        
        {
            "id": "max_concurrent_requests",
            "label": "Max Concurrent Requests",
            "type": "number",
            "default": 5,
            "section": "Performance",
            "help_text": "Maximum number of simultaneous API requests"
        },
        
        {
            "id": "rate_limit_mode",
            "label": "Rate Limiting",
            "type": "select",
            "default": "adaptive",
            "section": "Performance",
            "options": [
                {"value": "none", "label": "No Rate Limiting"},
                {"value": "fixed", "label": "Fixed Rate Limit"},
                {"value": "adaptive", "label": "Adaptive Rate Limiting"},
            ],
            "help_text": "How to handle API rate limits"
        },
        
        # ------------------------------------------------------------------------
        # NOTIFICATIONS SECTION
        # Notification preferences
        # ------------------------------------------------------------------------
        
        {
            "id": "enable_notifications",
            "label": "Enable Notifications",
            "type": "boolean",
            "default": True,
            "section": "Notifications",
            "help_text": "Show notifications for plugin events"
        },
        
        {
            "id": "notification_level",
            "label": "Notification Level",
            "type": "select",
            "default": "important",
            "section": "Notifications",
            "options": [
                {"value": "all", "label": "All Events"},
                {"value": "important", "label": "Important Events Only"},
                {"value": "errors", "label": "Errors Only"},
            ],
            "help_text": "Which events should trigger notifications"
        },
        
        {
            "id": "notification_sound",
            "label": "Notification Sound",
            "type": "boolean",
            "default": False,
            "section": "Notifications",
            "help_text": "Play a sound when notifications appear"
        },
    ]
    
    # ============================================================================
    # PLUGIN ACTIONS
    # ============================================================================
    # Actions appear as buttons in the plugin card on the Plugins page
    # When clicked, they call the run() method with the action ID
    
    actions = [
        {
            "id": "test_connection",
            "label": "Test Connection",
            "description": "Test the API connection with current settings"
        },
        {
            "id": "clear_cache",
            "label": "Clear Cache",
            "description": "Clear all cached data"
        },
        {
            "id": "generate_report",
            "label": "Generate Report",
            "description": "Generate a status report with current statistics"
        },
    ]
    
    # ============================================================================
    # PLUGIN METHODS
    # ============================================================================
    
    def run(self, action: str, params: dict, context: dict):
        """
        Execute a plugin action.
        
        This method is called when:
        1. A user clicks an action button in the plugin card
        2. The plugin is triggered by a scheduled task
        3. Another plugin or system component invokes this plugin
        
        Args:
            action (str): The action ID from the actions list
            params (dict): Additional parameters passed to the action
            context (dict): Context provided by Dispatcharr, includes:
                - settings: Current plugin settings (dict)
                - logger: Logger instance for this plugin
                - user: User who triggered the action (if applicable)
        
        Returns:
            dict: Response with status and message
                - status: "success", "error", or "warning"
                - message: Human-readable message to display
                - data: Optional additional data
        """
        
        # Extract context
        settings = context.get("settings", {})
        logger = context.get("logger")
        
        # Log the action
        if logger:
            logger.info(f"Simple Settings Plugin: Executing action '{action}'")
            logger.debug(f"Settings: {settings}")
            logger.debug(f"Params: {params}")
        
        # ========================================================================
        # ACTION: Test Connection
        # ========================================================================
        if action == "test_connection":
            api_endpoint = settings.get("api_endpoint", "")
            api_key = settings.get("api_key", "")
            timeout = settings.get("timeout", 30)
            
            if logger:
                logger.info(f"Testing connection to {api_endpoint}")
            
            # In a real plugin, you would make an actual API call here
            # For this example, we'll simulate a successful connection
            
            if not api_endpoint:
                return {
                    "status": "error",
                    "message": "API endpoint is not configured. Please set it in Settings."
                }
            
            # Simulate connection test
            return {
                "status": "success",
                "message": f"Successfully connected to {api_endpoint}",
                "data": {
                    "endpoint": api_endpoint,
                    "timeout": timeout,
                    "ssl_verify": settings.get("verify_ssl", True)
                }
            }
        
        # ========================================================================
        # ACTION: Clear Cache
        # ========================================================================
        elif action == "clear_cache":
            cache_enabled = settings.get("enable_cache", True)
            
            if not cache_enabled:
                return {
                    "status": "warning",
                    "message": "Cache is not enabled. Nothing to clear."
                }
            
            if logger:
                logger.info("Clearing plugin cache")
            
            # In a real plugin, you would clear the actual cache here
            
            return {
                "status": "success",
                "message": "Cache cleared successfully",
                "data": {
                    "items_cleared": 42,  # Example data
                    "cache_size_before": "2.5 MB",
                    "cache_size_after": "0 MB"
                }
            }
        
        # ========================================================================
        # ACTION: Generate Report
        # ========================================================================
        elif action == "generate_report":
            if logger:
                logger.info("Generating status report")
            
            # Collect current settings for the report
            report_data = {
                "plugin_name": self.name,
                "plugin_version": self.version,
                "enabled": settings.get("enabled", False),
                "mode": settings.get("plugin_mode", "unknown"),
                "api_endpoint": settings.get("api_endpoint", "not configured"),
                "cache_enabled": settings.get("enable_cache", False),
                "debug_mode": settings.get("debug_mode", False),
                "notifications_enabled": settings.get("enable_notifications", False),
            }
            
            return {
                "status": "success",
                "message": "Report generated successfully",
                "data": report_data
            }
        
        # ========================================================================
        # UNKNOWN ACTION
        # ========================================================================
        else:
            if logger:
                logger.warning(f"Unknown action requested: {action}")
            
            return {
                "status": "error",
                "message": f"Unknown action: {action}"
            }
