# Generated manually to add DVR retry settings

from django.db import migrations
from django.utils.text import slugify


def add_dvr_retry_settings(apps, schema_editor):
    """Add DVR retry configuration settings"""
    CoreSettings = apps.get_model("core", "CoreSettings")

    defaults = [
        (slugify("DVR Max Retries"), "DVR Max Retries", "3"),
        (slugify("DVR Retry Frequency"), "DVR Retry Frequency", "30"),
    ]

    for key, name, value in defaults:
        CoreSettings.objects.get_or_create(
            key=key,
            defaults={"name": name, "value": value}
        )
        print(f"Added or ensured setting: {name} = {value}")


def reverse_dvr_retry_settings(apps, schema_editor):
    """Remove DVR retry configuration settings"""
    CoreSettings = apps.get_model("core", "CoreSettings")

    keys = [
        slugify("DVR Max Retries"),
        slugify("DVR Retry Frequency"),
    ]

    for key in keys:
        CoreSettings.objects.filter(key=key).delete()
        print(f"Removed setting with key: {key}")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_update_dvr_template_paths"),
    ]

    operations = [
        migrations.RunPython(add_dvr_retry_settings, reverse_dvr_retry_settings),
    ]
