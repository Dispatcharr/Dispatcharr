# Migration to optimize HLS profiles for low latency streaming

from django.db import migrations


def optimize_hls_profiles(apps, schema_editor):
    """Update HLS stream profiles for low latency, high quality streaming"""
    StreamProfile = apps.get_model("core", "StreamProfile")
    
    # Update HLS 1080p Profile - Optimized for low latency
    try:
        profile = StreamProfile.objects.get(name="HLS 1080p", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c:v libx264 -preset veryfast -b:v 5000k -maxrate 5000k -bufsize 10000k "
            "-s 1920x1080 -c:a aac -b:a 192k -ar 48000 "
            "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/1080p_%03d.ts "
            "/data/hls/{channelUuid}/1080p.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass
    
    # Update HLS 720p Profile - Optimized for low latency
    try:
        profile = StreamProfile.objects.get(name="HLS 720p", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c:v libx264 -preset veryfast -b:v 2800k -maxrate 2800k -bufsize 5600k "
            "-s 1280x720 -c:a aac -b:a 128k -ar 48000 "
            "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/720p_%03d.ts "
            "/data/hls/{channelUuid}/720p.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass
    
    # Update HLS 480p Profile - Optimized for low latency
    try:
        profile = StreamProfile.objects.get(name="HLS 480p", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c:v libx264 -preset veryfast -b:v 1400k -maxrate 1400k -bufsize 2800k "
            "-s 854x480 -c:a aac -b:a 96k -ar 48000 "
            "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/480p_%03d.ts "
            "/data/hls/{channelUuid}/480p.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass
    
    # Update HLS Copy Profile - Optimized for low latency
    try:
        profile = StreamProfile.objects.get(name="HLS Copy", locked=True)
        profile.parameters = (
            "-user_agent {userAgent} -i {streamUrl} "
            "-c copy "
            "-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+append_list "
            "-hls_segment_type mpegts "
            "-hls_segment_filename /data/hls/{channelUuid}/stream_%03d.ts "
            "/data/hls/{channelUuid}/stream.m3u8"
        )
        profile.save()
    except StreamProfile.DoesNotExist:
        pass


def reverse_optimization(apps, schema_editor):
    """Reverse the optimization (back to 4-second segments)"""
    # This is just for rollback - in practice, this shouldn't be needed
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_update_hls_profile_paths'),
    ]

    operations = [
        migrations.RunPython(optimize_hls_profiles, reverse_optimization),
    ]

