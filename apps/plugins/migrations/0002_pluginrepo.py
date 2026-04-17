import django.db.models.deletion
from django.db import migrations, models


def seed_official_repo(apps, schema_editor):
    PluginRepo = apps.get_model("plugins", "PluginRepo")
    PluginRepo.objects.get_or_create(
        url="https://raw.githubusercontent.com/Dispatcharr/Plugins/releases/manifest.json",
        defaults={
            "name": "Dispatcharr Official",
            "is_official": True,
            "enabled": True,
        },
    )


def unseed_official_repo(apps, schema_editor):
    PluginRepo = apps.get_model("plugins", "PluginRepo")
    PluginRepo.objects.filter(is_official=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PluginRepo",
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
                ("name", models.CharField(max_length=255)),
                ("url", models.URLField(unique=True)),
                ("is_official", models.BooleanField(default=False)),
                ("enabled", models.BooleanField(default=True)),
                ("cached_manifest", models.JSONField(blank=True, default=dict)),
                ("last_fetched", models.DateTimeField(blank=True, null=True)),
                ("public_key", models.TextField(blank=True, default="")),
                ("signature_verified", models.BooleanField(blank=True, default=None, null=True)),
                ("last_fetch_status", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-is_official", "name"],
            },
        ),
        migrations.RunPython(seed_official_repo, unseed_official_repo),
        migrations.AddField(
            model_name="pluginconfig",
            name="source_repo",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="installed_plugins",
                to="plugins.pluginrepo",
            ),
        ),
        migrations.AddField(
            model_name="pluginconfig",
            name="slug",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="pluginconfig",
            name="installed_version_is_prerelease",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="pluginconfig",
            name="deprecated",
            field=models.BooleanField(default=False),
        ),
    ]
