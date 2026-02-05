"""
Tests for plugin storage infrastructure.

Covers:
- PluginDocument model
- PluginCollection class
- PluginStorage class
- Manifest key detection
- Storage API endpoints
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import PluginConfig, PluginDocument
from .storage import PluginStorage, PluginCollection
from .manifest import (
    load_manifest,
    get_manifest_key,
    derive_key_from_directory,
    detect_plugin_key,
)

User = get_user_model()


class PluginDocumentModelTestCase(TestCase):
    """Test cases for PluginDocument model."""

    def test_create_document(self):
        """Test creating a plugin document."""
        doc = PluginDocument.objects.create(
            plugin_key="test-plugin",
            collection="tasks",
            doc_id="task-1",
            data={"title": "Test Task", "done": False},
        )

        self.assertEqual(doc.plugin_key, "test-plugin")
        self.assertEqual(doc.collection, "tasks")
        self.assertEqual(doc.doc_id, "task-1")
        self.assertEqual(doc.data["title"], "Test Task")
        self.assertIsNotNone(doc.created_at)
        self.assertIsNotNone(doc.updated_at)

    def test_unique_constraint(self):
        """Test that plugin_key + collection + doc_id is unique."""
        PluginDocument.objects.create(
            plugin_key="test-plugin",
            collection="tasks",
            doc_id="task-1",
            data={"title": "First"},
        )

        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            PluginDocument.objects.create(
                plugin_key="test-plugin",
                collection="tasks",
                doc_id="task-1",
                data={"title": "Duplicate"},
            )

    def test_str_representation(self):
        """Test string representation of document."""
        doc = PluginDocument.objects.create(
            plugin_key="my-plugin",
            collection="notes",
            doc_id="note-123",
            data={},
        )
        self.assertEqual(str(doc), "my-plugin/notes/note-123")


class PluginCollectionTestCase(TestCase):
    """Test cases for PluginCollection class."""

    def setUp(self):
        self.collection = PluginCollection("test-plugin", "tasks")

    def test_save_creates_document(self):
        """Test saving a new document."""
        result = self.collection.save("task-1", {"title": "My Task"})

        self.assertEqual(result["id"], "task-1")
        self.assertEqual(result["data"]["title"], "My Task")
        self.assertIn("created_at", result)
        self.assertIn("updated_at", result)

        # Verify in database
        doc = PluginDocument.objects.get(
            plugin_key="test-plugin",
            collection="tasks",
            doc_id="task-1",
        )
        self.assertEqual(doc.data["title"], "My Task")

    def test_save_updates_existing_document(self):
        """Test that save updates an existing document."""
        self.collection.save("task-1", {"title": "Original"})
        result = self.collection.save("task-1", {"title": "Updated"})

        self.assertEqual(result["data"]["title"], "Updated")
        self.assertEqual(PluginDocument.objects.filter(doc_id="task-1").count(), 1)

    def test_save_requires_doc_id(self):
        """Test that save requires a doc_id."""
        with self.assertRaises(ValueError) as ctx:
            self.collection.save("", {"title": "Test"})
        self.assertIn("doc_id is required", str(ctx.exception))

    def test_save_requires_dict_data(self):
        """Test that save requires data to be a dict."""
        with self.assertRaises(ValueError) as ctx:
            self.collection.save("task-1", "not a dict")
        self.assertIn("data must be a dict", str(ctx.exception))

    def test_get_returns_document(self):
        """Test getting an existing document."""
        self.collection.save("task-1", {"title": "Test"})

        result = self.collection.get("task-1")

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "task-1")
        self.assertEqual(result["data"]["title"], "Test")

    def test_get_returns_none_for_missing(self):
        """Test that get returns None for non-existent document."""
        result = self.collection.get("nonexistent")
        self.assertIsNone(result)

    def test_all_returns_documents(self):
        """Test listing all documents in collection."""
        self.collection.save("task-1", {"title": "Task 1"})
        self.collection.save("task-2", {"title": "Task 2"})
        self.collection.save("task-3", {"title": "Task 3"})

        results = self.collection.all()

        self.assertEqual(len(results), 3)
        ids = [r["id"] for r in results]
        self.assertIn("task-1", ids)
        self.assertIn("task-2", ids)
        self.assertIn("task-3", ids)

    def test_all_with_limit(self):
        """Test listing with limit."""
        for i in range(5):
            self.collection.save(f"task-{i}", {"title": f"Task {i}"})

        results = self.collection.all(limit=3)
        self.assertEqual(len(results), 3)

    def test_all_with_offset(self):
        """Test listing with offset."""
        for i in range(5):
            self.collection.save(f"task-{i}", {"title": f"Task {i}"})

        results = self.collection.all(offset=2)
        self.assertEqual(len(results), 3)

    def test_all_returns_empty_for_empty_collection(self):
        """Test that all returns empty list for empty collection."""
        results = self.collection.all()
        self.assertEqual(results, [])

    def test_delete_removes_document(self):
        """Test deleting a document."""
        self.collection.save("task-1", {"title": "Test"})

        result = self.collection.delete("task-1")

        self.assertTrue(result)
        self.assertIsNone(self.collection.get("task-1"))

    def test_delete_returns_false_for_missing(self):
        """Test that delete returns False for non-existent document."""
        result = self.collection.delete("nonexistent")
        self.assertFalse(result)

    def test_clear_removes_all_documents(self):
        """Test clearing all documents in collection."""
        self.collection.save("task-1", {"title": "Task 1"})
        self.collection.save("task-2", {"title": "Task 2"})

        count = self.collection.clear()

        self.assertEqual(count, 2)
        self.assertEqual(self.collection.all(), [])

    def test_count_returns_document_count(self):
        """Test counting documents."""
        self.assertEqual(self.collection.count(), 0)

        self.collection.save("task-1", {"title": "Task 1"})
        self.collection.save("task-2", {"title": "Task 2"})

        self.assertEqual(self.collection.count(), 2)

    def test_exists_returns_true_for_existing(self):
        """Test exists returns True for existing document."""
        self.collection.save("task-1", {"title": "Test"})

        self.assertTrue(self.collection.exists("task-1"))
        self.assertFalse(self.collection.exists("nonexistent"))

    def test_collection_isolation(self):
        """Test that collections are isolated from each other."""
        tasks = PluginCollection("test-plugin", "tasks")
        notes = PluginCollection("test-plugin", "notes")

        tasks.save("item-1", {"type": "task"})
        notes.save("item-1", {"type": "note"})

        self.assertEqual(tasks.get("item-1")["data"]["type"], "task")
        self.assertEqual(notes.get("item-1")["data"]["type"], "note")

    def test_plugin_isolation(self):
        """Test that plugins are isolated from each other."""
        plugin_a = PluginCollection("plugin-a", "tasks")
        plugin_b = PluginCollection("plugin-b", "tasks")

        plugin_a.save("task-1", {"owner": "a"})
        plugin_b.save("task-1", {"owner": "b"})

        self.assertEqual(plugin_a.get("task-1")["data"]["owner"], "a")
        self.assertEqual(plugin_b.get("task-1")["data"]["owner"], "b")


class PluginStorageTestCase(TestCase):
    """Test cases for PluginStorage class."""

    def setUp(self):
        self.storage = PluginStorage("test-plugin")

    def test_requires_plugin_key(self):
        """Test that PluginStorage requires a plugin_key."""
        with self.assertRaises(ValueError) as ctx:
            PluginStorage("")
        self.assertIn("plugin_key is required", str(ctx.exception))

    def test_collection_returns_collection_instance(self):
        """Test that collection() returns a PluginCollection."""
        tasks = self.storage.collection("tasks")

        self.assertIsInstance(tasks, PluginCollection)
        self.assertEqual(tasks.name, "tasks")

    def test_collection_caches_instances(self):
        """Test that collection() caches and returns same instance."""
        tasks1 = self.storage.collection("tasks")
        tasks2 = self.storage.collection("tasks")

        self.assertIs(tasks1, tasks2)

    def test_collection_requires_name(self):
        """Test that collection() requires a name."""
        with self.assertRaises(ValueError) as ctx:
            self.storage.collection("")
        self.assertIn("collection name is required", str(ctx.exception))

    def test_collections_lists_all_collections(self):
        """Test listing all collections with documents."""
        self.storage.collection("tasks").save("t1", {"x": 1})
        self.storage.collection("notes").save("n1", {"x": 1})
        self.storage.collection("logs").save("l1", {"x": 1})

        collections = self.storage.collections()

        self.assertEqual(len(collections), 3)
        self.assertIn("tasks", collections)
        self.assertIn("notes", collections)
        self.assertIn("logs", collections)

    def test_collections_returns_empty_when_no_documents(self):
        """Test that collections() returns empty list when no documents."""
        collections = self.storage.collections()
        self.assertEqual(collections, [])

    def test_drop_clears_collection(self):
        """Test that drop() removes all documents in a collection."""
        tasks = self.storage.collection("tasks")
        tasks.save("t1", {"x": 1})
        tasks.save("t2", {"x": 2})

        count = self.storage.drop("tasks")

        self.assertEqual(count, 2)
        self.assertEqual(tasks.all(), [])

    def test_clear_all_deletes_all_collections(self):
        """Test that clear_all() removes all documents across all collections."""
        self.storage.collection("tasks").save("t1", {"x": 1})
        self.storage.collection("tasks").save("t2", {"x": 2})
        self.storage.collection("notes").save("n1", {"x": 1})
        self.storage.collection("logs").save("l1", {"x": 1})

        count = self.storage.clear_all()

        self.assertEqual(count, 4)
        self.assertEqual(self.storage.collections(), [])

    def test_clear_all_only_affects_own_plugin(self):
        """Test that clear_all() doesn't affect other plugins' data."""
        # Create data for two plugins
        self.storage.collection("tasks").save("t1", {"x": 1})
        other_storage = PluginStorage("other-plugin")
        other_storage.collection("tasks").save("t1", {"x": 1})

        # Clear only test-plugin
        self.storage.clear_all()

        # Other plugin's data should remain
        self.assertEqual(other_storage.collection("tasks").count(), 1)


class ManifestTestCase(TestCase):
    """Test cases for manifest key detection."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_derive_key_from_directory(self):
        """Test deriving key from directory name."""
        self.assertEqual(derive_key_from_directory("my_plugin"), "my_plugin")
        self.assertEqual(derive_key_from_directory("My Plugin"), "my_plugin")
        self.assertEqual(derive_key_from_directory("MyPlugin"), "myplugin")

    def test_load_manifest_returns_none_when_no_file(self):
        """Test that load_manifest returns None when no manifest file."""
        result = load_manifest(self.temp_dir)
        self.assertIsNone(result)

    def test_load_manifest_reads_yaml(self):
        """Test loading manifest from plugin.yaml."""
        # Skip if PyYAML not available
        from apps.plugins.manifest import YAML_AVAILABLE
        if not YAML_AVAILABLE:
            self.skipTest("PyYAML not installed")

        manifest_path = os.path.join(self.temp_dir, "plugin.yaml")
        with open(manifest_path, "w") as f:
            f.write("plugin:\n  key: my-plugin\n  name: My Plugin\n")

        result = load_manifest(self.temp_dir)

        self.assertIsNotNone(result)
        self.assertEqual(result["plugin"]["key"], "my-plugin")

    def test_load_manifest_reads_yml(self):
        """Test loading manifest from plugin.yml."""
        # Skip if PyYAML not available
        from apps.plugins.manifest import YAML_AVAILABLE
        if not YAML_AVAILABLE:
            self.skipTest("PyYAML not installed")

        manifest_path = os.path.join(self.temp_dir, "plugin.yml")
        with open(manifest_path, "w") as f:
            f.write("plugin:\n  key: my-plugin\n")

        result = load_manifest(self.temp_dir)

        self.assertIsNotNone(result)
        self.assertEqual(result["plugin"]["key"], "my-plugin")

    def test_get_manifest_key_nested(self):
        """Test extracting key from nested plugin.key."""
        manifest = {"plugin": {"key": "my-plugin", "name": "My Plugin"}}
        result = get_manifest_key(manifest)
        self.assertEqual(result, "my-plugin")

    def test_get_manifest_key_top_level(self):
        """Test extracting key from top-level key."""
        manifest = {"key": "my-plugin", "name": "My Plugin"}
        result = get_manifest_key(manifest)
        self.assertEqual(result, "my-plugin")

    def test_get_manifest_key_returns_none_when_missing(self):
        """Test that get_manifest_key returns None when no key."""
        manifest = {"name": "My Plugin"}
        result = get_manifest_key(manifest)
        self.assertIsNone(result)

    def test_get_manifest_key_returns_none_for_none(self):
        """Test that get_manifest_key returns None for None input."""
        result = get_manifest_key(None)
        self.assertIsNone(result)

    @patch("apps.plugins.manifest.load_manifest")
    def test_detect_plugin_key_uses_manifest(self, mock_load):
        """Test that detect_plugin_key prefers manifest key."""
        mock_load.return_value = {"plugin": {"key": "manifest-key"}}

        key, source = detect_plugin_key("/path/to/plugin", "directory_name")

        self.assertEqual(key, "manifest-key")
        self.assertEqual(source, "manifest")

    @patch("apps.plugins.manifest.load_manifest")
    def test_detect_plugin_key_falls_back_to_directory(self, mock_load):
        """Test that detect_plugin_key falls back to directory name."""
        mock_load.return_value = None

        key, source = detect_plugin_key("/path/to/plugin", "my_plugin")

        self.assertEqual(key, "my_plugin")
        self.assertEqual(source, "directory")


class PluginStorageAPITestCase(TestCase):
    """Test cases for plugin storage API endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass123",
        )
        # Set user_level to ADMIN (10) for permission checks
        self.admin_user.user_level = 10
        self.admin_user.save()
        self.plugin = PluginConfig.objects.create(
            key="test-plugin",
            name="Test Plugin",
            enabled=True,
        )

    def get_auth_header(self, user):
        """Helper to get JWT auth header."""
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    def test_list_collections_requires_auth(self):
        """Test that listing collections requires authentication."""
        url = "/api/plugins/plugins/test-plugin/storage/"
        response = self.client.get(url)
        self.assertIn(response.status_code, [401, 403])

    def test_list_collections_success(self):
        """Test listing collections for a plugin."""
        # Create some documents
        storage = PluginStorage("test-plugin")
        storage.collection("tasks").save("t1", {"x": 1})
        storage.collection("notes").save("n1", {"x": 1})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("tasks", data["collections"])
        self.assertIn("notes", data["collections"])

    def test_list_collections_plugin_not_found(self):
        """Test listing collections for non-existent plugin."""
        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/nonexistent/storage/"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 404)

    def test_list_documents_success(self):
        """Test listing documents in a collection."""
        storage = PluginStorage("test-plugin")
        storage.collection("tasks").save("t1", {"title": "Task 1"})
        storage.collection("tasks").save("t2", {"title": "Task 2"})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["documents"]), 2)

    def test_list_documents_with_pagination(self):
        """Test listing documents with limit and offset."""
        storage = PluginStorage("test-plugin")
        for i in range(10):
            storage.collection("tasks").save(f"t{i}", {"num": i})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/?limit=3&offset=2"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["documents"]), 3)

    def test_save_document_success(self):
        """Test saving a document via API."""
        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/"
        response = self.client.post(
            url,
            {"id": "task-1", "data": {"title": "My Task"}},
            format="json",
            HTTP_AUTHORIZATION=auth,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["document"]["id"], "task-1")

        # Verify in database
        doc = PluginDocument.objects.get(
            plugin_key="test-plugin",
            collection="tasks",
            doc_id="task-1",
        )
        self.assertEqual(doc.data["title"], "My Task")

    def test_save_document_requires_id(self):
        """Test that save requires an id."""
        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/"
        response = self.client.post(
            url,
            {"data": {"title": "My Task"}},
            format="json",
            HTTP_AUTHORIZATION=auth,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("id", response.json()["error"])

    def test_save_document_requires_dict_data(self):
        """Test that save requires data to be an object."""
        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/"
        response = self.client.post(
            url,
            {"id": "task-1", "data": "not an object"},
            format="json",
            HTTP_AUTHORIZATION=auth,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("data", response.json()["error"])

    def test_save_document_requires_enabled_plugin(self):
        """Test that save requires plugin to be enabled."""
        self.plugin.enabled = False
        self.plugin.save()

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/"
        response = self.client.post(
            url,
            {"id": "task-1", "data": {"title": "My Task"}},
            format="json",
            HTTP_AUTHORIZATION=auth,
        )

        self.assertEqual(response.status_code, 403)

    def test_get_document_success(self):
        """Test getting a document via API."""
        storage = PluginStorage("test-plugin")
        storage.collection("tasks").save("task-1", {"title": "My Task"})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/task-1/"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["document"]["data"]["title"], "My Task")

    def test_get_document_not_found(self):
        """Test getting a non-existent document."""
        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/nonexistent/"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 404)

    def test_delete_document_success(self):
        """Test deleting a document via API."""
        storage = PluginStorage("test-plugin")
        storage.collection("tasks").save("task-1", {"title": "My Task"})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/task-1/"
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        # Verify deleted
        self.assertIsNone(storage.collection("tasks").get("task-1"))

    def test_delete_document_not_found(self):
        """Test deleting a non-existent document."""
        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/nonexistent/"
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 404)

    def test_delete_collection_success(self):
        """Test deleting an entire collection via API."""
        storage = PluginStorage("test-plugin")
        storage.collection("tasks").save("t1", {"x": 1})
        storage.collection("tasks").save("t2", {"x": 2})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/"
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_count"], 2)

        # Verify deleted
        self.assertEqual(storage.collection("tasks").all(), [])

    def test_list_documents_default_limit(self):
        """Test that listing documents has a default limit."""
        # Create more than the default limit of documents
        storage = PluginStorage("test-plugin")
        for i in range(150):
            storage.collection("tasks").save(f"t{i}", {"x": i})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/tasks/"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Default limit is 100
        self.assertEqual(len(data["documents"]), 100)

    def test_list_documents_max_limit(self):
        """Test that listing documents enforces a max limit."""
        auth = self.get_auth_header(self.admin_user)
        # Request more than max limit
        url = "/api/plugins/plugins/test-plugin/storage/tasks/?limit=5000"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        # Should be capped at MAX_LIMIT (1000), not 5000

    def test_list_documents_invalid_pagination(self):
        """Test that negative pagination values are rejected."""
        auth = self.get_auth_header(self.admin_user)

        # Negative offset
        url = "/api/plugins/plugins/test-plugin/storage/tasks/?offset=-1"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)
        self.assertEqual(response.status_code, 400)

        # Zero limit
        url = "/api/plugins/plugins/test-plugin/storage/tasks/?limit=0"
        response = self.client.get(url, HTTP_AUTHORIZATION=auth)
        self.assertEqual(response.status_code, 400)

    def test_delete_all_plugin_storage(self):
        """Test deleting all storage for a plugin via API."""
        storage = PluginStorage("test-plugin")
        storage.collection("tasks").save("t1", {"x": 1})
        storage.collection("tasks").save("t2", {"x": 2})
        storage.collection("notes").save("n1", {"x": 1})

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/"
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_count"], 3)

        # Verify all deleted
        self.assertEqual(storage.collections(), [])

    def test_delete_all_plugin_storage_works_when_disabled(self):
        """Test that delete all storage works even when plugin is disabled."""
        storage = PluginStorage("test-plugin")
        storage.collection("tasks").save("t1", {"x": 1})

        # Disable the plugin
        self.plugin.enabled = False
        self.plugin.save()

        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/test-plugin/storage/"
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth)

        # Should still work
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_count"], 1)

    def test_delete_all_plugin_storage_plugin_not_found(self):
        """Test delete all storage returns 404 for non-existent plugin."""
        auth = self.get_auth_header(self.admin_user)
        url = "/api/plugins/plugins/nonexistent/storage/"
        response = self.client.delete(url, HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 404)


class PluginStorageDocumentSizeLimitTestCase(TestCase):
    """Tests for document size limits."""

    def test_save_document_size_limit(self):
        """Test that saving a document exceeding size limit raises error."""
        storage = PluginStorage("test-plugin")
        collection = storage.collection("large")

        # Create data that exceeds 1MB
        large_data = {"content": "x" * (1024 * 1024 + 1)}  # Just over 1MB

        with self.assertRaises(ValueError) as ctx:
            collection.save("large-doc", large_data)

        self.assertIn("exceeds maximum size", str(ctx.exception))

    def test_save_document_within_size_limit(self):
        """Test that saving a document within size limit works."""
        storage = PluginStorage("test-plugin")
        collection = storage.collection("normal")

        # Create data that's under 1MB
        normal_data = {"content": "x" * 1000}

        doc = collection.save("normal-doc", normal_data)
        self.assertEqual(doc["id"], "normal-doc")


class PluginStorageIdentifierValidationTestCase(TestCase):
    """Tests for collection name and doc_id validation."""

    def setUp(self):
        self.storage = PluginStorage("test-plugin")
        self.collection = self.storage.collection("tasks")

    def test_doc_id_max_length(self):
        """Test that doc_id over 255 characters is rejected."""
        long_id = "x" * 256

        with self.assertRaises(ValueError) as ctx:
            self.collection.save(long_id, {"data": "test"})

        self.assertIn("255 characters or less", str(ctx.exception))

    def test_collection_name_max_length(self):
        """Test that collection name over 128 characters is rejected."""
        long_name = "x" * 129

        with self.assertRaises(ValueError) as ctx:
            self.storage.collection(long_name)

        self.assertIn("128 characters or less", str(ctx.exception))

    def test_doc_id_null_byte_rejected(self):
        """Test that doc_id with null byte is rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.collection.save("doc\x00id", {"data": "test"})

        self.assertIn("null bytes", str(ctx.exception))

    def test_collection_name_null_byte_rejected(self):
        """Test that collection name with null byte is rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.storage.collection("tasks\x00evil")

        self.assertIn("null bytes", str(ctx.exception))

    def test_doc_id_control_char_rejected(self):
        """Test that doc_id with control characters is rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.collection.save("doc\nid", {"data": "test"})

        self.assertIn("control characters", str(ctx.exception))

    def test_collection_name_control_char_rejected(self):
        """Test that collection name with control characters is rejected."""
        with self.assertRaises(ValueError) as ctx:
            self.storage.collection("tasks\ttab")

        self.assertIn("control characters", str(ctx.exception))

    def test_international_characters_allowed(self):
        """Test that international characters (Unicode) are allowed."""
        # Japanese
        doc1 = self.collection.save("日本語", {"title": "Japanese"})
        self.assertEqual(doc1["id"], "日本語")

        # Spanish with accents
        doc2 = self.collection.save("El-Señor", {"title": "Spanish"})
        self.assertEqual(doc2["id"], "El-Señor")

        # Emoji
        doc3 = self.collection.save("movie-🎬", {"title": "Emoji"})
        self.assertEqual(doc3["id"], "movie-🎬")

    def test_punctuation_allowed(self):
        """Test that common punctuation is allowed in identifiers."""
        # Apostrophes, periods, colons
        doc = self.collection.save("Marvel's Agents of S.H.I.E.L.D.", {"x": 1})
        self.assertEqual(doc["id"], "Marvel's Agents of S.H.I.E.L.D.")

    def test_spaces_allowed(self):
        """Test that spaces are allowed in identifiers."""
        doc = self.collection.save("The Office (US)", {"x": 1})
        self.assertEqual(doc["id"], "The Office (US)")
