from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_systemnotification_notificationdismissal"),
    ]

    operations = [
        migrations.CreateModel(
            name="IPAlias",
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
                    "ip_address",
                    models.GenericIPAddressField(
                        help_text="The IP address to assign an alias to.",
                        unique=True,
                    ),
                ),
                (
                    "alias",
                    models.CharField(
                        help_text="A friendly name for this IP address (e.g., 'Dad's House').",
                        max_length=100,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "IP Alias",
                "verbose_name_plural": "IP Aliases",
                "ordering": ["alias"],
            },
        ),
    ]
