# Media Library

Media Library imports movies and TV episodes from Plex, Emby, Jellyfin,
explicitly allowed local filesystem roots, and completed Dispatcharr DVR
recordings. It can export normalized Dispatcharr VOD content as
media-server-compatible STRM and NFO directory trees.

## Container paths

Set `MEDIA_LIBRARY_IMPORT_ROOTS` to an `os.pathsep`-separated list of
container-side media roots. In modular deployments, mount every root at the
same path in both the web and Celery containers. Import mounts should normally
be read-only. Import roots intentionally default to an empty list: until this
setting is configured, the directory browser displays a configuration message
and cannot expose the container filesystem.

Set `MEDIA_LIBRARY_EXPORT_ROOTS` to the container-side roots under which export
targets may be created. The default is `/data/media/strm`.

Examples:

```yaml
volumes:
  - /srv/media:/media:ro
  - /srv/jellyfin-dispatcharr:/exports
environment:
  - MEDIA_LIBRARY_IMPORT_ROOTS=/media
  - MEDIA_LIBRARY_EXPORT_ROOTS=/exports
```

The export mount must be read-write in Dispatcharr and every Celery worker.
The consuming media server may mount that same host directory read-only.

Local paths are canonicalized and revalidated whenever they are scanned or
played. A symlink is accepted only when its resolved destination remains below
an allowed import root.

The permanent **DVR** source uses the recording library directory
configured under **Settings > DVR Settings** (default `/data/recordings`). It
can be disabled but not edited or deleted. Completed recordings are classified
and upserted individually when the source is enabled; they do not rescan the
recording library. **Sync** remains available for full manual reconciliation.
Metadata edits refresh the managed sidecar and normalized VOD item, while
recording deletion removes only that file's VOD relations and queues affected
STRM targets for rebuilding. DVR recording paths are validated against
that dedicated directory rather than `MEDIA_LIBRARY_IMPORT_ROOTS`. A completed
recording also receives a same-basename movie or episode NFO sidecar containing
the available EPG title, plot, season/episode, air date, rating, genres,
channel, credits, cast, and stable identifiers before synchronization begins.
When a Media Library TMDB key is configured, DVR artwork lookup uses the shared
unambiguous movie/show matcher and writes a resolved poster URL into the NFO.
Manual DVR synchronization refreshes Dispatcharr-managed sidecars before
scanning so newly resolved artwork reaches the normalized VOD record; an
existing operator-managed NFO is preserved.

When automatic Comskip is enabled, the initial DVR import waits for Comskip to
reach a terminal state. A successful cut records the final duration in seconds
and final file size, rewrites the managed NFO, and then synchronizes VOD. Mark,
no-commercial, missing-binary, and failure outcomes also synchronize the intact
recording so post-processing cannot silently prevent it from entering VOD.
Running **Sync** on the DVR Media Library also repairs Dispatcharr-managed
sidecars created before this sequencing fix when their stored Comskip file
size or exact duration is stale.

## Reusable directory browser

The frontend `SafeDirectoryBrowser` component uses the admin-only
`/api/core/directories/browse/` endpoint. The endpoint accepts a named scope,
not an arbitrary root. Each scope is registered server-side in
`SAFE_DIRECTORY_BROWSER_SCOPES` and points to an explicit root setting. Media
Library currently registers import and export scopes; other Dispatcharr
features can reuse the component by registering their own scope without
granting general filesystem access.

The source editor can test an unsaved local or remote configuration before it
is persisted. Remote tests also discover supported movie and TV libraries so a
subset can be selected before the first import. Each selected Plex, Emby, or
Jellyfin library can retain the server-detected media type or override it as
Movies, TV shows, or Movies and TV. The effective per-library type determines
which provider collections the synchronization enumerates. Creating a source
does not immediately import it; use **Sync** or configure a non-zero automatic
import interval.

Imports use provider metadata, filenames, local NFO files, and optional TMDB
enrichment. They do not probe media with ffprobe. TMDB/title-year matches are
accepted only when they produce one unambiguous candidate. Stale relations are
removed only from library/location scopes that completed an authoritative
scan; normalized VOD content is retained while another source relation exists.
Removing or disabling a local location, deselecting a remote library, changing
provider type, or disabling VOD integration explicitly retires the affected
scopes without waiting for another provider scan.

The administrator-only **Settings > Media Library** section stores a write-only
TMDB v3 API key using the current `CoreSettings` group mechanism. Its help
dialog links directly to TMDB's API-key setup page. A key may instead be
supplied with `TMDB_API_KEY`. API responses expose configuration status only,
never the key, and a saved key is removed only with the explicit clear control.

**Prefer NFO metadata** is enabled by default. In that mode NFO/local values
take priority and TMDB fills missing fields. When disabled, TMDB values take
priority and NFO data remains the fallback. Stable identifiers found in NFO
files can still be used for confident TMDB lookups in either mode. This
priority is reapplied during later authoritative local scans, so changing an
NFO file or changing the preference can update previously imported metadata;
filename-only guesses do not overwrite populated metadata.

For local media, Dispatcharr recognizes same-basename movie and episode NFO
files, `movie.nfo`, `episode.nfo`, and parent `tvshow.nfo` files. It imports
titles, plots, years, ratings, runtimes, genres, people, content ratings,
studio, country, language, provider identifiers, and artwork references where
present. Multi-episode NFO files are supported.

## Managing imports

The **View scan** drawer receives live WebSocket progress with polling as a
fallback. It shows discovery, import, and cleanup stages; per-run counts;
authoritative location/library results; ambiguity counts; messages; and start
and finish times. Queued work can be removed, active work can be cancelled, and
finished history can be cleared. These operations and all Media Library
configuration are administrator-only.

Plex supports the PIN sign-in flow without returning its token to the browser.
Emby and Jellyfin can use either a token or account credentials. Secret fields
are write-only, omitted edits preserve existing values, and clearing a saved
secret is always explicit.

Every import source has a configurable VOD provider priority. It defaults to
10,000 and is copied to the source's managed M3U account, so normal VOD
playback, artwork selection, and failover use the same higher-number-first
ordering as directly configured M3U accounts.

## STRM playback

Each export target requires:

- a Dispatcharr base URL reachable by the consuming media server;
- an optional target-wide stream limit.

Export targets are opt-in: administrators choose the normalized movies and TV
series that belong in each target. The selection dialog supports individual
titles plus provider, category, text, and selected-state filters. Movies also
support **Select all movies**. A global TV-series selection is intentionally
unavailable because discovering every episode can issue a large burst of
provider requests; TV series can instead be selected individually or through a
provider/category/search filter.

Each target can set a selected-series refresh interval in hours. Zero (the
default) disables it. A scheduled refresh updates episode details for selected
XC series and then rebuilds that target's STRM/NFO snapshot. Other imported
provider types continue to receive updates through their normal source sync.
If any selected XC series cannot return a usable episode list, the refresh and
export run is marked failed and the existing completed snapshot is retained.

STRM playback uses the global **Settings > Network Access > Stream Endpoints**
CIDR policy, consistent with other Dispatcharr stream URLs.

Generated STRM files contain a target-specific Dispatcharr playback URL. They
never contain provider tokens, Dispatcharr JWTs, API keys, usernames, or
passwords. Disabling the target immediately revokes its URLs. Rotating its
playback identifier revokes the old URLs and queues a rebuild.

Playback continues through the current Dispatcharr VOD proxy, including active
relation selection, provider failover, provider-profile capacity, HTTP Range
handling, and Redis-backed multi-worker sessions.

STRM export is limited to selected movies and episodes that have at least one
active XC or local-filesystem relation and no Plex, Emby, or Jellyfin
import relation. This avoids duplicating media already present in a configured
media server. Playback through an exported URL considers only XC and local
relations; it never fails over to a Plex, Emby, or Jellyfin import. If no safe
relation remains, the proxy returns HTTP 503 until a rebuild removes the stale
generated file.

Provider credentials remain server-side, are sent in request headers only to
the configured provider origin, and are never returned by the source API.

The exporter owns only files listed in its
`.dispatcharr-media-library.json` manifest. It does not recursively delete an
export directory or remove untracked files. Managed files are removed when a
target is disabled, deleted, or moved to another output root, and relevant
configuration changes queue a replacement snapshot. Cached Media Library
artwork is removed when its database logo becomes unused; artwork owned by
other Dispatcharr features is not touched.
