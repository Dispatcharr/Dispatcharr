# Generated migration - add MaxPlayer user agents
from django.db import migrations


def add_maxplayer_user_agents(apps, schema_editor):
    UserAgent = apps.get_model("core", "UserAgent")

    # Add MaxPlayer (Electron/Chromium) - used for API/EPG/playlist requests
    if not UserAgent.objects.filter(name="MaxPlayer").exists():
        UserAgent.objects.create(
            name="MaxPlayer",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "MaxPlayer/1.2.47 Chrome/106.0.5249.199 "
                "Electron/21.4.4 Safari/537.36"
            ),
            description="MaxPlayer desktop app (Electron/Chromium)",
            is_active=True,
        )

    # Add MaxPlayer (libmpv) - used for actual video stream requests
    if not UserAgent.objects.filter(name="MaxPlayer (libmpv)").exists():
        UserAgent.objects.create(
            name="MaxPlayer (libmpv)",
            user_agent="MaxPlayer/1.2.47 (win32 - x64) (libmpv)",
            description="MaxPlayer stream UA used by libmpv for video playback",
            is_active=True,
        )


def reverse_add_maxplayer_user_agents(apps, schema_editor):
    UserAgent = apps.get_model("core", "UserAgent")
    UserAgent.objects.filter(name__in=["MaxPlayer", "MaxPlayer (libmpv)"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_move_preferred_region_and_auto_import_to_system_settings"),
    ]

    operations = [
        migrations.RunPython(
            add_maxplayer_user_agents,
            reverse_add_maxplayer_user_agents,
        ),
    ]
