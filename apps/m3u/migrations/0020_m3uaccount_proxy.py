# Generated migration for adding proxy field to M3UAccount

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0019_m3uaccountprofile_exp_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='m3uaccount',
            name='proxy',
            field=models.CharField(
                blank=True,
                help_text='HTTP proxy URL (e.g., http://proxy.example.com:8080) for this M3U account',
                max_length=255,
                null=True
            ),
        ),
    ]
