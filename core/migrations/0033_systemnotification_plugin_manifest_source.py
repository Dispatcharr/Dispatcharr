from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0032_limit_default_interleave_delta")]

    operations = [
        migrations.AlterField(
            model_name="systemnotification",
            name="source",
            field=models.CharField(
                choices=[
                    ("system", "System Generated"),
                    ("developer", "Developer Notification"),
                    ("plugin_manifest", "Plugin System Notification"),
                ],
                db_index=True,
                default="system",
                max_length=20,
            ),
        ),
    ]
