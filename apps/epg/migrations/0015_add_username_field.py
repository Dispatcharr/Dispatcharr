from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('epg', '0014_epgsource_extracted_file_path'),
    ]

    operations = [
        migrations.AddField(
            model_name='epgsource',
            name='username',
            field=models.CharField(blank=True, help_text='For Schedules Direct username', max_length=255, null=True),
        ),
    ]