import os


def normalize_plugin_key(value: str) -> str:
    """Return the database key used by plugin discovery in development."""
    base = os.path.basename(value or "")
    return base.replace(" ", "_").lower()


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
