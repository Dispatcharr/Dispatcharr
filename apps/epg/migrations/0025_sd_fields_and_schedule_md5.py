from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0024_alter_epgsource_api_key'),
    ]

    operations = [
        # Add sd_changes_remaining to EPGSource
        migrations.AddField(
            model_name='epgsource',
            name='sd_changes_remaining',
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text='Number of Schedules Direct lineup additions remaining today (resets at midnight UTC)',
            ),
        ),
        # Add sd_changes_reset_at to EPGSource
        migrations.AddField(
            model_name='epgsource',
            name='sd_changes_reset_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='UTC datetime when the Schedules Direct daily lineup change counter resets',
            ),
        ),
        # Add sd_program_md5 to ProgramData
        migrations.AddField(
            model_name='programdata',
            name='sd_program_md5',
            field=models.CharField(
                blank=True,
                max_length=22,
                null=True,
                help_text='MD5 hash from Schedules Direct for delta detection',
            ),
        ),
        # Create SDScheduleMD5 model
        migrations.CreateModel(
            name='SDScheduleMD5',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('station_id', models.CharField(help_text='Schedules Direct stationID', max_length=20)),
                ('date', models.DateField(help_text='Schedule date (UTC)')),
                ('md5', models.CharField(help_text='MD5 hash of the schedule for this station/date from Schedules Direct', max_length=22)),
                ('last_modified', models.DateTimeField(help_text='Last modified timestamp from Schedules Direct')),
                ('epg_source', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sd_schedule_md5s',
                    to='epg.epgsource',
                )),
            ],
            options={
                'indexes': [
                    models.Index(fields=['epg_source', 'station_id'], name='epg_sdsche_epg_sou_idx'),
                ],
                'unique_together': {('epg_source', 'station_id', 'date')},
            },
        ),
    ]
