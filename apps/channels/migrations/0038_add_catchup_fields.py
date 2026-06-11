"""Add denormalized catch-up fields to Stream and Channel.

Populated at M3U/XC import time so _xc_channel_entry() can read them as
zero-cost column reads instead of introspecting custom_properties JSON
per channel on every xc_get_live_streams call.
"""

from django.db import migrations, models


def backfill_stream_catchup(apps, schema_editor):
    """Derive is_catchup/catchup_days from Stream.custom_properties JSON."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            UPDATE dispatcharr_channels_stream
            SET is_catchup = TRUE,
                catchup_days = COALESCE(
                    CASE WHEN (custom_properties->>'tv_archive_duration') ~ '^\\d+$'
                         THEN (custom_properties->>'tv_archive_duration')::int
                         ELSE NULL
                    END, 7
                )
            WHERE custom_properties IS NOT NULL
              AND custom_properties != 'null'::jsonb
              AND (
                  custom_properties->>'tv_archive' = '1'
                  -- JSON booleans extract as lowercase 'true' via ->>; the
                  -- 'True' spelling covers Python-str values stored by
                  -- older import code.
                  OR custom_properties->>'tv_archive' = 'true'
                  OR custom_properties->>'tv_archive' = 'True'
              )
        """)


def backfill_channel_catchup(apps, schema_editor):
    """Roll up catch-up fields from streams to channels."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            UPDATE dispatcharr_channels_channel c SET
                is_catchup = EXISTS (
                    SELECT 1 FROM dispatcharr_channels_channelstream cs
                    JOIN dispatcharr_channels_stream s ON s.id = cs.stream_id
                    WHERE cs.channel_id = c.id AND s.is_catchup = TRUE
                ),
                catchup_days = COALESCE((
                    SELECT MAX(s.catchup_days) FROM dispatcharr_channels_channelstream cs
                    JOIN dispatcharr_channels_stream s ON s.id = cs.stream_id
                    WHERE cs.channel_id = c.id AND s.is_catchup = TRUE
                ), 0)
        """)


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0037_auto_sync_overhaul"),
    ]

    operations = [
        # Stream fields
        migrations.AddField(
            model_name="stream",
            name="is_catchup",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Whether this stream supports catch-up/timeshift (tv_archive=1)",
            ),
        ),
        migrations.AddField(
            model_name="stream",
            name="catchup_days",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of days of catch-up archive available (tv_archive_duration)",
            ),
        ),
        # Channel fields
        migrations.AddField(
            model_name="channel",
            name="is_catchup",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Whether any stream on this channel supports catch-up (tv_archive=1)",
            ),
        ),
        migrations.AddField(
            model_name="channel",
            name="catchup_days",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Max catch-up archive days across all streams on this channel",
            ),
        ),
        # Backfill existing data
        migrations.RunPython(
            backfill_stream_catchup,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            backfill_channel_catchup,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
