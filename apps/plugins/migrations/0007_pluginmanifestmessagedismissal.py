import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0006_repair_acknowledged_capabilities"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PluginManifestMessageDismissal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.UUIDField()),
                ("dismissed_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dismissed_plugin_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["user", "message_id"], name="plugins_pm_user_id_8f5f4f_idx")],
                "constraints": [models.UniqueConstraint(fields=("user", "message_id"), name="unique_plugin_message_dismissal")],
            },
        ),
    ]
