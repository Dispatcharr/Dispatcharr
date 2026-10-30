import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("django_celery_beat", "0019_alter_periodictasks_options"),
        ("m3u", "0019_m3uaccountprofile_exp_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="m3uaccount",
            name="vod_refresh_interval",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="m3uaccount",
            name="vod_refresh_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="django_celery_beat.periodictask",
            ),
        ),
        migrations.AddField(
            model_name="m3uaccount",
            name="vod_refresh_after_live",
            field=models.BooleanField(
                default=True,
                help_text="Refresh VOD after Live TV unless a separate VOD schedule is configured.",
            ),
        ),
    ]
