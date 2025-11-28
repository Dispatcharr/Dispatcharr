# Migration to add HLS Output fields to Channel model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('channels', '0030_alter_stream_url'),
        ('hls_output', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='hls_output_enabled',
            field=models.BooleanField(default=False, help_text='Enable HLS output streaming for this channel'),
        ),
        migrations.AddField(
            model_name='channel',
            name='hls_output_profile',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='channels',
                to='hls_output.hlsoutputprofile',
                help_text='HLS output profile to use for this channel'
            ),
        ),
    ]

