from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        # HIER DEINE LETZTE MIGRATION EINTRAGEN!
        # Beispiel:
        # ("m3u", "0011_auto_20241010_1234"),
        ("m3u", "0018_add_profile_custom_properties"),
    ]

    operations = [
        migrations.CreateModel(
            name="M3UAccountMac",
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
                    "address",
                    models.CharField(
                        max_length=17,
                        help_text="Normalized MAC address (AA:BB:CC:DD:EE:FF)",
                    ),
                ),
                (
                    "priority",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Order in which MACs are tried for streaming (0 = highest priority)",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        max_length=20,
                        choices=[
                            ("unknown", "Unknown"),
                            ("valid", "Valid"),
                            ("expired", "Expired"),
                            ("error", "Error"),
                        ],
                        default="unknown",
                        help_text="Validation status based on last portal check",
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        null=True,
                        blank=True,
                        help_text="Parsed expiry timestamp if available",
                    ),
                ),
                (
                    "expires_text",
                    models.CharField(
                        max_length=255,
                        null=True,
                        blank=True,
                        help_text="Raw expiry text from portal (for UI display)",
                    ),
                ),
                (
                    "last_checked",
                    models.DateTimeField(
                        null=True,
                        blank=True,
                    ),
                ),
                (
                    "last_error",
                    models.TextField(
                        null=True,
                        blank=True,
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="macs",
                        help_text="Parent MAC / STB-Portal account",
                        to="m3u.m3uaccount",
                    ),
                ),
            ],
            options={
                "ordering": ["priority", "id"],
                "unique_together": {("account", "address")},
            },
        ),
    ]
