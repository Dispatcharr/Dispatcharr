"""
Plugin storage interface.

Provides a simple CRUD API for plugins to store documents without migrations.
Each plugin's data is namespaced by its plugin_key.
"""

import json
import logging
import unicodedata
from typing import Any, Dict, List, Optional

from django.db import transaction

from .models import PluginDocument

logger = logging.getLogger(__name__)

# Length limits matching model constraints
MAX_COLLECTION_LENGTH = 128
MAX_DOC_ID_LENGTH = 255


def _validate_identifier(value: str, field_name: str, max_length: int) -> None:
    """
    Validate a collection name or doc_id.

    Allows full Unicode (including international characters) while blocking
    control characters and null bytes that could cause issues.

    Args:
        value: The string to validate
        field_name: Name of field for error messages (e.g., "doc_id")
        max_length: Maximum allowed length

    Raises:
        ValueError: If validation fails
    """
    if not value:
        raise ValueError(f"{field_name} is required")

    if len(value) > max_length:
        raise ValueError(
            f"{field_name} must be {max_length} characters or less "
            f"(got {len(value)})"
        )

    # Block null bytes
    if "\x00" in value:
        raise ValueError(f"{field_name} cannot contain null bytes")

    # Block control characters (ASCII 0-31, 127, Unicode Cc category)
    # but allow normal spaces and printable punctuation
    for char in value:
        if unicodedata.category(char) == "Cc":
            raise ValueError(f"{field_name} cannot contain control characters")


class PluginCollection:
    """
    A reference to a specific collection within a plugin's storage.

    Provides CRUD operations on documents within this collection.
    All operations are automatically namespaced by the parent plugin's key.

    Example usage:
        tasks = storage.collection("tasks")
        tasks.save("task-1", {"title": "My Task", "done": False})
        tasks.get("task-1")
        tasks.all()
        tasks.delete("task-1")
    """

    def __init__(self, plugin_key: str, collection_name: str):
        """
        Initialize a collection reference.

        Args:
            plugin_key: The plugin's unique key (namespace)
            collection_name: Name of this collection
        """
        self._plugin_key = plugin_key
        self._collection_name = collection_name

    @property
    def name(self) -> str:
        """The collection name."""
        return self._collection_name

    def save(self, doc_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save a document to this collection.

        Creates a new document or updates an existing one with the same doc_id.

        Args:
            doc_id: Document ID within the collection
            data: Document data as a dict

        Returns:
            The saved document data with metadata
        """
        _validate_identifier(doc_id, "doc_id", MAX_DOC_ID_LENGTH)

        if not isinstance(data, dict):
            raise ValueError("data must be a dict")

        # Enforce document size limit (1MB)
        MAX_DOCUMENT_SIZE = 1024 * 1024  # 1MB
        try:
            data_size = len(json.dumps(data))
            if data_size > MAX_DOCUMENT_SIZE:
                raise ValueError(
                    f"Document exceeds maximum size of {MAX_DOCUMENT_SIZE} bytes "
                    f"(got {data_size} bytes)"
                )
        except (TypeError, ValueError) as e:
            if "exceeds maximum size" in str(e):
                raise
            raise ValueError(f"Data is not JSON-serializable: {e}")

        doc, created = PluginDocument.objects.update_or_create(
            plugin_key=self._plugin_key,
            collection=self._collection_name,
            doc_id=doc_id,
            defaults={"data": data},
        )

        logger.debug(
            f"{'Created' if created else 'Updated'} document "
            f"{self._plugin_key}/{self._collection_name}/{doc_id}"
        )

        return self._document_to_dict(doc)

    def get(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document data with metadata, or None if not found
        """
        _validate_identifier(doc_id, "doc_id", MAX_DOC_ID_LENGTH)

        try:
            doc = PluginDocument.objects.get(
                plugin_key=self._plugin_key,
                collection=self._collection_name,
                doc_id=doc_id,
            )
            return self._document_to_dict(doc)
        except PluginDocument.DoesNotExist:
            return None

    def all(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List all documents in this collection.

        Args:
            limit: Maximum number of documents to return
            offset: Number of documents to skip

        Returns:
            List of documents with metadata
        """
        queryset = PluginDocument.objects.filter(
            plugin_key=self._plugin_key,
            collection=self._collection_name,
        ).order_by("-updated_at")

        # Apply offset and limit using slicing
        if offset and limit:
            queryset = queryset[offset:offset + limit]
        elif offset:
            queryset = queryset[offset:]
        elif limit:
            queryset = queryset[:limit]

        return [self._document_to_dict(doc) for doc in queryset]

    def delete(self, doc_id: str) -> bool:
        """
        Delete a document by ID.

        Args:
            doc_id: Document ID

        Returns:
            True if document was deleted, False if it didn't exist
        """
        _validate_identifier(doc_id, "doc_id", MAX_DOC_ID_LENGTH)

        deleted_count, _ = PluginDocument.objects.filter(
            plugin_key=self._plugin_key,
            collection=self._collection_name,
            doc_id=doc_id,
        ).delete()

        if deleted_count > 0:
            logger.debug(
                f"Deleted document {self._plugin_key}/{self._collection_name}/{doc_id}"
            )
            return True
        return False

    def clear(self) -> int:
        """
        Delete all documents in this collection.

        Uses transaction.atomic() to ensure all-or-nothing deletion.
        If interrupted, the entire operation rolls back.

        Returns:
            Number of documents deleted
        """
        with transaction.atomic():
            deleted_count, _ = PluginDocument.objects.filter(
                plugin_key=self._plugin_key,
                collection=self._collection_name,
            ).delete()

            if deleted_count > 0:
                logger.debug(
                    f"Cleared {deleted_count} documents from "
                    f"{self._plugin_key}/{self._collection_name}"
                )
            return deleted_count

    def count(self) -> int:
        """
        Count documents in this collection.

        Returns:
            Number of documents
        """
        return PluginDocument.objects.filter(
            plugin_key=self._plugin_key,
            collection=self._collection_name,
        ).count()

    def exists(self, doc_id: str) -> bool:
        """
        Check if a document exists.

        Args:
            doc_id: Document ID

        Returns:
            True if document exists
        """
        _validate_identifier(doc_id, "doc_id", MAX_DOC_ID_LENGTH)

        return PluginDocument.objects.filter(
            plugin_key=self._plugin_key,
            collection=self._collection_name,
            doc_id=doc_id,
        ).exists()

    def _document_to_dict(self, doc: PluginDocument) -> Dict[str, Any]:
        """Convert a PluginDocument to a dict with metadata."""
        return {
            "id": doc.doc_id,
            "data": doc.data,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        }


class PluginStorage:
    """
    Storage interface for a single plugin.

    Provides document-style storage organized into collections.
    All data is namespaced by the plugin's key.

    Example usage:
        storage = PluginStorage("my_plugin")

        # Get a collection reference
        tasks = storage.collection("tasks")

        # CRUD operations on the collection
        tasks.save("task-1", {"title": "My Task", "done": False})
        task = tasks.get("task-1")
        all_tasks = tasks.all()
        tasks.delete("task-1")

        # List all collections
        storage.collections()
    """

    def __init__(self, plugin_key: str):
        """
        Initialize storage for a plugin.

        Args:
            plugin_key: The plugin's unique key (namespace)
        """
        if not plugin_key:
            raise ValueError("plugin_key is required")
        self.plugin_key = plugin_key
        self._collection_cache: Dict[str, PluginCollection] = {}

    def collection(self, name: str) -> PluginCollection:
        """
        Get a reference to a collection.

        Collections are created lazily - they don't exist until you save
        a document to them.

        Args:
            name: Collection name

        Returns:
            A PluginCollection instance for the named collection
        """
        _validate_identifier(name, "collection name", MAX_COLLECTION_LENGTH)

        # Cache collection references for efficiency
        if name not in self._collection_cache:
            self._collection_cache[name] = PluginCollection(self.plugin_key, name)

        return self._collection_cache[name]

    def collections(self) -> List[str]:
        """
        List all collections that have documents.

        Returns:
            List of collection names
        """
        result = (
            PluginDocument.objects.filter(plugin_key=self.plugin_key)
            .values_list("collection", flat=True)
            .distinct()
        )
        return list(result)

    def drop(self, collection_name: str) -> int:
        """
        Drop an entire collection (delete all its documents).

        Args:
            collection_name: Name of collection to drop

        Returns:
            Number of documents deleted
        """
        return self.collection(collection_name).clear()

    def clear_all(self) -> int:
        """
        Delete ALL documents for this plugin (all collections).

        This is a destructive operation intended for the "Delete Plugin Data"
        UI action. Uses transaction.atomic() for all-or-nothing deletion.

        Returns:
            Number of documents deleted
        """
        with transaction.atomic():
            deleted_count, _ = PluginDocument.objects.filter(
                plugin_key=self.plugin_key,
            ).delete()

            if deleted_count > 0:
                logger.info(
                    f"Cleared all storage for plugin {self.plugin_key}: "
                    f"{deleted_count} documents"
                )

            return deleted_count
