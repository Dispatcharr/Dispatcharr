import datetime
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def get_backup_dir() -> Path:
    """Get the backup directory, creating it if necessary."""
    backup_dir = Path(settings.BACKUP_ROOT)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _is_postgresql() -> bool:
    """Check if we're using PostgreSQL."""
    return settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def _get_pg_env() -> dict:
    """Get environment variables for PostgreSQL commands."""
    db_config = settings.DATABASES["default"]
    env = os.environ.copy()
    env["PGPASSWORD"] = db_config.get("PASSWORD", "")
    return env


def _get_pg_args() -> list[str]:
    """Get common PostgreSQL command arguments."""
    db_config = settings.DATABASES["default"]
    return [
        "-h", db_config.get("HOST", "localhost"),
        "-p", str(db_config.get("PORT", 5432)),
        "-U", db_config.get("USER", "postgres"),
        "-d", db_config.get("NAME", "dispatcharr"),
    ]


def _dump_postgresql(output_file: Path) -> None:
    """Dump PostgreSQL database using pg_dump."""
    logger.info("Dumping PostgreSQL database with pg_dump...")

    cmd = [
        "pg_dump",
        *_get_pg_args(),
        "-Fc",  # Custom format for pg_restore
        "-v",   # Verbose
        "-f", str(output_file),
    ]

    result = subprocess.run(
        cmd,
        env=_get_pg_env(),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"pg_dump failed: {result.stderr}")
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    logger.debug(f"pg_dump output: {result.stderr}")


def _restore_postgresql(dump_file: Path) -> None:
    """Restore PostgreSQL database using pg_restore."""
    logger.info("[PG_RESTORE] Starting pg_restore...")
    logger.info(f"[PG_RESTORE] Dump file: {dump_file}")

    pg_args = _get_pg_args()
    logger.info(f"[PG_RESTORE] Connection args: {pg_args}")

    cmd = [
        "pg_restore",
        "--clean",  # Clean (drop) database objects before recreating
        *pg_args,
        "-v",  # Verbose
        str(dump_file),
    ]

    logger.info(f"[PG_RESTORE] Running command: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        env=_get_pg_env(),
        capture_output=True,
        text=True,
    )

    logger.info(f"[PG_RESTORE] Return code: {result.returncode}")

    # pg_restore may return non-zero even on partial success
    # Check for actual errors vs warnings
    if result.returncode != 0:
        # Some errors during restore are expected (e.g., "does not exist" when cleaning)
        # Only fail on critical errors
        stderr = result.stderr.lower()
        if "fatal" in stderr or "could not connect" in stderr:
            logger.error(f"[PG_RESTORE] Failed critically: {result.stderr}")
            raise RuntimeError(f"pg_restore failed: {result.stderr}")
        else:
            logger.warning(f"[PG_RESTORE] Completed with warnings: {result.stderr[:500]}...")

    logger.info("[PG_RESTORE] Completed successfully")


def _dump_sqlite(output_file: Path) -> None:
    """Dump SQLite database using sqlite3 .backup command."""
    logger.info("Dumping SQLite database with sqlite3 .backup...")
    db_path = Path(settings.DATABASES["default"]["NAME"])

    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    # Use sqlite3 .backup command via stdin for reliable execution
    result = subprocess.run(
        ["sqlite3", str(db_path)],
        input=f".backup '{output_file}'\n",
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"sqlite3 backup failed: {result.stderr}")
        raise RuntimeError(f"sqlite3 backup failed: {result.stderr}")

    # Verify the backup file was created
    if not output_file.exists():
        raise RuntimeError("sqlite3 backup failed: output file not created")

    logger.info(f"sqlite3 backup completed successfully: {output_file}")


def _restore_sqlite(dump_file: Path) -> None:
    """Restore SQLite database by replacing the database file."""
    logger.info("Restoring SQLite database...")
    db_path = Path(settings.DATABASES["default"]["NAME"])
    backup_current = None

    # Backup current database before overwriting
    if db_path.exists():
        backup_current = db_path.with_suffix(".db.bak")
        shutil.copy2(db_path, backup_current)
        logger.info(f"Backed up current database to {backup_current}")

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # The backup file from _dump_sqlite is a complete SQLite database file
    # We can simply copy it over the existing database
    shutil.copy2(dump_file, db_path)

    # Verify the restore worked by checking if sqlite3 can read it
    result = subprocess.run(
        ["sqlite3", str(db_path)],
        input=".tables\n",
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"sqlite3 verification failed: {result.stderr}")
        # Try to restore from backup
        if backup_current and backup_current.exists():
            shutil.copy2(backup_current, db_path)
            logger.info("Restored original database from backup")
        raise RuntimeError(f"sqlite3 restore verification failed: {result.stderr}")

    logger.info("sqlite3 restore completed successfully")


def create_backup() -> Path:
    """
    Create a backup archive containing database dump and data directories.
    Returns the path to the created backup file.
    """
    backup_dir = get_backup_dir()
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y.%m.%d.%H.%M.%S")
    backup_name = f"dispatcharr-backup-{timestamp}.zip"
    backup_file = backup_dir / backup_name

    logger.info(f"Creating backup: {backup_name}")

    with tempfile.TemporaryDirectory(prefix="dispatcharr-backup-") as temp_dir:
        temp_path = Path(temp_dir)

        # Determine database type and dump accordingly
        if _is_postgresql():
            db_dump_file = temp_path / "database.dump"
            _dump_postgresql(db_dump_file)
            db_type = "postgresql"
        else:
            db_dump_file = temp_path / "database.sqlite3"
            _dump_sqlite(db_dump_file)
            db_type = "sqlite"

        # Create ZIP archive with compression and ZIP64 support for large files
        with ZipFile(backup_file, "w", compression=ZIP_DEFLATED, allowZip64=True) as zip_file:
            # Add database dump
            zip_file.write(db_dump_file, db_dump_file.name)

            # Add metadata
            metadata = {
                "format": "dispatcharr-backup",
                "version": 2,
                "database_type": db_type,
                "database_file": db_dump_file.name,
                "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            }
            zip_file.writestr("metadata.json", json.dumps(metadata, indent=2))

    logger.info(f"Backup created successfully: {backup_file}")
    return backup_file


def restore_backup(backup_file: Path) -> None:
    """
    Restore from a backup archive.
    WARNING: This will overwrite the database!
    """
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    logger.info(f"Restoring from backup: {backup_file}")

    with tempfile.TemporaryDirectory(prefix="dispatcharr-restore-") as temp_dir:
        temp_path = Path(temp_dir)

        # Extract backup
        logger.debug("Extracting backup archive...")
        with ZipFile(backup_file, "r") as zip_file:
            zip_file.extractall(temp_path)

        # Read metadata
        metadata_file = temp_path / "metadata.json"
        if not metadata_file.exists():
            raise ValueError("Invalid backup: missing metadata.json")

        with open(metadata_file) as f:
            metadata = json.load(f)

        # Restore database
        _restore_database(temp_path, metadata)

    logger.info("Restore completed successfully")


def _restore_database(temp_path: Path, metadata: dict) -> None:
    """Restore database from backup."""
    db_type = metadata.get("database_type", "postgresql")
    db_file = metadata.get("database_file", "database.dump")
    dump_file = temp_path / db_file

    if not dump_file.exists():
        raise ValueError(f"Invalid backup: missing {db_file}")

    current_db_type = "postgresql" if _is_postgresql() else "sqlite"

    if db_type != current_db_type:
        raise ValueError(
            f"Database type mismatch: backup is {db_type}, "
            f"but current database is {current_db_type}"
        )

    if db_type == "postgresql":
        _restore_postgresql(dump_file)
    else:
        _restore_sqlite(dump_file)


def list_backups() -> list[dict]:
    """List all available backup files with metadata."""
    backup_dir = get_backup_dir()
    backups = []

    for backup_file in sorted(backup_dir.glob("dispatcharr-backup-*.zip"), reverse=True):
        backups.append({
            "name": backup_file.name,
            "size": backup_file.stat().st_size,
            "created": datetime.datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat(),
        })

    return backups


def delete_backup(filename: str) -> None:
    """Delete a backup file."""
    backup_dir = get_backup_dir()
    backup_file = backup_dir / filename

    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {filename}")

    if not backup_file.is_file():
        raise ValueError(f"Invalid backup file: {filename}")

    backup_file.unlink()
    logger.info(f"Deleted backup: {filename}")
