from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0021_epgsource_priority'),
    ]

    operations = [
        migrations.AddField(
            model_name='epgsource',
            name='programme_index',
            field=models.JSONField(
                blank=True,
                default=None,
                help_text='Byte-offset index mapping tvg_id to file positions, built after each EPG refresh',
                null=True,
            ),
        ),
    ]
