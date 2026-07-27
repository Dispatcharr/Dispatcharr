# Dispatcharr Plugins

This document explains how to build, install, and use Python plugins in Dispatcharr. It covers discovery, the plugin interface, settings, actions, how to access application APIs, and examples.

---

## Quick Start

1) Create a folder under `/app/data/plugins/my_plugin/` (host path `data/plugins/my_plugin/` in the repo).

2) Add a `plugin.json` manifest (new standard) and a `plugin.py` file:

`/app/data/plugins/my_plugin/plugin.json`
```json
{
  "name": "My Plugin",
  "version": "0.1.0",
  "description": "Does something useful",
  "author": "Acme Labs",
  "help_url": "https://example.com/docs/my-plugin",
  "fields": [
    { "id": "enabled", "label": "Enabled", "type": "boolean", "default": true },
    { "id": "limit", "label": "Item limit", "type": "number", "default": 5 },
    {
      "id": "mode",
      "label": "Mode",
      "type": "select",
      "default": "safe",
      "options": [
        { "value": "safe", "label": "Safe" },
        { "value": "fast", "label": "Fast" }
      ]
    },
    { "id": "note", "label": "Note", "type": "string", "default": "" }
  ],
  "actions": [
    {
      "id": "do_work",
      "label": "Do Work",
      "description": "Process items",
      "button_label": "Run Job",
      "button_variant": "filled",
      "button_color": "blue"
    }
  ]
}
```

```
# /app/data/plugins/my_plugin/plugin.py
class Plugin:
    name = "My Plugin"
    version = "0.1.0"
    description = "Does something useful"
    author = "Acme Labs"
    help_url = "https://example.com/docs/my-plugin"

    # Settings fields rendered by the UI and persisted by the backend
    fields = [
        {"id": "enabled", "label": "Enabled", "type": "boolean", "default": True},
        {"id": "limit", "label": "Item limit", "type": "number", "default": 5},
        {"id": "mode", "label": "Mode", "type": "select", "default": "safe",
         "options": [
            {"value": "safe", "label": "Safe"},
            {"value": "fast", "label": "Fast"},
         ]},
        {"id": "note", "label": "Note", "type": "string", "default": ""},
    ]

    # Actions appear as buttons. Clicking one calls run(action, params, context)
    actions = [
        {
            "id": "do_work",
            "label": "Do Work",
            "description": "Process items",
            "button_label": "Run Job",
            "button_variant": "filled",
            "button_color": "blue",
        },
    ]

    def run(self, action: str, params: dict, context: dict):
        settings = context.get("settings", {})
        logger = context.get("logger")

        if action == "do_work":
            limit = int(settings.get("limit", 5))
            mode = settings.get("mode", "safe")
            logger.info(f"My Plugin running with limit={limit}, mode={mode}")
            # Do a small amount of work here. Schedule Celery tasks for heavy work.
            return {"status": "ok", "processed": limit, "mode": mode}

        return {"status": "error", "message": f"Unknown action {action}"}
```

3) Open the Plugins page in the UI, click the refresh icon to reload discovery, then configure and run your plugin.

---

## Where Plugins Live

- Default directory: `/app/data/plugins` inside the container.
- Override with env var: `DISPATCHARR_PLUGINS_DIR`.
- Each plugin is a directory containing either:
  - `plugin.py` exporting a `Plugin` class, or
  - a Python package (`__init__.py`) exporting a `Plugin` class.
- New standard: include a `plugin.json` manifest alongside your code for safe metadata discovery.
- Optional: include `logo.png` next to `plugin.py` to show a logo in the UI.

The directory name (lowercased, spaces as `_`) is used as the registry key. Plugins are imported under a safe internal package name; if the folder name is a valid identifier (and not reserved), it is also registered as an alias for convenience.

---

## Discovery & Lifecycle

- Discovery runs at server startup and on-demand when:
  - Fetching the plugins list from the UI
  - Hitting `POST /api/plugins/plugins/reload/`
- The loader reads `plugin.json` for metadata without executing plugin code.
- Plugin code is only imported and instantiated when the plugin is enabled.
- Metadata (name, version, description) and a per-plugin settings JSON are stored in the DB.

Backend code:
- Loader: `apps/plugins/loader.py`
- API Views: `apps/plugins/api_views.py`
- API URLs: `apps/plugins/api_urls.py`
- Model: `apps/plugins/models.py` (stores `enabled` flag and `settings` per plugin)

---

## Plugin Manifest (`plugin.json`)

`plugin.json` lets Dispatcharr list your plugin safely without executing code. It should live next to `plugin.py`.

Example:
```
{
  "name": "My Plugin",
  "version": "1.2.3",
  "description": "Does something useful",
  "author": "Acme Labs",
  "help_url": "https://example.com/docs/my-plugin",
  "fields": [
    { "id": "limit", "label": "Item limit", "type": "number", "default": 5 }
  ],
  "actions": [
    {
      "id": "do_work",
      "label": "Do Work",
      "description": "Process items",
      "button_label": "Run Job",
      "button_variant": "filled",
      "button_color": "blue"
    }
  ]
}
```

Notes:
- `author` and `help_url` are optional. If provided, the UI shows “By {author}” and a Docs link.
- If your plugin includes a `logo.png` file next to `plugin.py`, it will be shown on the plugin card.

If `plugin.json` is missing or invalid, the plugin is treated as **legacy**:
- The name is inferred from the folder name.
- `logo.png` still displays if present.
- The UI shows a warning asking the developer to upgrade to the new standard.

---

## Plugin Interface

Export a `Plugin` class. Supported attributes and behavior:

- `name` (str): Human-readable name.
- `version` (str): Semantic version string.
- `description` (str): Short description.
- `author` (str, optional): Author or team name shown on the card.
- `help_url` (str, optional): Docs/support link shown on the card.
- `fields` (list): Settings schema used by the UI to render controls.
- `actions` (list): Available actions; the UI renders a button for each (defaults to Run).
- `run(action, params, context)` (callable): Invoked when a user clicks an action.
- `stop(context)` (optional callable): Invoked when the plugin is disabled, deleted, or reloaded so you can gracefully shut down any processes you started. If `stop()` is not defined but you have an action with id `stop`, Dispatcharr will call `run("stop", {}, context)` as a fallback.

### Settings Schema
Supported field `type`s:
- `boolean`
- `number`
- `string` (single-line text)
- `text` (multi-line textarea)
- `select` (requires `options`: `[{"value": ..., "label": ...}, ...]`)
- `multiselect` (requires `options`, same shape as `select`; stores/returns a JSON array of selected values)
- `info` (display-only text; useful for headings or notes)
- `section` (display-only grouping marker; see "Sections" below)
- `table` (editable list of rows; see "Table Fields" below)
- `file` (uploads a file into the plugin's own directory; see "File Fields" below)

Common field keys:
- `id` (str): Settings key.
- `label` (str): Label shown in the UI.
- `type` (str): One of above.
- `default` (any): Default value used until saved.
- `help_text` / `description` (str, optional): Shown under the control.
- `placeholder` (str, optional): Placeholder text for inputs.
- `input_type` (str, optional): For `string` fields, set to `"password"` to mask input.
- `options` (list, for `select`/`multiselect`): List of `{value, label}`.
- `section` (str, optional): The `id` of a `section` field this field belongs to. If it names a section that isn't declared, the field renders ungrouped rather than being hidden.
- `columns` (list, for `table`): See "Table Fields" below.
- `accept` / `max_size` (for `file`): See "File Fields" below.

Notes:
- For `info` fields, you can use `description`/`help_text` (or `value`) to show the text.

The UI automatically renders settings and persists them. The backend stores settings in `PluginConfig.settings`.

### Sections
Group related fields into collapsible sections by declaring a `section`-type marker field and having other fields reference its `id` via their own `section` key. A section marker stores no value.

- `id` (str): Section id, referenced by member fields' `section` key.
- `label` (str): Section heading text.
- `collapsed` (bool, optional, default `false`): Renders the section collapsed by default (e.g. for an "Advanced" section). Expand/collapse state is a UI-only preference and is never written to settings.

```json
{
  "fields": [
    { "id": "enabled", "label": "Enable plugin", "type": "boolean" },

    { "id": "sec_advanced", "label": "Advanced", "type": "section", "collapsed": true },
    { "id": "batch_size", "label": "Batch size", "type": "number", "section": "sec_advanced" }
  ]
}
```

### Table Fields
A `table` field lets the user add, edit, and delete rows of structured data instead of hand-editing JSON in a text field. The value is stored as a JSON array of row objects keyed by column `id` (no separate storage migration needed).

- `columns` (list): Column definitions, each with:
  - `id` (str): Row key for this column.
  - `label` (str, optional): Column header text.
  - `type` (str): One of `string`, `number`, `boolean`, `select`. `select` columns use `options` with the same `{value, label}` shape as a top-level `select` field.

Row order is preserved as submitted. Cell values that don't match their declared column type are rejected when settings are saved, with an error naming the field, row, and column. Keys present in a stored row that no longer match a declared column are ignored, not deleted.

```json
{
  "id": "rename_rules",
  "label": "Rename rules",
  "type": "table",
  "default": [],
  "columns": [
    { "id": "find", "label": "Find", "type": "string" },
    { "id": "replace", "label": "Replace", "type": "string" },
    { "id": "enabled", "label": "Enabled", "type": "boolean" }
  ]
}
```

### File Fields
A `file` field lets the user upload a file (e.g. a config, cert, or overlay image) instead of typing a host path or pasting content into a text field. Selecting a file uploads it immediately via `POST /api/plugins/plugins/<key>/fields/<field_id>/upload/`; only the resulting server-side path is stored in settings, never the file's bytes.

- `accept` (str, optional): Browser file-picker hint, e.g. `.ini,.json`. This only narrows what the picker shows — the server enforces its own fixed extension allowlist regardless of this value.
- `max_size` (int, optional): Requested max size in bytes. The server clamps this to a hard ceiling; a plugin cannot request an unbounded upload.

Server-side, for safety:
- Only a fixed extension allowlist is accepted (config/text formats, certs, and common image formats). Script/executable extensions are always rejected.
- The upload is written under a dedicated `uploads/<field_id>/` subdirectory inside the plugin's own directory, never into the plugin's root, so it can never overwrite `plugin.py`, `plugin.json`, or `__init__.py`.
- Re-uploading to the same field replaces the previous file. Uninstalling the plugin removes the file along with the rest of the plugin's directory.

```json
{
  "id": "cert_bundle",
  "label": "Certificate bundle",
  "type": "file",
  "accept": ".pem,.crt",
  "max_size": 1048576,
  "help_text": "Uploaded once; read back via context['settings']['cert_bundle']."
}
```

Read the stored path in `run()` via `context["settings"][field_id]` and open it directly, the same way the DVR `comskip.ini` path is used.

### Example: stop() Hook
```
import signal

class Plugin:
    name = "Example Plugin"
    version = "1.0.0"
    description = "Shows how to shut down gracefully."

    def run(self, action: str, params: dict, context: dict):
        # Start a subprocess or background task here and store its PID.
        # Example: save pid in /data or in your own module-level variable.
        return {"status": "ok"}

    def stop(self, context: dict):
        logger = context.get("logger")
        pid = self._read_pid()  # your helper
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info("Stopped process %s", pid)
            except Exception:
                logger.exception("Failed to stop process %s", pid)
```

Read settings in `run` via `context["settings"]`.

### Actions
Each action is a dict:
- `id` (str): Unique action id.
- `label` (str): Action label.
- `description` (str, optional): Helper text.
- `button_label` (str, optional): Button text (defaults to “Run”).
- `button_variant` (str, optional): Button style (Mantine variants like `filled`, `outline`, `subtle`).
- `button_color` (str, optional): Button color (e.g., `red`, `blue`, `orange`).

Clicking an action calls your plugin’s `run(action, params, context)` and shows a notification with the result or error.

### Action Confirmation (Modal)
Developers can request a confirmation modal per action using the `confirm` key on the action. Options:

- Boolean: `confirm: true` will show a default confirmation modal.
- Object: `confirm: { required: true, title: '...', message: '...' }` to customize the modal title and message.

Example:
```
actions = [
    {
        "id": "danger_run",
        "label": "Do Something Risky",
        "description": "Runs a job that affects many records.",
        "confirm": { "required": true, "title": "Proceed?", "message": "This will modify many records." },
    }
]
```

---

## Accessing Dispatcharr APIs from Plugins

Plugins are server-side Python code running within the Django application. You can:

- Import models and run queries/updates:
  ```
  from apps.m3u.models import M3UAccount
  from apps.epg.models import EPGSource
  from apps.channels.models import Channel
  from core.models import CoreSettings
  ```

- Dispatch Celery tasks for heavy work (recommended):
  ```
  from apps.m3u.tasks import refresh_m3u_accounts            # apps/m3u/tasks.py
  from apps.epg.tasks import refresh_all_epg_data            # apps/epg/tasks.py

  refresh_m3u_accounts.delay()
  refresh_all_epg_data.delay()
  ```

- Send WebSocket updates:
  ```
  from core.utils import send_websocket_update
  send_websocket_update('updates', 'update', {"type": "plugin", "plugin": "my_plugin", "message": "Done"})
  ```

- Use transactions:
  ```
  from django.db import transaction
  with transaction.atomic():
      # bulk updates here
      ...
  ```

- Log via provided context or standard logging:
  ```
  def run(self, action, params, context):
      logger = context.get("logger")  # already configured
      logger.info("running action %s", action)
  ```

Prefer Celery tasks (`.delay()`) to keep `run` fast and non-blocking.

### Database connections

Dispatcharr uses `django-db-geventpool` with a bounded per-uWSGI-worker pool (`MAX_CONNS=8`). Each greenlet or OS thread that runs ORM code checks out a connection until Django closes it.

`PluginManager.run_action()` and `stop_plugin()` always call `close_old_connections()` in a `finally` block after your plugin returns (success or error). That returns the current greenlet's checkout to the pool. **You do not need to call `close_old_connections()` yourself for normal inline ORM inside `run()` or `stop()`.**

Still follow these rules:

- **Heavy or long work:** dispatch a Celery task (`.delay()`) and return quickly from `run()`. Celery workers close connections after each task; blocking the uWSGI gevent hub with `time.sleep`, sync HTTP, or large CPU work can freeze the whole worker regardless of DB cleanup.
- **Background threads or greenlets you spawn:** each thread/greenlet that uses the ORM must call `close_old_connections()` (or `connection.close()`) in its own `finally` block when done. The wrapper only covers the thread/greenlet that called `run_action()`.
- **Connect event hooks:** actions with an `"events"` list are dispatched from `log_system_event()` on a separate gevent when uWSGI has an active hub (otherwise synchronously, e.g. Celery). Keep handlers short or defer heavy work to Celery.

### Important: Don’t Ask Users for URL/User/Password
Dispatcharr plugins run **inside** the Dispatcharr backend process. That means they already have direct access to the app’s models, tasks, and internal utilities.  
Plugins **should not** ask users for “Dispatcharr URL”, “Admin Username”, or “Admin Password” just to call the API. That is unnecessary and unsafe because:

- It encourages users to enter privileged credentials.
- Malicious plugins could exfiltrate credentials.
- It duplicates access that plugins already have internally.

If you are writing a plugin, **use internal Python APIs** (models/tasks/utils) instead of making HTTP calls with user credentials.

### When You Do Need HTTP
In rare cases you may need to call a Dispatcharr HTTP endpoint (for example, to reuse an existing API response serializer). In that case:

1. **Do not ask the user for credentials.**  
   Use the backend’s internal access where possible.

2. Prefer **local/internal URLs** (never user-provided):
   - Docker: `http://web:9191` (service name inside the container network)
   - Dev: `http://127.0.0.1:5656`

3. Use Django helpers when building URLs:
   ```
   from django.urls import reverse
   path = reverse("api:channels:list")  # example name
   url = f"http://127.0.0.1:5656{path}"
   ```

4. Use a short timeout and robust error handling:
   ```
   import requests
   resp = requests.get(url, timeout=10)
   resp.raise_for_status()
   data = resp.json()
   ```

### Examples: Preferred Internal Access (No HTTP, No Credentials)

**Example 1: List channels directly from the DB**
```
from apps.channels.models import Channel

channels = Channel.objects.all().values("id", "name", "number")[:50]
return {"status": "ok", "channels": list(channels)}
```

**Example 2: Kick off an existing refresh task**
```
from apps.m3u.tasks import refresh_m3u_accounts
from apps.epg.tasks import refresh_all_epg_data

refresh_m3u_accounts.delay()
refresh_all_epg_data.delay()
return {"status": "queued"}
```

**Example 3: Send a WebSocket update to the UI**
```
from core.utils import send_websocket_update

send_websocket_update(
    "updates",
    "update",
    {"type": "plugin", "plugin": "my_plugin", "message": "Refresh queued"}
)
```

### Example: HTTP Access (Only If You Must)

**Find the endpoint**
- Use `reverse()` with the named route when possible.
- If you don’t know the route name, inspect `apps/*/api_urls.py` or Django’s URL config to find it.

```
from django.urls import reverse
import requests

path = reverse("api:channels:list")  # named route from apps/channels/api_urls.py
url = f"http://127.0.0.1:5656{path}"

resp = requests.get(url, timeout=10)
resp.raise_for_status()
data = resp.json()
```

### How Developers Find the API

1. **Prefer internal models/tasks** (best and safest).
2. **Check `apps/*/api_urls.py`** for named routes and endpoint patterns.
   - Example: `apps/channels/api_urls.py` for channel endpoints.
3. **Find the view** referenced in the URL config to see required params.
   - Example: `apps/channels/api_views.py` or `apps/epg/api_views.py`.
4. **Use `reverse()`** with the named route to build the path.
   - This avoids hardcoding paths and keeps plugins compatible if URLs change.
5. **Only use internal hostnames** (never user-provided URL).

### What Plugins Can Access
Because plugins run inside the server process, they can:
- Read and write database models (same permissions as the app)
- Invoke Celery tasks
- Send websocket updates
- Read configuration and settings

Treat plugins as **trusted server code** and avoid exposing sensitive data in plugin settings or logs.

---

## REST Endpoints (for UI and tooling)

- List plugins: `GET /api/plugins/plugins/`
  - Response: `{ "plugins": [{ key, name, version, description, enabled, fields, settings, actions }, ...] }`
- Reload discovery: `POST /api/plugins/plugins/reload/`
- Import plugin: `POST /api/plugins/plugins/import/` with form-data file field `file`
- Update settings: `POST /api/plugins/plugins/<key>/settings/` with `{"settings": {...}}`
- Run action: `POST /api/plugins/plugins/<key>/run/` with `{"action": "id", "params": {...}}`
- Enable/disable: `POST /api/plugins/plugins/<key>/enabled/` with `{"enabled": true|false}`

Notes:
- When disabled, a plugin cannot run actions; backend returns HTTP 403.

---

## Importing Plugins

- In the UI, click the Import button on the Plugins page and upload a `.zip` containing a plugin folder.
- The archive should contain either `plugin.py` or a Python package (`__init__.py`).
- Include `plugin.json` in the plugin folder to provide metadata without executing code.
- On success, the UI shows the plugin name/description and lets you enable it immediately (plugins are disabled by default).
  - If `plugin.json` is missing, the plugin is marked as legacy and the UI will show a warning.

---

## Enabling / Disabling Plugins

- Each plugin has a persisted `enabled` flag (default: disabled) and `ever_enabled` flag in the DB (`apps/plugins/models.py`).
- New plugins are disabled by default and require an explicit enable.
- The first time a plugin is enabled, the UI shows a trust warning modal explaining that plugins can run arbitrary server-side code.
- The Plugins page shows a toggle in the card header. Turning it off dims the card and disables the Run button.
- Backend enforcement: Attempts to run an action for a disabled plugin return HTTP 403.
- Dispatcharr will not import or execute plugin code unless the plugin is enabled.

---

## Example: Refresh All Sources Plugin

Path: `data/plugins/refresh_all/plugin.py`

```
class Plugin:
    name = "Refresh All Sources"
    version = "1.0.0"
    description = "Force refresh all M3U accounts and EPG sources."

    fields = [
        {"id": "confirm", "label": "Require confirmation", "type": "boolean", "default": True,
         "help_text": "If enabled, the UI should ask before running."}
    ]

    actions = [
        {"id": "refresh_all", "label": "Refresh All M3Us and EPGs",
         "description": "Queues background refresh for all active M3U accounts and EPG sources."}
    ]

    def run(self, action: str, params: dict, context: dict):
        if action == "refresh_all":
            from apps.m3u.tasks import refresh_m3u_accounts
            from apps.epg.tasks import refresh_all_epg_data
            refresh_m3u_accounts.delay()
            refresh_all_epg_data.delay()
            return {"status": "queued", "message": "Refresh jobs queued"}
        return {"status": "error", "message": f"Unknown action: {action}"}
```

---

## Best Practices

- Keep `run` short and schedule heavy operations via Celery tasks.
- Validate and sanitize `params` received from the UI.
- Use database transactions for bulk or related updates.
- Log actionable messages for troubleshooting.
- Only write files under `/data` or `/app/data` paths.
- Treat plugins as trusted code: they run with full app permissions.

---

## Troubleshooting

- Plugin not listed: ensure the folder exists and contains `plugin.py` with a `Plugin` class.
- Import errors: ensure the folder contains `plugin.py` or a package `__init__.py`. Folder names with spaces or dashes are supported; if you need to import by folder name inside your plugin, use a valid Python identifier.
- No confirmation: include a boolean field with `id: "confirm"` and set it to true or default true.
- HTTP 403 on run: the plugin is disabled; enable it from the toggle or via the `enabled/` endpoint.

---

## Contributing

- Keep dependencies minimal. Vendoring small helpers into the plugin folder is acceptable.
- Use the existing task and model APIs where possible; propose extensions if you need new capabilities.

---

## Internals Reference

- Loader: `apps/plugins/loader.py`
- API Views: `apps/plugins/api_views.py`
- API URLs: `apps/plugins/api_urls.py`
- Model: `apps/plugins/models.py`
- Frontend page: `frontend/src/pages/Plugins.jsx`
- Sidebar entry: `frontend/src/components/Sidebar.jsx`
