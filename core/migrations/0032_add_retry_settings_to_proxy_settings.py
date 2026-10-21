from django.db import migrations

PROXY_SETTINGS_KEY = "proxy_settings"


def add_retry_settings_to_proxy_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")

    try:
        obj = CoreSettings.objects.get(key=PROXY_SETTINGS_KEY)
    except CoreSettings.DoesNotExist:
        return

    value = obj.value if isinstance(obj.value, dict) else {}
    value.setdefault("max_retries", 3)
    value.setdefault("stream_retry_timeout", 3)
    obj.value = value
    obj.save()


def remove_retry_settings_from_proxy_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")

    try:
        obj = CoreSettings.objects.get(key=PROXY_SETTINGS_KEY)
    except CoreSettings.DoesNotExist:
        return

    value = obj.value if isinstance(obj.value, dict) else {}
    value.pop("max_retries", None)
    value.pop("stream_retry_timeout", None)
    obj.value = value
    obj.save()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0031_default_reverse_proxy_auth_settings"),
    ]

    operations = [
        migrations.RunPython(
            add_retry_settings_to_proxy_settings,
            remove_retry_settings_from_proxy_settings,
        ),
    ]
