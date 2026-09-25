# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0019_m3uaccountprofile_exp_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='m3uaccount',
            name='hash_key',
            field=models.CharField(
                blank=True,
                help_text=(
                    "Comma-separated fields used to generate this account's "
                    "stream hash (e.g. 'name,url'). Leave blank to use the "
                    "global 'M3U Hash Key' setting."
                ),
                max_length=255,
                null=True,
            ),
        ),
    ]
