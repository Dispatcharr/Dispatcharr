from django.db import migrations


def add_subtitle_copy(apps, schema_editor):
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


def remove_subtitle_copy(apps, schema_editor):
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


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_vlc_play_and_exit'),
    ]

    operations = [
        migrations.RunPython(
            add_subtitle_copy,
            remove_subtitle_copy,
        ),
    ]
