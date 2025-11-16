# Generated migration to add portrait conversion setting

from django.db import migrations
from django.utils.text import slugify


def add_portrait_conversion_setting(apps, schema_editor):
    """Add the convert banners to portrait setting with default value false"""
    CoreSettings = apps.get_model("core", "CoreSettings")

    # Create the setting if it doesn't exist (default: disabled)
    CoreSettings.objects.get_or_create(
        key=slugify("Convert Banners To Portrait"),
        defaults={
            "name": "Convert Banners To Portrait",
            "value": "false"  # Disabled by default - users opt-in
        }
    )


def reverse_portrait_conversion_setting(apps, schema_editor):
    """Remove the portrait conversion setting"""
    CoreSettings = apps.get_model("core", "CoreSettings")
    CoreSettings.objects.filter(key=slugify("Convert Banners To Portrait")).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_update_dvr_template_paths"),
    ]

    operations = [
        migrations.RunPython(
            add_portrait_conversion_setting,
            reverse_portrait_conversion_setting
        ),
    ]
