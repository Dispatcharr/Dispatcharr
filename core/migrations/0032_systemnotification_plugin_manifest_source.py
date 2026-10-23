from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0031_default_reverse_proxy_auth_settings")]

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
