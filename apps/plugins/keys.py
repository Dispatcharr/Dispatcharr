import os
import re


def normalize_plugin_key(value: str) -> str:
    """Return the canonical database key for an installed plugin directory."""
    base = os.path.basename(value or "")
    base = base.replace(" ", "_").replace("-", "_").lower()
    base = re.sub(r"[^a-z0-9_]", "_", base)
    base = base.strip("._ ")
    return base or "plugin"


def plugin_manifest_path(plugins_dir: str, key: str) -> str:
    """Find a manifest by canonical directory key without trusting its spelling."""
    try:
        entries = os.listdir(plugins_dir)
    except OSError:
        return os.path.join(plugins_dir, key, "plugin.json")

    for entry in entries:
        if normalize_plugin_key(entry) == key:
            return os.path.join(plugins_dir, entry, "plugin.json")
    return os.path.join(plugins_dir, key, "plugin.json")
