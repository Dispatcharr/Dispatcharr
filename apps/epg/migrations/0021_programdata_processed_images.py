# Generated migration to add processed_images field for portrait banner conversion

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0020_migrate_time_to_starttime_placeholders'),
    ]

    operations = [
        migrations.AddField(
            model_name='programdata',
            name='processed_images',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Processed portrait images (2:3 ratio) stored locally. Array of dicts with \'original_url\', \'local_path\', \'type\', etc.',
                null=True
            ),
        ),
    ]
