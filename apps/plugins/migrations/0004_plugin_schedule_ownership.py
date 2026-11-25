from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0003_update_official_repo_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluginconfig",
            name="owned_tasks",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="pluginconfig",
            name="suspended_schedules",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
