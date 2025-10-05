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

> **Heads up:** The example above uses the legacy `fields` + `actions` interface. Existing plugins continue to work unchanged, but Dispatcharr now ships with a declarative UI schema that lets plugins build complete dashboards, tables, charts, forms, and sidebar pages. Jump to [Advanced UI schema](#advanced-ui-schema) for details.

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

### Plugin Management UI

The Plugins page provides:

- Enable/disable toggle per plugin (with first-use trust modal).
- Card status badges showing the last reload time or the most recent reload error.
- Search/filter input for quickly locating plugins by name/description.
- Open button for plugins that define an advanced UI layout.
- Reorder controls that change the sidebar order for `placement: "sidebar"` pages.
- Inline delete/import/reload operations (mirrors REST endpoints listed below).

---

## Plugin Interface

Export a `Plugin` class. Supported attributes and behavior:

- `name` (str): Human-readable name.
- `version` (str): Semantic version string.
- `description` (str): Short description.
- `fields` (list): Settings schema used by the UI to render controls.
- `actions` (list): Available actions; the UI renders a Run button for each.
- `ui` / `ui_schema` (dict, optional): Declarative UI specification (see [Advanced UI Schema](#advanced-ui-schema)).
- `run(action, params, context)` (callable): Invoked when a user clicks an action.
- `resolve_ui_resource(resource_id, params, context)` (optional callable): Handle advanced UI data requests.

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
- Optional keys: `button_label`, `running_label`, `variant`, `color`, `size`, `success_message`, `error_message`, `confirm`, `params`, `download` metadata, etc.

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

## Advanced UI Schema

Dispatcharr now includes a declarative UI builder so plugins can render full dashboards, tables, data visualisations, forms, and even custom sidebar pages. The legacy `fields` + `actions` attributes continue to work; the optional `ui`/`ui_schema` attribute extends that foundation without breaking existing plugins.

### Declaring the Schema

Define a `ui` (or `ui_schema`) attribute on your plugin. The schema is JSON-serialisable and describes data sources, a component tree, and optional additional pages.

```python
class Plugin:
    name = "Service Monitor"
    version = "2.0.0"
    description = "Track worker status and run jobs."

    ui = {
        "version": 1,
        "dataSources": {
            "workers": {
                "type": "action",
                "action": "list_workers",
                "refresh": {"interval": 30},
                "subscribe": {"event": "plugin_event", "filter": {"event": "worker_update"}},
            },
            "metrics": {
                "type": "resource",
                "resource": "metrics",
                "allowDisabled": True,
                "refresh": {"interval": 10},
            },
        },
        "layout": {
            "type": "stack",
            "gap": "md",
            "children": [
                {"type": "stat", "label": "Active Workers", "value": "{{ metrics.active }}", "icon": "Server"},
                {
                    "type": "table",
                    "source": "workers",
                    "columns": [
                        {"id": "name", "label": "Name", "accessor": "name", "sortable": True},
                        {"id": "status", "label": "Status", "badge": {"colors": {"up": "teal", "down": "red"}}},
                        {
                            "id": "actions",
                            "type": "actions",
                            "actions": [
                                {"id": "restart_worker", "label": "Restart", "button_label": "Restart", "color": "orange", "params": {"id": "{{ row.id }}"}},
                            ],
                        },
                    ],
                    "expandable": {
                        "fields": [
                            {"path": "last_heartbeat", "label": "Last heartbeat"},
                            {"path": "notes", "label": "Notes"},
                        ]
                    },
                },
                {
                    "type": "form",
                    "title": "Queue Job",
                    "action": "queue_job",
                    "submitLabel": "Queue",
                    "fields": [
                        {"id": "name", "label": "Job Name", "type": "text", "required": True},
                        {"id": "priority", "label": "Priority", "type": "number", "default": 5, "min": 1, "max": 10},
                        {"id": "payload", "label": "Payload", "type": "json"},
                    ],
                },
            ],
        },
        "pages": [
            {
                "id": "service-dashboard",
                "label": "Service Dashboard",
                "placement": "sidebar",
                "icon": "Activity",
                "route": "/dashboards/service-monitor",
                "layout": {
                    "type": "tabs",
                    "tabs": [
                        {"id": "overview", "label": "Overview", "children": [{"type": "chart", "chartType": "line", "source": "metrics", "xKey": "timestamp", "series": [{"id": "queue", "dataKey": "queue_depth", "color": "#4dabf7"}]}]},
                        {"id": "logs", "label": "Logs", "children": [{"type": "logStream", "source": "workers", "path": "payload.logs", "limit": 200}]},
                    ],
                },
            }
        ],
    }
```

### Pages & Navigation

- `layout` – component tree rendered inside the plugin card on the Plugins page. Use layout components such as `stack`, `group`, `grid`, `card`, `tabs`, `accordion`, `modal`, or `drawer` to organise content.
- `pages` – optional additional pages. Set `placement`:
  - `plugin` (default) – renders inside the plugin card.
  - `sidebar` – adds a navigation entry in the main sidebar and exposes a route (`page.route` or `/plugins/<key>/<page id>`).
  - `hidden` – registered but not surfaced automatically.
- `icon` accepts any [lucide](https://lucide.dev) icon name (`"Activity"`, `"Server"`, `"Gauge"`, etc.).
- `requiresSetting` (optional) hides the page unless the specified setting is truthy—useful for feature toggles such as a “Show in sidebar” switch.

Pages render inside `/plugins/<plugin-key>` and can also map to custom routes. Dispatcharr automatically registers `<Route path='/plugins/<key>' …>` and any explicit `page.route`. The Sidebar reads `placement: "sidebar"` pages and lists them under the standard navigation.

### Data Sources

Declare reusable data sources under `ui.dataSources` and reference them by id from components (`{"type": "table", "source": "alerts"}`). Each source can be customised by components via `dataSource` overrides and at runtime via templated params.

| Option | Description |
| --- | --- |
| `type` | `action` (default) calls `Plugin.run`; `resource` calls `resolve_ui_resource`; `static` returns a literal payload; `url` performs an HTTP request |
| `action` / `resource` | Identifier invoked for `type: action`/`resource` |
| `params` | Base parameters merged with component `params` and runtime overrides |
| `refresh.interval` | Poll every _n_ seconds (`{"interval": 5}`) |
| `refresh.lazy` | Skip the initial fetch; the component can call `refresh()` manually |
| `allowDisabled` | Allow a resource to run even when the plugin is disabled (read-only dashboards) |
| `default` | Fallback data while the first fetch runs (accepts literals or callables) |
| `extract` / `responsePath` / `path` | Dot-path into the response object (e.g. `payload.items`) |
| `pick` | For array responses, keep only specified keys per object |
| `subscribe` | WebSocket subscription spec for live updates (see below) |

**WebSocket subscriptions**

```json
"subscribe": {
  "event": "plugin_event",
  "filter": { "plugin": "self", "event": "log" },
  "mode": "append",
  "path": "payload.entry",
  "limit": 200
}
```

- `mode: "refresh"` (default) triggers a refetch when the filter matches.
- `mode: "append"` treats the data as an array, appending or prepending (`"prepend": true`) new entries, trimmed by `limit`.
- `mode: "patch"` merges object payloads into the current state.
- `path` resolves the payload (falls back to `event.payload`).

Emit events with `context["emit_event"]("log", {"entry": {...}})` or `send_websocket_update`.

**HTTP sources**

```json
"dataSources": {
  "external": {
    "type": "url",
    "url": "https://api.example.com/metrics",
    "method": "POST",
    "params": { "token": "{{ settings.api_token }}" }
  }
}
```

`type: "url"` honours `method`, `headers`, and serialises `params` (JSON for non-GET, query string for GET).

### Templating & Scope

Any string value can reference data with `{{ ... }}`. The renderer merges several scopes:

- `settings` – plugin settings returned by the backend.
- `context` – metadata provided to `PluginCanvas` (`plugin`, `page`, `location`).
- `{sourceId}` – payload for each data source (e.g. `summary`, `alerts`).
- `data` – shorthand for the payload bound to the current component.
- `row`, `value` – row-level context inside tables, card lists, and sortable lists.

Examples:

```json
"value": "{{ summary.metrics.health_percent }}%",
"confirm": {"message": "Stop channel {{ row.channel_display }}?"},
"params": {"id": "{{ row.id }}", "cluster": "{{ context.plugin.settings.cluster }}"}
```

### Component Library

The renderer understands a broad set of components. Highlights include:

- **Layout** – `stack`, `group`, `grid`, `card`, `tabs`, `accordion`, `split`, `modal`, `drawer`, `simpleGrid`.
- **Forms & Inputs** – text/password/search, textarea, number with min/max/step, sliders and range sliders, checkbox/switch/radio, single & multi select (searchable + creatable tags), segmented controls, date/time/datetime/daterange pickers, color picker, file upload (drag-and-drop via dropzone), JSON editor, chips/tag input.
- **Data displays** – tables with sorting, column filters, pagination, inline/per-row actions (templated params, confirmations), expandable detail rows; card lists with thumbnails/metadata; tree/hierarchical lists; timeline; statistic cards; markdown/html blocks.
- **Charts & Visualisations** – line, area, bar, pie/donut, radar, heatmap, progress bars, ring/radial progress, loaders/spinners, status lights with custom colours.
- **Real-time** – `logStream`, auto-refresh data sources, event subscriptions, status indicators that update via WebSocket.
- **Interactions** – `actionButton`, button groups, confirmation modals, sortable/drag-and-drop lists, embedded forms, `settingsForm` (binds directly to plugin settings).

### Forms & Settings

- `form` – arbitrary action forms. `fields` accept any input type listed above. Useful options: `submitLabel`, `resetOnSuccess`, `encode: 'formdata'` for file uploads, `actions` (secondary buttons), `initialValues`, `successMessage`, `errorMessage`, `confirm` (modal before submit).
- `settingsForm` – specialised form that reads/writes `PluginConfig.settings` automatically.
- `action`, `actionButton`, and `buttons` – lightweight buttons that trigger actions. They support templated `params` (`{"channel_id": "{{ row.channel_id }}"}`), templated `confirm` objects (`{"title": "Delete", "message": "Remove {{ row.name }}?", "confirmLabel": "Delete"}`), and inherit the button styling keys (`variant`, `color`, `size`, `icon`).
- Return `{"download": {"filename": "report.csv", "content_type": "text/csv", "data": base64}}` (or `download.url`) from `run` to trigger a download, which the UI automatically handles.

### Statistic Cards (`stat`)

Use stat nodes for quick KPIs. They can display literal values or read from a data source.

```json
{
  "type": "stat",
  "source": "summary",
  "label": "Active Channels",
  "metricPath": "summary.metrics.active_channels.display",
  "fallback": "0",
  "icon": "Activity",
  "delta": "{{ summary.metrics.active_channels.delta }}"
}
```

- `source` + `metricPath` resolves a value from the bound data. The component scope exposes `data`, `{sourceId}`, and `context` (plugin metadata, current page, etc.).
- `fallback`, `defaultValue`, or `placeholder` are shown when the metric is missing or still loading.
- `delta` renders a green/red indicator automatically when numeric. Provide plain text ("+5% vs last hour") to bypass arrows.

### Tables & Row Actions

- `columns` support `accessor`, `template`, `format` (`date`, `time`, `datetime`), `badge` colour maps, `render` (`json`, `status`, `progress`), `width`, and `sortable` flags.
- `rowActions` renders button groups at the end of each row. Actions inherit the same schema as `actionButton` (params & confirm templating, variants, icons). Example:

```json
{
  "type": "table",
  "source": "workers",
  "columns": [ ... ],
  "rowActions": [
    {
      "id": "restart_worker",
      "label": "Restart",
      "color": "orange",
      "params": {"worker_id": "{{ row.id }}"},
      "confirm": {"title": "Restart?", "message": "Restart {{ row.name }}?", "confirmLabel": "Restart"}
    }
  ],
  "expandable": {
    "fields": [
      {"label": "Last heartbeat", "path": "last_heartbeat"},
      {"label": "Notes", "path": "notes"}
    ]
  },
  "initialSort": [{"id": "status", "desc": true}],
  "filterable": true,
  "pageSize": 25
}
```

- `expandable` with `fields` renders key/value pairs; omit `fields` to show JSON.
- `initialSort`, `filterable`, `pageSize`, and column-level `filter` definitions enable familiar datatable behaviour.

### Real-time Widgets

- `logStream` consumes append-mode data sources. Configure `dataSource` overrides to change polling interval, limits, or default text.
- `timeline`, `tree`, `cardList`, `progress`, `loader`, `status`, and the various `chart` types all accept `source` and templated values. Provide `series` definitions for multi-line charts (`[{"id": "errors", "dataKey": "errors", "color": "#fa5252"}]`).
- `sortableList` enables drag-and-drop reordering of items. When `action` is set, the renderer sends `{ order: [ids...] }` to that action after each drop; call the supplied `refresh()` callback to reload.

### Real-time & Events

- Call `context["emit_event"](event_name, payload)` inside `run` or `resolve_ui_resource` to broadcast `{"type": "plugin_event", "plugin": key, "event": event_name, "payload": payload}` over the `updates` WebSocket channel. Components with `subscribe` refresh automatically and the frontend can show rich notifications when `notification` metadata is included.
- `context["files"]` exposes uploaded files when an action is triggered with multipart/form-data. Each entry is a Django `UploadedFile`.
- `context["ui_schema"]` returns the resolved schema for convenience.

### Backend Helpers

- `resolve_ui_resource(self, resource_id, params, context)` – optional method invoked by `type: "resource"` data sources or `POST /api/plugins/plugins/<key>/ui/resource/`. Return JSON-like structures (dict/list) or raise to signal errors. `allowDisabled=True` lets resources run when the plugin is disabled (useful for dashboards).
- `context` now includes `emit_event`, `files`, `plugin` metadata, and the `actions` map alongside `settings` and `logger`.
- `/api/plugins/plugins/<key>/ui/resource/` accepts JSON or form data (`resource`, `params`, `allow_disabled`). Responses mirror `run`: `{"success": true, "result": {...}}`.

### Sidebar & Workspace

- The Plugins page renders the primary `layout`. Clicking **Open** on a plugin with an advanced UI navigates to `/plugins/<key>` which hosts the same layout. Additional pages registered with `placement: "sidebar"` appear in the main navigation and receive dedicated routes (`page.route` or `/plugins/<key>/<page id>`).
- All pages share the same component library; the only difference is where they surface.

### Compatibility

- `fields` + `actions` remain fully supported. Use them for quick settings; mix in `ui` gradually.
- When both are provided, the legacy sections render only if no advanced layout is supplied for the plugin card.

---

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

- Send WebSocket updates or trigger UI refreshes:
  ```
  from core.utils import send_websocket_update
  send_websocket_update('updates', 'update', {"type": "plugin", "plugin": "my_plugin", "message": "Done"})

  # Inside run / resolve_ui_resource you can also use the provided helper:
  context["emit_event"]("worker_update", {"id": worker.id, "status": "up"})
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

- Access uploaded files submitted through advanced forms:
  ```
  def run(self, action, params, context):
      files = context.get("files", {})  # dict keyed by form field id
      upload = files.get("payload")
      if upload:
          handle_file(upload)
  ```

Prefer Celery tasks (`.delay()`) to keep `run` fast and non-blocking.

### Core Django Modules

Prefer calling Django models and services directly; the REST API uses the same code paths. Common imports include:

```python
# Core configuration and helpers
from core.models import CoreSettings, StreamProfile, UserAgent
from core.utils import RedisClient, send_websocket_update

# Channels / DVR
from apps.channels.models import (
    Channel, ChannelGroup, ChannelStream, Stream,
    Recording, RecurringRecordingRule, ChannelProfile,
)
from apps.channels.tasks import (
    match_channels_to_epg, match_epg_channels, match_single_channel_epg,
    evaluate_series_rules, reschedule_upcoming_recordings_for_offset_change,
    rebuild_recurring_rule, maintain_recurring_recordings,
    run_recording, recover_recordings_on_startup, comskip_process_recording,
    prefetch_recording_artwork,
)
from apps.channels.services.channel_service import ChannelService

# M3U / ingest sources
from apps.m3u.models import M3UAccount, M3UFilter, M3UAccountProfile, ServerGroup
from apps.m3u.tasks import (
    refresh_m3u_accounts, refresh_single_m3u_account,
    refresh_m3u_groups, cleanup_streams, sync_auto_channels,
    refresh_account_info,
)

# EPG
from apps.epg.models import EPGSource, EPGData, ProgramData
from apps.epg.tasks import refresh_all_epg_data, refresh_epg_data, parse_programs_for_source

# VOD / media library
from apps.vod.models import (
    VODCategory, Series, Movie, Episode,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation,
)
from apps.vod.tasks import (
    refresh_vod_content, refresh_categories, refresh_movies,
    refresh_series, refresh_series_episodes, cleanup_orphaned_vod_content,
)

# Proxy / streaming state
from apps.proxy.ts_proxy.channel_status import ChannelStatus
from apps.proxy.ts_proxy.services.channel_service import ChannelService as TsChannelService
from apps.proxy.ts_proxy.utils import detect_stream_type, get_client_ip
from apps.proxy.vod_proxy.multi_worker_connection_manager import MultiWorkerVODConnectionManager

# Plugin infrastructure
from apps.plugins.loader import PluginManager
from apps.plugins.models import PluginConfig
```

Each app exposes additional utilities (serializers, services, helpers). Browse the `apps/` directory to discover modules relevant to your plugin.

---

## REST Endpoints (for UI and tooling)

- List plugins: `GET /api/plugins/plugins/`
  - Response: `{ "plugins": [{ key, name, version, description, enabled, fields, settings, actions, ui_schema }, ...] }`
- Reload discovery: `POST /api/plugins/plugins/reload/`
- Import plugin: `POST /api/plugins/plugins/import/` with form-data file field `file`
- Update settings: `POST /api/plugins/plugins/<key>/settings/` with `{"settings": {...}}`
- Run action: `POST /api/plugins/plugins/<key>/run/` with `{"action": "id", "params": {...}}`
- Resolve UI resource: `POST /api/plugins/plugins/<key>/ui/resource/` with `{"resource": "id", "params": {...}, "allow_disabled": false}`
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
