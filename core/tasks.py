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

        # Track statistics
        total_processed = 0
        duplicates_merged = 0
        # hash_keys maps new_hash -> stream_id for streams we've already processed
        hash_keys = {}
        # Track IDs of streams that have been deleted to avoid stale references
        deleted_stream_ids = set()

        # Get initial count for progress reporting
        initial_total_records = Stream.objects.count()
        logger.info(f"Starting rehash of {initial_total_records} streams with keys: {keys}")

        # Send initial WebSocket update
        send_websocket_update(
            'updates',
            'update',
            {
                "success": True,
                "type": "stream_rehash",
                "action": "starting",
                "progress": 0,
                "total_records": initial_total_records,
                "message": f"Starting rehash of {initial_total_records} streams"
            }
        )

        # Use ID-based pagination to handle deletions correctly
        # This ensures we don't skip records when items are deleted
        last_processed_id = 0
        batch_number = 0

        while True:
            batch_number += 1
            batch_processed = 0
            batch_duplicates = 0

            with transaction.atomic():
                # Fetch batch by ID ordering, using select_for_update to lock records
                # This prevents race conditions and ensures we process each record exactly once
                batch = list(
                    Stream.objects.filter(id__gt=last_processed_id)
                    .select_for_update(skip_locked=True, of=('self',))
                    .select_related('channel_group', 'm3u_account')
                    .order_by('id')[:batch_size]
                )

                if not batch:
                    # No more records to process
                    break

                for obj in batch:
                    # Update the last processed ID for next batch
                    last_processed_id = obj.id

                    # Generate new hash - handle XC accounts differently
                    group_name = obj.channel_group.name if obj.channel_group else None
                    account_type = obj.m3u_account.account_type if obj.m3u_account else None
                    stream_id_val = obj.stream_id if hasattr(obj, 'stream_id') else None

                    new_hash = Stream.generate_hash_key(
                        obj.name, obj.url, obj.tvg_id, keys,
                        m3u_id=obj.m3u_account_id, group=group_name,
                        account_type=account_type, stream_id=stream_id_val
                    )

                    # Check if this hash already exists in our tracking dict
                    if new_hash in hash_keys:
                        existing_stream_id = hash_keys[new_hash]

                        # Verify the target stream still exists and hasn't been deleted
                        if existing_stream_id in deleted_stream_ids:
                            # The target was deleted, so this stream becomes the new canonical one
                            obj.stream_hash = new_hash
                            obj.save(update_fields=['stream_hash'])
                            hash_keys[new_hash] = obj.id
                            batch_processed += 1
                            continue

                        try:
                            existing_stream = Stream.objects.get(id=existing_stream_id)
                        except Stream.DoesNotExist:
                            # Target stream was deleted externally, make this the canonical one
                            deleted_stream_ids.add(existing_stream_id)
                            obj.stream_hash = new_hash
                            obj.save(update_fields=['stream_hash'])
                            hash_keys[new_hash] = obj.id
                            batch_processed += 1
                            continue

                        # Determine which stream to keep based on channel ordering
                        stream_to_keep, stream_to_delete = _determine_stream_to_keep(existing_stream, obj)

                        # Move channel relationships from the stream being deleted to the one being kept
                        _merge_stream_relationships(stream_to_delete, stream_to_keep)

                        # Delete the duplicate FIRST to free up the unique hash constraint
                        deleted_stream_ids.add(stream_to_delete.id)
                        stream_to_delete.delete()
                        batch_duplicates += 1

                        # Now safely set the hash on the kept stream (after deletion freed it up)
                        if stream_to_keep.stream_hash != new_hash:
                            stream_to_keep.stream_hash = new_hash
                            stream_to_keep.save(update_fields=['stream_hash'])

                        # Update hash_keys to point to the kept stream
                        hash_keys[new_hash] = stream_to_keep.id
                    else:
                        # Check if hash already exists in database (from streams not yet processed)
                        existing_stream = Stream.objects.filter(stream_hash=new_hash).exclude(id=obj.id).first()
                        if existing_stream:
                            # Found duplicate in database - determine which to keep based on channel ordering
                            stream_to_keep, stream_to_delete = _determine_stream_to_keep(existing_stream, obj)

                            # Move channel relationships from the stream being deleted to the one being kept
                            _merge_stream_relationships(stream_to_delete, stream_to_keep)

                            # Delete the duplicate FIRST to free up the unique hash constraint
                            deleted_stream_ids.add(stream_to_delete.id)
                            stream_to_delete.delete()
                            batch_duplicates += 1

                            # Now safely set the hash on the kept stream (after deletion freed it up)
                            if stream_to_keep.stream_hash != new_hash:
                                stream_to_keep.stream_hash = new_hash
                                stream_to_keep.save(update_fields=['stream_hash'])

                            hash_keys[new_hash] = stream_to_keep.id
                        else:
                            # No duplicate - update hash for this stream
                            obj.stream_hash = new_hash
                            obj.save(update_fields=['stream_hash'])
                            hash_keys[new_hash] = obj.id

                    batch_processed += 1

            total_processed += batch_processed
            duplicates_merged += batch_duplicates

            # Calculate progress percentage based on initial count
            # Cap at 99% until we're actually done to avoid showing 100% prematurely
            progress_percent = min(99, int((total_processed / max(initial_total_records, 1)) * 100))

            # Send progress update via WebSocket
            send_websocket_update(
                'updates',
                'update',
                {
                    "success": True,
                    "type": "stream_rehash",
                    "action": "processing",
                    "progress": progress_percent,
                    "batch": batch_number,
                    "processed": total_processed,
                    "duplicates_merged": duplicates_merged,
                    "message": f"Processed batch {batch_number}: {batch_processed} streams, {batch_duplicates} duplicates merged"
                }
            )

            logger.info(f"Rehashed batch {batch_number}: "
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
        logger.error(f"Error during stream rehash: {e}", exc_info=True)
        raise
    finally:
        # Always release all acquired M3U locks
        for account_id in acquired_locks:
            release_task_lock('refresh_single_m3u_account', account_id)
        logger.info(f"Released M3U task locks for {len(acquired_locks)} accounts")


def _merge_stream_relationships(source_stream, target_stream):
    """
    Move channel relationships from source_stream to target_stream.
    Handles unique constraint violations by preserving existing relationships.
    Preserves the best ordering when merging relationships.
    """
    for channel_stream in ChannelStream.objects.filter(stream_id=source_stream.id):
        # Check if this channel already has a relationship with the target stream
        existing_relationship = ChannelStream.objects.filter(
            channel_id=channel_stream.channel_id,
            stream_id=target_stream.id
        ).first()

        if existing_relationship:
            # Relationship already exists - keep the one with better ordering (lower order value)
            if channel_stream.order < existing_relationship.order:
                existing_relationship.order = channel_stream.order
                existing_relationship.save(update_fields=['order'])
            # Delete the duplicate relationship
            channel_stream.delete()
        else:
            # Safe to update the relationship
            channel_stream.stream_id = target_stream.id
            channel_stream.save()


def _get_best_channel_order(stream):
    """
    Get the best (lowest) channel order for a stream.
    Returns None if stream has no channel relationships.
    Lower order value = better/higher position in the channel list.
    """
    best_order = ChannelStream.objects.filter(stream_id=stream.id).order_by('order').values_list('order', flat=True).first()
    return best_order


def _determine_stream_to_keep(stream_a, stream_b):
    """
    Determine which stream should be kept when merging duplicates.

    Priority:
    1. Stream with better (lower) channel order wins
    2. If both have same order or neither has channel relationships,
       keep the one with more recent updated_at
    3. If still tied, keep the one with the lower ID (more stable)

    Returns: (stream_to_keep, stream_to_delete)
    """
    order_a = _get_best_channel_order(stream_a)
    order_b = _get_best_channel_order(stream_b)

    # If one has channel relationships and the other doesn't, keep the one with relationships
    if order_a is not None and order_b is None:
        return (stream_a, stream_b)
    if order_b is not None and order_a is None:
        return (stream_b, stream_a)

    # If both have channel relationships, keep the one with better (lower) order
    if order_a is not None and order_b is not None:
        if order_a < order_b:
            return (stream_a, stream_b)
        elif order_b < order_a:
            return (stream_b, stream_a)
        # Same order, fall through to other criteria

    # Neither has relationships, or same order - use updated_at
    if stream_a.updated_at > stream_b.updated_at:
        return (stream_a, stream_b)
    elif stream_b.updated_at > stream_a.updated_at:
        return (stream_b, stream_a)

    # Same updated_at - keep lower ID for stability
    if stream_a.id < stream_b.id:
        return (stream_a, stream_b)
    return (stream_b, stream_a)


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


@shared_task
def check_for_version_update():
    """
    Check for new Dispatcharr versions on GitHub and create a notification if available.
    This task should be run periodically (e.g., daily) via Celery Beat.

    For dev builds (identified by __timestamp__), checks for stable releases only.
    For production builds, checks for stable releases.

    Note: Dev builds are container images from the dev branch and don't have GitHub releases.
    This checks if a stable release is available so dev users know when to upgrade.
    """
    import requests
    from datetime import datetime, timezone
    from packaging import version as pkg_version
    from version import __version__, __timestamp__
    from core.models import SystemNotification
    from core.utils import send_websocket_notification

    try:
        is_dev_build = __timestamp__ is not None
        DISPATCHARR_HEADERS = {'User-Agent': f'Dispatcharr/{__version__}'}
        if is_dev_build:
            # Check Docker Hub for newer dev builds
            docker_hub_url = "https://hub.docker.com/v2/repositories/dispatcharr/dispatcharr/tags/dev"

            response = requests.get(docker_hub_url, headers=DISPATCHARR_HEADERS, timeout=10)

            if response.status_code != 200:
                logger.warning(f"Failed to check Docker Hub for dev updates: HTTP {response.status_code}")
                return

            dev_tag_data = response.json()
            docker_last_updated = dev_tag_data.get("last_updated")

            if not docker_last_updated:
                logger.warning("No last_updated timestamp found in Docker Hub response")
                return

            # Parse timestamps for comparison
            local_dt = datetime.strptime(__timestamp__, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            docker_dt = datetime.fromisoformat(docker_last_updated.replace('Z', '+00:00'))

            # Calculate difference in minutes
            diff_minutes = (docker_dt - local_dt).total_seconds() / 60

            # Threshold to account for build/push time differences
            THRESHOLD_MINUTES = 10

            if diff_minutes > THRESHOLD_MINUTES:
                logger.info(f"New dev build available on Docker Hub (updated {int(diff_minutes)} minutes after current build)")

                # Delete any old version update notifications (both dev and stable, in case user switched)
                deleted_count = SystemNotification.objects.filter(
                    notification_type='version_update'
                ).delete()[0]
                if deleted_count > 0:
                    logger.debug(f"Deleted {deleted_count} old dev build notification(s)")
                    send_websocket_update(
                        'updates',
                        'update',
                        {
                            'success': True,
                            'type': 'notifications_cleared',
                            'count': deleted_count
                        }
                    )

                # Create notification for new dev build
                notification, created = SystemNotification.objects.get_or_create(
                    notification_key=f'version-dev-{docker_last_updated}',
                    defaults={
                        'notification_type': 'version_update',
                        'title': 'New Dev Build Available',
                        'message': f'A newer development build is available on Docker Hub (v{__version__}-dev)',
                        'priority': 'medium',
                        'action_data': {
                            'current_version': __version__,
                            'current_timestamp': __timestamp__,
                            'docker_updated': docker_last_updated,
                            'update_url': 'https://hub.docker.com/r/dispatcharr/dispatcharr/tags'
                        },
                        'is_active': True,
                        'admin_only': True,
                    }
                )

                if created:
                    # Only send WebSocket for newly created notifications
                    send_websocket_notification(notification)
                    logger.info(f"New dev build notification created and sent via WebSocket")
            else:
                logger.debug(f"Dev build is up to date (Docker Hub image is {abs(int(diff_minutes))} minutes {'newer' if diff_minutes > 0 else 'older'})")

                # Delete all version update notifications when up to date (both dev and stable)
                deleted_count = SystemNotification.objects.filter(
                    notification_type='version_update'
                ).delete()[0]

                if deleted_count > 0:
                    logger.info(f"Deleted {deleted_count} outdated dev build notification(s)")
                    send_websocket_update(
                        'updates',
                        'update',
                        {
                            'success': True,
                            'type': 'notifications_cleared',
                            'count': deleted_count
                        }
                    )
        else:
            # Production build - check GitHub for stable releases
            github_api_url = "https://api.github.com/repos/Dispatcharr/Dispatcharr/releases/latest"
            headers = {"Accept": "application/vnd.github.v3+json", **DISPATCHARR_HEADERS}
            response = requests.get(
                github_api_url,
                headers=headers,
                timeout=10
            )

            if response.status_code != 200:
                logger.warning(f"Failed to check for updates: HTTP {response.status_code}")
                return

            release_data = response.json()
            latest_version = release_data.get("tag_name", "").lstrip("v")
            release_url = release_data.get("html_url", "")

            if not latest_version:
                logger.warning("No version tag found in GitHub release")
                return

            # Compare versions
            current = pkg_version.parse(__version__)
            latest = pkg_version.parse(latest_version)
            if latest > current:
                logger.info(f"New stable version available: {latest_version} (current: {__version__})")

                # Delete any old version update notifications (superseded by this one)
                deleted_count = SystemNotification.objects.filter(
                    notification_type='version_update'
                ).exclude(
                    notification_key=f"version-{latest_version}"
                ).delete()[0]
                if deleted_count > 0:
                    logger.debug(f"Deleted {deleted_count} old version notification(s)")
                    send_websocket_update(
                        'updates',
                        'update',
                        {
                            'success': True,
                            'type': 'notifications_cleared',
                            'count': deleted_count
                        }
                    )

                # Create or update the notification for the new version
                notification, created = SystemNotification.create_version_notification(
                    version=latest_version,
                    release_url=release_url,
                )

                if created:
                    # Only send WebSocket for newly created notifications
                    send_websocket_notification(notification)
                    logger.info(f"New version notification created and sent via WebSocket")
            else:
                logger.debug(f"Dispatcharr is up to date (v{__version__})")

                # Delete ALL version update notifications when up to date (no longer needed)
                deleted_count = SystemNotification.objects.filter(
                    notification_type='version_update'
                ).delete()[0]

                if deleted_count > 0:
                    logger.info(f"Deleted {deleted_count} outdated version notification(s)")
                    send_websocket_update(
                        'updates',
                        'update',
                        {
                            'success': True,
                            'type': 'notifications_cleared',
                            'count': deleted_count
                        }
                    )

    except requests.RequestException as e:
        logger.warning(f"Network error checking for updates: {e}")
    except Exception as e:
        logger.error(f"Error checking for version updates: {e}")


def create_setting_recommendation(setting_key, recommended_value, reason, current_value=None):
    """
    Create a setting recommendation notification.
    This is a helper function that can be called from anywhere in the codebase.

    Args:
        setting_key: The setting key (e.g., 'proxy_settings.buffering_timeout')
        recommended_value: The recommended value for the setting
        reason: Why this setting is recommended
        current_value: The current value (optional)

    Returns:
        The created SystemNotification instance
    """
    from core.models import SystemNotification
    from core.utils import send_websocket_notification

    notification, created = SystemNotification.create_setting_recommendation(
        setting_key=setting_key,
        recommended_value=recommended_value,
        reason=reason,
        current_value=current_value
    )

    # Only send via WebSocket for newly created notifications
    if created:
        send_websocket_notification(notification)

    return notification

