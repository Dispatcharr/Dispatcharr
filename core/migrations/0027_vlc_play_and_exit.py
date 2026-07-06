# Add --play-and-exit so cvlc exits when the input cannot be opened.

from django.db import migrations

_VLC_PARAMETERS = (
    "-vv -I dummy --no-video-title-show --play-and-exit "
    "--http-user-agent {userAgent} {streamUrl} "
    "--sout #standard{access=file,mux=ts,dst=-}"
)


def update_vlc_profile(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    StreamProfile.objects.filter(name="VLC", locked=True).update(
        parameters=_VLC_PARAMETERS
    )


def revert_vlc_profile(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    StreamProfile.objects.filter(name="VLC", locked=True).update(
        parameters=(
            "-vv -I dummy --no-video-title-show --http-user-agent {userAgent} "
            "{streamUrl} --sout #standard{access=file,mux=ts,dst=-}"
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_add_channel_client_wait_period"),
    ]

    operations = [
        migrations.RunPython(update_vlc_profile, revert_vlc_profile),
    ]
