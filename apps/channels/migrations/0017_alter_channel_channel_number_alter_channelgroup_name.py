# Generated by Django 5.1.6 on 2025-04-19 12:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dispatcharr_channels', '0016_channelstream_unique_channel_stream'),
    ]

    operations = [
        migrations.AlterField(
            model_name='channel',
            name='channel_number',
            field=models.IntegerField(db_index=True),
        ),
        migrations.AlterField(
            model_name='channelgroup',
            name='name',
            field=models.CharField(db_index=True, max_length=100, unique=True),
        ),
    ]
