import json
import os

from django.db import migrations


# This is the registry that 0004 incorrectly granted to every previously
# enabled plugin. Keep it fixed so a later capability does not alter repair.
SEEDED_CAPABILITIES = {
    "background_tasks",
    "persistent_service",
    "network_listener",
    "subprocess",
    "outbound_network",
    "filesystem_write",
    "celery_dispatch",
    "proxy_internals",
    "user_data",
    "external_dependencies",
}


def effective_capabilities_for_plugin(plugin_key):
    from apps.plugins.capabilities import compute_effective_capabilities

    plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR", "/data/plugins")
    manifest_path = os.path.join(plugins_dir, plugin_key, "plugin.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except (OSError, ValueError):
        return []
    return compute_effective_capabilities(manifest) if isinstance(manifest, dict) else []


def repair_acknowledged_capabilities(apps, schema_editor):
    PluginConfig = apps.get_model("plugins", "PluginConfig")
    for plugin in PluginConfig.objects.filter(ever_enabled=True).iterator():
        if set(plugin.acknowledged_capabilities or []) != SEEDED_CAPABILITIES:
            continue
        plugin.acknowledged_capabilities = effective_capabilities_for_plugin(plugin.key)
        plugin.save(update_fields=["acknowledged_capabilities"])


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0004_plugin_acknowledged_capabilities"),
    ]

    operations = [
        migrations.RunPython(repair_acknowledged_capabilities, migrations.RunPython.noop),
    ]
