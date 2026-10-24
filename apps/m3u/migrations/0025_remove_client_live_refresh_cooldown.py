from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("m3u", "0024_m3uaccount_setup_navigation"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="m3uaccount",
            name="xc_live_refresh_min_age_minutes",
        ),
    ]
