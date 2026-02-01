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


class PluginDocument(models.Model):
    """
    Document storage for plugins.

    Provides a schema-free way for plugins to store data without migrations.
    Documents are organized into collections (like lightweight tables) and
    namespaced by plugin_key for isolation.

    Example usage in plugin:
        context.storage.save("tasks", "task-1", {"title": "My Task", "done": False})
        context.storage.list("tasks")
        context.storage.get("tasks", "task-1")
        context.storage.delete("tasks", "task-1")
    """

    plugin_key = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Plugin key that owns this document",
    )
    collection = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Collection name (like a table name)",
    )
    doc_id = models.CharField(
        max_length=255,
        help_text="Document ID within the collection",
    )
    data = models.JSONField(
        default=dict,
        help_text="Document data as JSON",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["plugin_key", "collection", "doc_id"]
        indexes = [
            models.Index(fields=["plugin_key", "collection"]),
        ]
        verbose_name = "Plugin Document"
        verbose_name_plural = "Plugin Documents"

    def __str__(self) -> str:
        return f"{self.plugin_key}/{self.collection}/{self.doc_id}"
