# Media Library

Media Library imports movies and TV episodes from Plex, Emby, Jellyfin, or
explicitly allowed local filesystem roots. It can export normalized Dispatcharr
VOD content as Jellyfin/Emby-compatible STRM and NFO directory trees.

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

Local paths are canonicalized and revalidated whenever they are scanned or
played. A symlink is accepted only when its resolved destination remains below
an allowed import root.

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

The administrator-only **Settings > Media Library** section stores a write-only
TMDB v3 API key using the current `CoreSettings` group mechanism. Its help
dialog links directly to TMDB's API-key setup page. A key may instead be
supplied with `TMDB_API_KEY`. API responses expose configuration status only,
never the key, and a saved key is removed only with the explicit clear control.

**Prefer NFO metadata** is enabled by default. In that mode NFO/local values
take priority and TMDB fills missing fields. When disabled, TMDB values take
priority and NFO data remains the fallback. Stable identifiers found in NFO
files can still be used for confident TMDB lookups in either mode.

For local media, Dispatcharr recognizes same-basename movie and episode NFO
files, `movie.nfo`, `episode.nfo`, and parent `tvshow.nfo` files. It imports
titles, plots, years, ratings, runtimes, genres, TMDB/IMDb identifiers, and
artwork references where present. Multi-episode NFO files are supported.

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

## STRM playback

Each export target requires:

- a Dispatcharr base URL reachable by Jellyfin or Emby;
- explicit CIDRs containing the media-server client;
- an optional target-wide stream limit.

Generated STRM files contain a target-specific Dispatcharr playback URL. They
never contain provider tokens, Dispatcharr JWTs, API keys, usernames, or
passwords. Disabling the target immediately revokes its URLs. Rotating its
playback identifier revokes the old URLs and queues a rebuild.

Playback continues through the current Dispatcharr VOD proxy, including active
relation selection, provider failover, provider-profile capacity, HTTP Range
handling, and Redis-backed multi-worker sessions.

Provider credentials remain server-side, are sent in request headers only to
the configured provider origin, and are never returned by the source API.

The exporter owns only files listed in its
`.dispatcharr-media-library.json` manifest. It does not recursively delete an
export directory or remove untracked files.
