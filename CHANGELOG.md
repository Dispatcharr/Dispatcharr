# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.23.0] - 2026-04-17

### Security

- Set `DEFAULT_PERMISSION_CLASSES` to `IsAdmin` in the DRF configuration. All viewsets and function-based views that require non-admin or unauthenticated access were explicitly annotated: proxy streaming endpoints (`stream_ts`, `stream_xc`, `stream_vod`, `head_vod`, `stream_xc_movie`, `stream_xc_episode`) use `@permission_classes([AllowAny])` (access is controlled by the per-stream-type network allow-list inside the view body); the `UserAgentViewSet`, `StreamProfileViewSet`, `CoreSettingsViewSet`, and `ProxySettingsViewSet` gained `get_permissions()` methods mapping read actions to `IsStandardUser` and write actions to `IsAdmin`; and `AuthViewSet.logout` was updated to return `[Authenticated()]`.
- Fixed missing `network_access_allowed` checks in the VOD proxy. `stream_vod`, `head_vod`, `stream_xc_movie`, and `stream_xc_episode` were not checking the `STREAMS` network policy, unlike the equivalent TS proxy endpoints.
- Explicitly marked the HDHomeRun discovery endpoints (`DiscoverAPIView`, `LineupAPIView`, `LineupStatusAPIView`, `HDHRDeviceXMLAPIView`) and the version endpoint with `permission_classes = [AllowAny]` to document their intentionally public access now that the global default is `IsAdmin`.
- Fixed path traversal vulnerability in file uploads. The M3U account upload (`apps/m3u/api_views.py`), logo upload (`apps/channels/api_views.py`), and backup upload (`apps/backups/api_views.py`) all used the uploaded filename directly without sanitization. `os.path.join()` discards all preceding components when it encounters an absolute path segment, and `pathlib`'s `/` operator behaves identically; a relative `../` sequence also escapes via OS path resolution at `open()` time. All three upload paths now strip directory components via `Path(name).name` and validate the resolved path remains within the intended upload directory. Exploiting any of these required admin credentials.
- Prevented users from setting `xc_password` (and other admin-managed keys) on their own account via the `PATCH /api/accounts/users/me/` endpoint.
- Hardened the HLS proxy `change_stream` endpoint by converting it from a plain Django view to a DRF `@api_view` with `@permission_classes([IsAdmin])`, ensuring the endpoint actually enforces admin-only access. The previous decorator arrangement (`@csrf_exempt` + `@permission_classes`) had no effect on a plain Django view.
- Added rate limiting to the login endpoint (`POST /api/accounts/token/`) using DRF's built-in throttling. A `LoginRateThrottle` (3 requests/minute per IP, sliding window) is applied to the `TokenObtainPairView`. Repeated failed attempts from the same IP receive `429 Too Many Requests`.
- Extended rate limiting to the session-auth login alias (`POST /api/accounts/auth/login/`). It now delegates entirely to `TokenObtainPairView`, inheriting its throttle, network access check, and audit logging, and returns JWT tokens instead of a session cookie (the session-based response was unusable since `SessionAuthentication` is not in `DEFAULT_AUTHENTICATION_CLASSES`). Both endpoints share the same `"login"` throttle scope, so attempts across either path count against the same per-IP limit.
- Removed `CORS_ALLOW_CREDENTIALS = True` from CORS configuration. Dispatcharr authenticates via JWT `Authorization` headers and API keys — not cookies — so credentials are never sent cross-origin by browsers. The setting was also redundant: browsers reject `Access-Control-Allow-Credentials: true` when `Access-Control-Allow-Origin` is a wildcard (`*`), so it had no effect in practice.
- Updated frontend npm dependencies to resolve 6 audit vulnerabilities (6 high):
  - Updated `@xmldom/xmldom` 0.8.11 → 0.8.12, resolving **high** XML injection via unsafe CDATA serialization allowing attacker-controlled markup insertion ([GHSA-wh4c-j3r5-mjhp](https://github.com/advisories/GHSA-wh4c-j3r5-mjhp))
  - Updated `lodash` 4.17.23 → 4.18.1, resolving **high** Code Injection via `_.template` imports key names ([GHSA-r5fr-rjxr-66jc](https://github.com/advisories/GHSA-r5fr-rjxr-66jc)) and **high** Prototype Pollution via array path bypass in `_.unset` and `_.omit` ([GHSA-f23m-r3pf-42rh](https://github.com/advisories/GHSA-f23m-r3pf-42rh))
  - Updated `vite` 7.3.1 → 7.3.2, resolving **high** Path Traversal in optimized deps `.map` handling ([GHSA-4w7w-66w2-5vf9](https://github.com/advisories/GHSA-4w7w-66w2-5vf9)), **high** `server.fs.deny` bypass with queries ([GHSA-v2wj-q39q-566r](https://github.com/advisories/GHSA-v2wj-q39q-566r)), and **high** Arbitrary File Read via dev server WebSocket ([GHSA-p9ff-h696-f583](https://github.com/advisories/GHSA-p9ff-h696-f583))
- Updated `Django` 6.0.3 → 6.0.4, resolving the following CVEs:
  - **CVE-2026-33033**: Potential DoS via `MultiPartParser` through crafted multipart uploads.
  - **CVE-2026-33034**: SGI requests with a missing or understated `Content-Length` header could bypass the `DATA_UPLOAD_MAX_MEMORY_SIZE` limit.
  - **CVE-2026-4292**: Privilege abuse in `ModelAdmin.list_editable`.
  - **CVE-2026-3902**: ASGI header spoofing via underscore/hyphen conflation.
  - **CVE-2026-4277**: Privilege abuse in `GenericInlineModelAdmin`.

### Added

- **EPG historical data window**: the EPG XML output and XC EPG API now support a `prev_days` URL parameter (e.g. `&prev_days=3`) to include past programs in the EPG response. This allows third-party players that request historical program schedules to receive the data they need. The EPG URL builder in the Channels page exposes "Days forward" and "Days back" controls. Per-user defaults for both values (`epg_days` / `epg_prev_days`) can be configured in the User settings modal and are applied automatically when no URL parameter is present. (Closes #1154)
- **Plugin Hub**: administrators can now browse, install, and update plugins directly from remote repositories via a new Plugin Hub page in Settings. (Closes #393) — Thanks [@sethwv](https://github.com/sethwv)
  - Install plugins directly from the hub: the release zip is downloaded, SHA256 integrity is verified, and the plugin is installed atomically.
  - Update managed plugins when a newer version is available from their source repo. Version compatibility constraints (`min_dispatcharr_version` / `max_dispatcharr_version`) are enforced at install time.
  - Browse available plugins from all enabled repos with name, description, version, author, and icon.
  - Plugins installed from a repo are tracked as "managed": source repo, slug, installed version, prerelease flag, and deprecated status are all persisted and surfaced in the UI.
  - Add plugin repositories by manifest URL. The official Dispatcharr Plugins repository is pre-configured; third-party repos are supported by supplying an optional GPG public key.
  - Manifest signatures are verified via GPG; the official repo uses a bundled public key. Signature status is displayed per-repo.
  - Preview a repository URL before adding it - validates the manifest and reports plugin count and signature status without saving anything.
  - Configurable automatic manifest refresh interval (in hours; 0 to disable) runs as a Celery background task.

### Removed

- Removed dead `VODConnectionManager` class (`apps/proxy/vod_proxy/connection_manager.py`) and its associated helpers, which had been superseded by `MultiWorkerVODConnectionManager`. All active code already used the multi-worker implementation. Removed the unused `VODConnectionManager` import from `vod_proxy/views.py`, the unscheduled `cleanup_vod_connections` task from `apps/proxy/tasks.py`, and the unscheduled `cleanup_vod_persistent_connections` task from `core/tasks.py`.
- Removed dead VOD URL routes: `VODPlaylistView` (playlist generation), `VODPositionView` (position tracking), and the class-based `VODStatsView` (replaced by the existing function-based `vod_stats` view).
- Removed dead `updateVODPosition()` API method from `frontend/src/api.js`, which called the now-removed position tracking endpoint.

### Fixed

- Fixed TV Guide "Record One" always scheduling the recording on the first channel that matched the program's `tvg_id`, rather than the channel the user actually selected. When multiple channels share the same EPG source, the intended channel was silently ignored. The selected channel object is now passed explicitly through the click handler chain to `recordOne`, bypassing the `findChannelByTvgId` fallback lookup entirely. (Fixes #1140) — Thanks [@fezster](https://github.com/fezster)
- Graceful container shutdown: `docker stop` no longer results in exit 137 (SIGKILL). The entrypoint now explicitly stops all child processes — including uWSGI workers, Celery, Daphne, and Redis, which are spawned as uWSGI `attach-daemon` children and were previously invisible to the signal handler. A polling loop replaces the old fixed `sleep`, exiting as soon as all processes have stopped (up to an 8-second ceiling before force-stopping). PostgreSQL is stopped using `pg_ctl stop -m immediate` as a fallback rather than SIGKILL to avoid data corruption. Process names are now recorded at startup and displayed correctly in crash diagnostics. The unexpected-exit diagnostic block is now suppressed on normal `docker stop` shutdowns. — Thanks [@Shokkstokk](https://github.com/Shokkstokk) for the initial fix!
- Fixed two race conditions in the VOD proxy that caused the `profile_connections` counter to go permanently negative, allowing connections beyond the configured profile limit. (1) `_decrement_profile_connections()` used a GET-before-DECR guard: two concurrent decrements could both read the same positive value, both pass the guard, and both fire, driving the counter below zero. Replaced with an unconditional `DECR` followed by a clamp-to-zero if the result is negative. (2) The `stream_generator` decremented `active_streams` and then checked `has_active_streams()` in two separate Redis round-trips without locking. A concurrent generator on another worker could read `active_streams=0` in the window between those two calls and also decrement the profile counter, producing a double-decrement. A new `decrement_active_streams_and_check()` method performs both operations under a single distributed lock, and a `profile_decremented` flag guards all four call sites in the generator so the profile counter is only ever decremented once per stream. (Closes #1125) — Thanks [@firestaerter3](https://github.com/firestaerter3)
- Fixed a provider TCP connection leak in the VOD proxy `stream_generator`. When a stream ended via an unhandled exception path that reached the `finally` block without any of the three exception handlers having run (e.g. an error raised before the first `yield`), the `finally` block decremented counters but never called `redis_connection.cleanup()`. The upstream `requests.Response` and `requests.Session` were left open until garbage collection. The `finally` block now starts a `delayed_cleanup` daemon thread (matching the 1-second delay used by the normal-completion and `GeneratorExit` paths) so that seeking clients have time to reconnect and increment `active_streams` before `cleanup()` checks whether it is safe to close the connection.
- Fixed manual stream selection from the Stats page not enforcing M3U profile connection limits in multi-worker deployments. When a non-owning worker handled the `change_stream` request it correctly packaged `stream_id` and `m3u_profile_id` into the Redis pubsub message, but the owning worker's pubsub handler only consumed `url` and `user_agent` silently dropping both IDs before calling `stream_manager.update_url()`. Because `update_url` only calls `update_stream_profile()` when a `stream_id` is provided, the `profile_connections` counter was never updated after the switch, causing subsequent capacity checks to see incorrect counts and bypass the full-profile guard. The handler now extracts `stream_id` and `m3u_profile_id` from the event and forwards them to `update_url()`. The bug did not affect single-worker / dev-mode deployments because the owning worker handles those requests directly without pubsub.
- Fixed the `next_stream` rotation endpoint applying the same class of bug: `get_stream_info_for_switch()` was called and returned `m3u_profile_id`, but the result was dropped when forwarding to `ChannelService.change_stream_url()`, so `update_stream_profile()` was never called and `profile_connections` counters were not updated after an automatic stream rotation.
- Fixed stream switch metadata (`url`, `user_agent`, `stream_id`, `m3u_profile`) being written to Redis before the switch was confirmed to succeed. If the switch failed, URL unchanged or exception during teardown, Redis described a URL not actually in use. Metadata is now written only after `update_url()` returns `True`; on failure the owner writes `stream_manager.url` back as the ground truth. The non-owner no longer pre-writes metadata at all, all needed info is carried in the pubsub payload and written by the owner after confirmation.
- Fixed the Stats page "Active Stream" dropdown not updating when a stream switch occurs. The card was matching the active stream by comparing the URL stored in Redis against stream URLs from the database, which failed silently when the stored URL was a transformed/rewritten value that didn't substring-match the original. The dropdown now matches by `stream_id` (the authoritative value already present in the stats payload) and re-runs only when `stream_id` changes, so the normal polling interval drives updates with no extra renders.
- Fixed the XC Password field in the User modal being editable by standard users despite the backend (`PATCH /api/accounts/users/me/`) stripping `xc_password` from `custom_properties` for non-admin users, causing the change to silently revert on save. The field and its generate button are now disabled with an explanatory description when the current user is not an administrator.
- Fixed live stream hiccups caused by nginx buffering TS proxy data to disk. The `/proxy/` location block used `proxy_buffering off` and `proxy_read/send_timeout` directives, which are silently ignored when the upstream is `uwsgi_pass` (a different directive family). nginx was therefore defaulting to `uwsgi_buffering on`, spooling stream data through temp files on disk. Replaced with the correct `uwsgi_buffering off`, `uwsgi_read_timeout 300s`, and `uwsgi_send_timeout 300s` directives so stream data flows directly from uWSGI to the client socket without intermediate disk I/O.
- Fixed the logo cache endpoint (`/api/channels/logos/{id}/cache/`) holding a uWSGI greenlet indefinitely when fetching from a slow or dripping remote server. The previous implementation used `StreamingHttpResponse(iter_content())` with only a per-chunk read timeout; a server that drips data just fast enough to reset the per-read timer could hold the greenlet open forever. Replaced with an eager read loop enforcing a hard total-download deadline (10 s) and a size cap (5 MB). Also fixed a race condition in the existing negative-cache logic: the failure entry for a URL was cleared immediately upon receiving HTTP 200, before the body was read. A concurrent greenlet seeing no failure entry during a slow download that ultimately timed out would also attempt the fetch, defeating the cache. The entry is now cleared only after the full body has been successfully received.
- Fixed uploading a local M3U file with no expiration date set sending the string `"null"` as the `exp_date` field in the `FormData` request, causing a 400 validation error from the API. Null/undefined values are now skipped when building the `FormData` body, matching the behaviour already present in the update path.
- Fixed `PATCH /api/channels/channels/edit/bulk/` returning a 500 error when the request body included a `streams` list. The bulk edit handler was iterating `validated_data` directly and calling `setattr(channel, "streams", value)`, which Django prohibits on ManyToMany fields. Also added an `@extend_schema` decorator so the Swagger UI correctly documents the endpoint as accepting a JSON array and shows the `streams` field. (Fixes #883)
- Fixed several incorrect or incomplete OpenAPI (`@extend_schema`) schemas across the API:
  - `POST /api/epg/import/` — request body was undocumented; now correctly shows the `id` field. Description updated from "import" to "refresh" to match frontend and backend terminology.
  - `DELETE /api/channels/logos/bulk-delete/` — `delete_files` boolean was missing from the documented request body.
  - `POST /api/channels/channels/batch-set-epg/` — `epg_data_id` inside each association object was not marked `allow_null`/`required=False`, even though passing `null` is the correct way to remove an EPG link.
  - `PUT /api/connect/integrations/{id}/subscriptions/set/` — endpoint had no `@extend_schema` at all; now documents that the request body is a JSON array of subscription objects.

### Changed

- **Output bitrate DB persistence**: the `ffmpeg_output_bitrate` stat is no longer written to the database on every FFmpeg stats tick (~2/second). Instead, a local exponential moving average (EMA, α=0.1) accumulates readings continuously. The first 10 samples (~5 seconds) are discarded as warmup to avoid polluting the average with FFmpeg's unstable ramp-up values. After warmup, the smoothed value is flushed to the database at most once every 30 seconds, and a final flush occurs when the stream stops but only if the EMA has been seeded (i.e. the stream ran past warmup). Streams that stop during warmup leave the existing database value untouched, preserving previously accurate measurements when channel-hopping.
- Performance: `generate_m3u`, `generate_epg`, and `xc_get_live_streams` now use `select_related('channel_group', 'logo')` (or `select_related('logo')` for EPG) on every Channel queryset in `apps/output/views.py`. Previously each channel in the loop triggered a separate database query for its `logo` and `channel_group` foreign keys; with the JOIN-based prefetch this is reduced to a single query per request. On deployments with ~2 000 channels, `xc_get_live_streams` response time drops from ~2.5–4 s to ~250–450 ms. (Closes #1127) — Thanks [@xBOBxSAGETx](https://github.com/xBOBxSAGETx)
- Performance: `generate_epg` now uses `select_related('epg_data__epg_source')` on all EPG channel querysets, eliminating N+1 database queries for `EPGSource` traversal per channel (~15 s improvement on ~2000-channel deployments; total EPG generation time dropped from ~87 s to ~72 s in benchmarks).
- Performance: `xc_get_epg` now uses `select_related('epg_data__epg_source')` on all three channel fetch paths. Previously each request triggered 2 additional queries to resolve `channel.epg_data` and `channel.epg_data.epg_source`.
- Performance: `generate_m3u` now uses `prefetch_related` for streams when `?direct=true` is requested, eliminating N+1 stream queries (one per channel) on that code path.
- Performance: `EPGGridAPIView` (`apps/epg/api_views.py`) now uses `select_related('epg_data__epg_source')` on the `channels_with_custom_dummy` queryset, eliminating 2 extra queries per channel (for `epg_data` and `epg_source`) in the dummy EPG generation loop.
- Performance: `generate_epg` now issues a single cross-channel `ProgramData` bulk query. `.values()` returns plain dicts, bypassing per-row Django model instantiation. Results are consumed in independent 5000-row keyset-paginated chunks. Combined with the `select_related` improvements above, EPG generation time on large deployments is significantly reduced.
- Performance: `xc_get_live_streams` no longer calls `ChannelGroup.objects.get_or_create(name="Default Group")` once per null-group channel; replaced with a lazy-initialised closure that executes at most one query regardless of how many ungrouped channels are present.
- AIO containers now connect to the internal PostgreSQL instance via a Unix domain socket instead of TCP loopback. Users who have `POSTGRES_HOST` explicitly set to `localhost` or `127.0.0.1` in their compose file are automatically migrated to the socket path; any other explicit value (external host/IP) is left untouched. — Thanks [@JCBird1012](https://github.com/JCBird1012)
- Improved the EPG response cache key. Previously it was based on the raw query string and username, meaning a user default of `epg_days=7` and an explicit `&days=7` URL parameter produced different cache entries for identical output. The key is now built from all resolved effective parameter values (`days`, `prev_days`, `cachedlogos`, `tvg_id_source`) so semantically equivalent requests always share the same cache entry.
- Improved the HDHR, M3U, and EPG URL builder popovers in the Channels table: each popover now opens with a brief intro sentence describing its purpose. Toggle switches were refactored to use Mantine's native `label` and `description` props (replacing the previous manual `Group`/`Stack`/`Text` layout), giving each switch a properly styled description line beneath its label. Switch alignment was also corrected. Toggles now appear on the left with the label and description stacked to the right, consistent with standard Mantine form layout.
- Redesigned the User settings modal with a tabbed layout: **Account** (username, email, name, password), **Permissions** (user level, stream limit, channel profiles, mature content filter - admin only), **EPG Defaults** (days forward/back), and **API & XC** (XC password, API key management). Fields are now logically grouped rather than split across two ad-hoc columns.
- EPG channel scanning now automatically removes stale `EPGData` entries. tvg-ids that were present in a previous scan but are no longer found in the upstream source, provided they are not mapped to any channel. This prevents unbounded database bloat over time. Entries mapped to at least one channel are always preserved.
- Rewrote the M3U line parser as an `iter_m3u_entries` generator that owns the full per-entry state machine. Intermediate directive lines between `#EXTINF` and the stream URL are now handled correctly rather than corrupting the pending entry or being silently misassigned. A `#EXTINF` with no following URL is discarded with a warning instead of carrying over a `url`-less entry into batch processing. Attribute keys are normalised to lowercase during parsing (provider attribute names remain case-insensitive end-to-end). The `#EXTINF` attribute regex is pre-compiled at module load, and attribute lookups use O(1) `dict.get()` instead of linear scans — approximately 10% faster parsing on large M3U files.
- Added support for the `#EXTGRP` directive in M3U files. When a `group-title` attribute is absent from the `#EXTINF` line, the value from a following `#EXTGRP:` line is used as the group. An explicit `group-title` attribute always takes priority. (Closes #1088)
- Added accumulation of `#EXTVLCOPT` directives per entry. Options are stored as a list under `vlc_opts` inside the stream's `custom_properties`, available for downstream use (e.g. passing VLC-specific options to the player). This is for a planned future enhancement and can also be utlized with the API.
- M3U stream name parsing now uses the comma text (the canonical display title per the base `#EXTINF` spec) as the primary stream name, falling back to `tvc-guide-title`, then `tvg-name`, rather than preferring `tvg-name` first. Providers that use `tvg-name` as an EPG key and put the human-readable title after the comma will now display the correct name. Providers that duplicate the same value in both fields are unaffected. (Fixes #1081)
- FloatingVideo player: the native video controls (timeline, play/pause, volume) are now hidden by default when a live stream starts and only appear when the user hovers over the player.
- Enhanced Swagger UI authorization dialog: registered a custom `OpenApiAuthenticationExtension` for `ApiKeyAuthentication` so drf-spectacular now generates an `ApiKeyAuth (apiKey)` entry alongside `jwtAuth`. Both entries include descriptive text linking to the relevant endpoints (`/api/accounts/token/`, `/api/accounts/api-keys/generate/`, `/api/accounts/api-keys/revoke/`).
- Refactored frontend form components (`AccountInfoModal`, `AssignChannelNumbers`, `Channel`, `ChannelBatch`, `ChannelGroup`, `Connection`, `CronBuilder`, `DummyEPG`, and `EPG`) to extract business logic into dedicated utility modules under `src/utils/forms/`. Each extracted module is covered by unit tests. Mantine compound component references (`Table.Tbody`, `Popover.Target`, `Accordion.Item`, etc.) have been updated to use flat named imports. — Thanks [@nick4810](https://github.com/nick4810)
- Improved the EPG BOM fix from v0.22.1: replaced the `lstrip(b'\xef\xbb\xbf')` / `startswith` approach with `start.find(b'<?xml')`, which locates the XML declaration regardless of any leading bytes BOM, whitespace, or other encoding markers without needing to know what those bytes are.
- Dependency updates:
  - `Django` 6.0.3 → 6.0.4 (security patch; see Security section)
  - `djangorestframework` 3.16.1 → 3.17.1
  - `requests` 2.33.0 → 2.33.1
  - `gevent` 25.9.1 → 26.4.0
  - `rapidfuzz` 3.14.3 → 3.14.5
  - `sentence-transformers` 5.3.0 → 5.4.0
  - `lxml` 6.0.2 → 6.0.3
  - Added `python-gnupg` for GPG signature verification of official and third-party plugin repository manifests.

## [0.22.1] - 2026-04-05

### Fixed

- Fixed EPG sources that emit a UTF-8 BOM (e.g. ErsatzTV, EPGShare, WebGrab+Plus) parsing 0 channels and 0 programmes after the HTML entity fix introduced in v0.22.0. `bytes.lstrip()` only strips ASCII whitespace, leaving the three BOM bytes (`EF BB BF`) in place, so `stripped.startswith(b'<?xml')` returned `False`. The function fell through to the no-declaration branch and prepended the HTML entity DOCTYPE block _before_ the BOM and XML declaration, producing invalid XML that lxml silently discarded under `recover=True`. Fixed by stripping the BOM explicitly before the whitespace strip: `start.lstrip(b'\xef\xbb\xbf').lstrip()`. BOM-free files are unaffected. (Closes #1173) — Thanks [@dwot](https://github.com/dwot) for the fix!

## [0.22.0] - 2026-04-01

### Security

- Updated `requests` 2.32.5 → 2.33.0, resolving the following CVE:
  - **CVE-2026-25645** (moderate): Insecure temp file reuse in `extract_zipped_paths()` utility function.
- Updated frontend npm dependencies to resolve 4 audit vulnerabilities (2 moderate, 2 high):
  - Updated `brace-expansion` 5.0.2 → 5.0.5, resolving **moderate** zero-step sequence causing process hang and memory exhaustion ([GHSA-f886-m6hf-6m8v](https://github.com/advisories/GHSA-f886-m6hf-6m8v))
  - Updated `flatted` 3.4.1 → 3.4.2, resolving **high** Prototype Pollution via `parse()` in NodeJS flatted ([GHSA-rf6f-7fwh-wjgh](https://github.com/advisories/GHSA-rf6f-7fwh-wjgh))
  - Updated `picomatch` 4.0.3 → 4.0.4, resolving **high** method injection in POSIX character classes causing incorrect glob matching ([GHSA-3v7f-55p6-f55p](https://github.com/advisories/GHSA-3v7f-55p6-f55p)) and a ReDoS vulnerability via extglob quantifiers ([GHSA-c2c7-rcm5-vvqj](https://github.com/advisories/GHSA-c2c7-rcm5-vvqj))
  - Updated `yaml` 1.10.2 → 1.10.3, resolving **moderate** stack overflow via deeply nested YAML collections ([GHSA-48c2-rrv3-qjmp](https://github.com/advisories/GHSA-48c2-rrv3-qjmp))

### Added

- Connection cards on the Stats page now show the **username** of the connected user. For live channel connections a new User column appears between IP Address and Connected; for VOD connections the username is shown inline next to the IP address in the Client summary row. The username is resolved from the user store using the `user_id` stored in Redis client metadata. (Closes #766, Closes #586)
- `ip_address` and `user_id` were not included in the client info returned by `get_detailed_channel_info()` despite being available in the Redis hash. Both fields are now extracted and returned. `user_id` is now also included in the VOD stats response.
- Web UI stream preview now sends an `Authorization: Bearer` header with each mpegts.js request, identifying the logged-in user. Live channel previews initiated from the web UI now appear on the Stats page with the correct username rather than as unknown user.
- `client_connect` and `client_disconnect` system events now include the **username** of the connected user. The username is stored alongside the client metadata in Redis and included in the event payload for `log_system_event` calls (making it available to webhook and script integrations).
- Donate button added to the sidebar footer. A heart icon links to the project's Open Collective page, visible in both expanded and collapsed states. Hovering shows a "Support Dispatcharr" tooltip. The version string is also now clickable to copy it to the clipboard.
- User stream limits: administrators can now set a maximum number of concurrent streams per user account. When a user reaches their limit, the system can automatically terminate an existing stream to free a slot based on configurable rules. Limit enforcement applies to both live channels and VOD. (Closes #544)
  - Each user account has a new **Stream Limit** field (0 = unlimited) configurable from the user edit form in Settings → Users.
  - Global enforcement behaviour is configurable in Settings → User Limits:
    - **Terminate on Limit Exceeded**: automatically stop an existing stream when the user's limit is reached (vs. rejecting the new connection).
    - **Terminate Oldest**: prefer terminating the oldest stream when freeing a slot; disable to prefer the newest.
    - **Prioritize Single-Client Channels**: prefer terminating streams on channels that only this user is watching.
    - **Ignore Same-Channel Connections**: count multiple connections to the same live channel as one stream toward the limit. Same-channel reconnects are always allowed through. When this is enabled and a channel must be freed, all connections to the chosen channel are terminated together so that the unique-channel count actually decreases. VOD is explicitly excluded from this bypass since VOD connections are not shared upstream.
- TLS and mutual TLS (mTLS) support for Redis and PostgreSQL connections in modular deployments. Supports encrypted connections, server certificate verification (Redis: on/off; PostgreSQL: verify-full, verify-ca, require), CA certificate configuration, and client certificate authentication. Configured via environment variables in the docker compose file. Includes startup validation for certificate paths and TLS/URL scheme conflicts, and a read-only Connection Security panel in System Settings. (Closes #950) — Thanks [@CodeBormen](https://github.com/CodeBormen)
- Status filter for M3U group and VOD category filter modals: A new **All / Enabled / Disabled** segmented control is now shown alongside the text search input in the Live, VOD - Movies, and VOD - Series tabs of the M3U Group Filter modal. The status filter works in combination with the text search and also scopes the "Select Visible" / "Deselect Visible" buttons so they only act on the currently visible subset. (Closes #312)

### Changed

- M3U Profile form (XC accounts): added a **Simple / Advanced** mode toggle for credential-based URL rewriting. In Simple mode users enter just a new username and password; the search and replace patterns are built automatically from the account's current credentials. In Advanced mode the full regex fields are shown as before. The selected mode is saved to `custom_properties.xcMode` and auto-detected on existing profiles (a profile whose search pattern matches the account's current `username/password` is recognised as Simple automatically). The Live Regex Demonstration panel is hidden in Simple mode.
- XtreamCodes VOD endpoints (`/movie/` and `/series/`) no longer redirect clients to a UUID-based proxy URL. Requests are now handled directly in the proxy layer via `stream_xc_movie` and `stream_xc_episode`, which call `stream_vod()` internally. The original XC path is preserved for the client throughout the stream.
- `CustomTable` column layout now supports flexible (`grow`) columns alongside fixed-width ones:
  - Column definitions accept a `grow` property (boolean or number) to opt into flex layout. A numeric value sets the flex-grow weight, allowing relative sizing between grow columns (e.g. `grow: 2` gives a column twice the share of spare space as `grow: 1`).
  - `maxSize` is now respected on grow columns, capping how wide they expand via `maxWidth`.
  - The wrapper's `minWidth` calculation now uses `minSize` (not TanStack's 150px default) for grow columns, preventing the table from overflowing its container when columns would otherwise be sized larger than available space.
- Dependency updates:
  - `requests` 2.32.5 → 2.33.0 (security patch; see Security section)
  - `celery` 5.6.2 → 5.6.3
  - `torch` 2.10.0+cpu → 2.11.0+cpu
  - `sentence-transformers` 5.2.3 → 5.3.0
  - `yt-dlp` 2026.3.13 → 2026.3.17
- Docker base image cleanup: removed `python-is-python3`, `python3-pip`, and `streamlink` from the apt package list in `DispatcharrBase`. `python3-pip` and `streamlink` were pulling outdated system Python packages (e.g. `requests 2.31.0`, `cryptography 41.0.7`, `lxml 5.2.1`) into the system Python's site-packages despite the app running entirely in the uv-managed venv at `/dispatcharrpy`. `streamlink` is already installed in the venv via `pyproject.toml`. `python-is-python3` is unnecessary as `PATH` resolves bare `python` to the venv binary.
- M3U table **Max Streams** column now reflects the combined limit across all active profiles. When a playlist has multiple active profiles, the column displays their summed total (or ∞ if any profile is unlimited) and a hover tooltip lists each profile's individual limit by name. (Closes #816)
- Toggling an M3U profile's active state now immediately updates the playlist store (including the `playlists` array), so the **Max Streams** total in the M3U table reflects the change without a page reload.
- M3U account form: **Max Streams** field changed from a plain text input to a number input with increment/decrement controls, consistent with other integer fields.
- M3U account form: removed unused `useMantineTheme` import and `theme` variable.
- Moved `guideUtils.js` from `frontend/src/pages/` to `frontend/src/utils/` to be consistent with other utility modules (e.g. `networkUtils.js`). Updated all imports across `GuideRow.jsx`, `HourTimeline.jsx`, `ProgramDetailModal.jsx`, `RecordingCardUtils.js`, `Guide.jsx`, and related test files.
- Frontend cleanup: removed unused imports from `M3UGroupFilter`, `LiveGroupFilter`, and `VODCategoryFilter` (`Yup`, `M3UProfiles`, several unused Mantine components, dead `OptionWithTooltip` component, duplicate lucide-react imports, and `Divider` in `VODCategoryFilter`). No behaviour changes.
- Network Access settings: leaving a field blank no longer shows a validation error. The default CIDR range for that field is saved automatically and a "Defaults Restored" warning is displayed listing which fields were reset. (Closes #726)

### Fixed

- M3U profile URL rewriting now uses the `regex` module instead of `re` across all URL transform code paths (`url_utils.transform_url`, `core/views.py`, `vod_proxy/_transform_url`, `tasks.get_transformed_credentials`, and the WebSocket live-preview handler in `consumers.py`). The `regex` module natively accepts JavaScript/PCRE-style named capture groups (`(?<name>...)`) without any conversion, eliminating the root cause of patterns that matched in the frontend live preview but failed on the backend with a `re.error`. As a further improvement, `regex` also supports variable-length lookbehind assertions (e.g. `(?<=a+)`), which `re` rejects with an error; patterns using these will now work correctly on the backend as well. Replace-pattern JS tokens are still normalised before calling `regex.sub`: `$<name>` → `\g<name>` and `$1`/`$2`/… → `\1`/`\2`/… (Python replacement syntax). Also fixed a bug in the WebSocket preview handler where a pattern error was incorrectly returning the search pattern string as the preview output instead of the original URL. (Fixes #1005)
- Web UI stream preview (`FloatingVideo`) was calling `mpegts.createPlayer()` with all `Config` options (e.g. `enableWorker`, `liveSync`, `headers`) merged into the first `MediaDataSource` argument. mpegts.js only reads `Config` from the optional second argument; unrecognised fields in the first are silently ignored. As a result all player configuration was effectively the library defaults — worker offloading was disabled, latency management had no effect, and the `Authorization: Bearer` header (required for user identification) was never sent. Fixed by splitting into the correct two-argument call. Both `liveBufferLatencyChasing` and `liveSync` have been disabled, eliminating playback-rate fluctuations that caused audible stuttering on live streams. SourceBuffer cleanup thresholds were also relaxed from 10s/5s to 120s/60s to prevent frequent SourceBuffer pauses.
- HTML named entities in XMLTV EPG files are now correctly preserved during lxml parsing. Some EPG providers (particularly French and other European sources) use HTML named entities like `&eacute;`, `&icirc;`, `&uuml;` in channel names, program titles, and metadata. These are not valid XML entities — lxml 6.0.2 with `recover=True` silently drops them, causing characters to go missing (e.g., "Chaîne Télé" becomes "Chane Tl"). This is now fixed by injecting an XML `<!DOCTYPE tv [...]>` internal subset declaring all 252 HTML 4 named entities directly into the byte stream that lxml reads, using a lightweight in-memory wrapper (`_PrependStream`) with zero disk I/O. libxml2 resolves the entities during its normal C-level parse pass — no Python-level preprocessing or temporary files are involved. The DOCTYPE block (~8 KB) is built once at module load from Python's stdlib `html.entities.name2codepoint` and reused for every parse. Files that already declare their own `<!DOCTYPE>` are passed through unchanged. (Closes #1095) — Thanks [@CodeBormen](https://github.com/CodeBormen) for helping with this!
- Duplicate recordings created when EPG sources refresh and re-evaluate series rules (Fixes #940) — Thanks [@CodeBormen](https://github.com/CodeBormen):
  - **Program ID instability**: `parse_programs_for_source()` deletes and recreates all `ProgramData` rows with new auto-increment IDs on every EPG refresh. The dedup set used these IDs, so it never matched after a refresh. Deduplication now uses a stable `(tvg_id, start_time, end_time)` composite key sourced from `Recording.custom_properties.program`.
  - **Secondary guard using wrong times**: The DB guard compared unadjusted program times against offset-adjusted `Recording.start_time`/`end_time`, so it never matched when any DVR pre/post offset was configured. It now queries `custom_properties__program__start_time/end_time` (the original, unadjusted program times stored at recording creation).
  - **No concurrency guard**: Each EPG source refresh fired `evaluate_series_rules.delay()` independently. Concurrent tasks loaded the dedup set before others committed, allowing races. Evaluation is now serialized with `acquire_task_lock` (reusing the existing EPG task pattern). Gracefully degrades if Redis is unavailable — the primary and secondary dedup guards still protect.
- EPG refresh tasks (`refresh_epg_data`) were being killed mid-transaction on large EPG sources. The `soft_time_limit=1700s` introduced in v0.21.0 raised `SoftTimeLimitExceeded`, a subclass of `Exception`, which was swallowed by the existing `except Exception` handler in `parse_programs_for_source`, leaving the database in a partial state with no logged error. `soft_time_limit` has been removed from `refresh_epg_data` and `time_limit` raised to 14400s (4 hours) as a true last-resort ceiling; the existing `TaskLockRenewer` daemon thread continues to renew the Redis lock every 120s for legitimately long-running tasks.

## [0.21.1] - 2026-03-18

### Fixed

- Docker container initialization fixes for PUID/PGID handling — Thanks [@CodeBormen](https://github.com/CodeBormen):
  - Backups failing on previous installations where `/data/backups` already existed: `/data/backups` was missing from the `DATA_DIRS` list in the init script, causing the PUID/PGID ownership migration to skip the directory and leave it with incorrect permissions.
  - Container startup failure on upgrade when data directories reside on external mounts (NFS, SMB/CIFS, FUSE): `chown` failures under `set -e` were crashing the container, breaking setups that worked fine on the previous image. Failures are now collected per-directory and reported as a consolidated warning; the container continues to start and Django reports at runtime if it cannot write a specific directory.
  - Upgrading users running as UID 102 (the internal PostgreSQL system user) instead of the expected UID 1000: the PUID/PGID auto-detect introduced in v0.21.0 read ownership from `/data/db`, which was UID 102 in pre-PUID images, causing Django, file creation, and comskip to all run as the wrong user. PUID/PGID now default to 1000 (matching the original Django UID) rather than auto-detecting from data directory ownership.

## [0.21.0] - 2026-03-17

### Security

- Updated frontend npm dependencies to resolve 1 high-severity vulnerability:
  - Updated `flatted` to 3.4.1, resolving **high** unbounded recursion DoS in the `parse()` revive phase ([GHSA-25h7-pfq9-p65f](https://github.com/advisories/GHSA-25h7-pfq9-p65f))
- Updated `Django` to 6.0.3 and `django-celery-beat` to 2.9.0, resolving new security vulnerabilities:
  - [CVE-2026-25673](https://www.cve.org/CVERecord?id=CVE-2026-25673): Potential denial-of-service vulnerability in URLField via Unicode normalization on Windows (March 3, 2026)
  - [CVE-2026-25674](https://www.cve.org/CVERecord?id=CVE-2026-25674): Potential incorrect permissions on newly created file system objects (March 3, 2026)

### Added

- Configurable sidebar navigation ordering and visibility — Thanks [@jcasimir](https://github.com/jcasimir)
  - Sidebar nav items can be reordered via drag-and-drop in Settings → UI Settings → Navigation.
  - Individual nav items can be hidden from the sidebar using the eye toggle. Hiding an item preserves its position in the order.
  - A "Reset to Default" button restores the role-appropriate default order and clears all hidden items.
  - Order and visibility are saved per-user with optimistic updates and automatic rollback on failure. Changes appear in the sidebar immediately without a page reload.
  - Admin users see a grouped navigation: flat items (`Channels`, `VODs`, `M3U & EPG Manager`, `TV Guide`, `DVR`, `Stats`, `Plugins`) plus collapsible `Integrations` (Connections, Logs) and `System` (Users, Logo Manager, Settings) groups. The `System` group cannot be hidden.
  - Non-admin users see `Channels`, `TV Guide`, and `Settings`, with the `Settings` item not hideable.
- Unit tests for `NotificationCenter`, `NotificationCenterUtils`, and `M3URefreshNotification` components, and for settings form components `DvrSettingsForm`, `NetworkAccessForm`, `ProxySettingsForm`, `StreamSettingsForm`, `SystemSettingsForm`, `UiSettingsForm`. — Thanks [@nick4810](https://github.com/nick4810)
- Unit tests for DVR port resolution (`build_dvr_candidates`) and selective Redis flush behavior in modular mode. — Thanks [@CodeBormen](https://github.com/CodeBormen)
- Floating video player improvements
  - **Title display**: The channel, stream, or VOD title is now shown in the player header bar. Title is passed through from all preview entry points: channel table, stream table, stream connection card, guide, DVR, recording cards, recording details modal, VOD modal, and series modal.
  - **Persistent state**: Size, position, volume level, and mute state are now saved across sessions using a single `dispatcharr-player-prefs` localStorage key. Size and position are restored on next open (clamped to the current viewport); volume and mute are restored when the player initialises.
- New Client Buffer proxy setting: new clients joining an active channel are now positioned a configurable number of seconds behind live rather than a fixed chunk count. The start position is determined by wall-clock chunk receive time (stored as a Redis sorted set alongside the buffer), so the buffer depth is consistent in seconds regardless of stream bitrate. Setting the value to `0` starts clients at live with no buffer. Defaults to 5 seconds. Existing chunk-count gating for the first client connecting to a channel is unchanged. The setting is exposed in Settings → Proxy as "New Client Buffer (seconds)".
- Channel table filter for channels that have stale streams: A new "Has Stale Streams" filter option in the channel table header menu highlights and filters channels containing at least one stale stream. Channels with stale streams are visually distinguished with an orange tint. The filter is mutually exclusive with "Only Empty Channels". - Thanks [@JCBird1012](https://github.com/JCBird1012)
- "Next Highest Channel" numbering mode when creating channels from streams: A new `Next Highest` option is available alongside `Provider`, `Auto`, and `Custom` when creating channels from the Streams table. Selecting it assigns channel numbers starting one above the current highest channel number; the next available number is fetched from the backend at selection time. (Closes #1000) — Thanks [@JCBird1012](https://github.com/JCBird1012)
- TV Guide program cards now display richer metadata — Thanks [@CodeBormen](https://github.com/CodeBormen)
  - **Season/episode badges** (e.g. `S12E06`) extracted from EPG `<episode-num>` elements, `onscreen` episode strings (e.g. `S12 E6`, `S3E21`, `S8 E8 P2/2`), and as a last-resort fallback from description text patterns at parse time (3-tier pipeline). (Closes #1065)
  - **Episode subtitle** shown below the program title on guide cards; falls back to the short description when no subtitle is available.
  - **Status badges**: `LIVE`, `NEW`, `PREMIERE`, and `FINALE` surfaced from EPG flags on both compact cards and the detail modal.
  - **Program detail modal**: Clicking any guide program opens a modal with full program details — poster/icon image, season/episode, subtitle, duration, categories, cast/director/writer credits, content rating, star ratings, production date, original air date, video quality, and external links to IMDb and TMDB where available. Detail data is fetched from a new `GET /api/epg/programs/{id}/` endpoint backed by the new `ProgramDetailSerializer`. Dummy/placeholder programs skip the fetch.
  - **Real-time progress bars**: Currently-airing programs show a green progress bar on their guide card that updates every second via direct DOM manipulation (no React re-renders).
  - **Channel name tooltip**: Hovering the channel logo column shows the channel name.
- Sort icons added to the Group and EPG column headers in the Channels table, and to the Group column header in the Streams table. Clicking a sort icon cycles through ascending/descending/unsorted states. EPG sorting required a backend change (`epg_data__name` added to `ChannelViewSet.ordering_fields`); Group sorting was already supported by the API in both tables. (Closes #854) — Thanks [@CodeBormen](https://github.com/CodeBormen)
- DVR enhancements — Thanks [@CodeBormen](https://github.com/CodeBormen)
  - **Stop Recording**: A new Stop button (distinct from Cancel) cleanly ends an in-progress recording early and keeps the partial file available for playback. The API returns immediately; stream teardown and task revocation happen in a background thread to prevent 504 timeouts. When multiple recordings run simultaneously, stopping one only terminates that recording's proxy client by ID, leaving all others unaffected. (Closes #454)
  - **Extend Recording**: In-progress recordings can be extended by 15, 30, or 60 minutes without interrupting the stream.
  - **Inline metadata editing**: Title and description can now be edited directly in the recording details modal.
  - **Refresh artwork button**: Manually re-run poster resolution on demand from the recording card.
  - **Multi-source poster resolution**: Added pipeline querying EPG, VOD, TMDB, OMDb, TVMaze, and iTunes for richer recording artwork.
  - **Series rules for currently-airing episodes**: Series rules now capture currently-airing episodes in addition to future scheduled ones. (Closes #473)
  - **Search and filter controls**: Added search and filter controls to the recordings list.
  - **Stream generator throttling**: Cached the `ProxyServer` singleton reference per client and throttled Redis resource checks (1 s) and non-owner health checks (2 s), eliminating 3+ Redis round-trips per stream loop iteration.
  - **Automatic crash recovery on worker restart**: A `worker_ready` Celery signal now fires `recover_recordings_on_startup` automatically when the worker starts, so recordings stuck in "recording" status are recovered without manual intervention.
- Account expiration tracking and notifications for M3U profiles
  - A new `exp_date` field on `M3UAccountProfile` stores the account expiration date as a proper `DateTimeField`. For Xtream Codes accounts the field is auto-synced from `custom_properties.user_info.exp_date` on every save (supports both Unix timestamps and ISO date strings). For non-XC M3U accounts the date can be entered manually via the account or profile form.
  - The M3U accounts table now shows an **Expiration** column displaying the earliest expiration date across all profiles for that account (color-coded: red = expired, orange = expiring soon, green = OK). Hovering the cell shows a tooltip with per-profile expiration details including inactive-profile labels.
  - A daily Celery Beat task (`check_xc_account_expirations`) checks all active profiles with an expiration date and manages system notifications: a normal-priority warning is raised for profiles expiring within 7 days; a high-priority alert is raised once the profile has already expired. Warning and expired notifications use separate keys so dismissing the 7-day warning does not suppress the expiration alert.
  - Notifications are also updated immediately when a profile is saved: if the expiration date is cleared or pushed beyond the 7-day window, any existing warning/expired notifications are deleted; if the date falls within the window or is already past, the matching notification is updated in place.
  - Non-XC accounts expose a `DateTimePicker` on both the M3U account form and the profile form.

### Changed

- Dependency updates:
  - `Django` 5.2.11 → 6.0.3 (security patch + major version upgrade; see Security section)
  - `django-celery-beat` ≥2.8.1 → ≥2.9.0 (adds explicit Django 6.0 support)
- When selecting an EPG source for a channel, the EPG source dropdown now only lists enabled (active) EPGs, sorted alphabetically.
- Channels page default splitter ratio changed from 50/50 to 60/40 (channels/streams) so all channel action buttons are visible without scrolling on 1080p displays.
- Frontend component refactoring and cleanup — Thanks [@nick4810](https://github.com/nick4810)
  - `FloatingVideo`, `SeriesModal`, `VODModal`, `SystemEvents`, `M3URefreshNotification`, and `NotificationCenter` significantly reduced in size by separating business logic into dedicated utility modules under `utils/components/` (`FloatingVideoUtils.js`, `SeriesModalUtils.js`, `VODModalUtils.js`, `NotificationCenterUtils.js`).
  - `FloatingVideo` resize handle elements extracted into a standalone `ResizeHandles` sub-component.
  - `YouTubeTrailerModal` extracted into a standalone component (`components/modals/YouTubeTrailerModal.jsx`).
  - `NotificationCenter` and `Sidebar` updated from Mantine dot-notation sub-components (`Popover.Target`, `Popover.Dropdown`, `ScrollArea.Autosize`, `AppShell.Navbar`) to Mantine v7 named imports (`PopoverTarget`, `PopoverDropdown`, `ScrollAreaAutosize`, `AppShellNavbar`).
  - `M3URefreshNotification` now uses the centralized `showNotification()` utility (from `notificationUtils.js`) instead of calling `notifications.show()` directly, bringing it in line with the rest of the app. State updates also converted to functional updater form (`prev => ...`) to eliminate potential stale-closure bugs.
  - `SystemEvents` now imports `format` from `dateTimeUtils` for consistent date/time formatting.
  - Removed a dead `onLogout` handler in `Sidebar` that called `logout()` and `window.location.reload()` but was never wired to any UI element.
- EPG output when no `days` parameter is specified now excludes already-ended programs instead of returning all historical data.

### Fixed

- Single-stream channel creation modal not opening correctly when clicking the channel-creation button on an individual stream row in the Streams table. — Thanks [@JCBird1012](https://github.com/JCBird1012)
- DVR series rule creation failing with a 500 error when the stored `series_rules` data contained corrupted (non-dict) entries. Added type guards on the getter, setter, and generic settings serializer to filter invalid entries on read and write. Hardened the EPG ignore list getters (`prefixes`, `suffixes`, `custom`) with the same pattern. Frontend settings parse and save now validate `series_rules` with `Array.isArray()`, matching the existing EPG field pattern, preventing corrupted data from being round-tripped back to the database. (Fixes #1059) — Thanks [@CodeBormen](https://github.com/CodeBormen)
- TS proxy clients stuck indefinitely in keepalive mode when a stream fails and never recovers (Fixes #1102, #1103) — Thanks [@cmcpherson274](https://github.com/cmcpherson274) & [@CodeBormen](https://github.com/CodeBormen)
  - **Keepalive duration cap**: Non-owner worker clients sending keepalive packets to hold a connection open during failover can now be held at most `MAX_KEEPALIVE_DURATION` seconds (default 300 s). If no real stream data has been received within that window, the client is disconnected with a warning log. The timer resets each time real data resumes, so independent stalls do not accumulate.
  - **`last_active` tracking**: `last_active` is now updated on every keepalive packet and on every real data chunk, so clients actively waiting during a failover are not incorrectly evicted as ghost clients by the heartbeat thread. The heartbeat thread now only refreshes the Redis TTL rather than updating `last_active`, ensuring the ghost-detection check reflects true client activity rather than heartbeat activity.
  - **Buffer reset on stream transition**: A new `reset_buffer_position()` method on `StreamBuffer` clears the in-memory write buffer and partial-packet accumulator when switching between FFmpeg processes. Without this, a partial 188-byte TS packet from the dying FFmpeg process was being prepended to the first bytes from the new FFmpeg process, producing a corrupted TS packet boundary that broke audio decoder sync on the client side. Redis-stored chunks already consumed by clients are unaffected.
  - **`add_chunk()` locking hardened**: The lock scope in `add_chunk()` was expanded to cover the entire partial-packet merge and write-buffer accumulation phase, preventing a race condition between `add_chunk()` and the new `reset_buffer_position()` call.
- uWSGI segfaults caused by mixing threading and gevent concurrency models. The dev and debug uWSGI configs had `threads` and `enable-threads = true` set alongside gevent, which triggers segmentation faults particularly on ARM64/Python 3.13. Removed those options to match the already-correct production config. — Thanks [@jcasimir](https://github.com/jcasimir)
- `Stream.last_seen` and `ChannelGroupM3UAccount.last_seen` model defaults now use `django.utils.timezone.now` instead of `datetime.datetime.now`, eliminating spurious `RuntimeWarning: DateTimeField received a naive datetime` warnings emitted during test database creation and on new record creation when `USE_TZ=True`.
- EPG programme parsing crash when an XMLTV source contains programme titles exceeding 255 characters. Previously, a single oversized title would cause the entire `bulk_create` batch to fail with a database truncation error, silently dropping all programmes in that batch. Titles are now truncated to 255 characters before being saved. (Fixes #1039)
- Container startup failure when `PUID`/`PGID` is set, caused by `/data/db` ownership conflicts between the `postgres` system user (UID 102) and the configured PUID/PGID. PostgreSQL now runs as the PUID/PGID user in AIO mode, eliminating all `chown`-to-UID-102 operations and unifying `/data` ownership. (Fixes #1078) — Thanks [@CodeBormen](https://github.com/CodeBormen)
  - Existing installations where PUID/PGID differs from the current `/data/db` owner are migrated automatically on first startup; a sentinel file prevents redundant recursive `chown` on subsequent boots.
  - PUID/PGID auto-detected from existing data ownership when not explicitly set, avoiding cross-UID `chown` failures on restricted filesystems (NFS `root_squash`, CIFS).
  - PUID/PGID validated as positive non-zero integers before any user/group operations.
  - UID collisions with the `postgres` system user (e.g. PUID=102) are now handled gracefully.
  - Ensured proper variable quoting in the /docker/ directory to guard from inappropriate input
- Floating video player bug fixes
  - **Resize stuck after releasing mouse outside window**: The `mouseup` event is not delivered when the pointer leaves the viewport, leaving the `mousemove` listener active indefinitely. Fixed by checking `event.buttons === 0` at the top of `handleResizeMove`; when no button is held the resize session is torn down immediately.
  - **Drag stuck after releasing mouse outside window**: Same root cause as the resize bug. Fixed by detecting `event.buttons === 0` in the `onDrag` handler and dispatching a synthetic `mouseup` event so react-draggable cleanly ends the drag session.
  - **Player draggable off screen**: The player could be dragged off any edge, making the header (and drag handle) unreachable. The player is now fully bounded: left and top edges are clamped to `x ≥ 0` / `y ≥ 0` so the header is always reachable, and right/bottom edges are clamped to the viewport. Size and position are also re-clamped automatically when the browser window is resized, with proportional scale-down if the saved size exceeds the new viewport.
- Double error notification when saving user preferences: `API.updateMe` was catching errors internally and displaying a notification before re-throwing, causing callers to display a second notification for the same failure.
- Navigation preference saves from concurrent sessions could overwrite each other due to a double-merge race: the frontend was pre-merging `custom_properties` before sending, then the backend merged again against the DB value, causing the second session's write to silently drop keys set by the first. The frontend now sends only the delta; the backend merges authoritatively against the stored value.
- Stale nav item IDs (e.g. from a previous nav structure) are now scrubbed from `navOrder` and `hiddenNav` on the next preference save, preventing unbounded growth of the `custom_properties` JSON field.
- Version update notification persisting after upgrading to the notified version (e.g. "v0.20.2 available" shown while already running v0.20.2). Root cause: `check_for_version_update.delay()` was called from `AppConfig.ready()`, which fires inside Celery prefork pool subprocesses before the broker connection is established, causing the dispatch to fail silently with no log output. Fixed by moving the startup dispatch to the `worker_ready` signal in `celery.py` (consistent with the existing `recover_recordings_on_startup` pattern), and deleting the stale `version-{current_version}` notification at the top of the production check path so it is cleared even when GitHub is unreachable. A WebSocket update is sent immediately on deletion so the frontend badge clears without waiting for the API response.
- VOD orphan cleanup crashing with a `ForeignKeyViolation` (`IntegrityError`) when a concurrent refresh task created a new `M3UMovieRelation` or `M3USeriesRelation` for a movie/series between the orphan-detection query and the `DELETE` SQL. Both `orphaned_movies.delete()` and `orphaned_series.delete()` are now wrapped in `try/except IntegrityError`; affected records are skipped with a warning and will be cleaned up on the next scheduled run.
- XC stream refresh crashing with a `null value in column "name"` database error when a provider returns streams with a null or empty name. Affected streams are now assigned a generated fallback name in the format `<account name> - <stream_id>` so the refresh completes successfully and the stream remains accessible. A warning is logged for each affected stream.
- 504 Gateway Timeout when saving M3U group settings on slower hardware (e.g. Synology NAS). Replaced per-row `update_or_create()` loops with `bulk_create(update_conflicts=True)` wrapped in `transaction.atomic()` for both `ChannelGroupM3UAccount` and `M3UVODCategoryRelation`, reducing hundreds of individual DB round-trips to a single query per model. (Fixes #745) — Thanks [@nickgerrer](https://github.com/nickgerrer)
- Improved frontend table stability during M3U imports: Fixed incorrect default `state` initialization (`[]` → `{}`) in `CustomTable` to match TanStack Table v8's expected state object shape. Added `autoResetPageIndex: false` and `autoResetExpanded: false` to prevent TanStack Table from issuing internal state resets on data updates. Memoized `processedData` in `M3UsTable` to avoid redundant sort/filter recomputation on re-renders. - Thanks [@marcinolek](https://github.com/marcinolek)
- `debian_install.sh` hardened for non-UTF8 environments (common in minimal LXC containers) - Thanks [@marcinolek](https://github.com/marcinolek)
  - Added `setup_locales` step that installs the `locales` package, enables `en_US.UTF-8`, regenerates locales, and exports `LANG`/`LC_ALL` before any other work runs, preventing PostgreSQL from defaulting to `SQL_ASCII` encoding.
  - PostgreSQL database creation now explicitly passes `-E UTF8` to `createdb`.
  - `PATH` in the Celery worker, Celery Beat, and Daphne systemd service files extended to include `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`, fixing failures where background tasks could not locate `ffmpeg` or `ffprobe`.
- `is_adult` field parsing now guards against invalid values (e.g. the string `"None"`) that providers may send instead of a valid integer, preventing a `ValueError` crash during M3U/XC stream refresh. A new `parse_is_adult()` helper wraps the cast in a `try/except`, returning `False` for anything that cannot be interpreted as `1`. (Fixes #1061) — Thanks [@JCBird1012](https://github.com/JCBird1012)
- M3U EXTINF attribute parsing for values containing `=` or `==` (e.g. base64-padded `tvg-logo` URLs, catchup tokens with query strings). The previous regex used `[^\s]+` for the key pattern, allowing `=` signs inside a quoted value to be greedily absorbed into the next attribute's key name, causing that attribute and all subsequent ones on the line to be silently dropped. Changed to `[^\s=]+` so the key match always stops at the first `=`. (Fixes #1055) - Thanks [@JCBird1012](https://github.com/JCBird1012)
- Celery worker memory leak during M3U/XC refresh causing 20–80 MB growth per cycle with no reclamation (Fixes #1012, #1053) - Thanks [@CodeBormen](https://github.com/CodeBormen)
  - Restructured `refresh_single_m3u_account()` with a `try/finally` that guarantees `del` of large data structures runs before Celery's `gc.collect()`, and lock release on all exit paths (success, exception, early return)
  - Re-enabled batch data cleanup in `process_m3u_batch_direct()` (was commented out)
  - Added `CELERY_WORKER_MAX_MEMORY_PER_CHILD = 512 MB` as a safety net against pymalloc arena fragmentation
- EPG output was filtering programs using `start_time__gte=now` when the `days` parameter was specified, which caused currently-airing programs (started before the request time but not yet ended) to be omitted from the XML output. This produced a gap in clients' guides immediately after an EPG refresh, lasting until the next program started. Fixed by changing the filter to `end_time__gte=now` so any program that has not yet finished is included.
- TS proxy connection slot leaks and TOCTOU races in stream initialization (Fixes #947) - Thanks [@CodeBormen](https://github.com/CodeBormen)
  - **TOCTOU race in slot reservation**: `get_stream()` previously used a `GET`→check→`INCR` sequence, allowing concurrent requests to both read the same count below the limit and both reserve a slot, silently exceeding `max_streams`. Replaced with an atomic `INCR`-first pattern: increment unconditionally, check the result, roll back with `DECR` if over capacity. — Thanks [@patchy8736](https://github.com/patchy8736)
  - **Leak on URL generation failure**: `generate_stream_url()` called `get_stream()` (which `INCR`s the counter) but had no cleanup path if subsequent DB lookups or URL construction failed. The post-`get_stream()` block is now wrapped in a `try/except` that calls `release_stream()` on any error.
  - **Leak on retry-loop timeout**: the retry loop in `stream_ts()` called a bare `get_stream()` on the first failure to classify the error reason. If a slot was available, this `INCR`'d the counter and set Redis keys that were never released when the loop timed out. A `release_stream()` call is now issued before returning 503.
  - **Leak on `initialize_channel()` failure**: when `initialize_channel()` returned `False`, the connection slot allocated by the preceding `get_stream()` was never released. A `connection_allocated` flag now tracks whether this request performed the `INCR` (fresh initialization vs. joining an existing channel), and `release_stream()` is called guarded by that flag to prevent incorrect decrements when attaching to an already-running channel.
  - **Safety net for unexpected exceptions**: the outer `except` in `stream_ts()` now checks `connection_allocated` and calls `release_stream()` as a last-resort cleanup for any unhandled exception that escapes before the channel is handed off to the stream lifecycle.
  - **`release_stream()` now returns `bool`** and adds a metadata-hash fallback: if the primary `channel_stream` / `stream_profile` Redis keys have already been cleaned up by the proxy, it recovers `stream_id` and `profile_id` from the channel's metadata hash and clears those fields atomically to prevent duplicate `DECR`s on repeated calls. — Thanks [@patchy8736](https://github.com/patchy8736)
  - **`update_stream_profile()` uses a Redis pipeline** for the old-profile DECR + key update + new-profile INCR sequence, preventing counter drift if the process crashes between operations.
  - **`stream_generator._cleanup()`** now falls back to `Stream.objects.get()` when the channel UUID resolves to a preview flow rather than a normal channel, rather than silently skipping the slot release.
  - **VOD `cleanup_persistent_connection()`** fallback DECR is now conditional: it only decrements the profile counter when the connection tracking key had already expired by TTL (i.e., `remove_connection()` would have skipped the DECR), preventing double-decrements when the key is still present.
- Ghost clients and channels stuck in `INITIALIZING` state in the TS proxy (Fixes #695, #669) — Thanks [@CodeBormen](https://github.com/CodeBormen)
  - **`INITIALIZING` added to cleanup grace period monitoring**: channels stuck in `INITIALIZING` are now surfaced by the cleanup task and torn down, preventing indefinite hangs when stream startup fails.
  - **Orphaned channel cleanup validates client SET entries**: the cleanup task now cross-checks client SET members against actual metadata hashes; ghost SET entries are removed and the channel is torn down cleanly when no real clients remain.
  - **Stats page self-heals**: ghost client SET entries are detected and removed when reading channel stats, preventing stale entries from inflating the active-client count.
  - **`remove_ghost_clients()` extracted to `ClientManager`**: ghost-detection logic is now a single authoritative helper, callable with an optional pre-fetched `client_ids` set to eliminate a redundant Redis `SMEMBERS` round-trip when the caller already holds the set.
  - **Ownership TTL fallback**: the error-state writer now triggers via ownership check _or_ state guard fallback, so a channel stuck in a pre-active state is correctly marked `ERROR` even when the ownership TTL expired during retries.
  - **Missing `SOURCE_BITRATE` / `FFMPEG_BITRATE` metadata constants** added to `ChannelMetadataField`, preventing `AttributeError` on detailed channel stats reads.
- TS proxy client stream lag recovery now only bumps clients forward when their next required chunk has genuinely expired from Redis (TTL), rather than unconditionally jumping if they fell more than 50 chunks behind. Clients are repositioned to the oldest available chunk (minimum data loss) using an atomic server-side Lua binary search, falling back to near the buffer head if nothing is available.
- TS proxy streams dying after 30–200 seconds in multi-worker uWSGI/Celery deployments, caused by three interrelated bugs. (Fixes #992, #980) - Thanks [@PFalko](https://github.com/PFalko)
  - **Double ProxyServer instantiation**: `ProxyConfig.ready()` called `TSProxyServer()` directly while `TSProxyConfig.ready()` also called `TSProxyServer.get_instance()`, creating two instances per worker — each with its own cleanup thread. The orphaned thread could not extend ownership because it had no entries in `stream_managers`. Fixed by using `TSProxyServer.get_instance()` in `ProxyConfig.ready()`.
  - **`flushdb()` on every Redis client init**: `RedisClient.get_client()` called `client.flushdb()` whenever `_client` was `None`. Celery autoscale (`--autoscale=6,1`) spawning new workers mid-stream triggered this path, nuking all Redis keys including active ownership keys, client records, and channel metadata. Removed the `flushdb()` call entirely.
  - **No recovery from expired ownership**: `get_channel_owner()` called `redis.get()` twice inside a lambda (TOCTOU race — key could expire between calls); `extend_ownership()` silently returned `False` on expiry with no re-acquisition; and the non-owner cleanup path unconditionally killed streams even when the worker held the `stream_manager`. Fixed with a single `GET` in `get_channel_owner()`, re-acquisition via atomic `SET NX EX` in `extend_ownership()`, and a re-acquisition attempt with client-aware cleanup deferral in the cleanup thread.
- `get_instance()` deadlock: if `ProxyServer()` raised an exception during singleton construction, `_instance` was left permanently as the `_INITIALIZING` sentinel, causing all subsequent `get_instance()` callers to spin in an infinite `gevent.sleep()` loop. Construction is now wrapped in `try/except`; on failure `_instance` resets to `None` so the next call can retry.
- Non-atomic ownership acquisition in `try_acquire_ownership()`: replaced the separate `setnx()` + `expire()` calls with a single atomic `SET NX EX`, eliminating the race window where a process crash between the two calls could leave an ownership key with no TTL (permanent ownership lock).
- DVR bug fixes — Thanks [@CodeBormen](https://github.com/CodeBormen)
  - **Duplicate recording execution**: `run_recording.apply_async(countdown=...)` exceeded Redis' default `visibility_timeout` (3600 s) for recordings scheduled more than one hour out, causing Redis to redeliver the task to multiple workers simultaneously and producing corrupted output files. Replaced `apply_async` with `ClockedSchedule` + `PeriodicTask` for database-backed one-shot scheduling that survives restarts and upgrades without the redelivery race. `run_recording` also now exits immediately if the recording is already in progress, completed, or stopped. `revoke_task()` cleans up both the `PeriodicTask` and its orphaned `ClockedSchedule` on execution. (Fixes #940, #641)
  - **Stream reconnection resilience**: Recordings now survive transient network drops with automatic reconnection retrying up to 5 times and appending to the existing file. DB operations use exponential-backoff retry for transient database errors throughout the recording lifecycle.
  - **Crash recovery pipeline**: On worker restart, recordings stuck in "recording" status have their segments concatenated and remuxed. Remux sanity checks reject MKV output that is less than 50% the size of a previous MKV (duplicate-task overwrite) or less than 10% of the source TS (corrupt first attempt); the source `.ts` is preserved for manual recovery on all failure paths. (Fixes #619, #624)
  - **Output file collision**: Fixed collision when multiple tasks targeted the same filename.
  - **WebSocket deadlock**: `send_websocket_update()` was deadlocking the gevent event loop, causing one recording's WebSocket events to block all other simultaneous recordings.
  - **DVR client isolation**: Stop and Cancel operations now identify the target client by recording ID (via `User-Agent: Dispatcharr-DVR/recording-{id}`), ensuring only the correct proxy client is torn down and never affecting other recordings on the same channel.
  - **Accidental stream termination on delete**: `destroy()` now only calls `_stop_dvr_clients()` for in-progress recordings, preventing stream termination when deleting a completed recording.
  - **Recording card logos**: Logos were not displaying due to a channel summary API shape mismatch.
  - **Logo fetch negative cache**: Added negative cache for failed remote logo fetches so dead CDNs no longer block Daphne workers on repeated requests.
  - **Artwork fuzzy-match sanitisation**: Poster artwork fuzzy-matching against external APIs (TMDB, OMDb, etc.) was producing incorrect results for channels with names like "USA A&E SD\*"; channel-name strings are now sanitised before querying external sources.
  - **Series modal "No upcoming episodes"**: Fixed due to a missing `_group_count` merge and an incorrect time filter.
  - **Series rule cleanup**: Deleting a series rule left orphaned recordings and stale Guide indicators; rule deletion now cleans up all associated recordings. Orphaned recordings with no parent rule are also cleaned up automatically. (Fixes #1041)
  - **Series rule timezone calculation**: Recurring rules silently dropped scheduled recordings for users in UTC-negative timezones after 4 pm local time. (Fixes #1042)
  - **Recording modal TDZ crash**: Modal crashed on load in production bundles due to a Temporal Dead Zone error — editing state was referenced before its declaration in the minified bundle.
  - **Description textarea focus loss**: The description textarea lost focus immediately when opened because the inline editing component was remounting on every render.
  - **WebSocket-driven refresh**: Replaced all manual `fetchRecordings()` polling calls with debounced WebSocket-driven refresh so the recordings list stays up to date without redundant API requests.
  - **comskip exit code handling**: comskip treated exit code 1 ("no commercials found") as a fatal error, causing post-processing to fail on clean recordings. Exit code 1 is now recognised as a successful no-op.
  - **Differentiated WebSocket notification events**: `recording_stopped`, `recording_cancelled` (in-progress cancel), and `recording_deleted` with a `was_in_progress` flag now allow the frontend to display distinct "Recording stopped", "Recording cancelled", and "Recording deleted" toasts.
  - **Duplicate series rule evaluation race**: Creating a series rule fired `evaluate_series_rules.delay()` in the API view while the frontend immediately called the synchronous evaluate endpoint, racing to create duplicate recordings for the same program. Removed the redundant async call from the API; the frontend's explicit evaluate call is now the sole evaluation path.
  - **Recording card S/E badge overlap**: Season/episode badges were overlapping and metadata was hidden on the recording card.
  - **Orphaned recording fallback in series modal**: When a series rule no longer exists, the recurring rule modal now shows a "Delete Recording" button for the orphaned recording instead of failing silently.
- Modular mode deployment hardening — Thanks [@CodeBormen](https://github.com/CodeBormen)
  - **Postgres version check with restricted DB users**: The version check was connecting to the hardcoded `postgres` database, which fails when the configured user lacks access to it. Changed to use `$POSTGRES_DB` so the check works with least-privilege database users. (Fixes #1045)
  - **DVR recording broken in modular mode**: Internal TS stream URL candidates hardcoded port `9191`, so recordings failed when `DISPATCHARR_PORT` was set to any other value. URL construction now reads `DISPATCHARR_PORT` from the environment via the new `build_dvr_candidates()` helper. `DISPATCHARR_PORT` is also now explicitly passed to the Celery container in `docker-compose.yml`.
  - **Selective Redis flush in modular mode**: `wait_for_redis.py` now performs a targeted flush in modular mode — clearing stale stream locks, proxy metadata, and server-state keys — while preserving Celery broker and result-backend keys. Previously either a full `flushdb()` (which wiped Celery queues) or no flush at all was performed.
  - **Redis wait stripping environment variables**: The modular-mode Redis readiness check ran as a uWSGI `exec-pre` hook, which executes under `su -` and strips Docker environment variables, making `DISPATCHARR_ENV` and `REDIS_HOST` unavailable. Moved to the container entrypoint so all env vars are present.
  - **Stale environment variables after container restart**: `/etc/profile.d/dispatcharr.sh` was only written on the first container run; restarts with changed env vars (e.g. a rotated `POSTGRES_PASSWORD`) retained stale values. The file is now truncated and rewritten on every startup. `/etc/environment` entries are likewise updated rather than skipped when a key already exists. All exported values are now quoted to prevent breakage from special characters.
  - **Celery entrypoint startup timeouts**: The JWT key wait and migration wait loops had no timeout, leaving the Celery worker hanging indefinitely if the web container was stuck. Each loop now times out (120 s for JWT, 300 s for migrations) and exits with a clear diagnostic message. The migration readiness check is also replaced from a fragile `showmigrations | grep` pattern to `migrate --check`, which exits cleanly on both unapplied migrations and connection errors.
  - **Service startup ordering**: `depends_on` entries for `db` and `redis` in `docker-compose.yml` upgraded from plain name-link ordering to `condition: service_healthy`, ensuring containers wait for actual readiness signals before starting.
  - **`host.docker.internal` resolution on Linux**: Added `extra_hosts: host.docker.internal:host-gateway` to the web service in `docker-compose.yml` so Linux hosts resolve `host.docker.internal` the same way Docker Desktop does on macOS/Windows.

## [0.20.2] - 2026-03-03

### Security

- Updated frontend npm dependencies to resolve 2 high-severity vulnerabilities:
  - Updated `minimatch` to ≥10.2.3, resolving **high** ReDoS via matchOne() combinatorial backtracking with multiple non-adjacent GLOBSTAR segments ([GHSA-7r86-cg39-jmmj](https://github.com/advisories/GHSA-7r86-cg39-jmmj))
  - Updated `rollup` to ≥4.58.1, resolving **high** Arbitrary File Write via Path Traversal ([GHSA-mw96-cpmx-2vgc](https://github.com/advisories/GHSA-mw96-cpmx-2vgc))

### Fixed

- EPG filter regression in channel table (introduced in 0.20.0 channel store refactor): The EPG filter dropdown was showing all EPG sources regardless of whether they had any channels assigned, and the "No EPG" option was never displayed. Fixed by annotating EPGSource records with a `has_channels` flag (via a lightweight `EXISTS` subquery) so only active EPG sources with at least one channel assigned appear as filter options. "No EPG" now appears only when at least one channel globally has no EPG assigned; this is determined by a second `EXISTS` query embedded directly in the paginated channel response (`has_unassigned_epg_channels`), avoiding any additional network requests.
- Stale stream rows missing hover effect: Stale streams in the streams table had no hover color change, unlike channels with no streams assigned. Converted the inline `backgroundColor` style to a CSS class (`stale-stream-row`) so the `:hover` rule can apply correctly. Applied the same fix to the channel-streams sub-table, where the teal expanded-row background caused the semi-transparent red tint to visually mismatch; the sub-table now uses a pre-blended solid color via `color-mix()` to match the appearance of stale rows in the main streams table.
- Channel table onboarding shown when filter returns zero results: The channel store refactor changed to loading only channel IDs instead of full channel objects, leaving `Object.keys(channels).length` always `0` and incorrectly triggering the onboarding state on any empty filter. Fixed by checking `channelIds.length` instead.
- TV Guide scrolls to position 0 when a filter yields no results: Applying any filter that temporarily empties the channel list (e.g. switching directly between two channel groups, or typing a search query that matches nothing) caused the guide to show a blank/empty view with no programs visible. The `VariableSizeList` unmounts when `filteredChannels` becomes empty, destroying its DOM node and resetting `scrollLeft` to 0. On remount the scroll position was never restored because `initialScrollComplete` was still `true`. Fixed by saving the user's current scroll position when the channel list empties mid-transition, then restoring it once new channels have loaded. On first load the guide still scrolls to the current time as before.
- `debian_install.sh` regressions after `uv` migration on clean/minimal Debian installs: fixed pip-less venv (`ensurepip`), missing `gunicorn` for the systemd unit, and inconsistent `DJANGO_SECRET_KEY` availability (now persisted to `.env` via `EnvironmentFile`). Docker unaffected. - Thanks [@marcinolek](https://github.com/marcinolek)

## [0.20.1] - 2026-02-26

### Fixed

- Login form disabled after token expiry: The login button was permanently rendered as disabled ("Logging you in...") on page load after a session expired, preventing users from logging back in. A regression in v0.20.0 caused `LoginForm` to check `if (user)` to detect an already-authenticated reload, but the Zustand auth store initializes `user` as a truthy empty object `{ username: '', email: '', user_level: '' }`, so the loading state was set immediately on every mount. Reverted to pre-regression behavior. (Fixes #1029)

## [0.20.0] - 2026-02-26

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

- API key authentication: Added support for API key-based authentication as an alternative to JWT tokens. Users can generate and revoke their own personal API key from their profile page, enabling programmatic access for scripts, automations, and third-party integrations without exposing account credentials. Keys authenticate via the `Authorization: ApiKey <key>` header or the `X-API-Key: <key>` header. Admin users can additionally generate and revoke keys on behalf of any user.
- Lightweight channel summary API endpoint: Added a new `/api/channels/summary/` endpoint that returns only the minimal channel data needed for TV Guide and DVR scheduling (id, name, logo), avoiding the overhead of serializing full channel objects for high-frequency UI operations.
- Custom Dummy EPG subtitle template support: Added optional subtitle template field to custom dummy EPG configuration. Users can now define subtitle patterns using extracted regex groups and time/date placeholders (e.g., `{starttime} - {endtime}`). (Closes #942)
- Event-driven webhooks and script execution (Integrations): Added new Integrations feature that enables event-driven execution of custom scripts and webhooks in response to system events. (Closes #203)
  - **Supported event types**: channel lifecycle (start, stop, reconnect, error, failover), stream operations (switch), recording events (start, end), data refreshes (EPG, M3U), and client activity (connect, disconnect)
  - **Event data delivery**: available as environment variables in scripts (prefixed with `DISPATCHARR_`), POST payloads for webhooks, and plugin execution payloads
  - **Plugin support**: plugins can subscribe to events by specifying an `events` array in their action definitions
  - **Connection testing**: test endpoint with dummy payloads for validation before going live
  - **Custom HTTP headers**: webhook connections support configurable key/value header pairs
  - **Per-event Jinja2 payload templates**: each enabled event can have its own template rendered with the full event payload as context; rendered output is sent as JSON (with `Content-Type: application/json` set automatically) if valid, or as a raw string body otherwise
  - **Tabbed connection form**: Settings, Event Triggers, and Payload Templates organized into separate tabs for clarity
- Cron scheduling support for M3U and EPG refreshes: Added interactive cron expression builder with preset buttons and custom field editors, plus info popover with common cron examples. Refactored backup scheduling to use shared ScheduleInput component for consistency across all scheduling interfaces. (Closes #165)
- Channel numbering modes for auto channel sync: Added three channel numbering modes when auto-syncing channels from M3U groups:
  - **Fixed Start Number** (default): Start at a specified number and increment sequentially
  - **Use Provider Number**: Use channel numbers from the M3U source (tvg-chno), with configurable fallback if provider number is missing
  - **Next Available**: Auto-assign starting from 1, skipping all used channel numbers
    Each mode includes its own configuration options accessible via the "Channel Numbering Mode" dropdown in auto sync settings. (Closes #956, #433)
- Legacy NumPy for modular Docker: Added entrypoint detection and automatic installation for the Celery container (use `USE_LEGACY_NUMPY`) to support older CPUs. - Thanks [@patrickjmcd](https://github.com/patrickjmcd)
- `series_relation` foreign key on `M3UEpisodeRelation`: episode relations now carry a direct FK to their parent `M3USeriesRelation`. This enables correct CASCADE deletion (removing a series relation automatically removes its episode relations), precise per-provider scoping during stale-stream cleanup.
- Streamer accounts attempting to log into the web UI now receive a clear notification explaining they cannot access the UI but their stream URLs still work. Previously the login button would silently stop with no feedback.

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
- XC API `get_series` now includes `tmdb_id` and `imdb_id` fields, matching `get_vod_streams`. Clients that use TMDB enrichment (e.g. Chillio) can now resolve clean series titles and poster images. - Thanks [@firestaerter3](https://github.com/firestaerter3)
- Stats page "Now Playing" EPG lookup updated to use `channel_uuids` directly (the proxy stats already key active channels by UUID), removing the need for a UUID→integer ID conversion step introduced alongside the lazy channel-fetch refactor. Stream preview sessions (which use a content hash rather than a UUID as their channel ID) are now filtered out before any API call is made, preventing a backend `ValidationError` on both the `current-programs` and `by-uuids` endpoints when a stream preview is active on the Stats page.

### Fixed

- Fixed admin permission checks inconsistently using `is_superuser`/`is_staff` instead of `user_level>=10`, causing API-created admin accounts to intermittently see the setup page, lose access to backup endpoints, and miss admin-only notifications. `manage.py createsuperuser` now also correctly sets `user_level=10`. (Fixes #954) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Channel table group filter sort order: The group dropdown in the channel table is now sorted alphabetically.
- DVR one-time recording scheduling: Fixed a bug where scheduling a one-time recording for a future program caused the recording to start immediately instead of at the scheduled time.
- XC API `added` field type inconsistencies: `get_live_streams` and `get_vod_info` now return the `added` field as a string (e.g., `"1708300800"`) instead of an integer, fixing compatibility with XC clients that have strict JSON serializers (such as Jellyfin's Xtream Library plugin). (Closes #978)
- Stream Profile form User-Agent not populating when editing: The User-Agent field was not correctly loaded from the existing profile when opening the edit modal. (Fixes #650)
- VOD proxy connection counter leak on client disconnect: Fixed a connection leak in the VOD proxy where connection counters were not properly decremented when clients disconnected, causing the connection pool to lose track of available connections. The multi-worker connection manager now correctly handles client disconnection events across all proxy configurations. Includes three key fixes: (1) Replaced GET-check-INCR race condition with atomic INCR-first-then-check pattern in both connection managers to prevent concurrent requests exceeding max_streams; (2) Decrement profile counter directly in stream generator exit paths instead of deferring to daemon thread cleanup; (3) Decrement profile counter on create_connection() failure to release reserved slots. (Fixes #962, #971, #451, #533) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- XC profile refresh credential extraction with sub-paths: Fixed credential extraction in `get_transformed_credentials()` to use negative indices anchored to the known tail structure instead of hardcoded indices that broke when server URLs contained sub-paths (e.g., `http://server.com/portal/a/`). This ensures XC accounts with sub-paths in their server URLs work correctly for profile refreshes. (Fixes #945) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- XC EPG URL construction for accounts with sub-paths or trailing slashes: Fixed EPG URL construction in M3U forms to normalize server URL to origin before appending `xmltv.php` endpoint, preventing double slashes and incorrect path placement when server URLs include sub-paths or trailing slashes. (Fixes #800) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- Auto channel sync duplicate channel numbers across groups: Fixed issue where multiple auto-sync groups starting at the same number would create duplicate channel numbers. The used channel number tracking now persists across all groups in a single sync operation, ensuring each assigned channel number is globally unique.
- Modular mode PostgreSQL/Redis connection checks: Replaced raw Python socket checks with native tools (`pg_isready` for PostgreSQL and `socket.create_connection` for Redis) in modular deployment mode to prevent indefinite hangs in Docker environments with non-standard networking or DNS configurations. Now properly supports IPv4 and IPv6 configurations. (Fixes #952) - Thanks [@CodeBormen](https://github.com/CodeBormen)
- VOD episode UUID regeneration on every refresh: a pre-emptive `Episode.objects.delete()` in `refresh_series_episodes` ran before `batch_process_episodes`, defeating its update-in-place logic and forcing all episodes to be recreated with new UUIDs on every refresh. Clients (Jellyfin, Emby, Plex, etc.) with cached episode paths received 500 errors until a full library rescan. Removing the delete allows episodes to be updated in place with stable UUIDs. (Fixes #785, #985, #820) - Thanks [@znake-oil](https://github.com/znake-oil)
- VOD stale episode stream cleanup scoped incorrectly per provider: when a provider removed a stream from a series, `batch_process_episodes` could delete episode relations belonging to a different provider version of the same series (e.g. EN vs ES) that had deduped to the same `Series` object via TMDB/IMDB ID. Cleanup is now scoped to the specific `M3USeriesRelation` that was queried.

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
- M3U/EPG tasks downloading endlessly for large files: Fixed the root cause where the Redis task lock (300s TTL) expired during long downloads, allowing Celery Beat to start competing duplicate tasks that never completed. Added a `TaskLockRenewer` daemon thread that periodically extends the lock TTL while a task is actively working, applied to all long-running task paths (M3U refresh, M3U group refresh, EPG refresh, EPG program parsing). Also adds an HTTP timeout to M3U download requests, streams M3U downloads directly to a temp file on disk instead of accumulating the entire file in memory, and adds Celery task time limits as a safety net against runaway tasks. (Fixes #861) - Thanks [@CodeBormen](https://github.com/CodeBormen)

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
