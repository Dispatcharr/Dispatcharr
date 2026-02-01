# Plugin Storage API

The Plugin Storage API allows plugins to persist data without requiring database migrations. Data is organized into **collections** (like lightweight tables) and automatically namespaced by your plugin's key.

## Quick Start

In your plugin's `run()` method, access storage via `context["storage"]`:

```python
def run(self, action, params, context):
    storage = context["storage"]
    
    # Get a collection reference
    tasks = storage.collection("tasks")
    
    # Save a document
    tasks.save("task-1", {"title": "My Task", "done": False})
    
    # Get a document
    task = tasks.get("task-1")
    
    # List all documents
    all_tasks = tasks.all()
    
    # Delete a document
    tasks.delete("task-1")
```

## Storage Hierarchy

```
plugin_key (automatic, from your plugin)
  └── collection (you define these, e.g., "tasks", "settings")
        └── doc_id (you define these, unique within the collection)
              └── data (JSON object you store)
```

Each plugin's data is completely isolated. Plugin A cannot access Plugin B's data.

## API Reference

### `storage.collection(name)`

Get a reference to a collection. Collections are created lazily - they don't exist until you save a document.

```python
tasks = storage.collection("tasks")
notes = storage.collection("notes")
settings = storage.collection("settings")
```

### `collection.save(doc_id, data)`

Save a document. Creates a new document or updates an existing one.

```python
# Create a new document
tasks.save("task-1", {"title": "Buy groceries", "done": False})

# Update an existing document
tasks.save("task-1", {"title": "Buy groceries", "done": True})
```

**Parameters:**
- `doc_id` (str): Unique identifier within this collection
- `data` (dict): JSON-serializable data to store

**Returns:** Document dict with metadata:
```python
{
    "id": "task-1",
    "data": {"title": "Buy groceries", "done": True},
    "created_at": "2026-02-01T10:30:00.000000",
    "updated_at": "2026-02-01T10:35:00.000000"
}
```

### `collection.get(doc_id)`

Retrieve a document by ID.

```python
task = tasks.get("task-1")
if task:
    print(task["data"]["title"])
else:
    print("Task not found")
```

**Returns:** Document dict or `None` if not found.

### `collection.all(limit=None, offset=0)`

List all documents in the collection.

```python
# Get all tasks
all_tasks = tasks.all()

# Get first 10 tasks
first_page = tasks.all(limit=10)

# Get next 10 tasks
second_page = tasks.all(limit=10, offset=10)
```

**Returns:** List of document dicts, ordered by most recently updated.

### `collection.delete(doc_id)`

Delete a document by ID.

```python
deleted = tasks.delete("task-1")
if deleted:
    print("Task deleted")
else:
    print("Task not found")
```

**Returns:** `True` if deleted, `False` if document didn't exist.

### `collection.clear()`

Delete all documents in the collection.

```python
count = tasks.clear()
print(f"Deleted {count} tasks")
```

**Returns:** Number of documents deleted.

### `collection.count()`

Count documents in the collection.

```python
total = tasks.count()
print(f"You have {total} tasks")
```

### `collection.exists(doc_id)`

Check if a document exists without fetching it.

```python
if tasks.exists("task-1"):
    print("Task exists")
```

### `storage.collections()`

List all collections that have documents.

```python
names = storage.collections()
# ["tasks", "notes", "settings"]
```

### `storage.drop(collection_name)`

Delete an entire collection.

```python
storage.drop("tasks")
```

## Example: Counter Plugin

```python
class Plugin:
    name = "Counter"
    actions = [
        {"id": "increment", "label": "Increment"},
        {"id": "reset", "label": "Reset"},
    ]
    
    def run(self, action, params, context):
        counters = context["storage"].collection("counters")
        
        if action == "increment":
            doc = counters.get("main")
            value = doc["data"]["value"] if doc else 0
            value += 1
            counters.save("main", {"value": value})
            return {"status": "ok", "value": value}
        
        elif action == "reset":
            counters.save("main", {"value": 0})
            return {"status": "ok", "value": 0}
```

## Example: Notes Plugin

```python
class Plugin:
    name = "Notes"
    actions = [
        {"id": "add", "label": "Add Note", "params": [
            {"name": "title", "type": "string"},
            {"name": "content", "type": "string"},
        ]},
        {"id": "list", "label": "List Notes"},
        {"id": "delete", "label": "Delete Note", "params": [
            {"name": "id", "type": "string"},
        ]},
    ]
    
    def run(self, action, params, context):
        notes = context["storage"].collection("notes")
        
        if action == "add":
            import uuid
            note_id = str(uuid.uuid4())
            notes.save(note_id, {
                "title": params["title"],
                "content": params["content"],
            })
            return {"status": "ok", "id": note_id}
        
        elif action == "list":
            all_notes = notes.all()
            return {
                "status": "ok",
                "notes": [
                    {"id": n["id"], **n["data"]}
                    for n in all_notes
                ]
            }
        
        elif action == "delete":
            if notes.delete(params["id"]):
                return {"status": "ok"}
            return {"status": "error", "message": "Note not found"}
```

## Best Practices

1. **Use descriptive collection names**: `tasks`, `settings`, `cache`, `logs`

2. **Use meaningful document IDs**: Consider using UUIDs for auto-generated IDs, or semantic IDs like `"config"` for singleton documents.

3. **Keep documents reasonably sized**: Storage is backed by a JSON field. Very large documents (>1MB) may impact performance.

4. **Use multiple collections**: Organize your data into logical groups rather than putting everything in one collection.

5. **Handle missing documents**: Always check if `get()` returns `None`.

## Plugin Key (Manifest)

By default, your plugin key is derived from its directory name. For more control, create a `plugin.yaml` file:

```yaml
plugin:
  key: my-unique-plugin-key
  name: My Plugin
  version: 1.0.0
```

When a manifest key is present, it takes precedence over the directory name. This is useful when:
- You want a different key than your directory name
- You want to ensure key consistency across installations
- You're preparing for future plugin versioning features
