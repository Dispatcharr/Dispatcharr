from django.db import migrations

def update_url(apps, schema_editor):
    PluginRepo = apps.get_model("plugins", "PluginRepo")
    PluginRepo.objects.filter(is_official=True).update(
        url="https://dispatcharr.github.io/Plugins/manifest.json"
    )


def revert_url(apps, schema_editor):
    PluginRepo = apps.get_model("plugins", "PluginRepo")
    PluginRepo.objects.filter(is_official=True).update(
        url="https://raw.githubusercontent.com/Dispatcharr/Plugins/releases/manifest.json"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0002_pluginrepo"),
    ]

    operations = [
        migrations.RunPython(update_url, revert_url),
    ]
