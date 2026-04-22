# Generated for FR #1196 (per-channel lock and hide flags for auto-sync'd channels)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dispatcharr_channels', '0034_remove_stream_dispatcharr_stream_id_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='user_hidden',
            field=models.BooleanField(db_index=True, default=False, help_text='When True, the channel is excluded from HDHR, M3U, and EPG output and preserved across auto-sync refreshes.'),
        ),
        migrations.AddField(
            model_name='channel',
            name='user_locked',
            field=models.BooleanField(default=False, help_text='When True, auto-sync preserves user-set name, number, and group but continues updating EPG data, tvg_id, logo, and tvc_guide_stationid.'),
        ),
    ]
