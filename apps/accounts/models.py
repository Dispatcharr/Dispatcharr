# apps/accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser, Permission, UserManager


class CustomUserManager(UserManager):
    def get_queryset(self):
        # app_data can grow with third-party client blobs. Keep it out of the
        # default load path (auth, /me, user list) so those responses stay small.
        return super().get_queryset().defer("app_data")

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
    # Per-app client storage keyed by an app-supplied namespace. Not included in
    # UserSerializer; only the dedicated /me/app-data/ endpoints read or write it.
    app_data = models.JSONField(default=dict, blank=True)
    api_key = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    stream_limit = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        # app_data is owned by the app-data endpoints (save(update_fields=["app_data"])).
        # A stale in-memory {} (for example the instance returned by create_user)
        # must not wipe concurrent writes when some other field is saved.
        if (
            not self._state.adding
            and kwargs.get("update_fields") is None
            and "app_data" not in self.get_deferred_fields()
        ):
            kwargs["update_fields"] = [
                field.attname
                for field in self._meta.concrete_fields
                if not field.primary_key and field.attname != "app_data"
            ]
        super().save(*args, **kwargs)

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
