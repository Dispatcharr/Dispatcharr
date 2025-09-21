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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"
