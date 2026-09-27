"""Add radio fields to Stream, Channel and ChannelOverride.

Schema only. Stream.is_radio is set on the account's next refresh, and
auto-synced channels copy it from their stream on the sync pass that follows.
Manual channels stay TV until a user sets them.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dispatcharr_channels", "0038_add_catchup_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="stream",
            name="is_radio",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Whether this stream is a radio (audio-only) stream, per the provider",
            ),
        ),
        migrations.AddField(
            model_name="channel",
            name="is_radio",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text="Whether this channel is a radio channel, copied from its source stream",
            ),
        ),
        migrations.AddField(
            model_name="channeloverride",
            name="is_radio",
            field=models.BooleanField(
                null=True,
                blank=True,
                help_text="User override for is_radio; null follows the channel value",
            ),
        ),
    ]
