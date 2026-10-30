from django.db import migrations, models
from django.db.models import F
from django.db.models.functions import Now
import django.utils.timezone


def preserve_library_dates(apps, schema_editor):
    for name in ("Movie", "Series"):
        apps.get_model("vod", name).objects.using(
            schema_editor.connection.alias
        ).update(library_added_at=F("created_at"))


class Migration(migrations.Migration):
    dependencies = [("vod", "0008_category_ignored")]
    operations = [
        *[
            migrations.AddField(model_name=model, name=name, field=field)
            for model in ("movie", "series")
            for name, field in (
                (
                    "display_name",
                    models.CharField(
                        max_length=255, blank=True, default="", db_default=""
                    ),
                ),
                (
                    "clean_title",
                    models.CharField(
                        max_length=255, blank=True, default="", db_default=""
                    ),
                ),
                (
                    "tmdb_lookup_excluded",
                    models.BooleanField(default=False, db_default=False, db_index=True),
                ),
                (
                    "tmdb_metadata",
                    models.JSONField(default=dict, db_default={}, blank=True),
                ),
                (
                    "tmdb_match_id",
                    models.CharField(
                        max_length=50,
                        blank=True,
                        default="",
                        db_default="",
                        db_index=True,
                    ),
                ),
                (
                    "tmdb_imdb_id",
                    models.CharField(
                        max_length=50, blank=True, default="", db_default=""
                    ),
                ),
                (
                    "tmdb_poster_url",
                    models.CharField(
                        max_length=500, blank=True, default="", db_default=""
                    ),
                ),
                (
                    "tmdb_backdrop_url",
                    models.CharField(
                        max_length=500, blank=True, default="", db_default=""
                    ),
                ),
                (
                    "tmdb_status",
                    models.CharField(
                        max_length=16,
                        blank=True,
                        default="",
                        db_default="",
                        db_index=True,
                    ),
                ),
                ("tmdb_enriched_at", models.DateTimeField(null=True, blank=True)),
                (
                    "library_added_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        db_default=Now(),
                        db_index=True,
                    ),
                ),
            )
        ],
        migrations.RunPython(preserve_library_dates, migrations.RunPython.noop),
        migrations.CreateModel(
            name="VODMetadataState",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        primary_key=True, default=1, editable=False, serialize=False
                    ),
                ),
                ("task_id", models.CharField(max_length=255, blank=True)),
                ("status", models.CharField(max_length=12, default="idle")),
                ("selection", models.JSONField(default=list, blank=True)),
                ("progress", models.JSONField(default=dict, blank=True)),
                ("started_at", models.DateTimeField(null=True, blank=True)),
                ("completed_at", models.DateTimeField(null=True, blank=True)),
                ("error", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
