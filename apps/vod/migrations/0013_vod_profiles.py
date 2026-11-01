from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def create_default_profile(apps, schema_editor):
    """Preserve the current client output: every enabled category, account priority."""
    profile_model = apps.get_model("vod", "VODProfile")
    rule_model = apps.get_model("vod", "VODProfileCategoryRule")
    if not profile_model.objects.using(schema_editor.connection.alias).filter(
        is_default=True
    ).exists():
        profile = profile_model.objects.using(schema_editor.connection.alias).create(
            name="Default",
            is_default=True,
            ranking=["provider"],
        )
        rule_model.objects.using(schema_editor.connection.alias).bulk_create(
            rule_model(
                profile=profile, scope=scope, regex_pattern=".*", action="enable"
            )
            for scope in ("movie", "series")
        )


class Migration(migrations.Migration):
    dependencies = [
        ("vod", "0012_library_blocked"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VODProfile",
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
                ("name", models.CharField(max_length=255, unique=True)),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "output_mode",
                    models.CharField(
                        choices=[("compact", "Compact"), ("variants", "Sources")],
                        default="compact",
                        max_length=10,
                    ),
                ),
                (
                    "name_template",
                    models.CharField(
                        default="{title} [{dub} · {resolution} · {features}]",
                        max_length=500,
                    ),
                ),
                (
                    "output_groups",
                    models.CharField(
                        choices=[
                            ("provider", "Provider"),
                            ("movie_series", "Movie & Series"),
                        ],
                        default="provider",
                        max_length=12,
                    ),
                ),
                (
                    "title_source",
                    models.CharField(default="provider", max_length=10),
                ),
                (
                    "metadata_source",
                    models.CharField(
                        choices=[("provider", "Provider"), ("enriched", "Enriched")],
                        default="provider",
                        max_length=10,
                    ),
                ),
                ("category_choices", models.JSONField(blank=True, default=list)),
                ("content_filters", models.JSONField(blank=True, default=dict)),
                ("excluded_titles", models.JSONField(blank=True, default=list)),
                ("edition_rules", models.JSONField(blank=True, default=list)),
                ("ranking", models.JSONField(blank=True, default=list)),
                ("audio_language_order", models.JSONField(blank=True, default=list)),
                (
                    "subtitle_language_order",
                    models.JSONField(blank=True, default=list),
                ),
                ("provider_order", models.JSONField(blank=True, default=list)),
                (
                    "catalog_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("building", "Building"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("catalog_generation", models.CharField(blank=True, max_length=32)),
                ("catalog_signature", models.CharField(blank=True, max_length=64)),
                ("catalog_counts", models.JSONField(blank=True, default=dict)),
                ("catalog_progress", models.JSONField(blank=True, default=dict)),
                ("catalog_started_at", models.DateTimeField(blank=True, null=True)),
                ("catalog_completed_at", models.DateTimeField(blank=True, null=True)),
                ("catalog_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("-is_default", "name"),
                "constraints": [
                    models.UniqueConstraint(
                        condition=Q(is_default=True),
                        fields=("is_default",),
                        name="vod_single_default_profile",
                    ),
                    models.CheckConstraint(
                        condition=Q(is_default=False) | Q(is_active=True),
                        name="vod_default_profile_active",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="VODProfileAssignment",
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
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="assignments",
                        to="vod.vodprofile",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="vod_profile_assignment",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="VODProfileCategoryRule",
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
                (
                    "scope",
                    models.CharField(
                        choices=[("movie", "VOD Movies"), ("series", "VOD Series")],
                        max_length=10,
                    ),
                ),
                ("regex_pattern", models.CharField(max_length=500)),
                (
                    "action",
                    models.CharField(
                        choices=[("enable", "Enabled"), ("disable", "Disabled")],
                        default="disable",
                        max_length=10,
                    ),
                ),
                ("case_sensitive", models.BooleanField(default=False)),
                ("enabled", models.BooleanField(default=True)),
                ("order", models.PositiveIntegerField(default=0)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="category_rules",
                        to="vod.vodprofile",
                    ),
                ),
            ],
            options={"ordering": ("scope", "order", "id")},
        ),
        migrations.RunPython(create_default_profile, migrations.RunPython.noop),
    ]
