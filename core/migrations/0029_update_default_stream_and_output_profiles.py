from django.db import migrations

_FFMPEG_PARAMETERS = (
    '-fflags +genpts+discardcorrupt '
    '-user_agent {userAgent} '
    '-i {streamUrl} '
    '-map 0 '
    '-c copy '
    '-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity '
    '-f mpegts pipe:1'
)

_PREVIOUS_FFMPEG_PARAMETERS = (
    '-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1'
)

_STREAMLINK_PARAMETERS = (
    '--http-header User-Agent={userAgent} '
    '--ffmpeg-fout mpegts '
    '--stdout {streamUrl} best'
)

_PREVIOUS_STREAMLINK_PARAMETERS = (
    '{streamUrl} --http-header User-Agent={userAgent} best --stdout'
)


def update_default_profiles(apps, schema_editor):
    OutputProfile = apps.get_model('core', 'OutputProfile')
    OutputProfile.objects.filter(
        name='Media Server (AC3 Audio)', locked=True,
    ).update(
        parameters=(
            '-fflags +discardcorrupt+genpts+nobuffer '
            '-probesize 512K '
            '-analyzeduration 0 '
            '-i pipe:0 '
            '-map 0 '
            '-c:v copy '
            '-c:a ac3 '
            '-b:a 384k '
            '-c:s copy '
            '-max_muxing_queue_size 4096 '
            '-flush_packets 1 '
            '-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity '
            '-f mpegts pipe:1'
        ),
    )
    OutputProfile.objects.filter(
        name='Web Player (AAC Audio)', locked=True,
    ).update(
        parameters=(
            '-fflags +discardcorrupt+genpts+nobuffer '
            '-probesize 512K '
            '-analyzeduration 0 '
            '-i pipe:0 '
            '-map 0 '
            '-c:v copy '
            '-c:a aac '
            '-b:a 192k '
            '-ac 2 '
            '-c:s copy '
            '-max_muxing_queue_size 4096 '
            '-flush_packets 1 '
            '-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity '
            '-f mpegts pipe:1'
        ),
    )

    StreamProfile = apps.get_model('core', 'StreamProfile')
    StreamProfile.objects.filter(name='ffmpeg', locked=True).update(
        parameters=_FFMPEG_PARAMETERS
    )
    StreamProfile.objects.filter(name='streamlink', locked=True).update(
        parameters=_STREAMLINK_PARAMETERS
    )


def revert_default_profiles(apps, schema_editor):
    OutputProfile = apps.get_model('core', 'OutputProfile')
    OutputProfile.objects.filter(
        name='Media Server (AC3 Audio)', locked=True,
    ).update(
        parameters=(
            '-fflags +discardcorrupt+genpts+nobuffer '
            '-probesize 512K '
            '-analyzeduration 0 '
            '-i pipe:0 '
            '-map 0 '
            '-c:v copy '
            '-c:a ac3 '
            '-b:a 384k '
            '-max_muxing_queue_size 4096 '
            '-flush_packets 1 '
            '-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity '
            '-f mpegts pipe:1'
        ),
    )
    OutputProfile.objects.filter(
        name='Web Player (AAC Audio)', locked=True,
    ).update(
        parameters=(
            '-fflags +discardcorrupt+genpts+nobuffer '
            '-probesize 512K '
            '-analyzeduration 0 '
            '-i pipe:0 '
            '-map 0 '
            '-c:v copy '
            '-c:a aac '
            '-b:a 192k '
            '-ac 2 '
            '-max_muxing_queue_size 4096 '
            '-flush_packets 1 '
            '-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity '
            '-f mpegts pipe:1'
        ),
    )

    StreamProfile = apps.get_model('core', 'StreamProfile')
    StreamProfile.objects.filter(name='ffmpeg', locked=True).update(
        parameters=_PREVIOUS_FFMPEG_PARAMETERS
    )
    StreamProfile.objects.filter(name='streamlink', locked=True).update(
        parameters=_PREVIOUS_STREAMLINK_PARAMETERS
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0028_alter_systemevent_event_type'),
    ]

    operations = [
        migrations.RunPython(update_default_profiles, revert_default_profiles),
    ]
