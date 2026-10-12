from django.db import migrations, models

_RENAMES = (
    ("ffmpeg", "FFmpeg"),
    ("streamlink", "Streamlink"),
)


def rename_default_stream_profiles(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    for old_name, new_name in _RENAMES:
        StreamProfile.objects.filter(name__iexact=old_name, locked=True).update(
            name=new_name
        )


def revert_default_stream_profile_names(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    for old_name, new_name in _RENAMES:
        StreamProfile.objects.filter(name__iexact=new_name, locked=True).update(
            name=old_name
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_update_default_stream_and_output_profiles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="streamprofile",
            name="parameters",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Command-line parameters. Use {userAgent}, {streamUrl}, "
                    "and {channelId} as placeholders."
                ),
            ),
        ),
        migrations.RunPython(
            rename_default_stream_profiles,
            revert_default_stream_profile_names,
        ),
    ]
