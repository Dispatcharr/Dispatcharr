from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.management import call_command
from django.db.models.signals import pre_save
from django.utils import timezone
from django.core.exceptions import ImproperlyConfigured

from version import __version__ as DISPATCHARR_VERSION

from .models import BackupJob
from apps.channels.models import Stream
from apps.channels.signals import set_default_m3u_account

try:
    from django_celery_beat.models import CrontabSchedule, PeriodicTask
except Exception:  # pragma: no cover - celery beat optional in some contexts
    CrontabSchedule = None
    PeriodicTask = None

logger = logging.getLogger(__name__)

DB_DUMP_FILENAME = "database.json"
MANIFEST_FILENAME = "manifest.json"
DATA_PREFIX = "data"
BACKUP_TASK_NAME = "dispatcharr.backups.schedule"
EXCLUDED_MODELS = [
    "contenttypes",
    "auth.Permission",
    "admin.LogEntry",
    "sessions.Session",
]
def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    base = getattr(settings, "BACKUP_ROOT", settings.BASE_DIR)
    return (Path(base) / path).resolve()


def get_configured_backup_root() -> Path:
    from core.models import CoreSettings

    configured = CoreSettings.get_backup_path()
    if configured:
        root = _resolve_path(configured)
    else:
        root = Path(settings.BACKUP_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_configured_data_dirs() -> list[Path]:
    from core.models import CoreSettings

    dirs = getattr(settings, "BACKUP_DATA_DIRS", [])
    paths = [Path(entry) for entry in dirs if entry]

    include_recordings = CoreSettings.get_backup_include_recordings()

    extra = CoreSettings.get_backup_extra_paths()
    for value in extra:
        paths.append(_resolve_path(value))

    unique = []
    seen = set()
    for path in paths:
        key = path.resolve()
        if key in seen:
            continue
        if not include_recordings and path.name.lower() == "recordings":
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _write_database_dump(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        call_command(
            "dumpdata",
            use_natural_foreign_keys=True,
            use_natural_primary_keys=True,
            indent=2,
            exclude=EXCLUDED_MODELS,
            stdout=handle,
        )


def _build_manifest(data_dirs: Iterable[Path], missing: Iterable[str]) -> dict:
    from core.models import CoreSettings

    schedule = CoreSettings.get_backup_schedule()
    return {
        "format": "dispatcharr-backup",
        "version": 1,
        "created_at": timezone.now().isoformat(),
        "dispatcharr_version": DISPATCHARR_VERSION,
        "data_directories": [str(path) for path in data_dirs],
        "missing_directories": list(missing),
        "database_dump": DB_DUMP_FILENAME,
        "include_recordings": CoreSettings.get_backup_include_recordings(),
        "schedule": schedule,
    }


def _safe_tar_extract(tar: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = destination / member.name
        if not str(member_path.resolve()).startswith(str(destination)):
            raise ImproperlyConfigured("Archive contains invalid paths")
    tar.extractall(destination)


def create_backup_archive(job: BackupJob) -> Path:
    backup_root = get_configured_backup_root()
    timestamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    archive_name = f"dispatcharr-backup-{timestamp}.tar.gz"
    archive_path = backup_root / archive_name
    counter = 1
    while archive_path.exists():
        archive_name = f"dispatcharr-backup-{timestamp}-{counter}.tar.gz"
        archive_path = backup_root / archive_name
        counter += 1

    data_dirs = []
    missing = []
    for path in get_configured_data_dirs():
        if path.exists():
            data_dirs.append(path)
        else:
            missing.append(str(path))

    with tempfile.TemporaryDirectory(prefix="dispatcharr-backup-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        dump_path = tmp_path / DB_DUMP_FILENAME
        manifest_path = tmp_path / MANIFEST_FILENAME

        logger.debug("Writing database dump to %s", dump_path)
        _write_database_dump(dump_path)

        manifest = _build_manifest(data_dirs, missing)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(dump_path, arcname=DB_DUMP_FILENAME)
            tar.add(manifest_path, arcname=MANIFEST_FILENAME)
            for directory in data_dirs:
                arcname = Path(DATA_PREFIX) / directory.name
                logger.debug("Adding directory %s as %s", directory, arcname)
                tar.add(directory, arcname=str(arcname))

    try:
        job.file_path = archive_name
        job.original_filename = archive_name
        job.file_size = archive_path.stat().st_size
        job.save(update_fields=["file_path", "original_filename", "file_size", "updated_at"])
    except Exception:
        logger.exception("Failed to update backup job %s with archive info", job.pk)

    return archive_path


def enforce_retention() -> None:
    from core.models import CoreSettings

    retention = CoreSettings.get_backup_retention_count()
    if retention <= 0:
        return

    jobs = (
        BackupJob.objects.filter(job_type=BackupJob.JobType.BACKUP)
        .filter(status=BackupJob.Status.SUCCEEDED)
        .order_by("-created_at")
    )
    for job in jobs[retention:]:
        logger.info("Pruning old backup job %s", job.pk)
        job.delete_archive()
        job.delete()


def restore_archive(job: BackupJob) -> None:
    archive_path = job.archive_path
    if not archive_path or not archive_path.exists():
        raise FileNotFoundError("Archive file not found for restore")

    with tempfile.TemporaryDirectory(prefix="dispatcharr-restore-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        logger.info("Extracting backup archive %s", archive_path)
        with tarfile.open(archive_path, "r:gz") as tar:
            _safe_tar_extract(tar, tmp_path)

        dump_path = tmp_path / DB_DUMP_FILENAME
        if not dump_path.exists():
            raise ImproperlyConfigured("Backup archive missing database dump")

        data_root = tmp_path / DATA_PREFIX
        extracted_dirs = [p for p in data_root.iterdir()] if data_root.exists() else []

        logger.info("Restoring database from %s", dump_path)
        call_command("flush", verbosity=0, interactive=False)

        signal_connected = True
        try:
            pre_save.disconnect(set_default_m3u_account, sender=Stream)
        except Exception:  # pragma: no cover - defensive
            signal_connected = False

        try:
            call_command("loaddata", str(dump_path))
        finally:
            if signal_connected:
                try:
                    pre_save.connect(set_default_m3u_account, sender=Stream)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Failed to reconnect stream default account signal after restore")

        for directory in extracted_dirs:
            target_name = directory.name
            candidates = [path for path in get_configured_data_dirs() if path.name == target_name]
            if not candidates:
                logger.warning("No target directory configured for %s; skipping", target_name)
                continue
            target = candidates[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Restoring directory %s to %s", directory, target)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(directory, target)


def sync_backup_schedule() -> None:
    if not (CrontabSchedule and PeriodicTask):
        logger.debug("django_celery_beat not available; skipping schedule sync")
        return

    from core.models import CoreSettings

    enabled = CoreSettings.get_backup_enabled()
    defaults = {
        "task": "apps.backups.tasks.run_scheduled_backup",
        "enabled": False,
        "crontab": None,
        "interval": None,
        "kwargs": json.dumps({"scheduled": True}),
    }

    if not CrontabSchedule:
        raise ImproperlyConfigured("django_celery_beat CrontabSchedule not available")

    schedule = CoreSettings.get_backup_schedule()
    cron, _ = CrontabSchedule.objects.get_or_create(
        minute=schedule["minute"],
        hour=schedule["hour"],
        day_of_month=schedule["day_of_month"],
        month_of_year=schedule["month"],
        day_of_week=schedule["day_of_week"],
        timezone=schedule["timezone"],
    )

    PeriodicTask.objects.update_or_create(
        name=BACKUP_TASK_NAME,
        defaults={
            **defaults,
            "enabled": bool(enabled),
            "crontab": cron,
            "interval": None,
        },
    )
