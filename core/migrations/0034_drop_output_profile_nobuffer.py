# nobuffer discards every packet read while FFmpeg identifies the codecs,
# and those packets are playable.
#
# MPEG-TS has no header, so FFmpeg does not stop probing when the program
# table is seen. With analyzeduration unset it reads 5 seconds of media, or
# 7 seconds if a stream is still unidentified. New clients join 5 seconds
# behind live, so a 7 second probe has to wait on the live edge. 3 seconds
# of media fits inside that buffer (on a buffered 1080p60 A&E capture the
# read took under 200ms of wall clock and still reported 1920x1080 and
# 5.1 AC3). probesize is 20MB so a 4K bitrate cannot end the probe on bytes
# before those 3 seconds of media have been read.

from django.db import migrations


_MEDIA_SERVER_PARAMETERS = (
    "-fflags +discardcorrupt+genpts "
    "-probesize 20M "
    "-analyzeduration 3M "
    "-i pipe:0 "
    "-map 0 "
    "-max_interleave_delta 100K "
    "-c:v copy "
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
    "-max_interleave_delta 100K "
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
    "-fflags +discardcorrupt+genpts "
    "-probesize 20M "
    "-analyzeduration 3M "
    "-i pipe:0 "
    "-map 0 "
    "-max_interleave_delta 100K "
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

_PREVIOUS_WEB_PLAYER_PARAMETERS = (
    "-fflags +discardcorrupt+genpts+nobuffer "
    "-probesize 512K "
    "-analyzeduration 0 "
    "-i pipe:0 "
    "-map 0 "
    "-max_interleave_delta 100K "
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


def retune_output_profile_probe(apps, schema_editor):
    OutputProfile = apps.get_model("core", "OutputProfile")
    OutputProfile.objects.filter(
        name="Media Server (AC3 Audio)", locked=True
    ).update(parameters=_MEDIA_SERVER_PARAMETERS)
    OutputProfile.objects.filter(
        name="Web Player (AAC Audio)", locked=True
    ).update(parameters=_WEB_PLAYER_PARAMETERS)


def restore_output_profile_probe(apps, schema_editor):
    OutputProfile = apps.get_model("core", "OutputProfile")
    OutputProfile.objects.filter(
        name="Media Server (AC3 Audio)", locked=True
    ).update(parameters=_PREVIOUS_MEDIA_SERVER_PARAMETERS)
    OutputProfile.objects.filter(
        name="Web Player (AAC Audio)", locked=True
    ).update(parameters=_PREVIOUS_WEB_PLAYER_PARAMETERS)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0033_systemnotification_plugin_manifest_source"),
    ]

    operations = [
        migrations.RunPython(
            retune_output_profile_probe,
            restore_output_profile_probe,
        ),
    ]
