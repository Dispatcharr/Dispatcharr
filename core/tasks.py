from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import logging
import re
import time
import os
from core.utils import RedisClient, send_websocket_update, acquire_task_lock, release_task_lock
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
LOGO_WATCH_DIR = '/data/logos'
MIN_AGE_SECONDS = 6
STARTUP_SKIP_AGE = 30
REDIS_PREFIX = "processed_file:"
REDIS_TTL = 60 * 60 * 24 * 3  # expire keys after 3 days (optional)
SUPPORTED_LOGO_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']

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
    dirs_exist = all(os.path.exists(d) for d in [M3U_WATCH_DIR, EPG_WATCH_DIR, LOGO_WATCH_DIR])
    if not dirs_exist:
        throttled_log(logger.warning, f"Watch directories missing: M3U ({os.path.exists(M3U_WATCH_DIR)}), EPG ({os.path.exists(EPG_WATCH_DIR)}), LOGO ({os.path.exists(LOGO_WATCH_DIR)})", "watch_dirs_missing")

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

    # Process Logo files (including subdirectories)
    try:
        logo_files = []
        if os.path.exists(LOGO_WATCH_DIR):
            for root, dirs, files in os.walk(LOGO_WATCH_DIR):
                for filename in files:
                    logo_files.append(os.path.join(root, filename))
        logger.trace(f"Found {len(logo_files)} files in LOGO directory (including subdirectories)")
    except Exception as e:
        logger.error(f"Error listing LOGO directory: {e}")
        logo_files = []

    logo_processed = 0
    logo_skipped = 0
    logo_errors = 0

    for filepath in logo_files:
        filename = os.path.basename(filepath)

        if not os.path.isfile(filepath):
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Not a file")
            else:
                logger.debug(f"Skipping {filename}: Not a file")
            logo_skipped += 1
            continue

        # Check if file has supported logo extension
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in SUPPORTED_LOGO_FORMATS:
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Not a supported logo format")
            else:
                logger.debug(f"Skipping {filename}: Not a supported logo format")
            logo_skipped += 1
            continue

        mtime = os.path.getmtime(filepath)
        age = now - mtime
        redis_key = REDIS_PREFIX + filepath
        stored_mtime = redis_client.get(redis_key)

        # Check if logo already exists in database
        if not stored_mtime and age > STARTUP_SKIP_AGE:
            from apps.channels.models import Logo
            existing_logo = Logo.objects.filter(url=filepath).exists()
            if existing_logo:
                if _first_scan_completed:
                    logger.trace(f"Skipping {filename}: Already exists in database")
                else:
                    logger.debug(f"Skipping {filename}: Already exists in database")
                redis_client.set(redis_key, mtime, ex=REDIS_TTL)
                logo_skipped += 1
                continue
            else:
                logger.debug(f"Processing {filename} despite age: Not found in database")

        # File too new — probably still being written
        if age < MIN_AGE_SECONDS:
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Too new, possibly still being written (age={age}s)")
            else:
                logger.debug(f"Skipping {filename}: Too new, possibly still being written (age={age}s)")
            logo_skipped += 1
            continue

        # Skip if we've already processed this mtime
        if stored_mtime and float(stored_mtime) >= mtime:
            if _first_scan_completed:
                logger.trace(f"Skipping {filename}: Already processed this version")
            else:
                logger.debug(f"Skipping {filename}: Already processed this version")
            logo_skipped += 1
            continue

        try:
            from apps.channels.models import Logo

            # Create logo entry with just the filename (without extension) as name
            logo_name = os.path.splitext(filename)[0]

            logo, created = Logo.objects.get_or_create(
                url=filepath,
                defaults={
                    "name": logo_name,
                }
            )

            redis_client.set(redis_key, mtime, ex=REDIS_TTL)

            if created:
                logger.info(f"Created new logo entry: {logo_name}")
            else:
                logger.debug(f"Logo entry already exists: {logo_name}")

            logo_processed += 1

        except Exception as e:
            logger.error(f"Error processing logo file {filename}: {str(e)}", exc_info=True)
            logo_errors += 1
            continue

    logger.trace(f"LOGO processing complete: {logo_processed} processed, {logo_skipped} skipped, {logo_errors} errors")

    # Send summary websocket update for logo processing
    if logo_processed > 0 or logo_errors > 0:
        send_websocket_update(
            "updates",
            "update",
            {
                "success": True,
                "type": "logo_processing_summary",
                "processed": logo_processed,
                "skipped": logo_skipped,
                "errors": logo_errors,
                "total_files": len(logo_files),
                "message": f"Logo processing complete: {logo_processed} processed, {logo_skipped} skipped, {logo_errors} errors"
            }
        )

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
    """
    Regenerate stream hashes for all streams based on current hash key configuration.
    This task checks for and blocks M3U refresh tasks to prevent conflicts.
    """
    from apps.channels.models import Stream
    from apps.m3u.models import M3UAccount

    logger.info("Starting stream rehash process")

    # Get all M3U account IDs for locking
    m3u_account_ids = list(M3UAccount.objects.filter(is_active=True).values_list('id', flat=True))

    # Check if any M3U refresh tasks are currently running
    blocked_accounts = []
    for account_id in m3u_account_ids:
        if not acquire_task_lock('refresh_single_m3u_account', account_id):
            blocked_accounts.append(account_id)

    if blocked_accounts:
        # Release any locks we did acquire
        for account_id in m3u_account_ids:
            if account_id not in blocked_accounts:
                release_task_lock('refresh_single_m3u_account', account_id)

        logger.warning(f"Rehash blocked: M3U refresh tasks running for accounts: {blocked_accounts}")

        # Send WebSocket notification to inform user
        send_websocket_update(
            'updates',
            'update',
            {
                "success": False,
                "type": "stream_rehash",
                "action": "blocked",
                "blocked_accounts": len(blocked_accounts),
                "total_accounts": len(m3u_account_ids),
                "message": f"Stream rehash blocked: M3U refresh tasks are currently running for {len(blocked_accounts)} accounts. Please try again later."
            }
        )

        return f"Rehash blocked: M3U refresh tasks running for {len(blocked_accounts)} accounts"

    acquired_locks = m3u_account_ids.copy()

    try:
        batch_size = 1000
        queryset = Stream.objects.all()

        # Track statistics
        total_processed = 0
        duplicates_merged = 0
        hash_keys = {}

        total_records = queryset.count()
        logger.info(f"Starting rehash of {total_records} streams with keys: {keys}")

        # Send initial WebSocket update
        send_websocket_update(
            'updates',
            'update',
            {
                "success": True,
                "type": "stream_rehash",
                "action": "starting",
                "progress": 0,
                "total_records": total_records,
                "message": f"Starting rehash of {total_records} streams"
            }
        )

        for start in range(0, total_records, batch_size):
            batch_processed = 0
            batch_duplicates = 0

            with transaction.atomic():
                batch = queryset[start:start + batch_size]

                for obj in batch:
                    # Generate new hash
                    new_hash = Stream.generate_hash_key(obj.name, obj.url, obj.tvg_id, keys, m3u_id=obj.m3u_account_id)

                    # Check if this hash already exists in our tracking dict or in database
                    if new_hash in hash_keys:
                        # Found duplicate in current batch - merge the streams
                        existing_stream_id = hash_keys[new_hash]
                        existing_stream = Stream.objects.get(id=existing_stream_id)

                        # Move any channel relationships from duplicate to existing stream
                        # Handle potential unique constraint violations
                        for channel_stream in ChannelStream.objects.filter(stream_id=obj.id):
                            # Check if this channel already has a relationship with the target stream
                            existing_relationship = ChannelStream.objects.filter(
                                channel_id=channel_stream.channel_id,
                                stream_id=existing_stream_id
                            ).first()

                            if existing_relationship:
                                # Relationship already exists, just delete the duplicate
                                channel_stream.delete()
                            else:
                                # Safe to update the relationship
                                channel_stream.stream_id = existing_stream_id
                                channel_stream.save()

                        # Update the existing stream with the most recent data
                        if obj.updated_at > existing_stream.updated_at:
                            existing_stream.name = obj.name
                            existing_stream.url = obj.url
                            existing_stream.logo_url = obj.logo_url
                            existing_stream.tvg_id = obj.tvg_id
                            existing_stream.m3u_account = obj.m3u_account
                            existing_stream.channel_group = obj.channel_group
                            existing_stream.custom_properties = obj.custom_properties
                            existing_stream.last_seen = obj.last_seen
                            existing_stream.updated_at = obj.updated_at
                            existing_stream.save()

                        # Delete the duplicate
                        obj.delete()
                        batch_duplicates += 1
                    else:
                        # Check if hash already exists in database (from previous batches or existing data)
                        existing_stream = Stream.objects.filter(stream_hash=new_hash).exclude(id=obj.id).first()
                        if existing_stream:
                            # Found duplicate in database - merge the streams
                            # Move any channel relationships from duplicate to existing stream
                            # Handle potential unique constraint violations
                            for channel_stream in ChannelStream.objects.filter(stream_id=obj.id):
                                # Check if this channel already has a relationship with the target stream
                                existing_relationship = ChannelStream.objects.filter(
                                    channel_id=channel_stream.channel_id,
                                    stream_id=existing_stream.id
                                ).first()

                                if existing_relationship:
                                    # Relationship already exists, just delete the duplicate
                                    channel_stream.delete()
                                else:
                                    # Safe to update the relationship
                                    channel_stream.stream_id = existing_stream.id
                                    channel_stream.save()

                            # Update the existing stream with the most recent data
                            if obj.updated_at > existing_stream.updated_at:
                                existing_stream.name = obj.name
                                existing_stream.url = obj.url
                                existing_stream.logo_url = obj.logo_url
                                existing_stream.tvg_id = obj.tvg_id
                                existing_stream.m3u_account = obj.m3u_account
                                existing_stream.channel_group = obj.channel_group
                                existing_stream.custom_properties = obj.custom_properties
                                existing_stream.last_seen = obj.last_seen
                                existing_stream.updated_at = obj.updated_at
                                existing_stream.save()

                            # Delete the duplicate
                            obj.delete()
                            batch_duplicates += 1
                            hash_keys[new_hash] = existing_stream.id
                        else:
                            # Update hash for this stream
                            obj.stream_hash = new_hash
                            obj.save(update_fields=['stream_hash'])
                            hash_keys[new_hash] = obj.id

                    batch_processed += 1

            total_processed += batch_processed
            duplicates_merged += batch_duplicates

            # Calculate progress percentage
            progress_percent = int((total_processed / total_records) * 100)
            current_batch = start // batch_size + 1
            total_batches = (total_records // batch_size) + 1

            # Send progress update via WebSocket
            send_websocket_update(
                'updates',
                'update',
                {
                    "success": True,
                    "type": "stream_rehash",
                    "action": "processing",
                    "progress": progress_percent,
                    "batch": current_batch,
                    "total_batches": total_batches,
                    "processed": total_processed,
                    "duplicates_merged": duplicates_merged,
                    "message": f"Processed batch {current_batch}/{total_batches}: {batch_processed} streams, {batch_duplicates} duplicates merged"
                }
            )

            logger.info(f"Rehashed batch {current_batch}/{total_batches}: "
                       f"{batch_processed} processed, {batch_duplicates} duplicates merged")

        logger.info(f"Rehashing complete: {total_processed} streams processed, "
                   f"{duplicates_merged} duplicates merged")

        # Send completion update via WebSocket
        send_websocket_update(
            'updates',
            'update',
            {
                "success": True,
                "type": "stream_rehash",
                "action": "completed",
                "progress": 100,
                "total_processed": total_processed,
                "duplicates_merged": duplicates_merged,
                "final_count": total_processed - duplicates_merged,
                "message": f"Rehashing complete: {total_processed} streams processed, {duplicates_merged} duplicates merged"
            },
            collect_garbage=True  # Force garbage collection after completion
        )

        logger.info("Stream rehash completed successfully")
        return f"Successfully rehashed {total_processed} streams"

    except Exception as e:
        logger.error(f"Error during stream rehash: {e}")
        raise
    finally:
        # Always release all acquired M3U locks
        for account_id in acquired_locks:
            release_task_lock('refresh_single_m3u_account', account_id)
        logger.info(f"Released M3U task locks for {len(acquired_locks)} accounts")


@shared_task
def cleanup_vod_persistent_connections():
    """Clean up stale VOD persistent connections"""
    try:
        from apps.proxy.vod_proxy.connection_manager import VODConnectionManager

        # Clean up connections older than 30 minutes
        VODConnectionManager.cleanup_stale_persistent_connections(max_age_seconds=1800)
        logger.info("VOD persistent connection cleanup completed")

    except Exception as e:
        logger.error(f"Error during VOD persistent connection cleanup: {e}")
