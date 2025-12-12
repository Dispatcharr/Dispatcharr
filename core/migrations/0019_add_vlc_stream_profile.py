# Generated migration to add VLC stream profile

from django.db import migrations

def add_vlc_profile(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    UserAgent = apps.get_model("core", "UserAgent")
    
    # Check if VLC profile already exists
    if not StreamProfile.objects.filter(name="vlc").exists():
        # Get the TiviMate user agent (should be pk=1)
        try:
            tivimate_ua = UserAgent.objects.get(pk=1)
        except UserAgent.DoesNotExist:
            # Fallback: get first available user agent
            tivimate_ua = UserAgent.objects.first()
            if not tivimate_ua:
                # No user agents exist, skip creating profile
                return
        
        StreamProfile.objects.create(
            name="vlc",
            command="cvlc",
            parameters="-vv -I dummy --no-video-title-show --http-user-agent {userAgent} {streamUrl} --sout #standard{access=file,mux=ts,dst=-}",
            is_active=True,
            user_agent=tivimate_ua,
            locked=True,  # Make it read-only like ffmpeg/streamlink
        )

def remove_vlc_profile(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    StreamProfile.objects.filter(name="vlc").delete()

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_alter_systemevent_event_type'),
    ]

    operations = [
        migrations.RunPython(add_vlc_profile, remove_vlc_profile),
    ]
