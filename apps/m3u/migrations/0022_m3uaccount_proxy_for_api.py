# Generated migration for proxy and proxy_for_api fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0021_m3uaccountprofile_exp_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='m3uaccount',
            name='proxy',
            field=models.CharField(
                blank=True,
                max_length=255,
                null=True,
                help_text='HTTP proxy URL for streaming (e.g., http://proxy.example.com:8080)'
            ),
        ),
        migrations.AddField(
            model_name='m3uaccount',
            name='proxy_for_api',
            field=models.BooleanField(
                default=False,
                help_text='When enabled, the HTTP proxy will also be used for API calls (M3U download, XC API). When disabled, proxy is only used for streaming.'
            ),
        ),
    ]
