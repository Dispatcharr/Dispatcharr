# yourapp/tasks.py
from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import logging
import re
import time
import os
from core.utils import RedisClient, send_websocket_update
from .models import CoreSettings, AVAILABLE_UPDATE_VERSION_KEY, AVAILABLE_UPDATE_URL_KEY
from version import __version__
import requests
from apps.proxy.ts_proxy.channel_status import ChannelStatus
from apps.m3u.models import M3UAccount
from apps.epg.models import EPGSource
from apps.m3u.tasks import refresh_single_m3u_account
from apps.epg.tasks import refresh_epg_data
from .models import CoreSettings
from apps.channels.models import Stream, ChannelStream
from django.db import transaction

logger = logging.getLogger(__name__)

EPG_WATCH_DIR = '/data/epgs'
M3U_WATCH_DIR = '/data/m3us'
MIN_AGE_SECONDS = 6
STARTUP_SKIP_AGE = 30
REDIS_PREFIX = "processed_file:"
REDIS_TTL = 60 * 60 * 24 * 3  # expire keys after 3 days (optional)

# Store the last known value to compare with new data
last_known_data = {}
# Store when we last logged certain recurring messages
_last_log_times = {}
# Don't repeat similar log messages more often than this (in seconds)
LOG_THROTTLE_SECONDS = 300  # 5 minutes
# Track if this is the first scan since startup
_first_scan_completed = False

def throttled_log(logger_method, message, key=None, *args, **kwargs):
    """Only log messages with the same key once per throttle period"""
    if key is None:
        # Use message as key if no explicit key provided
        key = message

    now = time.time()
    if key not in _last_log_times or (now - _last_log_times[key]) >= LOG_THROTTLE_SECONDS:
        logger_method(message, *args, **kwargs)
        _last_log_times[key] = now


def _version_tuple(version_str):
    """Convert version string to tuple for comparison"""
    parts = re.findall(r"\d+", version_str)
    return tuple(int(p) for p in parts[:3])


@shared_task
def check_for_update():
    """Check GitHub for a newer Dispatcharr release."""
    try:
        resp = requests.get(
            "https://api.github.com/repos/Dispatcharr/Dispatcharr/releases/latest",
            timeout=10,
        )
        resp.raise_for_status()
        latest = resp.json().get("tag_name", "").lstrip("v")
        release_url = resp.json().get("html_url", "")

        if latest and _version_tuple(latest) > _version_tuple(__version__):
            send_websocket_update(
                "updates",
                "update",
                {
                    "success": True,
                    "type": "update_available",
                    "latest_version": latest,
                    "current_version": __version__,
                    "url": release_url,
                },
            )
            CoreSettings.objects.update_or_create(
                key=AVAILABLE_UPDATE_VERSION_KEY,
                defaults={"name": "Available Update Version", "value": latest},
            )
            CoreSettings.objects.update_or_create(
                key=AVAILABLE_UPDATE_URL_KEY,
                defaults={"name": "Available Update URL", "value": release_url},
            )
        else:
            CoreSettings.objects.filter(key=AVAILABLE_UPDATE_VERSION_KEY).delete()
            CoreSettings.objects.filter(key=AVAILABLE_UPDATE_URL_KEY).delete()
    except Exception as e:
        logger.warning(f"Failed to check for updates: {e}")


@shared_task
def beat_periodic_task():
    fetch_channel_stats()
    scan_and_process_files()

@shared_task
def scan_and_process_files():
    global _first_scan_completed
    redis_client = RedisClient.get_client()
    now = time.time()
    # Check if directories exist
    dirs_exist = all(os.path.exists(d) for d in [M3U_WATCH_DIR, EPG_WATCH_DIR])
    if not dirs_exist:
        throttled_log(logger.warning, f"Watch directories missing: M3U ({os.path.exists(M3U_WATCH_DIR)}), EPG ({os.path.exists(EPG_WATCH_DIR)})", "watch_dirs_missing")

    # Process M3U files
    m3u_files = [f for f in os.listdir(M3U_WATCH_DIR)
                if os.path.isfile(os.path.join(M3U_WATCH_DIR, f)) and
                (f.endswith('.m3u') or f.endswith('.m3u8'))]

    m3u_processed = 0
    m3u_skipped = 0

    for filename in m3u_files:
        filepath = os.path.join(M3U_WATCH_DIR, filename)
        mtime = os.path.getmtime(filepath)
        age = now - mtime
        redis_key = REDIS_PREFIX + filepath
        stored_mtime = redis_client.get(redis_key)

        # Instead of assuming old files were processed, check if they exist in the database
        if not stored_mtime and age > STARTUP_SKIP_AGE:
            # Check if this file is already in the database
            existing_m3u = M3UAccount.objects.filter(file_path=filepath).exists()
            if existing_m3u:
                # Use trace level if not first scan
                if _first_scan_completed:
                    logger.trace(f"Skipping {filename}: Already exists in database")
                else:
                    logger.debug(f"Skipping {filename}: Already exists in database")
                redis_client.set(redis_key, mtime, ex=REDIS_TTL)
                m3u_skipped += 1
                continue
            else:
                logger.debug(f"Processing {filename} despite age: Not found in database")
                # Continue processing this file even though it's old

        # File too new — probably still being written
        if age < MIN_AGE_SECONDS:
            logger.debug(f"Skipping {filename}: Too new (age={age}s)")
            m3u_skipped += 1
            continue

        # Skip if we've already processed this mtime
        if stored_mtime and float(stored_mtime) >= mtime:
            # Use trace level if not first scan
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Already processed this version")
            else:
                logger.debug(f"Skipping {filename}: Already processed this version")
            m3u_skipped += 1
            continue

        m3u_account, created = M3UAccount.objects.get_or_create(file_path=filepath, defaults={
            "name": filename,
            "is_active": CoreSettings.get_auto_import_mapped_files() in [True, "true", "True"],
        })

        redis_client.set(redis_key, mtime, ex=REDIS_TTL)

        # More descriptive creation logging that includes active status
        if created:
            if m3u_account.is_active:
                logger.info(f"Created new M3U account '{filename}' (active)")
            else:
                logger.info(f"Created new M3U account '{filename}' (inactive due to auto-import setting)")

        if not m3u_account.is_active:
            # Use trace level if not first scan
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: M3U account is inactive")
            else:
                logger.debug(f"Skipping {filename}: M3U account is inactive")
            m3u_skipped += 1
            continue

        # Log update for existing files (we've already logged creation above)
        if not created:
            logger.info(f"Detected update to existing M3U file: {filename}")

        logger.info(f"Queueing refresh for M3U file: {filename}")
        refresh_single_m3u_account.delay(m3u_account.id)
        m3u_processed += 1

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "updates",
            {
                "type": "update",
                "data": {"success": True, "type": "m3u_file", "filename": filename}
            },
        )

    logger.trace(f"M3U processing complete: {m3u_processed} processed, {m3u_skipped} skipped, {len(m3u_files)} total")

    # Process EPG files
    try:
        epg_files = os.listdir(EPG_WATCH_DIR)
        logger.trace(f"Found {len(epg_files)} files in EPG directory")
    except Exception as e:
        logger.error(f"Error listing EPG directory: {e}")
        epg_files = []

    epg_processed = 0
    epg_skipped = 0
    epg_errors = 0

    for filename in epg_files:
        filepath = os.path.join(EPG_WATCH_DIR, filename)

        if not os.path.isfile(filepath):
            # Use trace level if not first scan
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Not a file")
            else:
                logger.debug(f"Skipping {filename}: Not a file")
            epg_skipped += 1
            continue

        if not filename.endswith('.xml') and not filename.endswith('.gz') and not filename.endswith('.zip'):
            # Use trace level if not first scan
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Not an XML, GZ or zip file")
            else:
                logger.debug(f"Skipping {filename}: Not an XML, GZ or zip file")
            epg_skipped += 1
            continue

        mtime = os.path.getmtime(filepath)
        age = now - mtime
        redis_key = REDIS_PREFIX + filepath
        stored_mtime = redis_client.get(redis_key)

        # Instead of assuming old files were processed, check if they exist in the database
        if not stored_mtime and age > STARTUP_SKIP_AGE:
            # Check if this file is already in the database
            existing_epg = EPGSource.objects.filter(file_path=filepath).exists()
            if existing_epg:
                # Use trace level if not first scan
                if _first_scan_completed:
                    logger.trace(f"Skipping {filename}: Already exists in database")
                else:
                    logger.debug(f"Skipping {filename}: Already exists in database")
                redis_client.set(redis_key, mtime, ex=REDIS_TTL)
                epg_skipped += 1
                continue
            else:
                logger.debug(f"Processing {filename} despite age: Not found in database")
                # Continue processing this file even though it's old

        # File too new — probably still being written
        if age < MIN_AGE_SECONDS:
            # Use trace level if not first scan
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Too new, possibly still being written (age={age}s)")
            else:
                logger.debug(f"Skipping {filename}: Too new, possibly still being written (age={age}s)")
            epg_skipped += 1
            continue

        # Skip if we've already processed this mtime
        if stored_mtime and float(stored_mtime) >= mtime:
            # Use trace level if not first scan
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Already processed this version")
            else:
                logger.debug(f"Skipping {filename}: Already processed this version")
            epg_skipped += 1
            continue

        try:
            epg_source, created = EPGSource.objects.get_or_create(file_path=filepath, defaults={
                "name": filename,
                "source_type": "xmltv",
                "is_active": CoreSettings.get_auto_import_mapped_files() in [True, "true", "True"],
            })

            redis_client.set(redis_key, mtime, ex=REDIS_TTL)

            # More descriptive creation logging that includes active status
            if created:
                if epg_source.is_active:
                    logger.info(f"Created new EPG source '{filename}' (active)")
                else:
                    logger.info(f"Created new EPG source '{filename}' (inactive due to auto-import setting)")

            if not epg_source.is_active:
                # Use trace level if not first scan
                if _first_scan_completed:
                    logger.trace(f"Skipping {filename}: EPG source is marked as inactive")
                else:
                    logger.debug(f"Skipping {filename}: EPG source is marked as inactive")
                epg_skipped += 1
                continue

            # Log update for existing files (we've already logged creation above)
            if not created:
                logger.info(f"Detected update to existing EPG file: {filename}")

            logger.info(f"Queueing refresh for EPG file: {filename}")
            refresh_epg_data.delay(epg_source.id)  # Trigger Celery task
            epg_processed += 1

        except Exception as e:
            logger.error(f"Error processing EPG file {filename}: {str(e)}", exc_info=True)
            epg_errors += 1
            continue

    logger.trace(f"EPG processing complete: {epg_processed} processed, {epg_skipped} skipped, {epg_errors} errors")

    # Mark that the first scan is complete
    _first_scan_completed = True

def fetch_channel_stats():
    redis_client = RedisClient.get_client()

    try:
        # Basic info for all channels
        channel_pattern = "ts_proxy:channel:*:metadata"
        all_channels = []

        # Extract channel IDs from keys
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=channel_pattern)
            for key in keys:
                channel_id_match = re.search(r"ts_proxy:channel:(.*):metadata", key.decode('utf-8'))
                if channel_id_match:
                    ch_id = channel_id_match.group(1)
                    channel_info = ChannelStatus.get_basic_channel_info(ch_id)
                    if channel_info:
                        all_channels.append(channel_info)

            if cursor == 0:
                break

        send_websocket_update(
            "updates",
            "update",
            {
                "success": True,
                "type": "channel_stats",
                "stats": json.dumps({'channels': all_channels, 'count': len(all_channels)})
            },
            collect_garbage=True
        )

        # Explicitly clean up large data structures
        all_channels = None

    except Exception as e:
        logger.error(f"Error in channel_status: {e}", exc_info=True)
        return

@shared_task
def rehash_streams(keys):
    batch_size = 1000
    queryset = Stream.objects.all()

    hash_keys = {}
    total_records = queryset.count()
    for start in range(0, total_records, batch_size):
        with transaction.atomic():
            batch = queryset[start:start + batch_size]
            for obj in batch:
                stream_hash = Stream.generate_hash_key(obj.name, obj.url, obj.tvg_id, keys)
                if stream_hash in hash_keys:
                    # Handle duplicate keys and remove any without channels
                    stream_channels = ChannelStream.objects.filter(stream_id=obj.id).count()
                    if stream_channels == 0:
                        obj.delete()
                        continue


                    existing_stream_channels = ChannelStream.objects.filter(stream_id=hash_keys[stream_hash]).count()
                    if existing_stream_channels == 0:
                        Stream.objects.filter(id=hash_keys[stream_hash]).delete()

                obj.stream_hash = stream_hash
                obj.save(update_fields=['stream_hash'])
                hash_keys[stream_hash] = obj.id

        logger.debug(f"Re-hashed {batch_size} streams")

    logger.debug(f"Re-hashing complete")
