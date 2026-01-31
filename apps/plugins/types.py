"""Type definitions for the plugin system.

This module contains data classes and type aliases used throughout the plugin
system to provide type safety and documentation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union


class FieldType(str, Enum):
    """Supported field types for plugin settings."""

    BOOLEAN = "boolean"
    NUMBER = "number"
    STRING = "string"
    SELECT = "select"


@dataclass
class SelectOption:
    """An option for select-type fields."""

    value: str
    label: str


@dataclass
class PluginField:
    """Definition of a plugin setting field.

    Fields define the configuration UI rendered for a plugin.
    Values are persisted in PluginConfig.settings.
    """

    id: str
    label: str
    type: FieldType
    default: Any = None
    help_text: str = ""
    options: List[SelectOption] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "id": self.id,
            "label": self.label,
            "type": self.type.value if isinstance(self.type, FieldType) else self.type,
            "default": self.default,
        }
        if self.help_text:
            result["help_text"] = self.help_text
        if self.options:
            result["options"] = [
                {"value": o.value, "label": o.label} if isinstance(o, SelectOption) else o
                for o in self.options
            ]
        return result


@dataclass
class ActionConfirm:
    """Configuration for action confirmation modal."""

    required: bool = True
    title: str = "Confirm Action"
    message: str = "Are you sure you want to proceed?"


@dataclass
class ActionParam:
    """Definition of a parameter for a plugin action."""

    id: str
    label: str
    type: FieldType
    default: Any = None
    required: bool = False
    options: List[SelectOption] = field(default_factory=list)


@dataclass
class PluginAction:
    """Definition of a plugin action.

    Actions appear as buttons in the plugin UI. When clicked, the plugin's
    run() method is called with the action ID.
    """

    id: str
    label: str
    description: str = ""
    confirm: Optional[Union[bool, ActionConfirm]] = None
    params: List[ActionParam] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "id": self.id,
            "label": self.label,
        }
        if self.description:
            result["description"] = self.description
        if self.confirm is not None:
            if isinstance(self.confirm, bool):
                result["confirm"] = self.confirm
            elif isinstance(self.confirm, ActionConfirm):
                result["confirm"] = {
                    "required": self.confirm.required,
                    "title": self.confirm.title,
                    "message": self.confirm.message,
                }
            else:
                result["confirm"] = self.confirm
        if self.params:
            result["params"] = [
                {
                    "id": p.id,
                    "label": p.label,
                    "type": p.type.value if isinstance(p.type, FieldType) else p.type,
                    "default": p.default,
                    "required": p.required,
                }
                if isinstance(p, ActionParam)
                else p
                for p in self.params
            ]
        return result


@dataclass
class PluginContext:
    """Context passed to plugin run() method.

    Provides access to persisted settings, logging, and action metadata.
    """

    settings: Dict[str, Any]
    logger: Any
    actions: Dict[str, Dict[str, Any]]


@dataclass
class PluginResult:
    """Standard result format from plugin actions.

    Plugins can return this directly or a dict with similar structure.
    """

    status: str
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {"status": self.status}
        if self.message:
            result["message"] = self.message
        if self.data:
            result.update(self.data)
        return result


@dataclass
class LoadedPlugin:
    """Represents a successfully loaded plugin in the registry.

    Contains all metadata and references needed to execute the plugin.
    """

    key: str
    name: str
    version: str = ""
    description: str = ""
    module: Any = None
    instance: Any = None
    fields: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Check if the plugin has a valid runnable instance."""
        return self.instance is not None and callable(getattr(self.instance, "run", None))


# Type aliases for backwards compatibility and convenience
PluginFields = List[Union[PluginField, Dict[str, Any]]]
PluginActions = List[Union[PluginAction, Dict[str, Any]]]
RunMethod = Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
