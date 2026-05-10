from django.db import migrations


def move_to_system_settings(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")

    try:
        stream_obj = CoreSettings.objects.get(key="stream_settings")
    except CoreSettings.DoesNotExist:
        stream_obj = None

    system_obj, _ = CoreSettings.objects.get_or_create(
        key="system_settings",
        defaults={"name": "System Settings", "value": {}},
    )
    system_value = system_obj.value if isinstance(system_obj.value, dict) else {}

    if stream_obj:
        stream_value = stream_obj.value if isinstance(stream_obj.value, dict) else {}

        for field in ("preferred_region", "auto_import_mapped_files"):
            if field in stream_value:
                # Only migrate to system if not already explicitly set there
                if field not in system_value or system_value[field] is None:
                    system_value[field] = stream_value.pop(field)
                else:
                    stream_value.pop(field)

        stream_obj.value = stream_value
        stream_obj.save()

    # Ensure sensible defaults if the fields are still absent
    system_value.setdefault("preferred_region", None)
    system_value.setdefault("auto_import_mapped_files", True)
    system_obj.value = system_value
    system_obj.save()


def reverse_move(apps, schema_editor):
    CoreSettings = apps.get_model("core", "CoreSettings")

    try:
        system_obj = CoreSettings.objects.get(key="system_settings")
    except CoreSettings.DoesNotExist:
        return

    stream_obj, _ = CoreSettings.objects.get_or_create(
        key="stream_settings",
        defaults={"name": "Stream Settings", "value": {}},
    )

    system_value = system_obj.value if isinstance(system_obj.value, dict) else {}
    stream_value = stream_obj.value if isinstance(stream_obj.value, dict) else {}

    for field in ("preferred_region", "auto_import_mapped_files"):
        if field in system_value:
            stream_value[field] = system_value.pop(field)

    system_obj.value = system_value
    system_obj.save()
    stream_obj.value = stream_value
    stream_obj.save()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_outputprofile"),
    ]

    operations = [
        migrations.RunPython(move_to_system_settings, reverse_move),
    ]
