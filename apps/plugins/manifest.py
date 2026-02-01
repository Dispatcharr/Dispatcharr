"""Plugin manifest (plugin.yaml) parsing and validation."""

import logging
import os
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_manifest(plugin_path: str) -> dict | None:
    """
    Load and parse a plugin.yaml manifest file from the given plugin directory.

    Args:
        plugin_path: Path to the plugin directory.

    Returns:
        The parsed manifest dict if plugin.yaml exists and is valid YAML,
        or None if the file doesn't exist.

    Raises:
        yaml.YAMLError: If the YAML is malformed.
    """
    manifest_path = os.path.join(plugin_path, "plugin.yaml")
    if not os.path.isfile(manifest_path):
        return None

    with open(manifest_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_manifest(data: dict) -> tuple[bool, list[str]]:
    """
    Validate that a manifest dict has all required fields.

    Args:
        data: The parsed manifest dictionary.

    Returns:
        A tuple of (is_valid, list_of_errors).
        If valid, the errors list is empty.
    """
    errors = []

    if not isinstance(data, dict):
        return False, ["Manifest must be a YAML object"]

    plugin = data.get("plugin")
    if not isinstance(plugin, dict):
        errors.append("Missing or invalid 'plugin' section")
        return False, errors

    # Required fields
    if not plugin.get("key"):
        errors.append("Missing required field: plugin.key")
    elif not isinstance(plugin["key"], str):
        errors.append("Field 'plugin.key' must be a string")

    if not plugin.get("name"):
        errors.append("Missing required field: plugin.name")
    elif not isinstance(plugin["name"], str):
        errors.append("Field 'plugin.name' must be a string")

    if not plugin.get("version"):
        errors.append("Missing required field: plugin.version")
    elif not isinstance(plugin["version"], str):
        errors.append("Field 'plugin.version' must be a string")

    # Optional fields - validate types if present
    if "description" in plugin and not isinstance(plugin["description"], str):
        errors.append("Field 'plugin.description' must be a string")

    if "repository" in plugin and not isinstance(plugin["repository"], str):
        errors.append("Field 'plugin.repository' must be a string")

    if "authors" in plugin:
        if not isinstance(plugin["authors"], list):
            errors.append("Field 'plugin.authors' must be a list")
        elif not all(isinstance(a, str) for a in plugin["authors"]):
            errors.append("All entries in 'plugin.authors' must be strings")

    if "icon" in plugin and not isinstance(plugin["icon"], str):
        errors.append("Field 'plugin.icon' must be a string")

    if "requires" in plugin:
        requires = plugin["requires"]
        if not isinstance(requires, dict):
            errors.append("Field 'plugin.requires' must be an object")
        elif "dispatcharr" in requires and not isinstance(requires["dispatcharr"], str):
            errors.append("Field 'plugin.requires.dispatcharr' must be a string")

    return len(errors) == 0, errors


def extract_manifest_metadata(data: dict) -> dict[str, Any]:
    """
    Extract normalized metadata from a validated manifest.

    Args:
        data: The validated manifest dictionary.

    Returns:
        A dict with extracted fields ready for use in LoadedPlugin.
    """
    plugin = data.get("plugin", {})
    requires = plugin.get("requires", {})

    return {
        "key": plugin.get("key", ""),
        "name": plugin.get("name", ""),
        "version": str(plugin.get("version", "")),
        "description": plugin.get("description", ""),
        "repository": plugin.get("repository", ""),
        "authors": plugin.get("authors", []),
        "icon": plugin.get("icon", ""),
        "requires_dispatcharr": requires.get("dispatcharr", ""),
    }
