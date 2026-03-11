import base64
import hashlib

from django.db import migrations, models
import django.db.models.deletion


def encrypt_existing_secrets(apps, schema_editor):
    """Encrypt plaintext client_secret values created before this migration."""
    try:
        from cryptography.fernet import Fernet
        from django.conf import settings

        raw = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        f = Fernet(base64.urlsafe_b64encode(raw))
    except Exception:
        # cryptography unavailable; values will be encrypted on next save().
        return

    OIDCProvider = apps.get_model("accounts", "OIDCProvider")
    for provider in OIDCProvider.objects.all():
        secret = provider.client_secret
        if secret and not secret.startswith("enc$"):
            encrypted = "enc$" + f.encrypt(secret.encode()).decode()
            OIDCProvider.objects.filter(pk=provider.pk).update(client_secret=encrypted)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_alter_user_managers"),
    ]

    operations = [
        migrations.CreateModel(
            name="OIDCProvider",
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
                    "name",
                    models.CharField(
                        help_text="Display name for the provider (e.g. Google, Keycloak)",
                        max_length=255,
                    ),
                ),
                (
                    "slug",
                    models.SlugField(
                        help_text="URL-safe identifier",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "issuer_url",
                    models.URLField(
                        help_text="OIDC Issuer URL (e.g. https://accounts.google.com)",
                    ),
                ),
                ("client_id", models.CharField(max_length=512)),
                # Size allows for Fernet overhead.
                ("client_secret", models.CharField(max_length=1024)),
                (
                    "scopes",
                    models.CharField(
                        default="openid profile email",
                        max_length=512,
                    ),
                ),
                ("is_enabled", models.BooleanField(default=True)),
                (
                    "auto_create_users",
                    models.BooleanField(
                        default=True,
                        help_text="Automatically create local users on first OIDC login",
                    ),
                ),
                (
                    "default_user_level",
                    models.IntegerField(
                        choices=[(0, "Streamer"), (1, "Standard User"), (10, "Admin")],
                        default=1,
                        help_text="User level assigned to auto-created users",
                    ),
                ),
                (
                    "claim_mapping",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text='Map OIDC claims to user fields, e.g. {"preferred_username": "username", "email": "email"}',
                    ),
                ),
                (
                    "group_claim",
                    models.CharField(
                        blank=True,
                        default="groups",
                        help_text='OIDC claim that contains the user groups (e.g. "groups", "roles", "realm_access.roles")',
                        max_length=255,
                    ),
                ),
                (
                    "group_to_level_mapping",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text='Map IdP group names to Dispatcharr user levels, e.g. {"dispatcharr-admins": 10, "dispatcharr-users": 1, "dispatcharr-streamers": 0}',
                    ),
                ),
                (
                    "button_text",
                    models.CharField(
                        blank=True,
                        help_text="Custom button text on login page",
                        max_length=255,
                    ),
                ),
                (
                    "button_color",
                    models.CharField(
                        blank=True,
                        default="#4285F4",
                        max_length=50,
                    ),
                ),
                (
                    "allowed_redirect_uris",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Comma-separated list of allowed redirect URIs (e.g. https://app.example.com). If empty, only the request origin is allowed.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "OIDC Provider",
                "verbose_name_plural": "OIDC Providers",
            },
        ),
        migrations.AddField(
            model_name="user",
            name="oidc_provider",
            field=models.ForeignKey(
                blank=True,
                help_text="Set when the user was created or last authenticated via OIDC",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="users",
                to="accounts.oidcprovider",
            ),
        ),
        # Encrypt plaintext secrets already present in the DB.
        migrations.RunPython(encrypt_existing_secrets, noop),
    ]
