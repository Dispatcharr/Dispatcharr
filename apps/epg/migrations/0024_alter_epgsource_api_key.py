from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0023_epgsource_username'),
    ]

    operations = [
        migrations.AlterField(
            model_name='epgsource',
            name='api_key',
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                help_text='Password for Schedules Direct authentication',
            ),
        ),
    ]
