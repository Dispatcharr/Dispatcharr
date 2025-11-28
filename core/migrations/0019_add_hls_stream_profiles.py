# Migration to add HLS stream profiles

from django.db import migrations


def create_hls_profiles(apps, schema_editor):
    """Create locked HLS stream profiles"""
    StreamProfile = apps.get_model("core", "StreamProfile")
    
    # HLS 1080p Profile - Single quality HLS output at 1080p
    StreamProfile.objects.get_or_create(
        name="HLS 1080p",
        defaults={
            "command": "ffmpeg",
            "parameters": (
                "-user_agent {userAgent} -i {streamUrl} "
                "-c:v libx264 -preset fast -b:v 5000k -maxrate 5000k -bufsize 10000k "
                "-s 1920x1080 -c:a aac -b:a 192k -ar 48000 "
                "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
                "-hls_segment_type mpegts "
                "-hls_segment_filename /data/hls/{channelUuid}/1080p_%03d.ts "
                "/data/hls/{channelUuid}/1080p.m3u8"
            ),
            "locked": True,
            "is_active": True,
        }
    )

    # HLS 720p Profile - Single quality HLS output at 720p
    StreamProfile.objects.get_or_create(
        name="HLS 720p",
        defaults={
            "command": "ffmpeg",
            "parameters": (
                "-user_agent {userAgent} -i {streamUrl} "
                "-c:v libx264 -preset fast -b:v 2800k -maxrate 2800k -bufsize 5600k "
                "-s 1280x720 -c:a aac -b:a 128k -ar 48000 "
                "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
                "-hls_segment_type mpegts "
                "-hls_segment_filename /data/hls/{channelUuid}/720p_%03d.ts "
                "/data/hls/{channelUuid}/720p.m3u8"
            ),
            "locked": True,
            "is_active": True,
        }
    )

    # HLS 480p Profile - Single quality HLS output at 480p
    StreamProfile.objects.get_or_create(
        name="HLS 480p",
        defaults={
            "command": "ffmpeg",
            "parameters": (
                "-user_agent {userAgent} -i {streamUrl} "
                "-c:v libx264 -preset fast -b:v 1400k -maxrate 1400k -bufsize 2800k "
                "-s 854x480 -c:a aac -b:a 96k -ar 48000 "
                "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
                "-hls_segment_type mpegts "
                "-hls_segment_filename /data/hls/{channelUuid}/480p_%03d.ts "
                "/data/hls/{channelUuid}/480p.m3u8"
            ),
            "locked": True,
            "is_active": True,
        }
    )
    
    # HLS Copy Profile - HLS output with stream copy (no transcoding)
    StreamProfile.objects.get_or_create(
        name="HLS Copy",
        defaults={
            "command": "ffmpeg",
            "parameters": (
                "-user_agent {userAgent} -i {streamUrl} "
                "-c copy "
                "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
                "-hls_segment_type mpegts "
                "-hls_segment_filename /data/hls/{channelUuid}/stream_%03d.ts "
                "/data/hls/{channelUuid}/stream.m3u8"
            ),
            "locked": True,
            "is_active": True,
        }
    )


def remove_hls_profiles(apps, schema_editor):
    """Remove HLS stream profiles on migration rollback"""
    StreamProfile = apps.get_model("core", "StreamProfile")
    
    hls_profile_names = [
        "HLS 1080p",
        "HLS 720p",
        "HLS 480p",
        "HLS Copy",
    ]
    
    StreamProfile.objects.filter(name__in=hls_profile_names, locked=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_alter_systemevent_event_type'),
    ]

    operations = [
        migrations.RunPython(create_hls_profiles, remove_hls_profiles),
    ]

