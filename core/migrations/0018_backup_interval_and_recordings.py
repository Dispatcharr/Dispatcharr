from django.db import migrations
from django.utils.text import slugify


BACKUP_INTERVAL_KEY = slugify("Backup Interval Hours")
BACKUP_INCLUDE_RECORDINGS_KEY = slugify("Backup Include Recordings")


def add_backup_interval(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    CoreSettings.objects.get_or_create(
        key=BACKUP_INTERVAL_KEY,
        defaults={"name": "Backup Interval Hours", "value": "24"},
    )
    CoreSettings.objects.get_or_create(
        key=BACKUP_INCLUDE_RECORDINGS_KEY,
        defaults={"name": "Backup Include Recordings", "value": "true"},
    )


def remove_backup_interval(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    CoreSettings.objects.filter(
        key__in=[BACKUP_INTERVAL_KEY, BACKUP_INCLUDE_RECORDINGS_KEY]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_backup_settings_defaults"),
    ]

    operations = [
        migrations.RunPython(add_backup_interval, remove_backup_interval),
    ]
