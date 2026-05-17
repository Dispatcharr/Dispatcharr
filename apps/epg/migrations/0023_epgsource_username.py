# Generated migration — adds username field to EPGSource for Schedules Direct auth

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0022_alter_epgdata_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='epgsource',
            name='username',
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text='Username for Schedules Direct authentication',
            ),
        ),
    ]
