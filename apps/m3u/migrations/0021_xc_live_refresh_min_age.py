from django.core.validators import MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("m3u", "0020_separate_live_vod_refresh"),
    ]

    operations = [
        migrations.AddField(
            model_name="m3uaccount",
            name="xc_live_refresh_min_age_minutes",
            field=models.PositiveIntegerField(
                default=30,
                help_text="Minimum age of the last successful Live TV refresh before an XC client request may trigger another one.",
                validators=[MaxValueValidator(10080)],
            ),
        ),
    ]
