# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Updated Django 5.2.9 → 5.2.11, resolving the following CVEs:
  - **CVE-2025-13473** (low): Username enumeration via timing difference in mod_wsgi authentication handler.
  - **CVE-2025-14550** (moderate): Potential denial-of-service via repeated headers on ASGI requests.
  - **CVE-2026-1207** (high): Potential SQL injection via raster lookups on PostGIS.
  - **CVE-2026-1285** (moderate): Potential denial-of-service in `django.utils.text.Truncator` HTML methods via inputs with large numbers of unmatched HTML end tags.
  - **CVE-2026-1287** (high): Potential SQL injection in column aliases via control characters in `FilteredRelation`.
  - **CVE-2026-1312** (high): Potential SQL injection via `QuerySet.order_by()` and `FilteredRelation` when using column aliases containing periods.
- Updated frontend npm dependencies to resolve 5 audit vulnerabilities (1 moderate, 4 high):
  - Updated `ajv` 6.12.6 → 6.14.0, resolving a **moderate** ReDoS vulnerability when using the `$data` option ([GHSA-2g4f-4pwh-qvx6](https://github.com/advisories/GHSA-2g4f-4pwh-qvx6))
  - Enforced `minimatch` ≥10.2.2 via npm overrides, resolving **high** ReDoS via repeated wildcards with non-matching literal patterns ([GHSA-3ppc-4f35-3m26](https://github.com/advisories/GHSA-3ppc-4f35-3m26)) affecting `minimatch`, `@eslint/config-array`, `@eslint/eslintrc`, and `eslint`

### Added

- Lightweight channel summary API endpoint: Added a new `/api/channels/summary/` endpoint that returns only the minimal channel data needed for TV Guide and DVR scheduling (id, name, logo), avoiding the overhead of serializing full channel objects for high-frequency UI operations.
- Custom Dummy EPG subtitle template support: Added optional subtitle template field to custom dummy EPG configuration. Users can now define subtitle patterns using extracted regex groups and time/date placeholders (e.g., `{starttime} - {endtime}`). (Closes #942)
- Event-driven webhooks and script execution (Connect): Added new Connect feature that enables event-driven execution of custom scripts and webhooks in response to system events. Supports multiple event types including channel lifecycle (start, stop, reconnect, error, failover), stream operations (switch), recording events (start, end), data refreshes (EPG, M3U), and client activity (connect, disconnect). Event data is available as environment variables in scripts (prefixed with `DISPATCHARR_`), POST payloads for webhooks, and plugin execution payloads. Plugins can now subscribe to events by specifying an `events` array in their action definitions. Includes connection testing endpoint with dummy payloads for validation. (Closes #203)
- Cron scheduling support for M3U and EPG refreshes: Added interactive cron expression builder with preset buttons and custom field editors, plus info popover with common cron examples. Refactored backup scheduling to use shared ScheduleInput component for consistency across all scheduling interfaces. (Closes #165)
- Channel numbering modes for auto channel sync: Added three channel numbering modes when auto-syncing channels from M3U groups:
  - **Fixed Start Number** (default): Start at a specified number and increment sequentially
  - **Use Provider Number**: Use channel numbers from the M3U source (tvg-chno), with configurable fallback if provider number is missing
  - **Next Available**: Auto-assign starting from 1, skipping all used channel numbers
    Each mode includes its own configuration options accessible via the "Channel Numbering Mode" dropdown in auto sync settings. (Closes #956, #433)
- Legacy NumPy for modular Docker: Added entrypoint detection and automatic installation for the Celery container (use `USE_LEGACY_NUMPY`) to support older CPUs. - Thanks [@patrickjmcd](https://github.com/patrickjmcd)

### Changed

- Dependency updates:
  - `Django` 5.2.9 → 5.2.11 (security patch; see Security section)
  - `celery` 5.6.0 → 5.6.2
  - `psutil` 7.1.3 → 7.2.2
  - `torch` 2.9.1+cpu → 2.10.0+cpu
  - `sentence-transformers` 5.2.0 → 5.2.3
  - `ajv` 6.12.6 → 6.14.0 (security patch; see Security section)
  - `minimatch` enforced ≥10.2.2 via npm overrides (security patch; see Security section)
  - `react` / `react-dom` 19.2.3 → 19.2.4
  - `react-router-dom` / `react-router` 7.12.0 → 7.13.0
  - `react-hook-form` 7.70.0 → 7.71.2
  - `react-draggable` 4.4.6 → 4.5.0
  - `@tanstack/react-table` 8.21.2 → 8.21.3
  - `video.js` 8.23.4 → 8.23.7
  - `vite` 7.3.0 → 7.3.1
  - `zustand` 5.0.9 → 5.0.11
  - `allotment` 1.20.4 → 1.20.5
  - `prettier` 3.7.4 → 3.8.1
  - `@swc/wasm` 1.15.7 → 1.15.11
  - `@testing-library/react` 16.3.1 → 16.3.2
  - `@types/react` 19.2.7 → 19.2.14
  - `@vitejs/plugin-react-swc` 4.2.2 → 4.2.3
- Channel store optimization: Refactored frontend channel loading to only fetch channel IDs on initial login (matching the streams store pattern), instead of loading full channel objects upfront. Full channel data is fetched lazily as needed. This dramatically reduces login time and initial page load when large channel libraries are present.
- DVR scheduling: Channel selector now displays the channel number alongside the channel name when scheduling a recording.
- TV Guide performance improvements: Optimized the TV Guide with horizontal culling for off-screen program rows (only rendering visible programs), throttled now-line position updates, and improved scroll performance. Reduces unnecessary DOM work and improves responsiveness with large EPG datasets.
- Stream Profile form rework: Replaced the plain command text field with a dropdown listing built-in tools (FFmpeg, Streamlink, VLC, yt-dlp) plus a Custom option that reveals a free-text input. Each built-in now shows its default parameter string as a live example in the Parameters field description, updating as the command selection changes. Added descriptive help text to all fields to improve clarity.
- Custom Dummy EPG form UI improvements: Reorganized the form into collapsible accordion sections (Pattern Configuration, Output Templates, Upcoming/Ended Templates, Fallback Templates, EPG Settings) for better organization. Field descriptions now appear in info icon popovers instead of taking up vertical space, making the form more compact and easier to navigate while keeping help text accessible.
- XC API M3U stream URLs: M3U generation for Xtream Codes API endpoints now use proper XC-style stream URLs (`/live/username/password/channel_id`) instead of UUID-based stream endpoints, ensuring full compatibility with XC clients. (Fixes #839)

### Fixed

- Channel table group filter sort order: The group dropdown in the channel table is now sorted alphabetically.
- DVR one-time recording scheduling: Fixed a bug where scheduling a one-time recording for a future program caused the recording to start immediately instead of at the scheduled time.
- XC API `added` field type inconsistencies: `get_live_streams` and `get_vod_info` now return the `added` field as a string (e.g., `"1708300800"`) instead of an integer, fixing compatibility with XC clients that have strict JSON serializers (such as Jellyfin's Xtream Library plugin). (Closes #978)
- Stream Profile form User-Agent not populating when editing: The User-Agent field was not correctly loaded from the existing profile when opening the edit modal. (Fixes #650)
- VOD proxy connection counter leak on client disconnect: Fixed a connection leak in the VOD proxy where connection counters were not properly decremented when clients disconnected, causing the connection pool to lose track of available connections. The multi-worker connection manager now correctly handles client disconnection events across all proxy configurations. Includes three key fixes: (1) Replaced GET-check-INCR race condition with atomic INCR-first-then-check pattern in both connection managers to prevent concurrent requests exceeding max_streams; (2) Decrement profile counter directly in stream generator exit paths instead of deferring to daemon thread cleanup; (3) Decrement profile counter on create_connection() failure to release reserved slots. (Fixes #962, #971, #451, #533) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- XC profile refresh credential extraction with sub-paths: Fixed credential extraction in `get_transformed_credentials()` to use negative indices anchored to the known tail structure instead of hardcoded indices that broke when server URLs contained sub-paths (e.g., `http://server.com/portal/a/`). This ensures XC accounts with sub-paths in their server URLs work correctly for profile refreshes. (Fixes #945) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- XC EPG URL construction for accounts with sub-paths or trailing slashes: Fixed EPG URL construction in M3U forms to normalize server URL to origin before appending `xmltv.php` endpoint, preventing double slashes and incorrect path placement when server URLs include sub-paths or trailing slashes. (Fixes #800) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Auto channel sync duplicate channel numbers across groups: Fixed issue where multiple auto-sync groups starting at the same number would create duplicate channel numbers. The used channel number tracking now persists across all groups in a single sync operation, ensuring each assigned channel number is globally unique.
- Modular mode PostgreSQL/Redis connection checks: Replaced raw Python socket checks with native tools (`pg_isready` for PostgreSQL and `socket.create_connection` for Redis) in modular deployment mode to prevent indefinite hangs in Docker environments with non-standard networking or DNS configurations. Now properly supports IPv4 and IPv6 configurations. (Fixes #952) - Thanks [@CodeBormen](https://github.com/CodeBormen)

## [0.19.0] - 2026-02-10

### Added

- Add system notifications and update checks
  -Real-time notifications for system events and alerts
  -Per-user notification management and dismissal
  -Update check on startup and every 24 hours to notify users of available versions
  -Notification center UI component
  -Automatic cleanup of expired notifications
- Network Access "Reset to Defaults" button: Added a "Reset to Defaults" button to the Network Access settings form, matching the functionality in Proxy Settings. Users can now quickly restore recommended network access settings with one click.
- Streams table column visibility toggle: Added column menu to Streams table header allowing users to show/hide optional columns (TVG-ID, Stats) based on preference, with optional columns hidden by default for cleaner default view.
- Streams table TVG-ID column with search filter and sort: Added TVG-ID column to streams table with search filtering and sort capability for better stream organization. (Closes #866) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Frontend now automatically refreshes streams and channels after a stream rehash completes, ensuring the UI is always up-to-date following backend merge operations.
- Frontend Unit Tests: Added comprehensive unit tests for React hooks and Zustand stores, including:
  - `useLocalStorage` hook tests with localStorage mocking and error handling
  - `useSmartLogos` hook tests for logo loading and management
  - `useTablePreferences` hook tests for table settings persistence
  - `useAuthStore` tests for authentication flow and token management
  - `useChannelsStore` tests for channel data management
  - `useUserAgentsStore` tests for user agent CRUD operations
  - `useUsersStore` tests for user management functionality
  - `useVODLogosStore` tests for VOD logo operations
  - `useVideoStore` tests for video player state management
  - `useWarningsStore` tests for warning suppression functionality
  - Code refactoring for improved readability and maintainability - Thanks [@nick4810](https://github.com/nick4810)
- EPG auto-matching: Added advanced options to strip prefixes, suffixes, and custom text from channel names to assist matching; default matching behavior and settings remain unchanged (Closes #771) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Redis authentication support for modular deployments: Added support for authentication when connecting to external Redis instances using either password-only authentication (Redis <6) or username + password authentication (Redis 6+ ACL). REDIS_PASSWORD and REDIS_USER environment variables with URL encoding for special characters. (Closes #937) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Plugin logos: if a plugin ZIP includes `logo.png`, it is surfaced in the Plugins UI and shown next to the plugin name.
- Plugin manifests (`plugin.json`) for safe metadata discovery, plus legacy warnings and folder-name fallbacks when a manifest is missing.
- Plugin stop hooks: Dispatcharr now calls a plugin's optional `stop()` method (or `run("stop")` action) when disabling, deleting, or reloading plugins to allow graceful shutdown.
- Plugin action buttons can define `button_label`, `button_variant`, and `button_color` (e.g., Stop in red), falling back to “Run” for older plugins.
- Plugin card metadata: plugins can specify `author` and `help_url` in `plugin.json` to show author and docs link in the UI.
- Plugin cards can now be expanded/collapsed by clicking the header or chevron to hide settings and actions.

### Changed

- XtreamCodes Authentication Optimization: Reduced API calls during XC refresh by 50% by eliminating redundant authentication step. This should help reduce rate-limiting errors.
- App initialization efficiency: Refactored app initialization to prevent redundant execution across multiple worker processes. Created `dispatcharr.app_initialization` utility module with `should_skip_initialization()` function that prevents custom initialization tasks (backup scheduler sync, developer notifications sync) from running during management commands, in worker processes, or in development servers. This significantly reduces startup overhead in multi-worker deployments (e.g., uWSGI with 10 workers now syncs the scheduler once instead of 10 times). Applied to both `CoreConfig` and `BackupsConfig` apps.
- M3U/EPG Network Access Defaults: Updated default network access settings for M3U and EPG endpoints to only allow local/private networks by default (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1/128, fc00::/7, fe80::/10). This improves security by preventing public internet access to these endpoints unless explicitly configured. Other endpoints (Streams, XC API, UI) remain open by default.
- Modular deployments: Bumped modular Postgres image to 17 and added compatibility checks (PostgreSQL version and UTF-8 database encoding) when using external databases to prevent migration/encoding issues.
- Stream Identity Stability: Added `stream_id` (provider stream identifier) and `stream_chno` (provider channel number) fields to Stream model. For XC accounts, the stream hash now uses the stable `stream_id` instead of the URL when hashing, ensuring XC streams maintain their identity and channel associations even when account credentials or server URLs change. Supports both XC `num` and M3U `tvg-chno`/`channel-number` attributes.
- Swagger/OpenAPI Migration: Migrated from `drf-yasg` (OpenAPI 2.0) to `drf-spectacular` (OpenAPI 3.0) for API documentation. This provides:
  - Native Bearer token authentication support in Swagger UI - users can now enter just the JWT token and the "Bearer " prefix is automatically added
  - Modern OpenAPI 3.0 specification compliance
  - Better auto-generation of request/response schemas
  - Improved documentation accuracy with serializer introspection
- Switched to uv for package management: Migrated from pip to uv (Astral's fast Python package installer) for improved dependency resolution speed and reliability. This includes updates to Docker build processes, installation scripts (debian_install.sh), and project configuration (pyproject.toml) to leverage uv's features like virtual environment management and lockfile generation. - Thanks [@tobimichael96](https://github.com/tobimichael96) for getting it started!
- Copy to Clipboard: Refactored `copyToClipboard` utility function to include notification handling internally, eliminating duplicate notification code across the frontend. The function now accepts optional parameters for customizing success/failure messages while providing consistent behavior across all copy operations.

### Fixed

- XC EPG Logic: Fixed EPG filtering issues where short EPG requests had no time-based filtering (returning expired programs) and regular EPG requests used `start_time__gte` (missing the currently playing program). Both now correctly use `end_time__gt` to show programs that haven't ended yet, with short EPG additionally limiting results. (Fixes #915)
- Automatic backups not enabled by default on new installations: Added backups app to `INSTALLED_APPS` and implemented automatic scheduler initialization in `BackupsConfig.ready()`. The backup scheduler now properly syncs the periodic task on startup, ensuring automatic daily backups are enabled and scheduled immediately on fresh database creation without requiring manual user intervention.
- Fixed modular Docker Compose deployment and entrypoint/init scripts to properly support `DISPATCHARR_ENV=modular`, use external PostgreSQL/Redis services, and handle port, version, and encoding validation (Closes #324, Fixes #61, #445, #731) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Stream rehash/merge logic now guarantees unique stream_hash and always preserves the stream with the best channel ordering and relationships. This prevents duplicate key errors and ensures the correct stream is retained when merging. (Fixes #892)
- Admin URL Conflict with XC Streams: Updated nginx configuration to only redirect exact `/admin` and `/admin/` paths to login in production, preventing interference with stream URLs that use "admin" as a username (e.g., `/admin/password/stream_id` now properly routes to stream handling instead of being redirected).
- EPG Channel ID XML Escaping: Fixed XML parsing errors in EPG output when channel IDs contain special characters (&, <, >, \") by properly escaping them in XML attributes. (Fixes #765) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Fixed NumPy baseline detection in Docker entrypoint. Now properly detects when NumPy crashes on import due to CPU baseline incompatibility and installs legacy NumPy version. Previously, if NumPy failed to import, the script would skip legacy installation assuming it was already compatible.
- Backup Scheduler Test: Fixed test to correctly validate that automatic backups are enabled by default with a retention count of 3, matching the actual scheduler defaults. - Thanks [@jcasimir](https://github.com/jcasimir)
- Hardened plugin loading to avoid executing plugin code unless the plugin is enabled.
- Prevented plugin package names from shadowing standard library or installed modules by namespacing plugin imports with safe aliases.
- Added safety limits to plugin ZIP imports (file count and size caps) and sanitized plugin keys derived from uploads.
- Enforced strict boolean parsing for plugin enable/disable requests to avoid accidental enables from truthy strings.
- Applied plugin field defaults server-side when running actions so plugins receive expected settings even before a user saves.
- Plugin settings UI improvements: render `info`/`text` fields, support `input_type: password`, show descriptions/placeholders, surface save failures, and keep settings in sync after refresh.
- Disabled plugins now collapse settings/actions to match the closed state before first enable.
- Plugin card header controls (delete/version/toggle) now stay right-aligned even with long descriptions.
- Improved plugin logo resolution (case-insensitive paths + absolute URLs), fixing dev UI logo loading without a Vite proxy.
- Plugin reload now hits the backend, clears module caches across workers, and refreshes the UI so code changes apply without a full backend restart.
- Plugin loader now supports `plugin.py` without `__init__.py`, including folders with non-identifier names, by loading modules directly from file paths.
- Plugin action handling stabilized: avoids registry race conditions and only shows loading on the active action.
- Plugin enable/disable toggles now update immediately without requiring a full page refresh.

## [0.18.1] - 2026-01-27

### Fixed

- Series Rules API Swagger Documentation: Fixed drf_yasg validation error where TYPE_ARRAY schemas were missing required items parameter, causing module import failure

## [0.18.0] - 2026-01-27

### Security

- Updated react-router from 7.11.0 to 7.12.0 to address two security vulnerabilities:
  - **High**: Open Redirect XSS vulnerability in Action/Server Action Request Processing ([GHSA-h5cw-625j-3rxh](https://github.com/advisories/GHSA-h5cw-625j-3rxh), [GHSA-2w69-qvjg-hvjx](https://github.com/advisories/GHSA-2w69-qvjg-hvjx))
  - **Moderate**: SSR XSS vulnerability in ScrollRestoration component ([GHSA-8v8x-cx79-35w7](https://github.com/advisories/GHSA-8v8x-cx79-35w7))
- Updated react-router-dom from 7.11.0 to 7.12.0 (dependency of react-router)
- Fixed moderate severity Prototype Pollution vulnerability in Lodash (`_.unset` and `_.omit` functions) See [GHSA-xxjr-mmjv-4gpg](https://github.com/advisories/GHSA-xxjr-mmjv-4gpg) for details.

### Added

- Series Rules API Swagger Documentation: Added comprehensive Swagger/OpenAPI documentation for all series-rules endpoints (`GET /series-rules/`, `POST /series-rules/`, `DELETE /series-rules/{tvg_id}/`, `POST /series-rules/evaluate/`, `POST /series-rules/bulk-remove/`), including detailed descriptions, request/response schemas, and error handling information for improved API discoverability
- Editable Channel Table Mode:
  - Added a robust inline editing mode for the channels table, allowing users to quickly edit channel fields (name, number, group, EPG, logo) directly in the table without opening a modal.
  - EPG and logo columns support searchable dropdowns with instant filtering and keyboard navigation for fast assignment.
  - Drag-and-drop reordering of channels enabled when unlocked, with persistent order updates. (Closes #333)
  - Group column uses a searchable dropdown for quick group assignment, matching the UX of EPG and logo selectors.
  - All changes are saved via API with optimistic UI updates and error handling.
- Stats page enhancements: Added "Now Playing" program information for active streams with smart polling that only fetches EPG data when programs are about to change (not on every stats refresh). Features include:
  - Currently playing program title displayed with live broadcast indicator (green Radio icon)
  - Expandable program descriptions via chevron button
  - Progress bar showing elapsed and remaining time for currently playing programs
  - Efficient POST-based API endpoint (`/api/epg/current-programs/`) supporting batch channel queries or fetching all channels
  - Smart scheduling that fetches new program data 5 seconds after current program ends
  - Only polls when active channel list changes, not on stats refresh
- Channel preview button: Added preview functionality to active stream cards on stats page
- Unassociated streams filter: Added "Only Unassociated" filter option to streams table for quickly finding streams not assigned to any channels - Thanks [@JeffreyBytes](https://github.com/JeffreyBytes) (Closes #667)
- Streams table: Added "Hide Stale" filter to quickly hide streams marked as stale.
- Client-side logo caching: Added `Cache-Control` and `Last-Modified` headers to logo responses, enabling browsers to cache logos locally for 4 hours (local files) and respecting upstream cache headers (remote logos). This reduces network traffic and nginx load while providing faster page loads through browser-level caching that complements the existing nginx server-side cache - Thanks [@DawtCom](https://github.com/DawtCom)
- DVR recording remux fallback strategy: Implemented two-stage TS→MP4→MKV fallback when direct TS→MKV conversion fails due to timestamp issues. On remux failure, system now attempts TS→MP4 conversion (MP4 container handles broken timestamps better) followed by MP4→MKV conversion, automatically recovering from provider timestamp corruption. Failed conversions now properly clean up partial files and preserve source TS for manual recovery.
- Mature content filtering support:
  - Added `is_adult` boolean field to both Stream and Channel models with database indexing for efficient filtering and sorting
  - Automatically populated during M3U/XC refresh operations by extracting `is_adult` value from provider data
  - Type-safe conversion supporting both integer (0/1) and string ("0"/"1") formats from different providers
  - UI controls in channel edit form (Switch with tooltip) and bulk edit form (Select dropdown) for easy management
  - XtreamCodes API support with proper integer formatting (0/1) in live stream responses
  - Automatic propagation from streams to channels during both single and bulk channel creation operations
  - Included in serializers for full API support
  - User-level content filtering: Non-admin users can opt to hide mature content channels across all interfaces (web UI, M3U playlists, EPG data, XtreamCodes API) via "Hide Mature Content" toggle in user settings (stored in custom_properties, admin users always see all content)
- Table header pin toggle: Pin/unpin table headers to keep them visible while scrolling. Toggle available in channel table menu and UI Settings page. Setting persists across sessions and applies to all tables. (Closes #663)
- Cascading filters for streams table: Improved filter usability with hierarchical M3U and Group dropdowns. M3U acts as the parent filter showing only active/enabled accounts, while Group options dynamically update to display only groups available in the selected M3U(s). Only enabled M3U's are displayed. (Closes #647)
- Streams table UI: Added descriptive tooltips to top-toolbar buttons (Add to Channel, Create Channels, Filters, Create Stream, Delete) and to row action icons (Add to Channel, Create New Channel). Tooltips now use a 500ms open delay for consistent behavior with existing table header tooltips.

### Changed

- Data loading and initialization refactor: Major performance improvement reducing initial page load time by eliminating duplicate API requests caused by race conditions between authentication flow and route rendering:
  - Fixed authentication race condition where `isAuthenticated` was set before data loading completed, causing routes to render and tables to mount prematurely
  - Added `isInitialized` flag to delay route rendering until after all initialization data is loaded via `initData()`
  - Consolidated version and environment settings fetching into centralized settings store with caching to prevent redundant calls
  - Implemented stale fetch prevention in ChannelsTable and StreamsTable using fetch version tracking to ignore outdated responses
  - Fixed filter handling in tables to use `debouncedFilters` consistently, preventing unnecessary refetches
  - Added initialization guards using refs to prevent double-execution of auth and superuser checks during React StrictMode's intentional double-rendering in development
  - Removed duplicate version/environment fetch calls from Sidebar, LoginForm, and SuperuserForm by using centralized store
- Table preferences (header pin and table size) now managed together with centralized state management and localStorage persistence.
- Streams table button labels: Renamed "Remove" to "Delete" and "Add Stream to Channel" to "Add to Channel" for clarity and consistency with other UI terminology.
- Frontend tests GitHub workflow now uses Node.js 24 (matching Dockerfile) and runs on both `main` and `dev` branch pushes and pull requests for comprehensive CI coverage.
- Table preferences architecture refactored: Migrated `table-size` preference from individual `useLocalStorage` calls to centralized `useTablePreferences` hook. All table components now read preferences from the table instance (`table.tableSize`, `.g maintainability and providing consistent API across all tables.
- Optimized unassociated streams filter performance: Replaced inefficient reverse foreign key NULL check (`channels__isnull=True`) with Count annotation approach, reducing query time from 4-5 seconds to under 500ms for large datasets (75k+ streams)

### Fixed

- Channels table pagination error handling: Fixed "Invalid page" error notifications that appeared when filters reduced the result set while on a page beyond the new total. The API layer now automatically detects invalid page errors, resets pagination to page 1, and retries the request transparently. (Fixes #864)
- Fixed long IP addresses overlapping adjacent columns in stream connection card by adding truncation with tooltips displaying the full address. (Fixes #712)
- Fixed nginx startup failure due to group name mismatch in non-container deployments - Thanks [@s0len](https://github.com/s0len) (Fixes #877)
- Updated streamlink from 8.1.0 to 8.1.2 to fix YouTube live stream playback issues and improve Pluto TV ad detection (Fixes #869)
- Fixed date/time formatting across all tables to respect user's UI preferences (time format and date format) set in Settings page:
  - Stream connection card "Connected" column
  - VOD connection card "Connection Start Time" column
  - M3U table "Updated" column
  - EPG table "Updated" column
  - Users table "Last Login" and "Date Joined" columns
  - All components now use centralized `format()` helper from dateTimeUtils for consistency
- Removed unused imports from table components for cleaner code
- Fixed build-dev.sh script stability: Resolved Dockerfile and build context paths to be relative to script location for reliable execution from any working directory, added proper --platform argument handling with array-safe quoting, and corrected push behavior to honor -p flag with accurate messaging. Improved formatting and quoting throughout to prevent word-splitting issues - Thanks [@JeffreyBytes](https://github.com/JeffreyBytes)
- Fixed TypeError on streams table load after container restart: Added robust data validation and type coercion to handle malformed filter options during container startup. The streams table MultiSelect components now safely convert group names to strings and filter out null/undefined values, preventing "right-hand side of 'in' should be an object, got number" errors when the backend hasn't fully initialized. API error handling returns safe defaults.
- Fixed XtreamCodes API crash when channels have NULL channel_group: The `player_api.php` endpoint (`xc_get_live_streams`) now gracefully handles channels without an assigned channel_group by dynamically looking up and assigning them to "Default Group" instead of crashing with AttributeError. Additionally, the Channel serializer now auto-assigns new channels to "Default Group" when `channel_group_id` is omitted during creation, preventing future NULL channel_group issues.
- Fixed streams table column header overflow: Implemented fixed-height column headers (30px max-height) with pill-style filter display showing first selection plus count (e.g., "Sport +3"). Prevents header expansion when multiple filters are selected, maintaining compact table layout. (Fixes #613)
- Fixed VOD logo cleanup button count: The "Cleanup Unused" button now displays the total count of all unused logos across all pages instead of only counting unused logos on the current page.
- Fixed VOD refresh failures when logos are deleted: Changed logo comparisons to use `logo_id` (raw FK integer) instead of `logo` (related object) to avoid Django's lazy loading, which triggers a database fetch that fails if the referenced logo no longer exists. Also improved orphaned logo detection to properly clear stale references when logo URLs exist but logos are missing from the database.
- Fixed channel profile filtering to properly restrict content based on assigned channel profiles for all non-admin users (user_level < 10) instead of only streamers (user_level == 0). This corrects the XtreamCodes API endpoints (`get_live_categories` and `get_live_streams`) along with M3U and EPG generation, ensuring standard users (level 1) are properly restricted by their assigned channel profiles. Previously, "Standard" users with channel profiles assigned would see all channels instead of only those in their assigned profiles.
- Fixed NumPy baseline detection in Docker entrypoint. Now calls `numpy.show_config()` directly with case-insensitive grep instead of incorrectly wrapping the output.
- Fixed SettingsUtils frontend tests for new grouped settings architecture. Updated test suite to properly verify grouped JSON settings (stream_settings, dvr_settings, etc.) instead of individual CharField settings, including tests for type conversions, array-to-CSV transformations, and special handling of proxy_settings and network_access.

## [0.17.0] - 2026-01-13

### Added

- Added tooltip on filter pills showing all selected items in a vertical list (up to 10 items, with "+N more" indicator)
- Loading feedback for all confirmation dialogs: Extended visual loading indicators across all confirmation dialogs throughout the application. Delete, cleanup, and bulk operation dialogs now show an animated dots loader and disabled state during async operations, providing consistent user feedback for backups (restore/delete), channels, EPGs, logos, VOD logos, M3U accounts, streams, users, groups, filters, profiles, batch operations, and network access changes.
- Channel profile edit and duplicate functionality: Users can now rename existing channel profiles and create duplicates with automatic channel membership cloning. Each profile action (edit, duplicate, delete) in the profile dropdown for quick access.
- ProfileModal component extracted for improved code organization and maintainability of channel profile management operations.
- Frontend unit tests for pages and utilities: Added comprehensive unit test coverage for frontend components within pages/ and JS files within utils/, along with a GitHub Actions workflow (`frontend-tests.yml`) to automatically run tests on commits and pull requests - Thanks [@nick4810](https://github.com/nick4810)
- Channel Profile membership control for manual channel creation and bulk operations: Extended the existing `channel_profile_ids` parameter from `POST /api/channels/from-stream/` to also support `POST /api/channels/` (manual creation) and bulk creation tasks with the same flexible semantics:
  - Omitted parameter (default): Channels are added to ALL profiles (preserves backward compatibility)
  - Empty array `[]`: Channels are added to NO profiles
  - Sentinel value `[0]`: Channels are added to ALL profiles (explicit)
  - Specific IDs `[1, 2, ...]`: Channels are added only to the specified profiles
    This allows API consumers to control profile membership across all channel creation methods without requiring all channels to be added to every profile by default.
- Channel profile selection in creation modal: Users can now choose which profiles to add channels to when creating channels from streams (both single and bulk operations). Options include adding to all profiles, no profiles, or specific profiles with mutual exclusivity between special options ("All Profiles", "None") and specific profile selections. Profile selection defaults to the current table filter for intuitive workflow.
- Group retention policy for M3U accounts: Groups now follow the same stale retention logic as streams, using the account's `stale_stream_days` setting. Groups that temporarily disappear from an M3U source are retained for the configured retention period instead of being immediately deleted, preserving user settings and preventing data loss when providers temporarily remove/re-add groups. (Closes #809)
- Visual stale indicators for streams and groups: Added `is_stale` field to Stream and both `is_stale` and `last_seen` fields to ChannelGroupM3UAccount models to track items in their retention grace period. Stale groups display with orange buttons and a warning tooltip, while stale streams show with a red background color matching the visual treatment of empty channels.

### Changed

- Settings architecture refactored to use grouped JSON storage: Migrated from individual CharField settings to grouped JSONField settings for improved performance, maintainability, and type safety. Settings are now organized into logical groups (stream_settings, dvr_settings, backup_settings, system_settings, proxy_settings, network_access) with automatic migration handling. Backend provides helper methods (`get_stream_settings()`, `get_default_user_agent_id()`, etc.) for easy access. Frontend simplified by removing complex key mapping logic and standardizing on underscore-based field names throughout.
- Docker setup enhanced for legacy CPU support: Added `USE_LEGACY_NUMPY` environment variable to enable custom-built NumPy with no CPU baseline, allowing Dispatcharr to run on older CPUs (circa 2009) that lack support for newer baseline CPU features. When set to `true`, the entrypoint script will install the legacy NumPy build instead of the standard distribution. (Fixes #805)
- VOD upstream read timeout reduced from 30 seconds to 10 seconds to minimize lock hold time when clients disconnect during connection phase
- Form management refactored across application: Migrated Channel, Stream, M3U Profile, Stream Profile, Logo, and User Agent forms from Formik to React Hook Form (RHF) with Yup validation for improved form handling, better validation feedback, and enhanced code maintainability
- Stats and VOD pages refactored for clearer separation of concerns: extracted Stream/VOD connection cards (StreamConnectionCard, VodConnectionCard, VODCard, SeriesCard), moved page logic into dedicated utils, and lazy-loaded heavy components with ErrorBoundary fallbacks to improve readability and maintainability - Thanks [@nick4810](https://github.com/nick4810)
- Channel creation modal refactored: Extracted and unified channel numbering dialogs from StreamsTable into a dedicated CreateChannelModal component that handles both single and bulk channel creation with cleaner, more maintainable implementation and integrated profile selection controls.

### Fixed

- Fixed bulk channel profile membership update endpoint silently ignoring channels without existing membership records. The endpoint now creates missing memberships automatically (matching single-channel endpoint behavior), validates that all channel IDs exist before processing, and provides detailed response feedback including counts of updated vs. created memberships. Added comprehensive Swagger documentation with request/response schemas.
- Fixed bulk channel edit endpoint crashing with `ValueError: Field names must be given to bulk_update()` when the first channel in the update list had no actual field changes. The endpoint now collects all unique field names from all channels being updated instead of only looking at the first channel, properly handling cases where different channels update different fields or when some channels have no changes - Thanks [@mdellavo](https://github.com/mdellavo) (Fixes #804)
- Fixed PostgreSQL backup restore not completely cleaning database before restoration. The restore process now drops and recreates the entire `public` schema before running `pg_restore`, ensuring a truly clean restore that removes all tables, functions, and other objects not present in the backup file. This prevents leftover database objects from persisting when restoring backups from older branches or versions. Added `--no-owner` flag to `pg_restore` to avoid role permission errors when the backup was created by a different PostgreSQL user.
- Fixed TV Guide loading overlay not disappearing after navigating from DVR page. The `fetchRecordings()` function in the channels store was setting `isLoading: true` on start but never resetting it to `false` on successful completion, causing the Guide page's loading overlay to remain visible indefinitely when accessed after the DVR page.
- Fixed stream profile parameters not properly handling quoted arguments. Switched from basic `.split()` to `shlex.split()` for parsing command-line parameters, allowing proper handling of multi-word arguments in quotes (e.g., OAuth tokens in HTTP headers like `"--twitch-api-header=Authorization=OAuth token123"`). This ensures external streaming tools like Streamlink and FFmpeg receive correctly formatted arguments when using stream profiles with complex parameters - Thanks [@justinforlenza](https://github.com/justinforlenza) (Fixes #833)
- Fixed bulk and manual channel creation not refreshing channel profile memberships in the UI for all connected clients. WebSocket `channels_created` event now calls `fetchChannelProfiles()` to ensure profile membership updates are reflected in real-time for all users without requiring a page refresh.
- Fixed Channel Profile filter incorrectly applying profile membership filtering even when "Show Disabled" was enabled, preventing all channels from being displayed. Profile filter now only applies when hiding disabled channels. (Fixes #825)
- Fixed manual channel creation not adding channels to channel profiles. Manually created channels are now added to the selected profile if one is active, or to all profiles if "All" is selected, matching the behavior of channels created from streams.
- Fixed VOD streams disappearing from stats page during playback by adding `socket-timeout = 600` to production uWSGI config. The missing directive caused uWSGI to use its default 4-second timeout, triggering premature cleanup when clients buffered content. Now matches the existing `http-timeout = 600` value and prevents timeout errors during normal client buffering - Thanks [@patchy8736](https://github.com/patchy8736)
- Fixed Channels table EPG column showing "Not Assigned" on initial load for users with large EPG datasets. Added `tvgsLoaded` flag to EPG store to track when EPG data has finished loading, ensuring the table waits for EPG data before displaying. EPG cells now show animated skeleton placeholders while loading instead of incorrectly showing "Not Assigned". (Fixes #810)
- Fixed VOD profile connection count not being decremented when stream connection fails (timeout, 404, etc.), preventing profiles from reaching capacity limits and rejecting valid stream requests
- Fixed React warning in Channel form by removing invalid `removeTrailingZeros` prop from NumberInput component
- Release workflow Docker tagging: Fixed issue where `latest` and version tags (e.g., `0.16.0`) were creating separate manifests instead of pointing to the same image digest, which caused old `latest` tags to become orphaned/untagged after new releases. Now creates a single multi-arch manifest with both tags, maintaining proper tag relationships and download statistics visibility on GitHub.
- Fixed onboarding message appearing in the Channels Table when filtered results are empty. The onboarding message now only displays when there are no channels created at all, not when channels exist but are filtered out by current filters.
- Fixed `M3UMovieRelation.get_stream_url()` and `M3UEpisodeRelation.get_stream_url()` to use XC client's `_normalize_url()` method instead of simple `rstrip('/')`. This properly handles malformed M3U account URLs (e.g., containing `/player_api.php` or query parameters) before constructing VOD stream endpoints, matching behavior of live channel URL building. (Closes #722)
- Fixed bulk_create and bulk_update errors during VOD content refresh by pre-checking object existence with optimized bulk queries (3 queries total instead of N per batch) before creating new objects. This ensures all movie/series objects have primary keys before relation operations, preventing "prohibited to prevent data loss due to unsaved related object" errors. Additionally fixed duplicate key constraint violations by treating TMDB/IMDB ID values of `0` or `'0'` as invalid (some providers use this to indicate "no ID"), converting them to NULL to prevent multiple items from incorrectly sharing the same ID. (Fixes #813)

## [0.16.0] - 2026-01-04

### Added

- Advanced filtering for Channels table: Filter menu now allows toggling disabled channels visibility (when a profile is selected) and filtering to show only empty channels without streams (Closes #182)
- Network Access warning modal now displays the client's IP address for better transparency when network restrictions are being enforced - Thanks [@damien-alt-sudo](https://github.com/damien-alt-sudo) (Closes #778)
- VLC streaming support - Thanks [@sethwv](https://github.com/sethwv)
  - Added `cvlc` as an alternative streaming backend alongside FFmpeg and Streamlink
  - Log parser refactoring: Introduced `LogParserFactory` and stream-specific parsers (`FFmpegLogParser`, `VLCLogParser`, `StreamlinkLogParser`) to enable codec and resolution detection from multiple streaming tools
  - VLC log parsing for stream information: Detects video/audio codecs from TS demux output, supports both stream-copy and transcode modes with resolution/FPS extraction from transcode output
  - Locked, read-only VLC stream profile configured for headless operation with intelligent audio/video codec detection
  - VLC and required plugins installed in Docker environment with headless configuration
- ErrorBoundary component for handling frontend errors gracefully with generic error message - Thanks [@nick4810](https://github.com/nick4810)

### Changed

- Fixed event viewer arrow direction (previously inverted) — UI behavior corrected. - Thanks [@drnikcuk](https://github.com/drnikcuk) (Closes #772)
- Region code options now intentionally include both `GB` (ISO 3166-1 standard) and `UK` (commonly used by EPG/XMLTV providers) to accommodate real-world EPG data variations. Many providers use `UK` in channel identifiers (e.g., `BBCOne.uk`) despite `GB` being the official ISO country code. Users should select the region code that matches their specific EPG provider's convention for optimal region-based EPG matching bonuses - Thanks [@bigpandaaaa](https://github.com/bigpandaaaa)
- Channel number inputs in stream-to-channel creation modals no longer have a maximum value restriction, allowing users to enter any valid channel number supported by the database
- Stream log parsing refactored to use factory pattern: Simplified `ChannelService.parse_and_store_stream_info()` to route parsing through specialized log parsers instead of inline program-specific logic (~150 lines of code removed)
- Stream profile names in fixtures updated to use proper capitalization (ffmpeg → FFmpeg, streamlink → Streamlink)
- Frontend component refactoring for improved code organization and maintainability - Thanks [@nick4810](https://github.com/nick4810)
  - Extracted large nested components into separate files (RecordingCard, RecordingDetailsModal, RecurringRuleModal, RecordingSynopsis, GuideRow, HourTimeline, PluginCard, ProgramRecordingModal, SeriesRecordingModal, Field)
  - Moved business logic from components into dedicated utility files (dateTimeUtils, RecordingCardUtils, RecordingDetailsModalUtils, RecurringRuleModalUtils, DVRUtils, guideUtils, PluginsUtils, PluginCardUtils, notificationUtils)
  - Lazy loaded heavy components (SuperuserForm, RecordingDetailsModal, ProgramRecordingModal, SeriesRecordingModal, PluginCard) with loading fallbacks
  - Removed unused Dashboard and Home pages
  - Guide page refactoring: Extracted GuideRow and HourTimeline components, moved grid calculations and utility functions to guideUtils.js, added loading states for initial data fetching, improved performance through better memoization
  - Plugins page refactoring: Extracted PluginCard and Field components, added Zustand store for plugin state management, improved plugin action confirmation handling, better separation of concerns between UI and business logic
- Logo loading optimization: Logos now load only after both Channels and Streams tables complete loading to prevent blocking initial page render, with rendering gated by table readiness to ensure data loads before visual elements
- M3U stream URLs now use `build_absolute_uri_with_port()` for consistency with EPG and logo URLs, ensuring uniform port handling across all M3U file URLs
- Settings and Logos page refactoring for improved readability and separation of concerns - Thanks [@nick4810](https://github.com/nick4810)
  - Extracted individual settings forms (DVR, Network Access, Proxy, Stream, System, UI) into separate components with dedicated utility files
  - Moved larger nested components into their own files
  - Moved business logic into corresponding utils/ files
  - Extracted larger in-line component logic into its own function
  - Each panel in Settings now uses its own form state with the parent component handling active state management

### Fixed

- Auto Channel Sync Force EPG Source feature not properly forcing "No EPG" assignment - When selecting "Force EPG Source" > "No EPG (Disabled)", channels were still being auto-matched to EPG data instead of forcing dummy/no EPG. Now correctly sets `force_dummy_epg` flag to prevent unwanted EPG assignment. (Fixes #788)
- VOD episode processing now properly handles season and episode numbers from APIs that return string values instead of integers, with comprehensive error logging to track data quality issues - Thanks [@patchy8736](https://github.com/patchy8736) (Fixes #770)
- VOD episode-to-stream relations are now validated to ensure episodes have been saved to the database before creating relations, preventing integrity errors when bulk_create operations encounter conflicts - Thanks [@patchy8736](https://github.com/patchy8736)
- VOD category filtering now correctly handles category names containing pipe "|" characters (e.g., "PL | BAJKI", "EN | MOVIES") by using `rsplit()` to split from the right instead of the left, ensuring the category type is correctly extracted as the last segment - Thanks [@Vitekant](https://github.com/Vitekant)
- M3U and EPG URLs now correctly preserve non-standard HTTPS ports (e.g., `:8443`) when accessed behind reverse proxies that forward the port in headers — `get_host_and_port()` now properly checks `X-Forwarded-Port` header before falling back to other detection methods (Fixes #704)
- M3U and EPG manager page no longer crashes when a playlist references a deleted channel group (Fixes screen blank on navigation)
- Stream validation now returns original URL instead of redirected URL to prevent issues with temporary redirect URLs that expire before clients can connect
- XtreamCodes EPG limit parameter now properly converted to integer to prevent type errors when accessing EPG listings (Fixes #781)
- Docker container file permissions: Django management commands (`migrate`, `collectstatic`) now run as the non-root user to prevent root-owned `__pycache__` and static files from causing permission issues - Thanks [@sethwv](https://github.com/sethwv)
- Stream validation now continues with GET request if HEAD request fails due to connection issues - Thanks [@kvnnap](https://github.com/kvnnap) (Fixes #782)
- XtreamCodes M3U files now correctly set `x-tvg-url` and `url-tvg` headers to reference XC EPG URL (`xmltv.php`) instead of standard EPG endpoint when downloaded via XC API (Fixes #629)

## [0.15.1] - 2025-12-22

### Fixed

- XtreamCodes EPG `has_archive` field now returns integer `0` instead of string `"0"` for proper JSON type consistency
- nginx now gracefully handles hosts without IPv6 support by automatically disabling IPv6 binding at startup (Fixes #744)

## [0.15.0] - 2025-12-20

### Added

- VOD client stop button in Stats page: Users can now disconnect individual VOD clients from the Stats view, similar to the existing channel client disconnect functionality.
- Automated configuration backup/restore system with scheduled backups, retention policies, and async task processing - Thanks [@stlalpha](https://github.com/stlalpha) (Closes #153)
- Stream group as available hash option: Users can now select 'Group' as a hash key option in Settings → Stream Settings → M3U Hash Key, allowing streams to be differentiated by their group membership in addition to name, URL, TVG-ID, and M3U ID

### Changed

- Initial super user creation page now matches the login page design with logo, welcome message, divider, and version display for a more consistent and polished first-time setup experience
- Removed unreachable code path in m3u output - Thanks [@DawtCom](https://github.com/DawtCom)
- GitHub Actions workflows now use `docker/metadata-action` for cleaner and more maintainable OCI-compliant image label generation across all build pipelines (ci.yml, base-image.yml, release.yml). Labels are applied to both platform-specific images and multi-arch manifests with proper annotation formatting. - Thanks [@mrdynamo]https://github.com/mrdynamo) (Closes #724)
- Update docker/dev-build.sh to support private registries, multiple architectures and pushing. Now you can do things like `dev-build.sh  -p -r my.private.registry -a linux/arm64,linux/amd64` - Thanks [@jdblack](https://github.com/jblack)
- Updated dependencies: Django (5.2.4 → 5.2.9) includes CVE security patch, psycopg2-binary (2.9.10 → 2.9.11), celery (5.5.3 → 5.6.0), djangorestframework (3.16.0 → 3.16.1), requests (2.32.4 → 2.32.5), psutil (7.0.0 → 7.1.3), gevent (25.5.1 → 25.9.1), rapidfuzz (3.13.0 → 3.14.3), torch (2.7.1 → 2.9.1), sentence-transformers (5.1.0 → 5.2.0), lxml (6.0.0 → 6.0.2) (Closes #662)
- Frontend dependencies updated: Vite (6.2.0 → 7.1.7), ESLint (9.21.0 → 9.27.0), and related packages; added npm `overrides` to enforce js-yaml@^4.1.1 for transitive security fix. All 6 reported vulnerabilities resolved with `npm audit fix`.
- Floating video player now supports resizing via a drag handles, with minimum size enforcement and viewport/page boundary constraints to keep it visible.
- Redis connection settings now fully configurable via environment variables (`REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_URL`), replacing hardcoded `localhost:6379` values throughout the codebase. This enables use of external Redis services in production deployments. (Closes #762)
- Celery broker and result backend URLs now respect `REDIS_HOST`/`REDIS_PORT`/`REDIS_DB` settings as defaults, with `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` environment variables available for override.

### Fixed

- Docker init script now validates DISPATCHARR_PORT is an integer before using it, preventing sed errors when Kubernetes sets it to a service URL like `tcp://10.98.37.10:80`. Falls back to default port 9191 when invalid (Fixes #737)
- M3U Profile form now properly resets local state for search and replace patterns after saving, preventing validation errors when adding multiple profiles in a row
- DVR series rule deletion now properly handles TVG IDs that contain slashes by encoding them in the URL path (Fixes #697)
- VOD episode processing now correctly handles duplicate episodes (same episode in multiple languages/qualities) by reusing Episode records across multiple M3UEpisodeRelation entries instead of attempting to create duplicates (Fixes #556)
- XtreamCodes series streaming endpoint now correctly handles episodes with multiple streams (different languages/qualities) by selecting the best available stream based on account priority (Fixes #569)
- XtreamCodes series info API now returns unique episodes instead of duplicate entries when multiple streams exist for the same episode (different languages/qualities)
- nginx now gracefully handles hosts without IPv6 support by automatically disabling IPv6 binding at startup (Fixes #744)
- XtreamCodes EPG API now returns correct date/time format for start/end fields and proper string types for timestamps and channel_id
- XtreamCodes EPG API now handles None values for title and description fields to prevent AttributeError
- XtreamCodes EPG `id` field now provides unique identifiers per program listing instead of always returning "0" for better client EPG handling
- XtreamCodes EPG `epg_id` field now correctly returns the EPGData record ID (representing the EPG source/channel mapping) instead of a dummy value

## [0.14.0] - 2025-12-09

### Added

- Sort buttons for 'Group' and 'M3U' columns in Streams table for improved stream organization and filtering - Thanks [@bobey6](https://github.com/bobey6)
- EPG source priority field for controlling which EPG source is preferred when multiple sources have matching entries for a channel (higher numbers = higher priority) (Closes #603)

### Changed

- EPG program parsing optimized for sources with many channels but only a fraction mapped. Now parses XML file once per source instead of once per channel, dramatically reducing I/O and CPU overhead. For sources with 10,000 channels and 100 mapped, this results in ~99x fewer file opens and ~100x fewer full file scans. Orphaned programs for unmapped channels are also cleaned up during refresh to prevent database bloat. Database updates are now atomic to prevent clients from seeing empty/partial EPG data during refresh.
- EPG table now displays detailed status messages including refresh progress, success messages, and last message for idle sources (matching M3U table behavior) (Closes #214)
- IPv6 access now allowed by default with all IPv6 CIDRs accepted - Thanks [@adrianmace](https://github.com/adrianmace)
- nginx.conf updated to bind to both IPv4 and IPv6 ports - Thanks [@jordandalley](https://github.com/jordandalley)
- EPG matching now respects source priority and only uses active (enabled) EPG sources (Closes #672)
- EPG form API Key field now only visible when Schedules Direct source type is selected

### Fixed

- EPG table "Updated" column now updates in real-time via WebSocket using the actual backend timestamp instead of requiring a page refresh
- Bulk channel editor confirmation dialog now displays the correct stream profile name that will be applied to the selected channels.
- uWSGI not found and 502 bad gateway on first startup

## [0.13.1] - 2025-12-06

### Fixed

- JWT token generated so is unique for each deployment

## [0.13.0] - 2025-12-02

### Added

- `CHANGELOG.md` file following Keep a Changelog format to document all notable changes and project history
- System event logging and viewer: Comprehensive logging system that tracks internal application events (M3U refreshes, EPG updates, stream switches, errors) with a dedicated UI viewer for filtering and reviewing historical events. Improves monitoring, troubleshooting, and understanding system behavior
- M3U/EPG endpoint caching: Implements intelligent caching for frequently requested M3U playlists and EPG data to reduce database load and improve response times for clients.
- Search icon to name headers for the channels and streams tables (#686)
- Comprehensive logging for user authentication events and network access restrictions
- Validation for EPG objects and payloads in updateEPG functions to prevent errors from invalid data
- Referrerpolicy to YouTube iframes in series and VOD modals for better compatibility

### Changed

- XC player API now returns server_info for unknown actions to align with provider behavior
- XC player API refactored to streamline action handling and ensure consistent responses
- Date parsing logic in generate_custom_dummy_programs improved to handle empty or invalid inputs
- DVR cards now reflect date and time formats chosen by user - Thanks [@Biologisten](https://github.com/Biologisten)
- "Uncategorized" categories and relations now automatically created for VOD accounts to improve content management (#627)
- Improved minimum horizontal size in the stats page for better usability on smaller displays
- M3U and EPG generation now handles missing channel profiles with appropriate error logging

### Fixed

- Episode URLs in series modal now use UUID instead of ID, fixing broken links (#684, #694)
- Stream preview now respects selected M3U profile instead of always using default profile (#690)
- Channel groups filter in M3UGroupFilter component now filters out non-existent groups (prevents blank webui when editing M3U after a group was removed)
- Stream order now preserved in PATCH/PUT responses from ChannelSerializer, ensuring consistent ordering across all API operations - Thanks [@FiveBoroughs](https://github.com/FiveBoroughs) (#643)
- XC client compatibility: float channel numbers now converted to integers
- M3U account and profile modals now scrollable on mobile devices for improved usability

## [0.12.0] - 2025-11-19

### Added

- RTSP stream support with automatic protocol detection when a proxy profile requires it. The proxy now forces FFmpeg for RTSP sources and properly handles RTSP URLs - Thanks [@ragchuck](https://github.com/ragchuck) (#184)
- UDP stream support, including correct handling when a proxy profile specifies a UDP source. The proxy now skips HTTP-specific headers (like `user_agent`) for non-HTTP protocols and performs manual redirect handling to improve reliability (#617)
- Separate VOD logos system with a new `VODLogo` model, database migration, dedicated API/viewset, and server-paginated UI. This separates movie/series logos from channel logos, making cleanup safer and enabling independent bulk operations

### Changed

- Background profile refresh now uses a rate-limiting/backoff strategy to avoid provider bans
- Bulk channel editing now validates all requested changes up front and applies updates in a single database transaction
- ProxyServer shutdown & ghost-client handling improved to avoid initializing channels for transient clients and prevent duplicate reinitialization during rapid reconnects
- URL / Stream validation expanded to support credentials on non-FQDN hosts, skips HTTP-only checks for RTSP/RTP/UDP streams, and improved host/port normalization
- TV guide scrolling & timeline synchronization improved with mouse-wheel scrolling, synchronized timeline position with guide navigation, and improved mobile momentum scrolling (#252)
- EPG Source dropdown now sorts alphabetically - Thanks [@0x53c65c0a8bd30fff](https://github.com/0x53c65c0a8bd30fff)
- M3U POST handling restored and improved for clients (e.g., Smarters) that request playlists using HTTP POST - Thanks [@maluueu](https://github.com/maluueu)
- Login form revamped with branding, cleaner layout, loading state, "Remember Me" option, and focused sign-in flow
- Series & VOD now have copy-link buttons in modals for easier URL sharing
- `get_host_and_port` now prioritizes verified port sources and handles reverse-proxy edge cases more accurately (#618)

### Fixed

- EXTINF parsing overhauled to correctly extract attributes such as `tvg-id`, `tvg-name`, and `group-title`, even when values include quotes or commas (#637)
- Websocket payload size reduced during EPG processing to avoid UI freezes, blank screens, or memory spikes in the browser (#327)
- Logo management UI fixes including confirmation dialogs, header checkbox reset, delete button reliability, and full client refetch after cleanup

## [0.11.2] - 2025-11-04

### Added

- Custom Dummy EPG improvements:
  - Support for using an existing Custom Dummy EPG as a template for creating new EPGs
  - Custom fallback templates for unmatched patterns
  - `{endtime}` as an available output placeholder and renamed `{time}` → `{starttime}` (#590)
  - Support for date placeholders that respect both source and output timezones (#597)
  - Ability to bulk assign Custom Dummy EPGs to multiple channels
  - "Include New Tag" option to mark programs as new in Dummy EPG output
  - Support for month strings in date parsing
  - Ability to set custom posters and channel logos via regex patterns for Custom Dummy EPGs
  - Improved DST handling by calculating offsets based on the actual program date, not today's date

### Changed

- Stream model maximum URL length increased from 2000 to 4096 characters (#585)
- Groups now sorted during `xc_get_live_categories` based on the order they first appear (by lowest channel number)
- Client TTL settings updated and periodic refresh implemented during active streaming to maintain accurate connection tracking
- `ProgramData.sub_title` field changed from `CharField` to `TextField` to allow subtitles longer than 255 characters (#579)
- Startup improved by verifying `/data` directory ownership and automatically fixing permissions if needed. Pre-creates `/data/models` during initialization (#614)
- Port detection enhanced to check `request.META.get("SERVER_PORT")` before falling back to defaults, ensuring correct port when generating M3U, EPG, and logo URLs - Thanks [@lasharor](https://github.com/lasharor)

### Fixed

- Custom Dummy EPG frontend DST calculation now uses program date instead of current date
- Channel titles no longer truncated early after an apostrophe - Thanks [@0x53c65c0a8bd30fff](https://github.com/0x53c65c0a8bd30fff)

## [0.11.1] - 2025-10-22

### Fixed

- uWSGI not receiving environmental variables
- LXC unable to access daemons launched by uWSGI ([#575](https://github.com/Dispatcharr/Dispatcharr/issues/575), [#576](https://github.com/Dispatcharr/Dispatcharr/issues/576), [#577](https://github.com/Dispatcharr/Dispatcharr/issues/577))

## [0.11.0] - 2025-10-22

### Added

- Custom Dummy EPG system:
  - Regex pattern matching and name source selection
  - Support for custom upcoming and ended programs
  - Timezone-aware with source and local timezone selection
  - Option to include categories and date/live tags in Dummy EPG output
  - (#293)
- Auto-Enable & Category Improvements:
  - Auto-enable settings for new groups and categories in M3U and VOD components (#208)
- IPv6 CIDR validation in Settings - Thanks [@jordandalley](https://github.com/jordandalley) (#236)
- Custom logo support for channel groups in Auto Sync Channels (#555)
- Tooltips added to the Stream Table

### Changed

- Celery and uWSGI now have configurable `nice` levels (defaults: `uWSGI=0`, `Celery=5`) to prioritize streaming when needed. (#571)
- Directory creation and ownership management refactored in init scripts to avoid unnecessary recursive `chown` operations and improve boot speed
- HTTP streamer switched to threaded model with piped output for improved robustness
- Chunk timeout configuration improved and StreamManager timeout handling enhanced
- Proxy timeout values reduced to avoid unnecessary waiting
- Resource cleanup improved to prevent "Too many open files" errors
- Proxy settings caching implemented and database connections properly closed after use
- EPG program fetching optimized with chunked retrieval and explicit ordering to reduce memory usage during output
- EPG output now sorted by channel number for consistent presentation
- Stream Table buttons reordered for better usability
- Database connection handling improved throughout the codebase to reduce overall connection count

### Fixed

- Crash when resizing columns in the Channel Table (#516)
- Errors when saving stream settings (#535)
- Preview and edit bugs for custom streams where profile and group selections did not display correctly
- `channel_id` and `channel.uuid` now converted to strings before processing to fix manual switching when the uWSGI worker was not the stream owner (#269)
- Stream locking and connection search issues when switching channels; increased search timeout to reduce premature failures (#503)
- Stream Table buttons no longer shift into multiple rows when selecting many streams
- Custom stream previews
- Custom Stream settings not loading properly (#186)
- Orphaned categories now automatically removed for VOD and Series during M3U refresh (#540)

## [0.10.4] - 2025-10-08

### Added

- "Assign TVG-ID from EPG" functionality with frontend actions for single-channel and batch operations
- Confirmation dialogs in `ChannelBatchForm` for setting names, logos, TVG-IDs, and clearing EPG assignments
- "Clear EPG" button to `ChannelBatchForm` for easy reset of assignments
- Batch editing of channel logos - Thanks [@EmeraldPi](https://github.com/EmeraldPi)
- Ability to set logo name from URL - Thanks [@EmeraldPi](https://github.com/EmeraldPi)
- Proper timestamp tracking for channel creation and updates; `XC Get Live Streams` now uses this information
- Time Zone Settings added to the application ([#482](https://github.com/Dispatcharr/Dispatcharr/issues/482), [#347](https://github.com/Dispatcharr/Dispatcharr/issues/347))
- Comskip settings support including comskip.ini upload and custom directory selection (#418)
- Manual recording scheduling for channels without EPG data (#162)

### Changed

- Default M3U account type is now set to XC for new accounts
- Performance optimization: Only fetch playlists and channel profiles after a successful M3U refresh (rather than every status update)
- Playlist retrieval now includes current connection counts and improved session handling during VOD session start
- Improved stream selection logic when all profiles have reached max connections (retries faster)

### Fixed

- Large EPGs now fully parse all channels
- Duplicate channel outputs for streamer profiles set to "All"
- Streamer profiles with "All" assigned now receive all eligible channels
- PostgreSQL btree index errors from logo URL validation during channel creation (#519)
- M3U processing lock not releasing when no streams found during XC refresh, which also skipped VOD scanning (#449)
- Float conversion errors by normalizing decimal format during VOD scanning (#526)
- Direct URL ordering in M3U output to use correct stream sequence (#528)
- Adding multiple M3U accounts without refreshing modified only the first entry (#397)
- UI state bug where new playlist creation was not notified to frontend ("Fetching Groups" stuck)
- Minor FFmpeg task and stream termination bugs in DVR module
- Input escaping issue where single quotes were interpreted as code delimiters (#406)

## [0.10.3] - 2025-10-04

### Added

- Logo management UI improvements where Channel editor now uses the Logo Manager modal, allowing users to add logos by URL directly from the edit form - Thanks [@EmeraldPi](https://github.com/EmeraldPi)

### Changed

- FFmpeg base container rebuilt with improved native build support - Thanks [@EmeraldPi](https://github.com/EmeraldPi)
- GitHub Actions workflow updated to use native runners instead of QEMU emulation for more reliable multi-architecture builds

### Fixed

- EPG parsing stability when large EPG files would not fully parse all channels. Parser now uses `iterparse` with `recover=True` for both channel and program-level parsing, ensuring complete and resilient XML processing even when Cloudflare injects additional root elements

## [0.10.2] - 2025-10-03

### Added

- `m3u_id` parameter to `generate_hash_key` and updated related calls
- Support for `x-tvg-url` and `url-tvg` generation with preserved query parameters (#345)
- Exact Gracenote ID matching for EPG channel mapping (#291)
- Recovery handling for XMLTV parser errors
- `nice -n 5` added to Celery commands for better process priority management

### Changed

- Default M3U hash key changed to URL only for new installs
- M3U profile retrieval now includes current connection counts and improved session handling during VOD session start
- Improved stream selection logic when all profiles have reached max connections (retries faster)
- XMLTV parsing refactored to use `iterparse` for `<tv>` element
- Release workflow refactored to run on native architecture
- Docker build system improvements:
  - Split install/build steps
  - Switch from Yarn → NPM
  - Updated to Node.js 24 (frontend build)
  - Improved ARM build reliability
  - Pushes to DockerHub with combined manifest
  - Removed redundant tags and improved build organization

### Fixed

- Cloudflare-hosted EPG feeds breaking parsing (#497)
- Bulk channel creation now preserves the order channels were selected in (no longer reversed)
- M3U hash settings not saving properly
- VOD selecting the wrong M3U profile at session start (#461)
- Redundant `h` removed from 12-hour time format in settings page

## [0.10.1] - 2025-09-24

### Added

- Virtualized rendering for TV Guide for smoother performance when displaying large guides - Thanks [@stlalpha](https://github.com/stlalpha) (#438)
- Enhanced channel/program mapping to reuse EPG data across multiple channels that share the same TVG-ID

### Changed

- `URL` field length in EPGSource model increased from 200 → 1000 characters to support long URLs with tokens
- Improved URL transformation logic with more advanced regex during profile refreshes
- During EPG scanning, the first display name for a channel is now used instead of the last
- `whiteSpace` style changed from `nowrap` → `pre` in StreamsTable for better text formatting

### Fixed

- EPG channel parsing failure when channel `URL` exceeded 500 characters by adding validation during scanning (#452)
- Frontend incorrectly saving case-sensitive setting as a JSON string for stream filters

## [0.10.0] - 2025-09-18

### Added

- Channel Creation Improvements:
  - Ability to specify channel number during channel creation ([#377](https://github.com/Dispatcharr/Dispatcharr/issues/377), [#169](https://github.com/Dispatcharr/Dispatcharr/issues/169))
  - Asynchronous bulk channel creation from stream IDs with WebSocket progress updates
  - WebSocket notifications when channels are created
- EPG Auto-Matching (Rewritten & Enhanced):
  - Completely refactored for improved accuracy and efficiency
  - Can now be applied to selected channels or triggered directly from the channel edit form
  - Uses stricter matching logic with support from sentence transformers
  - Added progress notifications during the matching process
  - Implemented memory cleanup for ML models after matching operations
  - Removed deprecated matching scripts
- Logo & EPG Management:
  - Ability in channel edit form and bulk channel editor to set logos and names from assigned EPG (#157)
  - Improved logo update flow: frontend refreshes on changes, store updates after bulk changes, progress shown via notifications
- Table Enhancements:
  - All tables now support adjustable column resizing (#295)
  - Channels and Streams tables persist column widths and center divider position to local storage
  - Improved sizing and layout for user-agents, stream profiles, logos, M3U, and EPG tables

### Changed

- Simplified VOD and series access: removed user-level restrictions on M3U accounts
- Skip disabled M3U accounts when choosing streams during playback (#402)
- Enhanced `UserViewSet` queryset to prefetch related channel profiles for better performance
- Auto-focus added to EPG filter input
- Category API retrieval now sorts by name
- Increased default column size for EPG fields and removed max size on group/EPG columns
- Standardized EPG column header to display `(EPG ID - TVG-ID)`

### Fixed

- Bug during VOD cleanup where all VODs not from the current M3U scan could be deleted
- Logos not being set correctly in some cases
- Bug where not setting a channel number caused an error when creating a channel (#422)
- Bug where clicking "Add Channel" with a channel selected opened the edit form instead
- Bug where a newly created channel could reuse streams from another channel due to form not clearing properly
- VOD page not displaying correct order while changing pages
- `ReferenceError: setIsInitialized is not defined` when logging into web UI
- `cannot access local variable 'total_chunks' where it is not associated with a value` during VOD refresh

## [0.9.1] - 2025-09-13

### Fixed

- Broken migrations affecting the plugins system
- DVR and plugin paths to ensure proper functionality (#381)

## [0.9.0] - 2025-09-12

### Added

- **Video on Demand (VOD) System:**
  - Complete VOD infrastructure with support for movies and TV series
  - Advanced VOD metadata including IMDB/TMDB integration, trailers, cast information
  - Smart VOD categorization with filtering by type (movies vs series)
  - Multi-provider VOD support with priority-based selection
  - VOD streaming proxy with connection tracking and statistics
  - Season/episode organization for TV series with expandable episode details
  - VOD statistics and monitoring integrated with existing stats dashboard
  - Optimized VOD parsing and category filtering
  - Dedicated VOD page with movies and series tabs
  - Rich VOD modals with backdrop images, trailers, and metadata
  - Episode management with season-based organization
  - Play button integration with external player support
  - VOD statistics cards similar to channel cards
- **Plugin System:**
  - Extensible Plugin Framework - Developers can build custom functionality without modifying Dispatcharr core
  - Plugin Discovery & Management - Automatic detection of installed plugins, with enable/disable controls in the UI
  - Backend API Support - New APIs for listing, loading, and managing plugins programmatically
  - Plugin Registry - Structured models for plugin metadata (name, version, author, description)
  - UI Enhancements - Dedicated Plugins page in the admin panel for centralized plugin management
  - Documentation & Scaffolding - Initial documentation and scaffolding to accelerate plugin development
- **DVR System:**
  - Refreshed DVR page for managing scheduled and completed recordings
  - Global pre/post padding controls surfaced in Settings
  - Playback support for completed recordings directly in the UI
  - DVR table view includes title, channel, time, and padding adjustments for clear scheduling
  - Improved population of DVR listings, fixing intermittent blank screen issues
  - Comskip integration for automated commercial detection and skipping in recordings
  - User-configurable comskip toggle in Settings
- **Enhanced Channel Management:**
  - EPG column added to channels table for better organization
  - EPG filtering by channel assignment and source name
  - Channel batch renaming for efficient bulk channel name updates
  - Auto channel sync improvements with custom stream profile override
  - Channel logo management overhaul with background loading
- Date and time format customization in settings - Thanks [@Biologisten](https://github.com/Biologisten)
- Auto-refresh intervals for statistics with better UI controls
- M3U profile notes field for better organization
- XC account information retrieval and display with account refresh functionality and notifications

### Changed

- JSONB field conversion for custom properties (replacing text fields) for better performance
- Database encoding converted from ASCII to UTF8 for better character support
- Batch processing for M3U updates and channel operations
- Query optimization with prefetch_related to eliminate N+1 queries
- Reduced API calls by fetching all data at once instead of per-category
- Buffering speed setting now affects UI indicators
- Swagger endpoint accessible with or without trailing slash
- EPG source names displayed before channel names in edit forms
- Logo loading improvements with background processing
- Channel card enhancements with better status indicators
- Group column width optimization
- Better content-type detection for streams
- Improved headers with content-range and total length
- Enhanced user-agent handling for M3U accounts
- HEAD request support with connection keep-alive
- Progress tracking improvements for clients with new sessions
- Server URL length increased to 1000 characters for token support
- Prettier formatting applied to all frontend code
- String quote standardization and code formatting improvements

### Fixed

- Logo loading issues in channel edit forms resolved
- M3U download error handling and user feedback improved
- Unique constraint violations fixed during stream rehashing
- Channel stats fetching moved from Celery beat task to configurable API calls
- Speed badge colors now use configurable buffering speed setting
- Channel cards properly close when streams stop
- Active streams labeling updated from "Active Channels"
- WebSocket updates for client connect/disconnect events
- Null value handling before database saves
- Empty string scrubbing for cleaner data
- Group relationship cleanup for removed M3U groups
- Logo cleanup for unused files with proper batch processing
- Recordings start 5 mins after show starts (#102)

### Closed

- [#350](https://github.com/Dispatcharr/Dispatcharr/issues/350): Allow DVR recordings to be played via the UI
- [#349](https://github.com/Dispatcharr/Dispatcharr/issues/349): DVR screen doesn't populate consistently
- [#340](https://github.com/Dispatcharr/Dispatcharr/issues/340): Global find and replace
- [#311](https://github.com/Dispatcharr/Dispatcharr/issues/311): Stat's "Current Speed" does not reflect "Buffering Speed" setting
- [#304](https://github.com/Dispatcharr/Dispatcharr/issues/304): Name ignored when uploading logo
- [#300](https://github.com/Dispatcharr/Dispatcharr/issues/300): Updating Logo throws error
- [#286](https://github.com/Dispatcharr/Dispatcharr/issues/286): 2 Value/Column EPG in Channel Edit
- [#280](https://github.com/Dispatcharr/Dispatcharr/issues/280): Add general text field in M3U/XS profiles
- [#190](https://github.com/Dispatcharr/Dispatcharr/issues/190): Show which stream is being used and allow it to be altered in channel properties
- [#155](https://github.com/Dispatcharr/Dispatcharr/issues/155): Additional column with EPG assignment information / Allow filtering by EPG assignment
- [#138](https://github.com/Dispatcharr/Dispatcharr/issues/138): Bulk Channel Edit Functions

## [0.8.0] - 2025-08-19

### Added

- Channel & Stream Enhancements:
  - Preview streams under a channel, with stream logo and name displayed in the channel card
  - Advanced stats for channel streams
  - Stream qualities displayed in the channel table
  - Stream stats now saved to the database
  - URL badges can now be clicked to copy stream links to the clipboard
- M3U Filtering for Streams:
  - Streams for an M3U account can now be filtered using flexible parameters
  - Apply filters based on stream name, group title, or stream URL (via regex)
  - Filters support both inclusion and exclusion logic for precise control
  - Multiple filters can be layered with a priority order for complex rules
- Ability to reverse the sort order for auto channel sync
- Custom validator for URL fields now allows non-FQDN hostnames (#63)
- Membership creation added in `UpdateChannelMembershipAPIView` if not found (#275)

### Changed

- Bumped Postgres to version 17
- Updated dependencies in `requirements.txt` for compatibility and improvements
- Improved chunked extraction to prevent memory issues - Thanks [@pantherale0](https://github.com/pantherale0)

### Fixed

- XML escaping for channel ID in `generate_dummy_epg` function
- Bug where creating a channel from a stream not displayed in the table used an invalid stream name
- Debian install script - Thanks [@deku-m](https://github.com/deku-m)

## [0.7.1] - 2025-07-29

### Added

- Natural sorting for channel names during auto channel sync
- Ability to sort auto sync order by provider order (default), channel name, TVG ID, or last updated time
- Auto-created channels can now be assigned to specific channel profiles (#255)
- Channel profiles are now fetched automatically after a successful M3U refresh
- Uses only whole numbers when assigning the next available channel number

### Changed

- Logo upload behavior changed to wait for the Create button before saving
- Uses the channel name as the display name in EPG output for improved readability
- Ensures channels are only added to a selected profile if one is explicitly chosen

### Fixed

- Logo Manager prevents redundant messages from the file scanner by properly tracking uploaded logos in Redis
- Fixed an issue preventing logo uploads via URL
- Adds internal support for assigning multiple profiles via API

## [0.7.0] - 2025-07-19

### Added

- **Logo Manager:**
  - Complete logo management system with filtering, search, and usage tracking
  - Upload logos directly through the UI
  - Automatically scan `/data/logos` for existing files (#69)
  - View which channels use each logo
  - Bulk delete unused logos with cleanup
  - Enhanced display with hover effects and improved sizing
  - Improved logo fetching with timeouts and user-agent headers to prevent hanging
- **Group Manager:**
  - Comprehensive group management interface (#128)
  - Search and filter groups with ease
  - Bulk operations for cleanup
  - Filter channels by group membership
  - Automatically clean up unused groups
- **Auto Channel Sync:**
  - Automatic channel synchronization from M3U sources (#147)
  - Configure auto-sync settings per M3U account group
  - Set starting channel numbers by group
  - Override group names during sync
  - Apply regex match and replace for channel names
  - Filter channels by regex match on stream name
  - Track auto-created vs manually added channels
  - Smart updates preserve UUIDs and existing links
- Stream rehashing with WebSocket notifications
- Better error handling for blocked rehash attempts
- Lock acquisition to prevent conflicts
- Real-time progress tracking

### Changed

- Persist table page sizes in local storage (streams & channels)
- Smoother pagination and improved UX
- Fixed z-index issues during table refreshes
- Improved XC client with connection pooling
- Better error handling for API and JSON decode failures
- Smarter handling of empty content and blocking responses
- Improved EPG XML generation with richer metadata
- Better support for keywords, languages, ratings, and credits
- Better form layouts and responsive buttons
- Enhanced confirmation dialogs and feedback

### Fixed

- Channel table now correctly restores page size from local storage
- Resolved WebSocket message formatting issues
- Fixed logo uploads and edits
- Corrected ESLint issues across the codebase
- Fixed HTML validation errors in menus
- Optimized logo fetching with proper timeouts and headers ([#101](https://github.com/Dispatcharr/Dispatcharr/issues/101), [#217](https://github.com/Dispatcharr/Dispatcharr/issues/217))

## [0.6.2] - 2025-07-10

### Fixed

- **Streaming & Connection Stability:**
  - Provider timeout issues - Slow but responsive providers no longer cause channel lockups
  - Added chunk and process timeouts - Prevents hanging during stream processing and transcoding
  - Improved connection handling - Enhanced process management and socket closure detection for safer streaming
  - Enhanced health monitoring - Health monitor now properly notifies main thread without attempting reconnections
- **User Interface & Experience:**
  - Touch screen compatibility - Web player can now be properly closed on touch devices
  - Improved user management - Added support for first/last names, login tracking, and standardized table formatting
- Improved logging - Enhanced log messages with channel IDs for better debugging
- Code cleanup - Removed unused imports, variables, and dead links

## [0.6.1] - 2025-06-27

### Added

- Dynamic parameter options for M3U and EPG URLs (#207)
- Support for 'num' property in channel number extraction (fixes channel creation from XC streams not having channel numbers)

### Changed

- EPG generation now uses streaming responses to prevent client timeouts during large EPG file generation (#179)
- Improved reliability when downloading EPG data from external sources
- Better program positioning - Programs that start before the current view now have proper text positioning (#223)
- Better mobile support - Improved sizing and layout for mobile devices across multiple tables
- Responsive stats cards - Better calculation for card layout and improved filling on different screen sizes (#218)
- Enhanced table rendering - M3U and EPG tables now render better on small screens
- Optimized spacing - Removed unnecessary padding and blank space throughout the interface
- Better settings layout - Improved minimum widths and mobile support for settings pages
- Always show 2 decimal places for FFmpeg speed values

### Fixed

- TV Guide now properly filters channels based on selected channel group
- Resolved loading issues - Fixed channels and groups not loading correctly in the TV Guide
- Stream profile fixes - Resolved issue with setting stream profile to 'use default'
- Single channel editing - When only one channel is selected, the correct channel editor now opens
- Bulk edit improvements - Added "no change" options for bulk editing operations
- Bulk channel editor now properly saves changes (#222)
- Link form improvements - Better sizing and rendering of link forms with proper layering
- Confirmation dialogs added with warning suppression for user deletion, channel profile deletion, and M3U profile deletion

## [0.6.0] - 2025-06-19

### Added

- **User Management & Access Control:**
  - Complete user management system with user levels and channel access controls
  - Network access control with CIDR validation and IP-based restrictions
  - Logout functionality and improved loading states for authenticated users
- **Xtream Codes Output:**
  - Xtream Codes support enables easy output to IPTV clients (#195)
- **Stream Management & Monitoring:**
  - FFmpeg statistics integration - Real-time display of video/audio codec info, resolution, speed, and stream type
  - Automatic stream switching when buffering is detected
  - Enhanced stream profile management with better connection tracking
  - Improved stream state detection, including buffering as an active state
- **Channel Management:**
  - Bulk channel editing for channel group, stream profile, and user access level
- **Enhanced M3U & EPG Features:**
  - Dynamic `tvg-id` source selection for M3U and EPG (`tvg_id`, `gracenote`, or `channel_number`)
  - Direct URL support in M3U output via `direct=true` parameter
  - Flexible EPG output with a configurable day limit via `days=#` parameter
  - Support for LIVE tags and `dd_progrid` numbering in EPG processing
- Proxy settings configuration with UI integration and improved validation
- Stream retention controls - Set stale stream days to `0` to disable retention completely (#123)
- Tuner flexibility - Minimum of 1 tuner now allowed for HDHomeRun output
- Fallback IP geolocation provider (#127) - Thanks [@maluueu](https://github.com/maluueu)
- POST method now allowed for M3U output, enabling support for Smarters IPTV - Thanks [@maluueu](https://github.com/maluueu)

### Changed

- Improved channel cards with better status indicators and tooltips
- Clearer error messaging for unsupported codecs in the web player
- Network access warnings to prevent accidental lockouts
- Case-insensitive M3U parsing for improved compatibility
- Better EPG processing with improved channel matching
- Replaced Mantine React Table with custom implementations
- Improved tooltips and parameter wrapping for cleaner interfaces
- Better badge colors and status indicators
- Stronger form validation and user feedback
- Streamlined settings management using JSON configs
- Default value population for clean installs
- Environment-specific configuration support for multiple deployment scenarios

### Fixed

- FFmpeg process cleanup - Ensures FFmpeg fully exits before marking connection closed
- Resolved stream profile update issues in statistics display
- Fixed M3U profile ID behavior when switching streams
- Corrected stream switching logic - Redis is only updated on successful switches
- Fixed connection counting - Excludes the current profile from available connection counts
- Fixed custom stream channel creation when no group is assigned (#122)
- Resolved EPG auto-matching deadlock when many channels match simultaneously - Thanks [@xham3](https://github.com/xham3)

## [0.5.2] - 2025-06-03

### Added

- Direct Logo Support: Added ability to bypass logo caching by adding `?cachedlogos=false` to the end of M3U and EPG URLs (#109)

### Changed

- Dynamic Resource Management: Auto-scales Celery workers based on demand, reducing overall memory and CPU usage while still allowing high-demand tasks to complete quickly (#111)
- Enhanced Logging:
  - Improved logging for M3U processing
  - Better error output from XML parser for easier troubleshooting

### Fixed

- XMLTV Parsing: Added `remove_blank_text=True` to lxml parser to prevent crashes with poorly formatted XMLTV files (#115)
- Stats Display: Refactored channel info retrieval for safer decoding and improved error logging, fixing intermittent issues with statistics not displaying properly

## [0.5.1] - 2025-05-28

### Added

- Support for ZIP-compressed EPG files
- Automatic extraction of compressed files after downloading
- Intelligent file type detection for EPG sources:
  - Reads the first bits of files to determine file type
  - If a compressed file is detected, it peeks inside to find XML files
- Random descriptions for dummy channels in the TV guide
- Support for decimal channel numbers (converted from integer to float) - Thanks [@MooseyOnTheLoosey](https://github.com/MooseyOnTheLoosey)
- Show channels without EPG data in TV Guide
- Profile name added to HDHR-friendly name and device ID (allows adding multiple HDHR profiles to Plex)

### Changed

- About 30% faster EPG processing
- Significantly improved memory usage for large EPG files
- Improved timezone handling
- Cleaned up cached files when deleting EPG sources
- Performance improvements when processing extremely large M3U files
- Improved batch processing with better cleanup
- Enhanced WebSocket update handling for large operations
- Redis configured for better performance (no longer saves to disk)
- Improved memory management for Celery tasks
- Separated beat schedules with a file scanning interval set to 20 seconds
- Improved authentication error handling with user redirection to the login page
- Improved channel card formatting for different screen resolutions (can now actually read the channel stats card on mobile)
- Decreased line height for status messages in the EPG and M3U tables for better appearance on smaller screens
- Updated the EPG form to match the M3U form for consistency

### Fixed

- Profile selection issues that previously caused WebUI crashes
- Issue with `tvc-guide-id` (Gracenote ID) in bulk channel creation
- Bug when uploading an M3U with the default user-agent set
- Bug where multiple channel initializations could occur, causing zombie streams and performance issues (choppy streams)
- Better error handling for buffer overflow issues
- Fixed various memory leaks
- Bug in the TV Guide that would crash the web UI when selecting a profile to filter by
- Multiple minor bug fixes and code cleanup

## [0.5.0] - 2025-05-15

### Added

- **XtreamCodes Support:**
  - Initial XtreamCodes client support
  - Option to add EPG source with XC account
  - Improved XC login and authentication
  - Improved error handling for XC connections
- **Hardware Acceleration:**
  - Detection of hardware acceleration capabilities with recommendations (available in logs after startup)
  - Improved support for NVIDIA, Intel (QSV), and VAAPI acceleration methods
  - Added necessary drivers and libraries for hardware acceleration
  - Automatically assigns required permissions for hardware acceleration
  - Thanks to [@BXWeb](https://github.com/BXWeb), @chris.r3x, [@rykr](https://github.com/rykr), @j3111, [@jesmannstl](https://github.com/jesmannstl), @jimmycarbone, [@gordlaben](https://github.com/gordlaben), [@roofussummers](https://github.com/roofussummers), [@slamanna212](https://github.com/slamanna212)
- **M3U and EPG Management:**
  - Enhanced M3U profile creation with live regex results
  - Added stale stream detection with configurable thresholds
  - Improved status messaging for M3U and EPG operations:
    - Shows download speed with estimated time remaining
    - Shows parsing time remaining
  - Added "Pending Setup" status for M3U's requiring group selection
  - Improved handling of M3U group filtering
- **UI Improvements:**
  - Added configurable table sizes
  - Enhanced video player with loading and error states
  - Improved WebSocket connection handling with authentication
  - Added confirmation dialogs for critical operations
  - Auto-assign numbers now configurable by selection
  - Added bulk editing of channel profile membership (select multiple channels, then click the profile toggle on any selected channel to apply the change to all)
- **Infrastructure & Performance:**
  - Standardized and improved the logging system
  - New environment variable to set logging level: `DISPATCHARR_LOG_LEVEL` (default: `INFO`, available: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
  - Introduced a new base image build process: updates are now significantly smaller (typically under 15MB unless the base image changes)
  - Improved environment variable handling in container
- Support for Gracenote ID (`tvc-guide-stationid`) - Thanks [@rykr](https://github.com/rykr)
- Improved file upload handling with size limits removed

### Fixed

- Issues with profiles not loading correctly
- Problems with stream previews in tables
- Channel creation and editing workflows
- Logo display issues
- WebSocket connection problems
- Multiple React-related errors and warnings
- Pagination and filtering issues in tables

## [0.4.1] - 2025-05-01

### Changed

- Optimized uWSGI configuration settings for better server performance
- Improved asynchronous processing by converting additional timers to gevent
- Enhanced EPG (Electronic Program Guide) downloading with proper user agent headers

### Fixed

- Issue with "add streams to channel" functionality to correctly follow disabled state logic

## [0.4.0] - 2025-05-01

### Added

- URL copy buttons for stream and channel URLs
- Manual stream switching ability
- EPG auto-match notifications - Users now receive feedback about how many matches were found
- Informative tooltips throughout the interface, including stream profiles and user-agent details
- Display of connected time for each client
- Current M3U profile information to stats
- Better logging for which channel clients are getting chunks from

### Changed

- Table System Rewrite: Completely refactored channel and stream tables for dramatically improved performance with large datasets
- Improved Concurrency: Replaced time.sleep with gevent.sleep for better performance when handling multiple streams
- Improved table interactions:
  - Restored alternating row colors and hover effects
  - Added shift-click support for multiple row selection
  - Preserved drag-and-drop functionality
- Adjusted logo display to prevent layout shifts with different sized logos
- Improved sticky headers in tables
- Fixed spacing and padding in EPG and M3U tables for better readability on smaller displays
- Stream URL handling improved for search/replace patterns
- Enhanced stream lock management for better reliability
- Added stream name to channel status for better visibility
- Properly track current stream ID during stream switches
- Improved EPG cache handling and cleanup of old cache files
- Corrected content type for M3U file (using m3u instead of m3u8)
- Fixed logo URL handling in M3U generation
- Enhanced tuner count calculation to include only active M3U accounts
- Increased thread stack size in uwsgi configuration
- Changed proxy to use uwsgi socket
- Added build timestamp to version information
- Reduced excessive logging during M3U/EPG file importing
- Improved store variable handling to increase application efficiency
- Frontend now being built by Yarn instead of NPM

### Fixed

- Issues with channel statistics randomly not working
- Stream ordering in channel selection
- M3U profile name added to stream names for better identification
- Channel form not updating some properties after saving
- Issue with setting logos to default
- Channel creation from streams
- Channel group saving
- Improved error handling throughout the application
- Bugs in deleting stream profiles
- Resolved mimetype detection issues
- Fixed form display issues
- Added proper requerying after form submissions and item deletions
- Bug overwriting tvg-id when loading TV Guide
- Bug that prevented large m3u's and epg's from uploading
- Typo in Stream Profile header column for Description - Thanks [@LoudSoftware](https://github.com/LoudSoftware)
- Typo in m3u input processing (tv-chno instead of tvg-chno) - Thanks @www2a

## [0.3.3] - 2025-04-18

### Fixed

- Issue with dummy EPG calculating hours above 24, ensuring time values remain within valid 24-hour format
- Auto import functionality to properly process old files that hadn't been imported yet, rather than ignoring them

## [0.3.2] - 2025-04-16

### Fixed

- Issue with stream ordering for channels - resolved problem where stream objects were incorrectly processed when assigning order in channel configurations

## [0.3.1] - 2025-04-16

### Added

- Key to navigation links in sidebar to resolve DOM errors when loading web UI
- Channels that are set to 'dummy' epg to the TV Guide

### Fixed

- Issue preventing dummy EPG from being set
- Channel numbers not saving properly
- EPGs not refreshing when linking EPG to channel
- Improved error messages in notifications

## [0.3.0] - 2025-04-15

### Added

- URL validation for redirect profile:
  - Validates stream URLs before redirecting clients
  - Prevents clients from being redirected to unavailable streams
  - Now tries alternate streams when primary stream validation fails
- Dynamic tuner configuration for HDHomeRun devices:
  - TunerCount is now dynamically created based on profile max connections
  - Sets minimum of 2 tuners, up to 10 for unlimited profiles

### Changed

- More robust stream switching:
  - Clients now wait properly if a stream is in the switching state
  - Improved reliability during stream transitions
- Performance enhancements:
  - Increased workers and threads for uwsgi for better concurrency

### Fixed

- Issue with multiple dead streams in a row - System now properly handles cases where several sequential streams are unavailable
- Broken links to compose files in documentation

## [0.2.1] - 2025-04-13

### Fixed

- Stream preview (not channel)
- Streaming wouldn't work when using default user-agent for an M3U
- WebSockets and M3U profile form issues

## [0.2.0] - 2025-04-12

Initial beta public release.
