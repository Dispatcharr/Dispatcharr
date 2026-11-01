from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vod", "0013_vod_profiles"),
    ]

    operations = [
        migrations.CreateModel(
            name="VODProfileEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("generation", models.CharField(max_length=32)),
                (
                    "content_type",
                    models.CharField(
                        choices=[("movie", "Movie"), ("series", "Series")],
                        max_length=6,
                    ),
                ),
                ("content_id", models.PositiveIntegerField()),
                ("relation_id", models.PositiveIntegerField()),
                ("public_id", models.PositiveBigIntegerField()),
                ("edition", models.CharField(blank=True, max_length=120)),
                ("source_ids", models.JSONField(default=list)),
                ("primary", models.BooleanField(default=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="entries",
                        to="vod.vodprofile",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["profile", "generation", "content_type", "relation_id"],
                        name="vod_profile_entry_relation",
                    ),
                    models.Index(
                        fields=["profile", "generation", "content_type", "content_id"],
                        name="vod_profile_entry_content",
                    ),
                ],
            },
        ),
    ]
