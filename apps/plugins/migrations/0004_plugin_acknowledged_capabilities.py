from django.db import migrations, models


def seed_acknowledged_capabilities(apps, schema_editor):
    """Already-enabled plugins shouldn't hit a re-prompt storm on upgrade.
    Treat every capability known as of this release as already acknowledged
    for them. Only genuinely new capabilities added after this point should
    trigger the confirm dialog again."""
    from apps.plugins.capabilities import KNOWN_CAPABILITIES

    PluginConfig = apps.get_model("plugins", "PluginConfig")
    PluginConfig.objects.filter(ever_enabled=True).update(
        acknowledged_capabilities=list(KNOWN_CAPABILITIES.keys())
    )


def revert_acknowledged_capabilities(apps, schema_editor):
    PluginConfig = apps.get_model("plugins", "PluginConfig")
    PluginConfig.objects.update(acknowledged_capabilities=[])


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0003_update_official_repo_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluginconfig",
            name="acknowledged_capabilities",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(seed_acknowledged_capabilities, revert_acknowledged_capabilities),
    ]
