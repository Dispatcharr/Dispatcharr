from django.db import migrations


def preload_reverse_proxy_auth_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    CoreSettings.objects.get_or_create(
        key="reverse_proxy_auth",
        defaults={
            "name": "Reverse Proxy Auth",
            "value": {"enabled": False, "header": ""},
        },
    )


def remove_reverse_proxy_auth_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")
    CoreSettings.objects.filter(key="reverse_proxy_auth").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_rename_default_stream_profile_names"),
    ]

    operations = [
        migrations.RunPython(
            preload_reverse_proxy_auth_settings,
            remove_reverse_proxy_auth_settings,
        ),
    ]
