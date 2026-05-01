import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '022_default_user_limit_settings'),
        ('dispatcharr_channels', '0036_alter_stream_name'),
        ('epg', '0022_alter_epgdata_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='channel',
            name='user_hidden',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text='Exclude this channel from downstream client output (HDHR, M3U, EPG, XC). Auto-sync still updates provider metadata.',
            ),
        ),
        migrations.CreateModel(
            name='ChannelOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=512, null=True)),
                ('channel_number', models.FloatField(blank=True, null=True)),
                ('tvg_id', models.CharField(blank=True, max_length=255, null=True)),
                ('tvc_guide_stationid', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('channel', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='override', to='dispatcharr_channels.channel')),
                ('channel_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='dispatcharr_channels.channelgroup')),
                ('epg_data', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='epg.epgdata')),
                ('logo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='dispatcharr_channels.logo')),
                ('stream_profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='core.streamprofile')),
            ],
        ),
    ]
