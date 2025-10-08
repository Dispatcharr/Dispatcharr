from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("media_library", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="library",
            name="use_as_vod_source",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, media matched in this library syncs into the VOD catalog.",
            ),
        ),
    ]
