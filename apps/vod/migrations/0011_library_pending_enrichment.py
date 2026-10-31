import django.utils.timezone
from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):
    dependencies = (("vod", "0010_source_tmdb_assignment"),)
    operations = (
        migrations.AddField(
            model_name="vodmetadatastate",
            name="job_heartbeat",
            field=models.DateTimeField(
                db_default=Now(), default=django.utils.timezone.now
            ),
        ),
        migrations.AddField(
            model_name="vodmetadatastate",
            name="pending_enrichment",
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
        migrations.AddField(
            model_name="vodmetadatastate",
            name="refreshing_accounts",
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
    )
