# Generated manually to update DVR template paths

from django.db import migrations
from django.utils.text import slugify


def update_dvr_template_paths(apps, schema_editor):
    """Remove 'Recordings/' prefix from DVR template paths"""
    CoreSettings = apps.get_model("core", "CoreSettings")

    # Define the updates needed
    updates = [
        (slugify("DVR TV Template"), "TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"),
        (slugify("DVR Movie Template"), "Movies/{title} ({year}).mkv"),
        (slugify("DVR TV Fallback Template"), "TV_Shows/{show}/{start}.mkv"),
        (slugify("DVR Movie Fallback Template"), "Movies/{start}.mkv"),
    ]

    # Update each setting
    for key, new_value in updates:
        try:
            setting = CoreSettings.objects.get(key=key)
            setting.value = new_value
            setting.save()
            print(f"Updated {setting.name}: {new_value}")
        except CoreSettings.DoesNotExist:
            print(f"Setting with key '{key}' not found - skipping")


def reverse_dvr_template_paths(apps, schema_editor):
    """Add back 'Recordings/' prefix to DVR template paths"""
    CoreSettings = apps.get_model("core", "CoreSettings")

    # Define the reverse updates (add back Recordings/ prefix)
    updates = [
        (slugify("DVR TV Template"), "Recordings/TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"),
        (slugify("DVR Movie Template"), "Recordings/Movies/{title} ({year}).mkv"),
        (slugify("DVR TV Fallback Template"), "Recordings/TV_Shows/{show}/{start}.mkv"),
        (slugify("DVR Movie Fallback Template"), "Recordings/Movies/{start}.mkv"),
    ]

    # Update each setting back to original
    for key, original_value in updates:
        try:
            setting = CoreSettings.objects.get(key=key)
            setting.value = original_value
            setting.save()
            print(f"Reverted {setting.name}: {original_value}")
        except CoreSettings.DoesNotExist:
            print(f"Setting with key '{key}' not found - skipping")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_dvr_templates"),
    ]

    operations = [
        migrations.RunPython(update_dvr_template_paths, reverse_dvr_template_paths),
    ]