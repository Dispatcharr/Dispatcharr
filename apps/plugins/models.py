from django.db import models


class PluginConfig(models.Model):
    """Stores discovered plugins and their persisted settings."""

    key = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)
    # Tracks whether this plugin has ever been enabled at least once
    ever_enabled = models.BooleanField(default=False)
    settings = models.JSONField(default=dict, blank=True)

    # Managed plugin fields (populated when installed from a repo)
    source_repo = models.ForeignKey(
        "PluginRepo",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="installed_plugins",
    )
    slug = models.CharField(max_length=128, blank=True, default="")
    installed_version_is_prerelease = models.BooleanField(default=False)
    deprecated = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_managed(self):
        return bool(self.source_repo_id)

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


OFFICIAL_REPO_URL = (
    "https://raw.githubusercontent.com/Dispatcharr/Plugins/releases/manifest.json"
)


class PluginRepo(models.Model):
    """A remote plugin repository manifest URL."""

    name = models.CharField(max_length=255)
    url = models.URLField(unique=True)
    is_official = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    cached_manifest = models.JSONField(default=dict, blank=True)
    public_key = models.TextField(blank=True, default="")
    signature_verified = models.BooleanField(null=True, blank=True, default=None)
    last_fetched = models.DateTimeField(null=True, blank=True)
    last_fetch_status = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_official", "name"]

    def __str__(self) -> str:
        return self.name
