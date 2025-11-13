"""
Advanced Navigation Plugin - Example Plugin for Dispatcharr
============================================================

This is a comprehensive example plugin that demonstrates ALL features of the
Dispatcharr plugin system using the Navigation Page integration pattern.

INTEGRATION PATTERN: Dedicated Navigation Page
- This plugin gets its own item in the main navigation menu
- Clicking it navigates to a dedicated page for this plugin
- Settings are displayed on the dedicated page with more screen real estate
- Best for plugins with extensive configuration or complex workflows

FEATURES DEMONSTRATED:
1. Navigation integration (navigation = True)
2. All field types (boolean, number, string, select)
3. Multiple sections with many fields
4. Complex configuration scenarios
5. Multiple plugin actions
6. Advanced settings organization
7. Settings persistence and retrieval
8. Logging and error handling

INSTALLATION:
1. Copy this entire folder to /data/plugins/ on your Dispatcharr server
2. Restart Dispatcharr or use the plugin refresh feature
3. Go to Plugins page and enable "Advanced Navigation Plugin"
4. Look for "Advanced Navigation Plugin" in the main navigation menu
5. Click it to access the dedicated plugin page with all settings

DEVELOPER NOTES:
- navigation = True enables dedicated page integration
- Plugin name appears in main navigation menu
- Settings appear on dedicated page at /plugin/{plugin_key}
- Does NOT appear in Settings page accordion
- Use this pattern for plugins needing extensive configuration
"""

class Plugin:
    # ============================================================================
    # PLUGIN METADATA
    # ============================================================================
    
    # Plugin name - appears in UI and navigation menu
    name = "Advanced Navigation Plugin"
    
    # Version string - displayed in plugin card
    version = "2.0.0"
    
    # Description - shown in plugin card and dedicated page
    description = "Example plugin demonstrating Navigation page integration with extensive configuration options and advanced features"
    
    # Navigation integration - ENABLED
    # When True, plugin gets its own navigation menu item and dedicated page
    # Plugin will NOT appear in Settings page accordion
    navigation = True  # <-- This is the key difference from simple plugins
    
    # ============================================================================
    # SETTINGS FIELDS
    # ============================================================================
    # With navigation=True, you can have many more fields since they appear
    # on a dedicated page with more screen real estate
    
    fields = [
        # ------------------------------------------------------------------------
        # UNSECTIONED FIELDS
        # These appear at the top of the plugin page, before any sections
        # ------------------------------------------------------------------------
        
        {
            "id": "master_enable",
            "label": "Enable Advanced Features",
            "type": "boolean",
            "default": True,
            "help_text": "Master switch to enable/disable all advanced features of this plugin"
        },
        
        {
            "id": "operation_mode",
            "label": "Operation Mode",
            "type": "select",
            "default": "production",
            "options": [
                {"value": "development", "label": "Development (Testing)"},
                {"value": "staging", "label": "Staging (Pre-Production)"},
                {"value": "production", "label": "Production (Live)"},
            ],
            "help_text": "Select the environment mode for this plugin"
        },
        
        # ------------------------------------------------------------------------
        # CONNECTION SETTINGS SECTION
        # External service connection configuration
        # ------------------------------------------------------------------------
        
        {
            "id": "primary_endpoint",
            "label": "Primary API Endpoint",
            "type": "string",
            "default": "https://api.primary.example.com",
            "section": "Connection Settings",
            "help_text": "Primary API endpoint URL"
        },
        
        {
            "id": "fallback_endpoint",
            "label": "Fallback API Endpoint",
            "type": "string",
            "default": "https://api.fallback.example.com",
            "section": "Connection Settings",
            "help_text": "Fallback endpoint used when primary is unavailable"
        },
        
        {
            "id": "api_key",
            "label": "API Key",
            "type": "string",
            "default": "",
            "section": "Connection Settings",
            "help_text": "Your API authentication key"
        },
        
        {
            "id": "api_secret",
            "label": "API Secret",
            "type": "string",
            "default": "",
            "section": "Connection Settings",
            "help_text": "Your API secret for secure authentication"
        },
        
        {
            "id": "connection_timeout",
            "label": "Connection Timeout (seconds)",
            "type": "number",
            "default": 30,
            "section": "Connection Settings",
            "help_text": "Maximum time to wait for connection establishment"
        },
        
        {
            "id": "read_timeout",
            "label": "Read Timeout (seconds)",
            "type": "number",
            "default": 60,
            "section": "Connection Settings",
            "help_text": "Maximum time to wait for data from the server"
        },
        
        {
            "id": "verify_ssl",
            "label": "Verify SSL Certificates",
            "type": "boolean",
            "default": True,
            "section": "Connection Settings",
            "help_text": "Enable SSL certificate verification"
        },
        
        {
            "id": "use_proxy",
            "label": "Use Proxy Server",
            "type": "boolean",
            "default": False,
            "section": "Connection Settings",
            "help_text": "Route requests through a proxy server"
        },
        
        {
            "id": "proxy_url",
            "label": "Proxy URL",
            "type": "string",
            "default": "",
            "section": "Connection Settings",
            "help_text": "Proxy server URL (e.g., http://proxy.example.com:8080)"
        },
        
        # ------------------------------------------------------------------------
        # PROCESSING SETTINGS SECTION
        # Data processing and transformation options
        # ------------------------------------------------------------------------
        
        {
            "id": "enable_processing",
            "label": "Enable Data Processing",
            "type": "boolean",
            "default": True,
            "section": "Processing Settings",
            "help_text": "Enable automatic data processing and transformation"
        },
        
        {
            "id": "processing_mode",
            "label": "Processing Mode",
            "type": "select",
            "default": "balanced",
            "section": "Processing Settings",
            "options": [
                {"value": "fast", "label": "Fast (Lower Quality)"},
                {"value": "balanced", "label": "Balanced (Recommended)"},
                {"value": "quality", "label": "Quality (Slower)"},
            ],
            "help_text": "Balance between speed and quality"
        },
        
        {
            "id": "batch_size",
            "label": "Batch Size",
            "type": "number",
            "default": 100,
            "section": "Processing Settings",
            "help_text": "Number of items to process in each batch"
        },
        
        {
            "id": "parallel_workers",
            "label": "Parallel Workers",
            "type": "number",
            "default": 4,
            "section": "Processing Settings",
            "help_text": "Number of parallel processing workers"
        },
        
        {
            "id": "enable_validation",
            "label": "Enable Data Validation",
            "type": "boolean",
            "default": True,
            "section": "Processing Settings",
            "help_text": "Validate data before processing"
        },
        
        {
            "id": "validation_level",
            "label": "Validation Level",
            "type": "select",
            "default": "standard",
            "section": "Processing Settings",
            "options": [
                {"value": "basic", "label": "Basic Validation"},
                {"value": "standard", "label": "Standard Validation"},
                {"value": "strict", "label": "Strict Validation"},
            ],
            "help_text": "How strictly to validate incoming data"
        },
        
        # ------------------------------------------------------------------------
        # CACHING & PERFORMANCE SECTION
        # Performance optimization settings
        # ------------------------------------------------------------------------
        
        {
            "id": "enable_cache",
            "label": "Enable Caching",
            "type": "boolean",
            "default": True,
            "section": "Caching & Performance",
            "help_text": "Cache responses to improve performance"
        },
        
        {
            "id": "cache_backend",
            "label": "Cache Backend",
            "type": "select",
            "default": "memory",
            "section": "Caching & Performance",
            "options": [
                {"value": "memory", "label": "In-Memory (Fast, Volatile)"},
                {"value": "redis", "label": "Redis (Fast, Persistent)"},
                {"value": "disk", "label": "Disk (Slower, Persistent)"},
            ],
            "help_text": "Where to store cached data"
        },
        
        {
            "id": "cache_ttl",
            "label": "Cache TTL (seconds)",
            "type": "number",
            "default": 300,
            "section": "Caching & Performance",
            "help_text": "How long to keep cached data"
        },
        
        {
            "id": "cache_max_size",
            "label": "Max Cache Size (MB)",
            "type": "number",
            "default": 100,
            "section": "Caching & Performance",
            "help_text": "Maximum cache size in megabytes"
        },
        
        {
            "id": "enable_compression",
            "label": "Enable Compression",
            "type": "boolean",
            "default": True,
            "section": "Caching & Performance",
            "help_text": "Compress cached data to save space"
        },
        
        {
            "id": "max_concurrent_requests",
            "label": "Max Concurrent Requests",
            "type": "number",
            "default": 10,
            "section": "Caching & Performance",
            "help_text": "Maximum simultaneous API requests"
        },
        
        {
            "id": "request_queue_size",
            "label": "Request Queue Size",
            "type": "number",
            "default": 1000,
            "section": "Caching & Performance",
            "help_text": "Maximum number of queued requests"
        },
        
        # ------------------------------------------------------------------------
        # RETRY & ERROR HANDLING SECTION
        # Resilience and error recovery settings
        # ------------------------------------------------------------------------
        
        {
            "id": "enable_retry",
            "label": "Enable Automatic Retry",
            "type": "boolean",
            "default": True,
            "section": "Retry & Error Handling",
            "help_text": "Automatically retry failed requests"
        },
        
        {
            "id": "max_retries",
            "label": "Maximum Retries",
            "type": "number",
            "default": 3,
            "section": "Retry & Error Handling",
            "help_text": "Number of retry attempts for failed requests"
        },
        
        {
            "id": "retry_delay",
            "label": "Initial Retry Delay (seconds)",
            "type": "number",
            "default": 5,
            "section": "Retry & Error Handling",
            "help_text": "Initial delay before first retry"
        },
        
        {
            "id": "retry_strategy",
            "label": "Retry Strategy",
            "type": "select",
            "default": "exponential",
            "section": "Retry & Error Handling",
            "options": [
                {"value": "fixed", "label": "Fixed Delay"},
                {"value": "linear", "label": "Linear Backoff"},
                {"value": "exponential", "label": "Exponential Backoff"},
            ],
            "help_text": "How to calculate delay between retries"
        },
        
        {
            "id": "circuit_breaker_enabled",
            "label": "Enable Circuit Breaker",
            "type": "boolean",
            "default": True,
            "section": "Retry & Error Handling",
            "help_text": "Stop requests after too many failures"
        },
        
        {
            "id": "circuit_breaker_threshold",
            "label": "Circuit Breaker Threshold",
            "type": "number",
            "default": 5,
            "section": "Retry & Error Handling",
            "help_text": "Number of failures before opening circuit"
        },
        
        {
            "id": "circuit_breaker_timeout",
            "label": "Circuit Breaker Timeout (seconds)",
            "type": "number",
            "default": 60,
            "section": "Retry & Error Handling",
            "help_text": "How long to wait before retrying after circuit opens"
        },
        
        # ------------------------------------------------------------------------
        # LOGGING & MONITORING SECTION
        # Logging and monitoring configuration
        # ------------------------------------------------------------------------
        
        {
            "id": "enable_logging",
            "label": "Enable Logging",
            "type": "boolean",
            "default": True,
            "section": "Logging & Monitoring",
            "help_text": "Enable plugin logging"
        },
        
        {
            "id": "log_level",
            "label": "Log Level",
            "type": "select",
            "default": "info",
            "section": "Logging & Monitoring",
            "options": [
                {"value": "debug", "label": "Debug (Most Verbose)"},
                {"value": "info", "label": "Info"},
                {"value": "warning", "label": "Warning"},
                {"value": "error", "label": "Error (Least Verbose)"},
            ],
            "help_text": "Logging verbosity level"
        },
        
        {
            "id": "log_requests",
            "label": "Log All Requests",
            "type": "boolean",
            "default": False,
            "section": "Logging & Monitoring",
            "help_text": "Log every API request (can be verbose)"
        },
        
        {
            "id": "log_responses",
            "label": "Log All Responses",
            "type": "boolean",
            "default": False,
            "section": "Logging & Monitoring",
            "help_text": "Log every API response (can be verbose)"
        },
        
        {
            "id": "enable_metrics",
            "label": "Enable Metrics Collection",
            "type": "boolean",
            "default": True,
            "section": "Logging & Monitoring",
            "help_text": "Collect performance metrics"
        },
        
        {
            "id": "metrics_interval",
            "label": "Metrics Collection Interval (seconds)",
            "type": "number",
            "default": 60,
            "section": "Logging & Monitoring",
            "help_text": "How often to collect metrics"
        },
        
        # ------------------------------------------------------------------------
        # NOTIFICATIONS SECTION
        # Notification and alerting settings
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
            "help_text": "Which events trigger notifications"
        },
        
        {
            "id": "notification_sound",
            "label": "Notification Sound",
            "type": "boolean",
            "default": False,
            "section": "Notifications",
            "help_text": "Play sound for notifications"
        },
        
        {
            "id": "email_notifications",
            "label": "Email Notifications",
            "type": "boolean",
            "default": False,
            "section": "Notifications",
            "help_text": "Send email notifications for critical events"
        },
        
        {
            "id": "email_address",
            "label": "Email Address",
            "type": "string",
            "default": "",
            "section": "Notifications",
            "help_text": "Email address for notifications"
        },
        
        # ------------------------------------------------------------------------
        # ADVANCED FEATURES SECTION
        # Advanced and experimental features
        # ------------------------------------------------------------------------
        
        {
            "id": "enable_webhooks",
            "label": "Enable Webhooks",
            "type": "boolean",
            "default": False,
            "section": "Advanced Features",
            "help_text": "Enable webhook support for external integrations"
        },
        
        {
            "id": "webhook_url",
            "label": "Webhook URL",
            "type": "string",
            "default": "",
            "section": "Advanced Features",
            "help_text": "URL to send webhook notifications"
        },
        
        {
            "id": "enable_api",
            "label": "Enable Plugin API",
            "type": "boolean",
            "default": False,
            "section": "Advanced Features",
            "help_text": "Expose plugin functionality via API"
        },
        
        {
            "id": "api_rate_limit",
            "label": "API Rate Limit (requests/minute)",
            "type": "number",
            "default": 60,
            "section": "Advanced Features",
            "help_text": "Maximum API requests per minute"
        },
        
        {
            "id": "enable_scheduling",
            "label": "Enable Scheduled Tasks",
            "type": "boolean",
            "default": False,
            "section": "Advanced Features",
            "help_text": "Enable automatic scheduled task execution"
        },
        
        {
            "id": "schedule_interval",
            "label": "Schedule Interval (minutes)",
            "type": "number",
            "default": 60,
            "section": "Advanced Features",
            "help_text": "How often to run scheduled tasks"
        },
        
        {
            "id": "experimental_features",
            "label": "Enable Experimental Features",
            "type": "boolean",
            "default": False,
            "section": "Advanced Features",
            "help_text": "Enable experimental features (may be unstable)"
        },
    ]
    
    # ============================================================================
    # PLUGIN ACTIONS
    # ============================================================================
    # More actions for advanced functionality
    
    actions = [
        {
            "id": "test_connection",
            "label": "Test Connection",
            "description": "Test connectivity to all configured endpoints"
        },
        {
            "id": "clear_cache",
            "label": "Clear Cache",
            "description": "Clear all cached data"
        },
        {
            "id": "reset_circuit_breaker",
            "label": "Reset Circuit Breaker",
            "description": "Reset the circuit breaker to allow new requests"
        },
        {
            "id": "generate_report",
            "label": "Generate Status Report",
            "description": "Generate comprehensive status and metrics report"
        },
        {
            "id": "export_config",
            "label": "Export Configuration",
            "description": "Export current configuration as JSON"
        },
        {
            "id": "run_diagnostics",
            "label": "Run Diagnostics",
            "description": "Run full system diagnostics and health check"
        },
    ]
    
    # ============================================================================
    # PLUGIN METHODS
    # ============================================================================
    
    def run(self, action: str, params: dict, context: dict):
        """
        Execute a plugin action.
        
        Args:
            action (str): The action ID from the actions list
            params (dict): Additional parameters passed to the action
            context (dict): Context provided by Dispatcharr
        
        Returns:
            dict: Response with status and message
        """
        
        settings = context.get("settings", {})
        logger = context.get("logger")
        
        if logger:
            logger.info(f"Advanced Navigation Plugin: Executing action '{action}'")
        
        # ========================================================================
        # ACTION: Test Connection
        # ========================================================================
        if action == "test_connection":
            primary = settings.get("primary_endpoint", "")
            fallback = settings.get("fallback_endpoint", "")
            
            if not primary:
                return {
                    "status": "error",
                    "message": "Primary endpoint not configured"
                }
            
            return {
                "status": "success",
                "message": f"Successfully tested connections",
                "data": {
                    "primary_endpoint": primary,
                    "fallback_endpoint": fallback,
                    "ssl_verify": settings.get("verify_ssl", True),
                    "proxy_enabled": settings.get("use_proxy", False)
                }
            }
        
        # ========================================================================
        # ACTION: Clear Cache
        # ========================================================================
        elif action == "clear_cache":
            if not settings.get("enable_cache", True):
                return {
                    "status": "warning",
                    "message": "Cache is not enabled"
                }
            
            cache_backend = settings.get("cache_backend", "memory")
            
            return {
                "status": "success",
                "message": f"Cache cleared successfully ({cache_backend} backend)",
                "data": {
                    "backend": cache_backend,
                    "items_cleared": 156,
                    "space_freed": "15.3 MB"
                }
            }
        
        # ========================================================================
        # ACTION: Reset Circuit Breaker
        # ========================================================================
        elif action == "reset_circuit_breaker":
            if not settings.get("circuit_breaker_enabled", True):
                return {
                    "status": "warning",
                    "message": "Circuit breaker is not enabled"
                }
            
            return {
                "status": "success",
                "message": "Circuit breaker reset successfully",
                "data": {
                    "threshold": settings.get("circuit_breaker_threshold", 5),
                    "timeout": settings.get("circuit_breaker_timeout", 60)
                }
            }
        
        # ========================================================================
        # ACTION: Generate Report
        # ========================================================================
        elif action == "generate_report":
            report = {
                "plugin_info": {
                    "name": self.name,
                    "version": self.version,
                    "mode": settings.get("operation_mode", "unknown")
                },
                "connection": {
                    "primary_endpoint": settings.get("primary_endpoint", ""),
                    "fallback_endpoint": settings.get("fallback_endpoint", ""),
                    "ssl_verify": settings.get("verify_ssl", True),
                    "proxy_enabled": settings.get("use_proxy", False)
                },
                "performance": {
                    "cache_enabled": settings.get("enable_cache", True),
                    "cache_backend": settings.get("cache_backend", "memory"),
                    "max_concurrent": settings.get("max_concurrent_requests", 10),
                    "parallel_workers": settings.get("parallel_workers", 4)
                },
                "resilience": {
                    "retry_enabled": settings.get("enable_retry", True),
                    "max_retries": settings.get("max_retries", 3),
                    "circuit_breaker": settings.get("circuit_breaker_enabled", True)
                },
                "monitoring": {
                    "logging_enabled": settings.get("enable_logging", True),
                    "log_level": settings.get("log_level", "info"),
                    "metrics_enabled": settings.get("enable_metrics", True)
                }
            }
            
            return {
                "status": "success",
                "message": "Comprehensive report generated",
                "data": report
            }
        
        # ========================================================================
        # ACTION: Export Configuration
        # ========================================================================
        elif action == "export_config":
            return {
                "status": "success",
                "message": "Configuration exported successfully",
                "data": {
                    "config": settings,
                    "export_time": "2024-11-12T12:00:00Z",
                    "plugin_version": self.version
                }
            }
        
        # ========================================================================
        # ACTION: Run Diagnostics
        # ========================================================================
        elif action == "run_diagnostics":
            diagnostics = {
                "connection_test": "PASS",
                "cache_test": "PASS" if settings.get("enable_cache") else "SKIP",
                "processing_test": "PASS" if settings.get("enable_processing") else "SKIP",
                "validation_test": "PASS" if settings.get("enable_validation") else "SKIP",
                "circuit_breaker_test": "PASS" if settings.get("circuit_breaker_enabled") else "SKIP",
                "overall_health": "HEALTHY"
            }
            
            return {
                "status": "success",
                "message": "Diagnostics completed successfully",
                "data": diagnostics
            }
        
        # ========================================================================
        # UNKNOWN ACTION
        # ========================================================================
        else:
            return {
                "status": "error",
                "message": f"Unknown action: {action}"
            }
