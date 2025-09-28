from django.db import migrations
from django.utils.text import slugify


def seed_schedule_defaults(apps, schema_editor):
    from django.conf import settings

    CoreSettings = apps.get_model("core", "CoreSettings")
    timezone = getattr(settings, "TIME_ZONE", "UTC")
    defaults = [
        ("Backup Schedule Preset", slugify("Backup Schedule Preset"), "daily"),
        ("Backup Cron Minute", slugify("Backup Cron Minute"), "15"),
        ("Backup Cron Hour", slugify("Backup Cron Hour"), "3"),
        ("Backup Cron Day Of Month", slugify("Backup Cron Day Of Month"), "*"),
        ("Backup Cron Month Of Year", slugify("Backup Cron Month Of Year"), "*"),
        ("Backup Cron Day Of Week", slugify("Backup Cron Day Of Week"), "*"),
        ("Backup Cron Timezone", slugify("Backup Cron Timezone"), timezone),
    ]
    for name, key, value in defaults:
        CoreSettings.objects.get_or_create(
            key=key,
            defaults={"name": name, "value": value},
        )


def remove_schedule_defaults(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    keys = [
        slugify("Backup Schedule Preset"),
        slugify("Backup Cron Minute"),
        slugify("Backup Cron Hour"),
        slugify("Backup Cron Day Of Month"),
        slugify("Backup Cron Month Of Year"),
        slugify("Backup Cron Day Of Week"),
        slugify("Backup Cron Timezone"),
    ]
    CoreSettings.objects.filter(key__in=keys).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_backup_interval_and_recordings"),
    ]

    operations = [
        migrations.RunPython(seed_schedule_defaults, remove_schedule_defaults),
    ]
