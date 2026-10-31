from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vod", "0011_library_pending_enrichment")]
    operations = [
        migrations.AddField(
            model_name=model,
            name="library_blocked",
            field=models.BooleanField(default=False, db_default=False, db_index=True),
        )
        for model in ("movie", "series")
    ]
