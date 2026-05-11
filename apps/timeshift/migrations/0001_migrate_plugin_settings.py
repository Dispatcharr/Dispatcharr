"""Data migration: copy settings from the legacy `dispatcharr_timeshift`
plugin (when present) into the native `CoreSettings` `timeshift_settings`
group.

Idempotent and a no-op when the plugin record does not exist (clean install).
The plugin's PluginConfig row is left in place with ``enabled=False`` and a
``migrated_to_native: True`` marker so admins can inspect the legacy state.

No hard dependency on the `plugins` app — the lookup is wrapped in try/except
so this migration runs on installs that never had the plugin.
"""
from django.db import migrations


PLUGIN_KEY = "dispatcharr_timeshift"
TIMESHIFT_SETTINGS_KEY = "timeshift_settings"


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def migrate_plugin_settings(apps, schema_editor):
    try:
        PluginConfig = apps.get_model("plugins", "PluginConfig")
    except LookupError:
        # plugins app not installed (or model not yet registered) — nothing
        # to migrate. Clean install path.
        return

    plugin = PluginConfig.objects.filter(key=PLUGIN_KEY).first()
    if plugin is None:
        return

    plugin_settings = plugin.settings or {}
    if plugin_settings.get("migrated_to_native"):
        return

    timeshift_payload = {
        "default_timezone": plugin_settings.get("timezone") or "UTC",
        "default_language": plugin_settings.get("language") or "en",
        "xmltv_prev_days_override": _coerce_int(plugin_settings.get("xmltv_prev_days_override"), 0),
        "debug_logging": _coerce_bool(plugin_settings.get("debug_mode"), False),
    }

    CoreSettings = apps.get_model("core", "CoreSettings")
    obj, _created = CoreSettings.objects.get_or_create(
        key=TIMESHIFT_SETTINGS_KEY,
        defaults={"name": "Timeshift Settings", "value": {}},
    )
    current = obj.value if isinstance(obj.value, dict) else {}
    current.update(timeshift_payload)
    obj.value = current
    if not obj.name:
        obj.name = "Timeshift Settings"
    obj.save()

    plugin_settings["migrated_to_native"] = True
    plugin.settings = plugin_settings
    plugin.enabled = False
    plugin.save(update_fields=["settings", "enabled"])


def reverse_migrate(apps, schema_editor):
    # Settings migration is intentionally one-way; restoring would require
    # re-enabling the plugin, which the user can do manually.
    pass


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("core", "0023_alter_systemevent_event_type"),
    ]

    operations = [
        migrations.RunPython(migrate_plugin_settings, reverse_migrate),
    ]
