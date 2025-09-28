# Configuration Backups

Dispatcharr can snapshot configuration data so you can roll back quickly after a change or rebuild. Each archive contains:

- database content (settings, channels, playlists, plugins, etc.)
- directories listed in the backup settings (logos and, optionally, recordings)

Backups do **not** capture environment files (compose overrides, `.env`, secrets). Keep those backed up separately.

## Configure & Run

1. Open **Settings → Backups**.
2. Set the **backup path** (default `/data/backups` inside Docker). Ensure Dispatcharr can write to it.
3. Toggle **include recordings** if you want recordings copied alongside configuration.
4. Choose the **retention count**; older archives are removed after successful runs.
5. Pick a **schedule** (hourly/daily/weekly) and start time, or leave disabled for manual runs.
6. Save.

Press **Run Backup** to start immediately. Jobs appear in the history table with live status updates.

## Download

Completed jobs expose a download icon. Click it to retrieve the `.tar.gz` archive, which includes `database.json`, `manifest.json`, and data directories.

## Restore

1. Click **Upload Archive** above the history table.
2. Select an archive produced by Dispatcharr.
3. Confirm the dialog. The restore flow validates the archive, loads database data, and copies the stored directories back into place. Jobs created without recordings leave the recordings directory untouched.

## Cancel & Delete

- Cancel a running job with the stop icon.
- Delete an archive with the trash icon; this removes the file and the job record.

## Permissions & API

Only admin users can manage backups. API endpoints live under `/api/backups/` for automation and require authentication.

## Troubleshooting

- Ensure the backup path is writable (compose setups mount `./data:/data`, so `/data/backups` maps to `./data/backups`).
- Failed jobs show their error message via tooltip; check application logs for full stack traces.
- Scheduled runs depend on Celery beat/worker and Redis. Verify those services before debugging the backup app.
