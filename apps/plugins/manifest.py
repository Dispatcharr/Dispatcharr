"""
Plugin manifest utilities.

Handles reading plugin.yaml/plugin.yml manifests and extracting plugin keys.
Supports forward-compatible key detection: manifest key takes precedence,
directory name is fallback (to be deprecated in future).
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import yaml, but make it optional for now
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logger.debug("PyYAML not installed; manifest files will be ignored")


def load_manifest(plugin_path: str) -> Optional[dict]:
    """
    Load plugin manifest from plugin.yaml or plugin.yml.

    Args:
        plugin_path: Path to the plugin directory

    Returns:
        Parsed manifest dict, or None if no manifest found
    """
    if not YAML_AVAILABLE:
        return None

    for filename in ("plugin.yaml", "plugin.yml"):
        manifest_path = os.path.join(plugin_path, filename)
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        logger.debug(f"Loaded manifest from {manifest_path}")
                        return data
            except Exception as e:
                logger.warning(f"Failed to parse manifest {manifest_path}: {e}")

    return None


def get_manifest_key(manifest: Optional[dict]) -> Optional[str]:
    """
    Extract the plugin key from a manifest.

    Supports two formats:
    - plugin.key (nested under 'plugin' key)
    - key (top-level)

    Args:
        manifest: Parsed manifest dict

    Returns:
        Plugin key string, or None if not found
    """
    if not manifest:
        return None

    # Try nested format first: plugin.key
    if "plugin" in manifest and isinstance(manifest["plugin"], dict):
        key = manifest["plugin"].get("key")
        if key and isinstance(key, str):
            return key.strip()

    # Try top-level key
    key = manifest.get("key")
    if key and isinstance(key, str):
        return key.strip()

    return None


def derive_key_from_directory(directory_name: str) -> str:
    """
    Derive a plugin key from the directory name.

    This is the fallback method when no manifest key is present.
    Directory names are normalized: spaces become underscores, lowercase.

    Args:
        directory_name: Name of the plugin directory

    Returns:
        Normalized plugin key
    """
    return directory_name.replace(" ", "_").lower()


def detect_plugin_key(plugin_path: str, directory_name: str) -> Tuple[str, str]:
    """
    Detect the plugin key, preferring manifest over directory.

    Args:
        plugin_path: Full path to the plugin directory
        directory_name: Name of the plugin directory (for fallback)

    Returns:
        Tuple of (key, source) where source is 'manifest' or 'directory'
    """
    manifest = load_manifest(plugin_path)
    manifest_key = get_manifest_key(manifest)

    if manifest_key:
        logger.debug(f"Using manifest key '{manifest_key}' for plugin at {plugin_path}")
        return manifest_key, "manifest"

    directory_key = derive_key_from_directory(directory_name)
    logger.debug(f"Using directory key '{directory_key}' for plugin at {plugin_path}")
    return directory_key, "directory"
