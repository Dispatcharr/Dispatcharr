from django.db import migrations


def move_max_reconnect_attempts(apps, schema_editor):
    """Carry the fork-only ``max_reconnect_attempts`` value into ``max_retries``.

    Both keys control how many times the live proxy retries a stream before
    failing over. Upstream exposes it as ``max_retries`` (1-10), so keep that
    name and drop the legacy key.
    """
    CoreSettings = apps.get_model("core", "CoreSettings")
    try:
        settings_obj = CoreSettings.objects.get(key="proxy_settings")
    except CoreSettings.DoesNotExist:
        return

    current = settings_obj.value if isinstance(settings_obj.value, dict) else {}
    if "max_reconnect_attempts" not in current:
        return

    updated = dict(current)
    legacy = updated.pop("max_reconnect_attempts")
    if "max_retries" not in updated:
        try:
            updated["max_retries"] = max(1, min(int(legacy), 10))
        except (TypeError, ValueError):
            pass

    settings_obj.value = updated
    settings_obj.save(update_fields=["value"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_streamprofile_channel_name_tvg_id_placeholders"),
    ]

    operations = [
        migrations.RunPython(move_max_reconnect_attempts, migrations.RunPython.noop),
    ]
