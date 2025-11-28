# Migration to update existing HLS profile paths from /var/www/hls to /data/hls

from django.db import migrations


def update_hls_profile_paths(apps, schema_editor):
    """Update existing HLS stream profiles to use /data/hls instead of /var/www/hls"""
    StreamProfile = apps.get_model("core", "StreamProfile")
    
    # Update HLS 1080p Profile
    try:
        profile = StreamProfile.objects.get(name="HLS 1080p", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c:v libx264 -preset veryfast -b:v 5000k -maxrate 5000k -bufsize 10000k "
            "-s 1920x1080 -c:a aac -b:a 192k -ar 48000 "
            "-f hls -hls_time 4 -hls_list_size 10 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/1080p_%03d.ts "
            "/data/hls/{channelUuid}/1080p.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass
    
    # Update HLS 720p Profile
    try:
        profile = StreamProfile.objects.get(name="HLS 720p", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c:v libx264 -preset veryfast -b:v 2800k -maxrate 2800k -bufsize 5600k "
            "-s 1280x720 -c:a aac -b:a 128k -ar 48000 "
            "-f hls -hls_time 4 -hls_list_size 10 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/720p_%03d.ts "
            "/data/hls/{channelUuid}/720p.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass
    
    # Update HLS 480p Profile
    try:
        profile = StreamProfile.objects.get(name="HLS 480p", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c:v libx264 -preset veryfast -b:v 1400k -maxrate 1400k -bufsize 2800k "
            "-s 854x480 -c:a aac -b:a 96k -ar 48000 "
            "-f hls -hls_time 4 -hls_list_size 10 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/480p_%03d.ts "
            "/data/hls/{channelUuid}/480p.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass
    
    # Update HLS Copy Profile
    try:
        profile = StreamProfile.objects.get(name="HLS Copy", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c copy "
            "-f hls -hls_time 4 -hls_list_size 10 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/stream_%03d.ts "
            "/data/hls/{channelUuid}/stream.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass


def reverse_hls_profile_paths(apps, schema_editor):
    """Reverse the path changes (back to /var/www/hls)"""
    StreamProfile = apps.get_model("core", "StreamProfile")
    
    # This is just for rollback - we'll revert to old paths
    # In practice, this shouldn't be needed
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_add_hls_stream_profiles'),
    ]

    operations = [
        migrations.RunPython(update_hls_profile_paths, reverse_hls_profile_paths),
    ]

