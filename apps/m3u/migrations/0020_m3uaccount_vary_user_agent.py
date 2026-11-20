# Generated manually to match the project's existing migration style.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('m3u', '0019_m3uaccountprofile_exp_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='m3uaccount',
            name='vary_user_agent',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Append a per-connection number to this account's User-Agent so "
                    "concurrent streams don't all present an identical UA to the "
                    "provider. Some providers' middleware misbehaves when "
                    "multiple simultaneous connections share one UA string. Put {#} "
                    "anywhere in the User-Agent to control where the number goes; "
                    "otherwise it's appended as a suffix."
                ),
            ),
        ),
    ]
