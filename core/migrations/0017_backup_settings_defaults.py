from django.db import migrations
from django.utils.text import slugify
import json


def create_backup_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")

    defaults = [
        ("Backups Enabled", slugify("Backups Enabled"), "false"),
        ("Backup Frequency", slugify("Backup Frequency"), "manual"),
        ("Backup Retention Count", slugify("Backup Retention Count"), "5"),
        ("Backup Path", slugify("Backup Path"), "/data/backups"),
        ("Backup Extra Paths", slugify("Backup Extra Paths"), json.dumps([])),
    ]

    for name, key, value in defaults:
        CoreSettings.objects.get_or_create(key=key, defaults={"name": name, "value": value})


def remove_backup_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    keys = [
        slugify("Backups Enabled"),
        slugify("Backup Frequency"),
        slugify("Backup Retention Count"),
        slugify("Backup Path"),
        slugify("Backup Extra Paths"),
    ]
    CoreSettings.objects.filter(key__in=keys).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_update_dvr_template_paths"),
    ]

    operations = [
        migrations.RunPython(create_backup_settings, remove_backup_settings),
    ]
