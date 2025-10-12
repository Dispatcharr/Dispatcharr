from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("media_library", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="mediaitem",
            name="is_missing",
            field=models.BooleanField(default=False),
        ),
    ]

