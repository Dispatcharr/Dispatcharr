# Dispatcharr Plugin Repository Specification

How to create and host a plugin repository that Dispatcharr can consume.

For writing plugins themselves, see [Plugins.md](Plugins.md).

---

## Overview

Dispatcharr discovers plugins from remote repositories using a two-level manifest system:

1. **Repo manifest** - a JSON file listing all plugins in the repo with basic metadata.
2. **Per-plugin manifest** (optional) - a JSON file per plugin with full version history, checksums, and compatibility info.

Users add a repo by its manifest URL. Dispatcharr fetches and caches the repo manifest periodically (default: every 6 hours, configurable). The UI displays all plugins from enabled repos in a browsable store.

---

## Repo Manifest

The repo manifest is the entry point. Dispatcharr fetches this URL and caches the response.

### Minimal Example (no signing)

```json
{
  "registry_name": "My Plugin Repo",
  "plugins": [
    {
      "slug": "my_plugin",
      "name": "My Plugin",
      "description": "Does something useful",
      "author": "Your Name",
      "latest_version": "1.0.0",
      "latest_url": "https://example.com/releases/my_plugin-1.0.0.zip"
    }
  ]
}
```

This is the simplest valid repo manifest - one plugin with enough info to show in the store and install.

### Full Example (with signing)

```json
{
  "manifest": {
    "registry_name": "My Plugin Repo",
    "registry_url": "https://github.com/myorg/my-plugins",
    "root_url": "https://raw.githubusercontent.com/myorg/my-plugins/releases",
    "plugins": [
      {
        "slug": "weather_display",
        "name": "Weather Display",
        "description": "Shows weather info on the dashboard",
        "author": "Acme Labs",
        "maintainers": ["alice", "bob"],
        "license": "MIT",
        "deprecated": false,
        "repo_url": "https://github.com/acmelabs/dispatcharr-weather",
        "discord_thread": "https://discord.com/channels/123456/789012",
        "latest_version": "1.2.5",
        "last_updated": "2025-01-20T15:30:00Z",
        "manifest_url": "plugins/weather_display/manifest.json",
        "latest_url": "plugins/weather_display/releases/weather_display-1.2.5.zip",
        "latest_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "latest_size": 142,
        "icon_url": "plugins/weather_display/logo.png",
        "min_dispatcharr_version": "2.5.0",
        "max_dispatcharr_version": null
      }
    ]
  },
  "signature": "-----BEGIN PGP SIGNATURE-----\n..."
}
```

### Accepted Formats

Dispatcharr accepts two top-level shapes:

**Wrapped (supports signing):**
```json
{
  "manifest": { "plugins": [...], ... },
  "signature": "..."
}
```

**Flat (no signing):**
```json
{
  "plugins": [...],
  "registry_name": "...",
  "root_url": "..."
}
```

The wrapped format is required for signing. If you don't need signing, the flat format works and is simpler.

### Name Restrictions

`registry_name` is required. Dispatcharr rejects repos that are missing it.

Third-party repos must not use names that could be confused with an official Dispatcharr repo. The following words are blocked in `registry_name` (case-insensitive):

- "official"
- "dispatcharr plugins"
- "dispatcharr repo"
- "dispatcharr official"

If the name contains any of these, the repo will be rejected on add and skipped during refresh.

---

## Repo Manifest Fields

### Top-Level Metadata

| Field | Required | Description |
|-------|----------|-------------|
| `registry_name` | **Yes** | Display name for the repo. Must not contain words like "official" or "dispatcharr" that could be mistaken for an official repo (see [Name Restrictions](#name-restrictions)). |
| `registry_url` | No | URL to the repo's home page (e.g. GitHub). Used as a fallback for generating icon URLs. |
| `root_url` | No | Base URL for resolving relative URLs in plugin entries. Trailing slashes are stripped. |
| `plugins` | **Yes** | Array of plugin entry objects. |

### Plugin Entry Fields

| Field | Required | Description |
|-------|----------|-------------|
| `slug` | **Yes** | Unique identifier. Alphanumeric, dashes, and underscores. Used as the install directory name (lowercased, dashes converted to underscores). |
| `name` | **Yes** | Human-readable display name. |
| `description` | No | Short description shown on the plugin card. |
| `author` | No | Author or organization name. |
| `maintainers` | No | Array of maintainer GitHub usernames (e.g. `["alice", "bob"]`). Shown in the detail view. |
| `license` | No | SPDX license identifier (e.g. `MIT`, `GPL-3.0`). Displayed as a link to the SPDX license page. |
| `deprecated` | No | Boolean. When `true`, marks the plugin as deprecated in the store UI. Omit or set to `false` for active plugins. |
| `repo_url` | No | URL to the plugin's source code repository (e.g. GitHub). |
| `discord_thread` | No | URL to a Discord thread or channel for plugin support. Must start with `http://` or `https://`. |
| `latest_version` | No | Current latest version string (semver: `1.2.3` or `v1.2.3`). Drives update detection. |
| `last_updated` | No | ISO 8601 timestamp of the latest release. Shown as "Built" date in the detail view. |
| `manifest_url` | No | URL (or relative path) to the per-plugin manifest with full version history. See [Per-Plugin Manifest](#per-plugin-manifest). |
| `latest_url` | No | Direct download URL (or relative path) to the latest release zip. |
| `latest_sha256` | No | SHA256 checksum of the latest release zip (lowercase hex, 64 chars). |
| `latest_md5` | No | MD5 checksum of the latest release zip. Informational only - not validated by Dispatcharr. |
| `latest_size` | No | Size of the latest release zip in kilobytes. Informational only. |
| `icon_url` | No | URL (or relative path) to a logo image (PNG recommended). |
| `min_dispatcharr_version` | No | Minimum Dispatcharr version required. Install is blocked if the running version is older. |
| `max_dispatcharr_version` | No | Maximum Dispatcharr version supported. Install is blocked if the running version is newer. |

Extra fields in a plugin entry are passed through to the frontend as-is, so you can include custom metadata (e.g. `homepage`, `tags`) without breaking anything.

### URL Resolution

If `root_url` is set and a URL field (`manifest_url`, `latest_url`, `icon_url`) does not start with `http://` or `https://`, it is treated as relative and resolved as:

```
{root_url}/{field_value}
```

This lets you keep plugin entries compact:
```json
{
  "root_url": "https://raw.githubusercontent.com/myorg/my-plugins/releases",
  "plugins": [
    {
      "slug": "my_plugin",
      "latest_url": "plugins/my_plugin/my_plugin-1.0.0.zip",
      "icon_url": "plugins/my_plugin/logo.png",
      "manifest_url": "plugins/my_plugin/manifest.json"
    }
  ]
}
```

**Icon fallback:** If `icon_url` is missing and `registry_url` is set, Dispatcharr generates a fallback URL by converting the GitHub URL to a raw content URL:
```
{registry_url => raw.githubusercontent.com}/refs/heads/main/plugins/{slug}/logo.png
```

---

## Per-Plugin Manifest (Optional)

The per-plugin manifest provides full version history. It is fetched on-demand when a user clicks "More Info" on a plugin card. It is **not required** - if `manifest_url` is absent, the UI builds a detail view from the repo-level fields instead.

Include a per-plugin manifest if you want to:
- Offer multiple downloadable versions
- Show per-version compatibility ranges
- Display build timestamps and commit links for each version
- Provide detailed author/license info beyond what's in the repo manifest

### Accepted Formats

Same as the root manifest - both flat and wrapped formats are accepted:

**Flat (no signing):**
```json
{
  "slug": "...",
  "versions": [...]
}
```

**Wrapped (supports signing):**
```json
{
  "manifest": {
    "slug": "...",
    "versions": [...]
  },
  "signature": "-----BEGIN PGP SIGNATURE-----\n..."
}
```

Use the wrapped format if you want to GPG-sign the per-plugin manifest.

### Example

```json
{
  "slug": "weather_display",
  "name": "Weather Display",
  "description": "Shows weather information on the Dispatcharr dashboard",
  "author": "Acme Labs",
  "license": "MIT",
  "latest_version": "1.2.5",
  "registry_name": "Acme Labs Plugins",
  "registry_url": "https://github.com/acmelabs/dispatcharr-plugins",
  "versions": [
    {
      "version": "1.2.5",
      "url": "releases/weather_display-1.2.5.zip",
      "checksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "size": 142,
      "build_timestamp": "2025-01-20T15:30:00Z",
      "commit_sha": "4e8f1b108c1e84f60520710d13e54eb2fb519648",
      "commit_sha_short": "4e8f1b1",
      "min_dispatcharr_version": "2.5.0",
      "max_dispatcharr_version": null
    },
    {
      "version": "1.2.5-rc.1",
      "url": "releases/weather_display-1.2.5-rc.1.zip",
      "checksum_sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "size": 141,
      "prerelease": true,
      "build_timestamp": "2025-01-18T09:00:00Z",
      "min_dispatcharr_version": "2.5.0"
    },
    {
      "version": "1.2.4",
      "url": "releases/weather_display-1.2.4.zip",
      "checksum_sha256": "d4d967a67a4947e55183308cece206b30dda3e1b4fe00aae60f45a49c83b7ed6",
      "size": 138,
      "build_timestamp": "2025-01-15T10:00:00Z",
      "min_dispatcharr_version": "2.4.0"
    }
  ],
  "latest": {
    "version": "1.2.5",
    "url": "releases/weather_display-1.2.5.zip",
    "latest_url": "releases/weather_display-latest.zip",
    "checksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "size": 142,
    "build_timestamp": "2025-01-20T15:30:00Z",
    "min_dispatcharr_version": "2.5.0"
  }
}
```

### Per-Plugin Manifest Fields

| Field | Required | Description |
|-------|----------|-------------|
| `slug` | No | Plugin identifier (should match the repo entry). |
| `name` | No | Display name. |
| `description` | No | Full description shown in the detail modal. |
| `author` | No | Author/org name shown in the detail modal. |
| `license` | No | SPDX license identifier. |
| `latest_version` | No | Latest version string. |
| `registry_name` | No | Registry name inherited from the parent repo manifest. Injected automatically by the official publish tooling. |
| `registry_url` | No | Registry URL inherited from the parent repo manifest. Used by the store to build commit links. Injected automatically by the official publish tooling. |
| `versions` | No | Array of version objects (newest first recommended). |
| `latest` | No | Object mirroring the latest version entry for quick access. Accepts all the same fields as a version object. Additionally, `latest_url` may appear here pointing to a stable symlink (e.g. `plugin-latest.zip`) that always resolves to the newest release. |

### Version Object Fields

| Field | Required | Description |
|-------|----------|-------------|
| `version` | **Yes** | Version string (`1.2.3` or `v1.2.3`). |
| `url` | **Yes** | Download URL for the zip. Relative URLs are resolved against the repo's `root_url`. |
| `checksum_sha256` | No | SHA256 hex checksum. **Strongly recommended.** Validated on install - mismatch blocks the install. |
| `prerelease` | No | Boolean. When `true`, marks this version as a pre-release (alpha, beta, RC, etc.). If the installed version is a prerelease, Dispatcharr will not suggest updating to the latest stable version - the user must install a new version manually. The latest version in the root manifest is always assumed to be stable, so this field only needs to appear in the per-plugin manifest. Omit or set to `false` for stable releases. |
| `build_timestamp` | No | ISO 8601 build timestamp. Shown as "Built" in the version detail. |
| `commit_sha` | No | Full Git commit SHA. Used to build a commit link if `registry_url` is set. |
| `commit_sha_short` | No | Abbreviated commit SHA. Displayed in the version detail table as a clickable link. |
| `size` | No | Size of this version's zip in kilobytes. Informational only. |
| `min_dispatcharr_version` | No | Minimum compatible Dispatcharr version. |
| `max_dispatcharr_version` | No | Maximum compatible Dispatcharr version. |

Relative `url` values in versions are resolved the same way as repo-level URLs: `{root_url}/{url}`.

---

## Without a Per-Plugin Manifest

If you omit `manifest_url` from a plugin entry, the store still works. When a user clicks "More Info", the UI builds a detail view from the repo-level fields:

- `description`, `author`, `license` from the plugin entry
- A single version entry built from `latest_version`, `latest_url`, `latest_sha256`, `min_dispatcharr_version`, `max_dispatcharr_version`, and `last_updated`

This is the simplest path for third-party repos that only publish one version at a time. You lose version history and per-version release dates, but install, update detection, and everything else works the same.

---

## Signing

Signing your repo manifest lets Dispatcharr verify it hasn't been tampered with. Signing is **optional** - unsigned repos work fine but show an "unverified" badge in the UI.

### How It Works

1. You generate a GPG keypair.
2. You sign the manifest JSON and include the detached signature in the response.
3. When adding the repo in Dispatcharr, the user pastes your public key.
4. Dispatcharr verifies the signature on every manifest fetch.

### Key Format

Standard PGP/GPG armored keys:

```
-----BEGIN PGP PUBLIC KEY BLOCK-----

mQINBG...
...
-----END PGP PUBLIC KEY BLOCK-----
```

### Signing Convention

The signature is computed over the **canonical JSON** representation of the `manifest` object (not the entire response), plus a trailing newline:

```bash
# Canonical format: compact JSON (no spaces) + trailing newline
jq -c '.manifest' manifest.json | gpg --armor --detach-sign
```

In code terms:
```python
import json
canonical = json.dumps(manifest_obj, separators=(",", ":")) + "\n"
```

> **Important:** The signing input must be `json.dumps(obj, separators=(",", ":")) + "\n"` - compact JSON with no whitespace, followed by exactly one newline. Any difference (pretty-printing, trailing spaces, key ordering changes) will cause verification to fail.

### Manifest Structure for Signing

Use the wrapped format so the signature sits alongside the manifest:

```json
{
  "manifest": {
    "registry_name": "...",
    "plugins": [...]
  },
  "signature": "-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----"
}
```

### Verification Results

| Result | Meaning | UI Badge |
|--------|---------|----------|
| `true` | Valid signature | Green checkmark |
| `false` | Invalid signature or verification error | Red X |
| `null` | Not attempted (no signature, no key, or `python-gnupg` not installed) | Gray/neutral |

### Signing Workflow Example

```bash
# Generate a keypair (one-time)
gpg --gen-key

# Export your public key (give this to repo users)
gpg --armor --export "your@email.com" > my-repo.pub

# Build your manifest
cat > manifest.json << 'EOF'
{
  "manifest": {
    "registry_name": "My Repo",
    "root_url": "https://example.com/releases",
    "plugins": [
      {
        "slug": "my_plugin",
        "name": "My Plugin",
        "latest_version": "1.0.0",
        "latest_url": "plugins/my_plugin/my_plugin-1.0.0.zip"
      }
    ]
  }
}
EOF

# Sign the manifest object (canonical JSON + newline)
jq -c '.manifest' manifest.json | gpg --armor --detach-sign > manifest.sig

# Combine into final output
jq --arg sig "$(cat manifest.sig)" '.signature = $sig' manifest.json > signed_manifest.json
```

### Third-Party Key Management

When a user adds your repo URL, they can paste your public key. Dispatcharr stores the key per-repo and uses it for verification. Users can update the key at any time from the repo management UI.

If you don't provide a key and the repo is not the official Dispatcharr repo, signature verification is skipped (result: `null`).

---

## Release Zip Format

Each plugin release is a `.zip` archive.

### Requirements

- Must contain a `plugin.py` with a `Plugin` class, **or** a Python package with `__init__.py` exporting a `Plugin` class.
- Files can be at the top level of the zip or inside a single subdirectory.
- Optionally include `plugin.json` for metadata discovery without code execution.
- Optionally include `logo.png` for the plugin icon.

### Size Limits

- Maximum 2000 files per archive.
- Maximum total size: 200 MB (configurable via `MAX_PLUGIN_IMPORT_BYTES` setting).

### Recommended Structure

```
my_plugin-1.0.0.zip
  plugin.py
  plugin.json
  logo.png
  (any other files your plugin needs)
```

Or with a subdirectory:
```
my_plugin-1.0.0.zip
  my_plugin/
    plugin.py
    plugin.json
    logo.png
    utils.py
```

---

## Install Flow

When a user installs a plugin from the store:

1. **Version compatibility check** - if `min_dispatcharr_version` or `max_dispatcharr_version` is set, the running Dispatcharr version is compared. Install is blocked if out of range.
2. **Download** - the zip is streamed from `download_url` (max 200 MB).
3. **SHA256 integrity check** - if `sha256` was provided, the download is hashed and compared. Mismatch blocks the install.
4. **Extraction** - the zip is extracted to a temp directory, validated, then moved to `/data/plugins/{plugin_key}/`. If the plugin already exists, the old version is backed up and restored on failure (atomic rollback).
5. **Registration** - a `PluginConfig` record is created or updated, linking the plugin to its source repo and slug.
6. **Discovery reload** - the plugin loader re-scans all plugin directories.

The plugin is installed **disabled** by default. The user can enable it from the post-install dialog or the My Plugins page.

---

## Update Detection

Dispatcharr detects updates by comparing `installed_version` (stored in the database) against `latest_version` from the repo manifest. This uses repo-level fields only - per-plugin manifests are not needed for update detection.

A plugin shows "Update Available" when:
- It is managed (installed from a repo)
- Its `installed_version` differs from `latest_version`
- It was installed from the same repo

---

## Hosting Options

A plugin repo manifest is just a JSON file served over HTTPS. Some options:

### GitHub Pages / Raw Content
Host your manifest and release zips in a GitHub repo. Use raw.githubusercontent.com URLs:
```
https://raw.githubusercontent.com/myorg/my-plugins/main/manifest.json
```

Use `root_url` pointing to your releases branch/path so version URLs stay relative.

### Static File Server
Any web server that serves JSON works. Dispatcharr fetches manifests server-side, so CORS is not needed.

### GitHub Releases
You can host release zips as GitHub Release assets and reference them with absolute URLs in your manifest. The manifest itself can live in the repo's default branch.

---

## Refresh Behavior

- Manifests are refreshed automatically at a configurable interval (default: 6 hours, setting: `refresh_interval_hours`, 0 = disabled).
- Users can force a refresh from the repo management UI.
- A new repo is refreshed immediately when added.
- On refresh, if a plugin's `slug` disappears from the manifest, its `PluginConfig` is unlinked from the repo (becomes "unmanaged") but the installed files are not deleted.

---

## Checklist: Publishing a Plugin Repo

### Minimum Viable Repo

- [ ] Host a JSON file at a stable, public URL
- [ ] Set `registry_name` (required, must not sound official)
- [ ] Include at least one plugin entry with `slug`, `name`, and `latest_version`
- [ ] Host a downloadable `.zip` for each plugin and set `latest_url`
- [ ] Share the manifest URL with users

### Recommended

- [ ] Set `root_url` so plugin URLs can be relative
- [ ] Include `description`, `author`, and `icon_url` per plugin
- [ ] Include `latest_sha256` for integrity verification
- [ ] Include `license` (SPDX identifier)
- [ ] Include `last_updated` timestamps
- [ ] Add a per-plugin `manifest_url` with version history
- [ ] Include `sha256` in every version object
- [ ] Include `min_dispatcharr_version` where applicable
- [ ] Include `plugin.json` in each release zip

### Optional

- [ ] Sign your manifest with GPG and publish your public key
- [ ] Set `registry_url` to enable automatic icon fallback
- [ ] Set `max_dispatcharr_version` if a plugin is incompatible with newer releases

---

## Quick Reference: Repo Manifest Schema

```json
{
  "manifest": {
    "registry_name": "string (required)",
    "registry_url": "string (optional)",
    "root_url": "string (optional)",
    "plugins": [
      {
        "slug": "string (required)",
        "name": "string (required)",
        "description": "string",
        "author": "string",
        "maintainers": ["string"],
        "license": "string (SPDX)",
        "deprecated": "boolean",
        "repo_url": "string (URL)",
        "discord_thread": "string (URL)",
        "latest_version": "string (semver)",
        "last_updated": "string (ISO 8601)",
        "manifest_url": "string (URL or relative path)",
        "latest_url": "string (URL or relative path)",
        "latest_sha256": "string (64-char hex)",
        "latest_md5": "string",
        "latest_size": "number (KB)",
        "icon_url": "string (URL or relative path)",
        "min_dispatcharr_version": "string (semver)",
        "max_dispatcharr_version": "string (semver) or null"
      }
    ]
  },
  "signature": "string (armored PGP signature, optional)"
}
```

## Quick Reference: Per-Plugin Manifest Schema

```json
{
  "slug": "string",
  "name": "string",
  "description": "string",
  "author": "string",
  "license": "string (SPDX)",
  "latest_version": "string (semver)",
  "registry_name": "string",
  "registry_url": "string (URL)",
  "versions": [
    {
      "version": "string (required)",
      "url": "string (required, URL or relative path)",
      "checksum_sha256": "string (64-char hex)",
      "size": "number (KB)",
      "prerelease": "boolean",
      "build_timestamp": "string (ISO 8601)",
      "commit_sha": "string",
      "commit_sha_short": "string",
      "min_dispatcharr_version": "string (semver)",
      "max_dispatcharr_version": "string (semver) or null"
    }
  ],
  "latest": {
    "version": "string",
    "url": "string",
    "latest_url": "string (stable symlink URL)",
    "checksum_sha256": "string",
    "size": "number (KB)",
    "build_timestamp": "string",
    "min_dispatcharr_version": "string",
    "max_dispatcharr_version": "string or null"
  }
}
```
