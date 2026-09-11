"""Add denormalized radio fields to Stream and Channel."""

from django.db import migrations, models


def backfill_stream_radio(apps, schema_editor):
    """Derive is_radio from Stream.custom_properties JSON.

    Two provider conventions are known to carry this signal:
    - XC accounts: stream_type == "radio_streams" (confirmed against a real
      provider response).
    - Standard M3U accounts: a "radio" EXTINF attribute, stored verbatim in
      custom_properties by the generic attribute parser.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            UPDATE dispatcharr_channels_stream
            SET is_radio = TRUE
            WHERE custom_properties IS NOT NULL
              AND custom_properties != 'null'::jsonb
              AND (
                  lower(custom_properties->>'stream_type') = 'radio_streams'
                  OR lower(custom_properties->>'radio') IN ('1', 'true')
              )
        """)


def backfill_channel_radio(apps, schema_editor):
    """Roll up the radio flag from streams to channels."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            UPDATE dispatcharr_channels_channel c SET
                is_radio = EXISTS (
                    SELECT 1 FROM dispatcharr_channels_channelstream cs
                    JOIN dispatcharr_channels_stream s ON s.id = cs.stream_id
                    WHERE cs.channel_id = c.id AND s.is_radio = TRUE
                )
        """)


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0038_add_catchup_fields"),
    ]

    operations = [
        # Stream field
        migrations.AddField(
            model_name="stream",
            name="is_radio",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Whether this stream is a radio (audio-only) stream, per the provider",
            ),
        ),
        # Channel field
        migrations.AddField(
            model_name="channel",
            name="is_radio",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Whether any stream on this channel is a radio stream",
            ),
        ),
        # Backfill existing data
        migrations.RunPython(
            backfill_stream_radio,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            backfill_channel_radio,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
