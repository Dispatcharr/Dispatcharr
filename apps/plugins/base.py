"""Base class and protocol for Dispatcharr plugins.

This module provides the formal interface that plugins should implement.
While not strictly required (duck typing works), using PluginBase provides:
- Type hints and IDE autocomplete
- Documentation of the expected interface
- Default implementations for optional methods
- Validation of plugin structure
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from .types import (
    PluginAction,
    PluginContext,
    PluginField,
    PluginResult,
)


class PluginBase(ABC):
    """Abstract base class for Dispatcharr plugins.

    Plugins can inherit from this class to get type hints, documentation,
    and default implementations. The minimal implementation requires:
    - name: Human-readable plugin name
    - run(): Method to handle action execution

    Example:
        class Plugin(PluginBase):
            name = "My Plugin"
            version = "1.0.0"
            description = "Does something useful"

            fields = [
                {"id": "enabled", "label": "Enabled", "type": "boolean", "default": True},
            ]

            actions = [
                {"id": "run_task", "label": "Run Task", "description": "Executes the main task"},
            ]

            def run(self, action: str, params: dict, context: dict) -> dict:
                if action == "run_task":
                    return {"status": "ok", "message": "Task completed"}
                return {"status": "error", "message": f"Unknown action: {action}"}
    """

    # Required: Human-readable name
    name: str = "Unnamed Plugin"

    # Optional metadata
    version: str = ""
    description: str = ""

    # Optional: Settings fields rendered by the UI
    fields: List[Union[PluginField, Dict[str, Any]]] = []

    # Optional: Actions that appear as buttons
    actions: List[Union[PluginAction, Dict[str, Any]]] = []

    @abstractmethod
    def run(
        self,
        action: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a plugin action.

        This method is called when a user clicks an action button in the UI
        or when the action is triggered programmatically.

        Args:
            action: The ID of the action to execute (from self.actions)
            params: Parameters passed with the action request
            context: Runtime context containing:
                - settings: Persisted plugin settings (dict)
                - logger: Configured logger instance
                - actions: Dict mapping action IDs to action definitions

        Returns:
            A dictionary with at minimum a "status" key. Common patterns:
            - {"status": "ok", "message": "Success", ...}
            - {"status": "error", "message": "What went wrong"}
            - {"status": "queued", "message": "Task queued for background processing"}

        Raises:
            Any exception will be caught and returned as an error response.
        """
        pass

    def on_enable(self, context: Dict[str, Any]) -> None:
        """Called when the plugin is enabled.

        Override this method to perform setup tasks when the plugin is enabled.
        This is called after the enabled flag is set in the database.

        Args:
            context: Runtime context (same as run())
        """
        pass

    def on_disable(self, context: Dict[str, Any]) -> None:
        """Called when the plugin is disabled.

        Override this method to perform cleanup tasks when the plugin is disabled.
        This is called after the enabled flag is cleared in the database.

        Args:
            context: Runtime context (same as run())
        """
        pass

    def validate_settings(self, settings: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Validate plugin settings before saving.

        Override this method to add custom validation logic for settings.

        Args:
            settings: The settings dictionary to validate

        Returns:
            None if valid, or a dict mapping field IDs to error messages.

        Example:
            def validate_settings(self, settings):
                errors = {}
                if settings.get("limit", 0) < 1:
                    errors["limit"] = "Limit must be at least 1"
                return errors if errors else None
        """
        return None

    def get_status(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get plugin status information for display.

        Override this method to provide dynamic status information
        that will be displayed in the plugin card.

        Args:
            context: Runtime context (same as run())

        Returns:
            None or a dict with status information, e.g.:
            {"status": "healthy", "message": "Processing 5 items", "details": {...}}
        """
        return None

    # Helper methods for common patterns

    def success(self, message: str = "", **data: Any) -> Dict[str, Any]:
        """Create a success response.

        Args:
            message: Optional success message
            **data: Additional data to include in response

        Returns:
            Response dictionary with status="ok"
        """
        result = {"status": "ok"}
        if message:
            result["message"] = message
        result.update(data)
        return result

    def error(self, message: str, **data: Any) -> Dict[str, Any]:
        """Create an error response.

        Args:
            message: Error message describing what went wrong
            **data: Additional data to include in response

        Returns:
            Response dictionary with status="error"
        """
        result = {"status": "error", "message": message}
        result.update(data)
        return result

    def queued(self, message: str = "Task queued for background processing", **data: Any) -> Dict[str, Any]:
        """Create a queued response for background tasks.

        Args:
            message: Message describing the queued task
            **data: Additional data to include in response

        Returns:
            Response dictionary with status="queued"
        """
        result = {"status": "queued", "message": message}
        result.update(data)
        return result

    def get_setting(
        self,
        context: Dict[str, Any],
        key: str,
        default: Any = None,
    ) -> Any:
        """Get a setting value from context with type coercion.

        Args:
            context: The context dict passed to run()
            key: The setting key to retrieve
            default: Default value if setting is not found

        Returns:
            The setting value or default
        """
        settings = context.get("settings", {})
        return settings.get(key, default)

    def log(self, context: Dict[str, Any], level: str, message: str, *args: Any) -> None:
        """Log a message using the context logger.

        Args:
            context: The context dict passed to run()
            level: Log level ('debug', 'info', 'warning', 'error')
            message: Log message (can use % formatting)
            *args: Arguments for % formatting
        """
        logger = context.get("logger")
        if logger:
            log_method = getattr(logger, level, logger.info)
            log_method(message, *args)
