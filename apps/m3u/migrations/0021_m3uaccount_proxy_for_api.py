# Generated migration for proxy_for_api field
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0020_m3uaccount_proxy'),
    ]

    operations = [
        migrations.AddField(
            model_name='m3uaccount',
            name='proxy_for_api',
            field=models.BooleanField(
                default=False,
                help_text='When enabled, the HTTP proxy will also be used for API calls (M3U download, XC API). When disabled, proxy is only used for streaming.'
            ),
        ),
    ]
