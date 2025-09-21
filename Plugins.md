# Dispatcharr Plugins

This document explains how to build, install, and use Python plugins in Dispatcharr. It covers discovery, the plugin interface, settings, actions, how to access application APIs, and examples.

---

## Quick Start

1) Create a folder under `/app/data/plugins/my_plugin/` (host path `data/plugins/my_plugin/` in the repo).

2) Add a `plugin.py` file exporting a `Plugin` class:

```
# /app/data/plugins/my_plugin/plugin.py
class Plugin:
    name = "My Plugin"
    version = "0.1.0"
    description = "Does something useful"

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
        {"id": "do_work", "label": "Do Work", "description": "Process items"},
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

The directory name (lowercased, spaces as `_`) is used as the registry key and module import path (e.g. `my_plugin.plugin`).

---

## Discovery & Lifecycle

- Discovery runs at server startup and on-demand when:
  - Fetching the plugins list from the UI
  - Hitting `POST /api/plugins/plugins/reload/`
- The loader imports each plugin module and instantiates `Plugin()`.
- Metadata (name, version, description) and a per-plugin settings JSON are stored in the DB.

Backend code:
- Loader: `apps/plugins/loader.py`
- API Views: `apps/plugins/api_views.py`
- API URLs: `apps/plugins/api_urls.py`
- Model: `apps/plugins/models.py` (stores `enabled` flag and `settings` per plugin)

---

## Plugin Interface

Export a `Plugin` class. Supported attributes and behavior:

- `name` (str): Human-readable name.
- `version` (str): Semantic version string.
- `description` (str): Short description.
- `fields` (list): Settings schema used by the UI to render controls.
- `actions` (list): Available actions; the UI renders a Run button for each.
- `run(action, params, context)` (callable): Invoked when a user clicks an action.

### Settings Schema
Supported field `type`s:
- `boolean`
- `number`
- `string`
- `select` (requires `options`: `[{"value": ..., "label": ...}, ...]`)

Common field keys:
- `id` (str): Settings key.
- `label` (str): Label shown in the UI.
- `type` (str): One of above.
- `default` (any): Default value used until saved.
- `help_text` (str, optional): Shown under the control.
- `options` (list, for select): List of `{value, label}`.

The UI automatically renders settings and persists them. The backend stores settings in `PluginConfig.settings`.

Read settings in `run` via `context["settings"]`.

### Actions
Each action is a dict:
- `id` (str): Unique action id.
- `label` (str): Button label.
- `description` (str, optional): Helper text.

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
- On success, the UI shows the plugin name/description and lets you enable it immediately (plugins are disabled by default).

---

## Enabling / Disabling Plugins

- Each plugin has a persisted `enabled` flag (default: disabled) and `ever_enabled` flag in the DB (`apps/plugins/models.py`).
- New plugins are disabled by default and require an explicit enable.
- The first time a plugin is enabled, the UI shows a trust warning modal explaining that plugins can run arbitrary server-side code.
- The Plugins page shows a toggle in the card header. Turning it off dims the card and disables the Run button.
- Backend enforcement: Attempts to run an action for a disabled plugin return HTTP 403.

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
- Import errors: the folder name is the import name; avoid spaces or exotic characters.
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
