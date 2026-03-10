# apps/accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser, Permission, UserManager


class CustomUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('user_level', 10)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    objects = CustomUserManager()
    """
    Custom user model for Dispatcharr.
    Inherits from Django's AbstractUser to add additional fields if needed.
    """

    class UserLevel(models.IntegerChoices):
        STREAMER = 0, "Streamer"
        STANDARD = 1, "Standard User"
        ADMIN = 10, "Admin"

    avatar_config = models.JSONField(default=dict, blank=True, null=True)
    channel_profiles = models.ManyToManyField(
        "dispatcharr_channels.ChannelProfile",
        blank=True,
        related_name="users",
    )
    user_level = models.IntegerField(default=UserLevel.STREAMER)
    custom_properties = models.JSONField(default=dict, blank=True, null=True)
    api_key = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    oidc_provider = models.ForeignKey(
        'OIDCProvider',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='users',
        help_text='Set when the user was created or last authenticated via OIDC',
    )

    def __str__(self):
        return self.username

    def get_groups(self):
        """
        Returns the groups (roles) the user belongs to.
        """
        return self.groups.all()

    def get_permissions(self):
        """
        Returns the permissions assigned to the user and their groups.
        """
        return self.user_permissions.all() | Permission.objects.filter(group__user=self)


class OIDCProvider(models.Model):
    """Configuration for an OpenID Connect identity provider."""

    name = models.CharField(max_length=255, help_text="Display name for the provider (e.g. Google, Keycloak)")
    slug = models.SlugField(max_length=255, unique=True, help_text="URL-safe identifier")
    issuer_url = models.URLField(help_text="OIDC Issuer URL (e.g. https://accounts.google.com)")
    client_id = models.CharField(max_length=512)
    client_secret = models.CharField(max_length=512)
    scopes = models.CharField(max_length=512, default="openid profile email")
    is_enabled = models.BooleanField(default=True)
    auto_create_users = models.BooleanField(
        default=True,
        help_text="Automatically create local users on first OIDC login",
    )
    default_user_level = models.IntegerField(
        default=User.UserLevel.STANDARD,
        choices=User.UserLevel.choices,
        help_text="User level assigned to auto-created users",
    )
    claim_mapping = models.JSONField(
        default=dict,
        blank=True,
        help_text='Map OIDC claims to user fields, e.g. {"preferred_username": "username", "email": "email"}',
    )
    group_claim = models.CharField(
        max_length=255,
        blank=True,
        default="groups",
        help_text='OIDC claim that contains the user groups (e.g. "groups", "roles", "realm_access.roles")',
    )
    group_to_level_mapping = models.JSONField(
        default=dict,
        blank=True,
        help_text='Map IdP group names to Dispatcharr user levels, e.g. {"dispatcharr-admins": 10, "dispatcharr-users": 1, "dispatcharr-streamers": 0}',
    )
    button_text = models.CharField(max_length=255, blank=True, help_text="Custom button text on login page")
    button_color = models.CharField(max_length=50, blank=True, default="#4285F4")
    allowed_redirect_uris = models.TextField(
        blank=True,
        default="",
        help_text="Comma-separated list of allowed redirect URIs (e.g. https://app.example.com). If empty, only the request origin is allowed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "OIDC Provider"
        verbose_name_plural = "OIDC Providers"

    def __str__(self):
        return self.name

    @property
    def discovery_url(self):
        issuer = self.issuer_url.rstrip("/")
        return f"{issuer}/.well-known/openid-configuration"
