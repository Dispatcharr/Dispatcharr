from django.db import migrations

PROXY_SETTINGS_KEY = "proxy_settings"


def add_channel_client_wait_period(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")

    try:
        obj = CoreSettings.objects.get(key=PROXY_SETTINGS_KEY)
    except CoreSettings.DoesNotExist:
        return

    value = obj.value if isinstance(obj.value, dict) else {}

    # Add the new client-connect grace period default.
    value.setdefault("channel_client_wait_period", 5)

    # channel_init_grace_period was repurposed in 0.27.1 as the channel startup
    # timeout (replacing a hardcoded 10s). Values below the new 60s default are
    # too short when a channel has many failover streams to cycle through.
    current_init = value.get("channel_init_grace_period", 5)
    if current_init < 60:
        value["channel_init_grace_period"] = 60

    obj.value = value
    obj.save()


def remove_channel_client_wait_period(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")

    try:
        obj = CoreSettings.objects.get(key=PROXY_SETTINGS_KEY)
    except CoreSettings.DoesNotExist:
        return

    value = obj.value if isinstance(obj.value, dict) else {}
    value.pop("channel_client_wait_period", None)
    obj.value = value
    obj.save()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0025_move_preferred_region_and_auto_import_to_system_settings"),
    ]

    operations = [
        migrations.RunPython(add_channel_client_wait_period, remove_channel_client_wait_period),
    ]
