# Cap the muxer's interleave window on the locked profiles that map every
# input stream. The default 10s window keeps that much media queued whenever
# a mapped stream (often an empty timed-ID3 PID) never sends a packet.

from django.db import migrations

_INTERLEAVE = "-max_interleave_delta 100K "

_FFMPEG_PARAMETERS = (
    "-fflags +genpts+discardcorrupt "
    "-user_agent {userAgent} "
    "-i {streamUrl} "
    "-map 0 "
    + _INTERLEAVE
    + "-c copy "
    "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
    "-f mpegts pipe:1"
)

_PREVIOUS_FFMPEG_PARAMETERS = (
    "-fflags +genpts+discardcorrupt "
    "-user_agent {userAgent} "
    "-i {streamUrl} "
    "-map 0 "
    "-c copy "
    "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
    "-f mpegts pipe:1"
)

_MEDIA_SERVER_PARAMETERS = (
    "-fflags +discardcorrupt+genpts+nobuffer "
    "-probesize 512K "
    "-analyzeduration 0 "
    "-i pipe:0 "
    "-map 0 "
    + _INTERLEAVE
    + "-c:v copy "
    "-c:a ac3 "
    "-b:a 384k "
    "-c:s copy "
    "-max_muxing_queue_size 4096 "
    "-flush_packets 1 "
    "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
    "-f mpegts pipe:1"
)

_PREVIOUS_MEDIA_SERVER_PARAMETERS = (
    "-fflags +discardcorrupt+genpts+nobuffer "
    "-probesize 512K "
    "-analyzeduration 0 "
    "-i pipe:0 "
    "-map 0 "
    "-c:v copy "
    "-c:a ac3 "
    "-b:a 384k "
    "-c:s copy "
    "-max_muxing_queue_size 4096 "
    "-flush_packets 1 "
    "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
    "-f mpegts pipe:1"
)

_WEB_PLAYER_PARAMETERS = (
    "-fflags +discardcorrupt+genpts+nobuffer "
    "-probesize 512K "
    "-analyzeduration 0 "
    "-i pipe:0 "
    "-map 0 "
    + _INTERLEAVE
    + "-c:v copy "
    "-c:a aac "
    "-b:a 192k "
    "-ac 2 "
    "-c:s copy "
    "-max_muxing_queue_size 4096 "
    "-flush_packets 1 "
    "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
    "-f mpegts pipe:1"
)

_PREVIOUS_WEB_PLAYER_PARAMETERS = (
    "-fflags +discardcorrupt+genpts+nobuffer "
    "-probesize 512K "
    "-analyzeduration 0 "
    "-i pipe:0 "
    "-map 0 "
    "-c:v copy "
    "-c:a aac "
    "-b:a 192k "
    "-ac 2 "
    "-c:s copy "
    "-max_muxing_queue_size 4096 "
    "-flush_packets 1 "
    "-mpegts_flags +pat_pmt_at_frames+resend_headers+initial_discontinuity "
    "-f mpegts pipe:1"
)


def limit_default_interleave_delta(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    OutputProfile = apps.get_model("core", "OutputProfile")
    StreamProfile.objects.filter(name="FFmpeg", locked=True).update(
        parameters=_FFMPEG_PARAMETERS
    )
    OutputProfile.objects.filter(
        name="Media Server (AC3 Audio)", locked=True
    ).update(parameters=_MEDIA_SERVER_PARAMETERS)
    OutputProfile.objects.filter(
        name="Web Player (AAC Audio)", locked=True
    ).update(parameters=_WEB_PLAYER_PARAMETERS)


def restore_default_interleave_delta(apps, schema_editor):
    StreamProfile = apps.get_model("core", "StreamProfile")
    OutputProfile = apps.get_model("core", "OutputProfile")
    StreamProfile.objects.filter(name="FFmpeg", locked=True).update(
        parameters=_PREVIOUS_FFMPEG_PARAMETERS
    )
    OutputProfile.objects.filter(
        name="Media Server (AC3 Audio)", locked=True
    ).update(parameters=_PREVIOUS_MEDIA_SERVER_PARAMETERS)
    OutputProfile.objects.filter(
        name="Web Player (AAC Audio)", locked=True
    ).update(parameters=_PREVIOUS_WEB_PLAYER_PARAMETERS)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_default_reverse_proxy_auth_settings"),
    ]

    operations = [
        migrations.RunPython(
            limit_default_interleave_delta,
            restore_default_interleave_delta,
        ),
    ]
