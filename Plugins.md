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
- `info` (display-only text; useful for headings or notes)

Common field keys:
- `id` (str): Settings key.
- `label` (str): Label shown in the UI.
- `type` (str): One of above.
- `default` (any): Default value used until saved.
- `help_text` / `description` (str, optional): Shown under the control.
- `placeholder` (str, optional): Placeholder text for inputs.
- `input_type` (str, optional): For `string` fields, set to `"password"` to mask input.
- `options` (list, for select): List of `{value, label}`.

Notes:
- For `info` fields, you can use `description`/`help_text` (or `value`) to show the text.

The UI automatically renders settings and persists them. The backend stores settings in `PluginConfig.settings`.

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
