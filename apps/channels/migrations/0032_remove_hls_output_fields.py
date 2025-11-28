# Migration to remove HLS Output fields from Channel model

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dispatcharr_channels', '0031_channel_hls_output_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='channel',
            name='hls_output_profile',
        ),
        migrations.RemoveField(
            model_name='channel',
            name='hls_output_enabled',
        ),
    ]

