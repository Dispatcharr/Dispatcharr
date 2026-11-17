import json
import os

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def effective_capabilities_for_plugin(plugin_key):
    """Read the installed manifest without booting plugin discovery in a migration."""
    from apps.plugins.capabilities import compute_effective_capabilities

    plugins_dir = os.environ.get("DISPATCHARR_PLUGINS_DIR", "/data/plugins")
    from apps.plugins.keys import plugin_manifest_path

    manifest_path = plugin_manifest_path(plugins_dir, plugin_key)
    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except (OSError, ValueError):
        return []
    return compute_effective_capabilities(manifest) if isinstance(manifest, dict) else []


def seed_acknowledged_capabilities(apps, schema_editor):
    """Preserve consent for capabilities an existing plugin actually used."""
    PluginConfig = apps.get_model("plugins", "PluginConfig")
    for plugin in PluginConfig.objects.filter(ever_enabled=True).iterator():
        plugin.acknowledged_capabilities = effective_capabilities_for_plugin(plugin.key)
        plugin.save(update_fields=["acknowledged_capabilities"])


def revert_acknowledged_capabilities(apps, schema_editor):
    PluginConfig = apps.get_model("plugins", "PluginConfig")
    PluginConfig.objects.update(acknowledged_capabilities=[])


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0004_plugin_schedule_ownership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="pluginconfig",
            name="acknowledged_capabilities",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(seed_acknowledged_capabilities, revert_acknowledged_capabilities),
        migrations.CreateModel(
            name="PluginManifestMessageDismissal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.UUIDField()),
                ("dismissed_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dismissed_plugin_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["user", "message_id"], name="plugins_pm_user_id_8f5f4f_idx")],
                "constraints": [models.UniqueConstraint(fields=("user", "message_id"), name="unique_plugin_message_dismissal")],
            },
        ),
    ]
