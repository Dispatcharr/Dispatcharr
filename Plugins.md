# Dispatcharr Plugins

This document explains how to build, install, and use Python plugins in Dispatcharr. It covers discovery, manifests, settings, actions, storage, services, and application APIs.

For maintained plugins and working examples, see the [official Dispatcharr Plugins repository](https://github.com/Dispatcharr/Plugins).

---

## Quick Start

1) Create a folder under `/app/data/plugins/my_plugin/` (host path `data/plugins/my_plugin/` in the repo).

2) Add a `plugin.json` manifest (new standard) and a `plugin.py` file:

`/app/data/plugins/my_plugin/plugin.json`
```json
{
  "manifest_version": 2,
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

### `manifest_version` and `capabilities`

```
{
  "manifest_version": 2,
  "name": "My Plugin",
  "capabilities": ["background_tasks"],
  ...
}
```

- `manifest_version` (int, optional): controls capability parsing and best-effort runtime guards. If omitted, your manifest is treated as legacy version `0`; it remains compatible and capability declarations are ignored. Version `1` is the open-ended transition period: capabilities are parsed, shown to users, and acknowledged, but runtime guards are not enabled. Version `2` enables the supported guards for `context` helpers and selected top-level Python APIs. Plugins share Dispatcharr's interpreter, so these guards are defense in depth, not a security boundary or complete process isolation.
- `capabilities` (list of strings, optional): a self-declared list of what your plugin needs. Currently supported:
  - `background_tasks`: your plugin uses `context["dispatch_task"]` and/or a manifest action with `"async": true` (see "Long-Running Actions" below). Declaring it explicitly isn't required if you already set `async: true` on an action (that implies it), but is required if you *only* call `dispatch_task()` at runtime without any `async` action, since that usage can't be detected from the manifest alone.
  - `persistent_service`: your plugin runs a leader-elected long-lived service (see below).
  - `network_listener`: your plugin binds a socket or web server that accepts inbound connections.
  - `subprocess`: your plugin starts commands or processes on the Dispatcharr host.
  - `outbound_network`: your plugin connects to remote hosts or makes outbound HTTP requests.
  - `filesystem_write`: your plugin writes outside its code directory and persistent data directory.
  - `celery_dispatch`: your plugin dispatches an explicitly approved Dispatcharr background task.
  - `proxy_internals` and `user_data`: advisory disclosures for direct live-proxy internals and user-account data access. They are not currently runtime-enforced.
  - `external_dependencies`: declares that the plugin needs third-party Python packages. Dependency installation support is not yet available, so plugins must not depend on this declaration to install packages.
  - Unknown/future capability ids are ignored gracefully by older Dispatcharr builds; the registry is intentionally extensible.
- Declaring `background_tasks` shows users an itemized capability prompt the first time they enable your plugin.
- **`context["dispatch_task"]` is enforced for manifest version 2 and later:** calling it without the plugin having the `background_tasks` capability (declared directly, or implied by any `async: true` action) raises a `PermissionError`, surfaced to the caller as a 403. Versions `0` and `1` remain non-enforcing during the transition period. Manifest `async: true` actions never hit this check, since the capability is always inferred for them automatically.
- **Plugin directories:** `context["code_dir"]` is the installed plugin code directory. `context["data_dir"]` is the version-stable durable-data directory under `_data/<canonical-plugin-id>`. Managed plugins use their repository slug as the canonical, version-free ID; unmanaged plugins use their version-free plugin key. Both paths are available in `run()`, `stop()`, and leadership hooks, so plugins never need to derive them themselves.

  ```python
  import os

  def run(self, action, params, context):
      cache_path = os.path.join(context["data_dir"], "cache.json")
      with open(cache_path, "w", encoding="utf-8") as cache:
          cache.write("{}")
  ```

  For example, a plugin installed at `/data/plugins/example_plugin_1_2_3/` with canonical ID `example_plugin` receives `/data/plugins/_data/example_plugin/`. Writes to other directories, such as `/tmp/output.json`, still require `filesystem_write`.

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
- `stop(context)` (optional callable): Invoked when the plugin is disabled, deleted, or reloaded so you can gracefully shut down any processes you started. If `stop()` is not defined but you have an action with id `stop`, Dispatcharr will call `run("stop", {}, context)` as a fallback. On disable and delete, `stop()` runs inside the database transaction while the plugin's row is locked, so keep it short and do not close database connections in it. If `stop()` hits a database error, its database changes are rolled back and the disable or delete still completes.

### Scheduled Celery tasks

Import scheduled task modules from the plugin entrypoint so their tasks register when the plugin loads.

Dispatcharr records the Celery tasks your plugin registers in its own modules (`@shared_task`, with or without `name=`) each time it loads while enabled, and keeps names from earlier versions for deletion. django-celery-beat `PeriodicTask` rows whose `task` is a recorded name are disabled when the plugin is disabled and deleted with it. On enable, Dispatcharr reloads the installed plugin and restores only previously enabled rows whose tasks are still present. Removed tasks stay disabled. A plugin that has not been loaded while enabled since this behavior was introduced has no recorded task names, so its schedules are left untouched.

Deleting a plugin keeps shared interval and crontab definitions. These do not run without a `PeriodicTask` row.

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

- `accept` (str, optional): Browser file-picker hint, e.g. `.ini,.json`. This only narrows what the picker shows; the server enforces its own fixed extension allowlist regardless of this value.
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

Read settings in `run` via `context["settings"]`. Use `context["code_dir"]` for bundled read-only resources and `context["data_dir"]` for durable files that must survive plugin code upgrades.

### Running a Persistent Service (Leader Election)

**Do not start a server, socket listener, or other persistent process in `__init__` or at module import time.** Dispatcharr instantiates every enabled plugin's `Plugin` class in every process that touches the app, often a dozen or more per plugin. Anything started in `__init__` starts once per process, so servers collide on ports.

For a persistent background service, implement `on_leader_acquired`/`on_leader_lost` **and** declare the `persistent_service` capability:

```python
class Plugin:
    name = "Example Service Plugin"
    version = "1.0.0"

    def on_leader_acquired(self, context):
        """Called once, in one process cluster-wide."""
        context["start_service"](self._run_service, name="exporter")

    def _run_service(self, stop_event):
        while not stop_event.is_set():
            self._publish_metrics()
            stop_event.wait(10)

    def on_leader_lost(self, context):
        """Called after Dispatcharr signals and joins the service thread."""
        self._close_plugin_resources()
```

```json
{
  "manifest_version": 2,
  "capabilities": ["persistent_service"]
}
```

**Manifest version 2 and later require the capability.** Unlike `background_tasks`, nothing about `on_leader_acquired` can be inferred from the rest of the manifest, so version `2` plugins without `persistent_service` are skipped by leader election: `on_leader_acquired` is never called. Versions `0` and `1` remain non-enforcing during the transition period. Declaring the capability shows users an itemized capability prompt the first time they enable your plugin, the same as `background_tasks` (see `manifest_version` and `capabilities`, above).

Dispatcharr elects one process per plugin using a Redis lease (30s TTL, renewed every 10s). If the leader process dies, another takes over within about 30s. The `context` passed here is lighter than `run()`'s: `settings` (a snapshot from discovery time, not a live read), `code_dir`, `data_dir`, and `logger`, with no `actions`.

Use `context["start_service"](target, name=None)` to start exactly one persistent service. Dispatcharr owns its native OS thread and gives `target` one argument, a `threading.Event` named `stop_event`. Check or wait on that event frequently and release sockets and external resources promptly when it is set. Dispatcharr signals it and waits briefly for the thread whenever leadership is lost, the plugin is disabled or reloaded, or the worker shuts down.

Do not call `gevent.spawn`, `gevent.spawn_later`, or instantiate `threading.Thread` for persistent plugin work. Celery processes can have gevent monkey-patching without a running gevent hub. `start_service` is available only in leadership hooks. For finite background work, use an `async: true` action or `context["dispatch_task"]` instead.

Things every service plugin must handle:
- **Bind failures on takeover.** The previous leader's socket may still be closing (`TIME_WAIT`) when a new leader binds. Set `SO_REUSEADDR`, and give `on_leader_acquired` its own short bind retry.
- **Redis being unavailable.** Every process becomes leader in that case (same as today's behavior), so `on_leader_acquired` should be safe to run concurrently if your deployment doesn't run Redis.
- **Being called again after `on_leader_lost`.** Don't assume state survived a loss; restart your service from scratch on reacquisition.
- **A brief overlap window is possible.** This is a lease, not a strict lock: a stalled leader (e.g. a GC pause past the TTL) can briefly overlap with a new leader. Account for that if dual-leadership has unsafe side effects.
- **Disable/reload releases immediately**, not just on TTL expiry, so `on_leader_lost` can fire outside of a timeout too.

### Actions
Each action is a dict:
- `id` (str): Unique action id.
- `label` (str): Action label.
- `description` (str, optional): Helper text.
- `button_label` (str, optional): Button text (defaults to “Run”).
- `button_variant` (str, optional): Button style (Mantine variants like `filled`, `outline`, `subtle`).
- `button_color` (str, optional): Button color (e.g., `red`, `blue`, `orange`).
- `async` (bool, optional): See "Long-Running Actions" below.

Clicking an action calls your plugin’s `run(action, params, context)` and shows a notification with the result or error.

### Long-Running Actions (Async Dispatch)

Manual actions are queued on the `plugins` Celery queue and normally wait for the result. Event hooks are queued and return immediately. Use either of the following when the action itself should return immediately and report its work asynchronously:

**1. Mark the action `async` in its manifest.** The button dispatches immediately and returns; your `run()` executes on a Celery worker instead of the request:
```python
actions = [
    {"id": "bulk_match", "label": "Match All Streams", "async": True},
]
```

**2. Or call `context["dispatch_task"]` from any action, sync or async.** Useful when only some invocations of an action turn out to be slow:
```python
def run(self, action, params, context):
    if action == "start_scan":
        task_id = context["dispatch_task"]("do_scan", params)
        return {"status": "started", "task_id": task_id}
    if action == "do_scan":
        # runs on a Celery worker when reached via dispatch_task
        ...
```

Either way, call `context["report_progress"](percent, message)` from inside the dispatched action to push progress to the UI. It's a no-op when your action isn't running async, so it's safe to call unconditionally.

Event hooks and non-async manual actions always run through Celery too (queued and awaited synchronously for manual actions, fire-and-forget for event hooks). There's no separate opt-in setting for this anymore, and no inline-in-request-process execution path.

**Deployment note:** `async` actions and `dispatch_task` target the `plugins` Celery queue, which is serviced by the same worker that handles everything else (`-Q celery,plugins`) in both the AIO image and the standard split-container `docker-compose.yml`. If you run a custom-mounted `entrypoint.celery.sh` or `uwsgi.ini`, make sure your worker(s) consume the `plugins` queue too, or these dispatch paths will queue work that never runs.

**The default worker's concurrency ceiling is configurable.** The existing `CELERY_MAX_WORKERS` and `CELERY_MIN_WORKERS` environment variables control the shared worker that handles both core tasks and plugin tasks. They are read at container startup, so restart the Celery or AIO container after changing them.

### Calling Approved Internal Tasks

`context["dispatch_internal_task"]` is for the narrow case where a plugin needs a specific first-party Dispatcharr Celery task instead of one of its own declared actions. A plugin must declare `celery_dispatch` in a manifest version `2` or later, and Dispatcharr must explicitly mark the target task with `@plugin_callable_task`. Declaring the capability alone never grants access to arbitrary Celery tasks.

```python
def run(self, action, params, context):
    if action == "refresh_source":
        task_id = context["dispatch_internal_task"](
            "apps.epg.tasks.refresh_epg_data",
            args=[params["source_id"]],
        )
        return {"status": "started", "task_id": task_id}
```

Approved tasks are always queued on `plugins`, regardless of any queue supplied by plugin code. Currently, `apps.m3u.tasks.refresh_single_m3u_account` and `apps.epg.tasks.refresh_epg_data` are approved. Other tasks are rejected until Dispatcharr adds `@plugin_callable_task` at the task definition.

### Action Confirmation
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

## Using Dispatcharr APIs

Plugins run inside the Django application. They can import models and use normal Django transactions, but should use the plugin APIs instead of reaching around them:

- Use `context["dispatch_task"]` for the plugin's own long-running work and `context["report_progress"]` to update its task UI.
- Use `context["dispatch_internal_task"]` only for an approved first-party task. It is intentionally not a general Celery escape hatch.
- Use internal models and tasks where appropriate. A plugin must not ask users for a Dispatcharr URL, username, or password to call its own host application.
- If HTTP is genuinely necessary, use `reverse()` to build an internal URL, use a short timeout, and declare `outbound_network` before moving to manifest version `2`.
- Use `context["logger"]` for plugin logging. Do not put credentials or sensitive user data in log messages or plugin settings.

Normal ORM work in `run()` and `stop()` is cleaned up by Dispatcharr. Threads or greenlets started by a plugin must close their own database connections when they finish. Keep CPU-heavy or blocking work out of those methods and dispatch it to the background queue instead.

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

## Best Practices

- Keep `run` short and schedule heavy operations via Celery tasks.
- Validate and sanitize `params` received from the UI.
- Use database transactions for bulk or related updates.
- Log actionable messages for troubleshooting.
- Keep mutable files in `context["data_dir"]`. Declare `filesystem_write` before writing elsewhere in a version `2` plugin.
- Treat plugins as trusted code: they run with full app permissions.

---

## Troubleshooting

- Plugin not listed: ensure the folder exists and contains `plugin.py` with a `Plugin` class.
- Import errors: ensure the folder contains `plugin.py` or a package `__init__.py`. Folder names with spaces or dashes are supported; if you need to import by folder name inside your plugin, use a valid Python identifier.
- No capability approval prompt: version `0` manifests ignore capability declarations. Set `manifest_version` to `1` or `2`.
- HTTP 403 on run: the plugin is disabled; enable it from the toggle or via the `enabled/` endpoint.

---

## Contributing

- Keep dependencies minimal. Vendoring small helpers into the plugin folder is acceptable.
- Use the existing task and model APIs where possible; propose extensions if you need new capabilities.

---

## Migration Guide: Manifest Version 0 to 1 and 2

Existing plugins without `manifest_version` are version `0`. They remain supported. The current plugins in [Dispatcharr/Plugins](https://github.com/Dispatcharr/Plugins) are version `0`, so maintainers should use this guide before moving a plugin to the newer manifest versions.

This is not process isolation. Plugins still run in the Dispatcharr process and are trusted code. Version `2` adds guards around supported plugin APIs so that a plugin cannot accidentally use an undeclared capability through those APIs.

Manifest versions `1` and `2` require Dispatcharr `0.34.0` or newer. Timestamped development images satisfy lower compatibility bounds while they carry unreleased code, but do not satisfy an explicit maximum version. Version `0` remains compatible with older releases.

### Version 0 to 1

Add `manifest_version` and list the capabilities your plugin uses in `plugin.json`:

```json
{
  "manifest_version": 1,
  "capabilities": ["outbound_network"]
}
```

Version `1` parses and displays capabilities, asks the administrator to approve them, and otherwise keeps version `0` behavior. Use it as the compatibility step before version `2`.

### Move mutable files to plugin storage

Plugin code can be replaced when a managed plugin is updated. Do not keep a database, cache, download, or other mutable state beside `plugin.py`, and do not build a storage path from the versioned install folder.

Dispatcharr provides two paths in every action, `stop()` hook, and leader hook:

- `context["code_dir"]`: the installed plugin code. Treat this as read-only.
- `context["data_dir"]`: a durable, version-stable directory owned by the plugin. Use this for mutable state.

```python
from pathlib import Path

def run(self, action, params, context):
    state_file = Path(context["data_dir"]) / "state.json"
    state_file.write_text('{"last_run": "now"}', encoding="utf-8")
```

Writes under `data_dir` do not need `filesystem_write`. A plugin that writes anywhere else, including a general temporary or shared directory, must declare `filesystem_write` before moving to version `2`.

### Adopt the new action and service APIs

- For long-running work, set `"async": true` on an action or call `context["dispatch_task"]`. Dispatcharr runs the work on its background queue and records progress and task history. Use `context["report_progress"]` from dispatched work to update the UI.
- For a long-lived service, use `on_leader_acquired(context)` and `on_leader_lost(context)`. Dispatcharr elects one process to run the service and calls the lost hook when leadership is released.
- Use `context["dispatch_internal_task"]` only for an explicitly approved first-party Dispatcharr task. It is not a general way to queue arbitrary Celery task names.

### Version 1 to 2

Change `manifest_version` to `2` once the capability list is complete:

```json
{
  "manifest_version": 2,
  "capabilities": ["background_tasks", "persistent_service", "outbound_network"]
}
```

At version `2`, the following operations are blocked unless the matching capability is declared and approved:

| Capability | Declare it when the plugin... | Without it in version 2 |
| --- | --- | --- |
| `background_tasks` | calls `context["dispatch_task"]` or runs long work in a declared async action | `dispatch_task` raises `PermissionError`. An action with `"async": true` adds this capability automatically. |
| `persistent_service` | uses `on_leader_acquired` and `on_leader_lost` for a long-lived service | Dispatcharr does not run the leader lifecycle hook. Do not start a persistent thread or server in `__init__`; move that work into the leader hooks. |
| `network_listener` | binds or listens on a socket, such as an HTTP, metrics, or webhook server | `socket.bind()` and `socket.listen()` raise `PermissionError`. |
| `outbound_network` | calls remote HTTP services or opens outbound sockets | `requests`, `urllib.request`, and `socket.connect()` raise `PermissionError`. |
| `subprocess` | starts a command or process | `subprocess.Popen`, `run`, `call`, `check_call`, and `check_output` raise `PermissionError`. |
| `filesystem_write` | writes outside `context["code_dir"]` or `context["data_dir"]` | writes made through `open()` outside those directories raise `PermissionError`. Use `context["data_dir"]` for durable plugin data. |
| `celery_dispatch` | calls `context["dispatch_internal_task"]` for a first-party Dispatcharr task | the helper raises `PermissionError`. The target task must also be explicitly approved by Dispatcharr. |

The other capabilities are disclosures for the approval dialog and are not currently runtime-enforced:

- `proxy_internals`: direct use of live-stream proxy internals.
- `user_data`: access to Dispatcharr user account data.
- `external_dependencies`: the plugin needs third-party Python packages. Declaring this does not install packages. Dependency installation is not supported.

`network_listener` requires a Dispatcharr restart after approval because it affects container-started infrastructure. Other capability changes take effect when the plugin is enabled or reloaded.

### Practical upgrade checklist

1. Start with version `1` and declare every capability the plugin uses. Confirm the approval prompt is accurate.
2. For a service plugin, move startup and shutdown work out of `__init__` and into `on_leader_acquired` and `on_leader_lost` before moving to version `2`. For example, an exporter that starts an HTTP server needs `persistent_service` and `network_listener`.
3. Move mutable files to `context["data_dir"]`, and use the new async action or leader lifecycle APIs where they fit the plugin.
4. Change to version `2`, then test every action and lifecycle hook with only the declared capabilities.
5. Treat new capabilities in an update as a user-visible permission change. Dispatcharr requires approval before the updated plugin can be enabled.
