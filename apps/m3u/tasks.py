# apps/m3u/tasks.py
import logging
import re
import requests
import os
from celery.app.control import Inspect
from celery.result import AsyncResult
from celery import shared_task, current_app, group
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from .models import M3UAccount
from apps.channels.models import Stream, ChannelGroup, ChannelGroupM3UAccount
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
import time
import json
from core.utils import redis_client
from core.models import CoreSettings
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)

LOCK_EXPIRE = 300
BATCH_SIZE = 1000
SKIP_EXTS = {}
m3u_dir = os.path.join(settings.MEDIA_ROOT, "cached_m3u")

def fetch_m3u_lines(account, use_cache=False):
    os.makedirs(m3u_dir, exist_ok=True)
    file_path = os.path.join(m3u_dir, f"{account.id}.m3u")

    """Fetch M3U file lines efficiently."""
    if account.server_url:
        if not use_cache or not os.path.exists(file_path):
            headers = {"User-Agent": account.user_agent.user_agent}
            logger.info(f"Fetching from URL {account.server_url}")
            try:
                response = requests.get(account.server_url, headers=headers, stream=True)
                response.raise_for_status()  # This will raise an HTTPError if the status is not 200
                with open(file_path, 'wb') as file:
                    # Stream the content in chunks and write to the file
                    for chunk in response.iter_content(chunk_size=8192):  # You can adjust the chunk size
                        if chunk:  # Ensure chunk is not empty
                            file.write(chunk)
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching M3U from URL {account.server_url}: {e}")
                return []  # Return an empty list in case of error

        with open(file_path, 'r', encoding='utf-8') as f:
            return f.readlines()
    elif account.uploaded_file:
        try:
            # Open the file and return the lines as a list or iterator
            with open(account.uploaded_file.path, 'r', encoding='utf-8') as f:
                return f.readlines()  # Ensure you return lines from the file, not the file object
        except IOError as e:
            logger.error(f"Error opening file {account.uploaded_file.path}: {e}")
            return []  # Return an empty list in case of error

    # Return an empty list if neither server_url nor uploaded_file is available
    return []

def parse_extinf_line(line: str) -> dict:
    """
    Parse an EXTINF line from an M3U file.
    This function removes the "#EXTINF:" prefix, then splits the remaining
    string on the first comma that is not enclosed in quotes.

    Returns a dictionary with:
      - 'attributes': a dict of attribute key/value pairs (e.g. tvg-id, tvg-logo, group-title)
      - 'display_name': the text after the comma (the fallback display name)
      - 'name': the value from tvg-name (if present) or the display name otherwise.
    """
    if not line.startswith("#EXTINF:"):
        return None
    content = line[len("#EXTINF:"):].strip()
    # Split on the first comma that is not inside quotes.
    parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', content, maxsplit=1)
    if len(parts) != 2:
        return None
    attributes_part, display_name = parts[0], parts[1].strip()
    attrs = dict(re.findall(r'([^\s]+)=["\']([^"\']+)["\']', attributes_part))
    # Use tvg-name attribute if available; otherwise, use the display name.
    name = attrs.get('tvg-name', display_name)
    return {
        'attributes': attrs,
        'display_name': display_name,
        'name': name
    }

import re
import logging

logger = logging.getLogger(__name__)

def _matches_filters(stream_name: str, group_name: str, filters):
    """Check if a stream or group name matches a precompiled regex filter."""
    compiled_filters = [(re.compile(f.regex_pattern, re.IGNORECASE), f.exclude) for f in filters]
    for pattern, exclude in compiled_filters:
        target = group_name if f.filter_type == 'group' else stream_name
        if pattern.search(target or ''):
            return exclude
    return False

def acquire_lock(task_name, account_id):
    """Acquire a lock to prevent concurrent task execution."""
    lock_id = f"task_lock_{task_name}_{account_id}"
    lock_acquired = cache.add(lock_id, "locked", timeout=LOCK_EXPIRE)
    if not lock_acquired:
        logger.warning(f"Lock for {task_name} and account_id={account_id} already acquired. Task will not proceed.")
    return lock_acquired

def release_lock(task_name, account_id):
    """Release the lock after task execution."""
    lock_id = f"task_lock_{task_name}_{account_id}"
    cache.delete(lock_id)

@shared_task
def refresh_m3u_accounts():
    """Queue background parse for all active M3UAccounts."""
    active_accounts = M3UAccount.objects.filter(is_active=True)
    count = 0
    for account in active_accounts:
        refresh_single_m3u_account.delay(account.id)
        count += 1

    msg = f"Queued M3U refresh for {count} active account(s)."
    logger.info(msg)
    return msg

def check_field_lengths(streams_to_create):
    for stream in streams_to_create:
        for field, value in stream.__dict__.items():
            if isinstance(value, str) and len(value) > 255:
                print(f"{field} --- {value}")

        print("")
        print("")

@shared_task
def process_groups(account, group_names):
    existing_groups = {group.name: group for group in ChannelGroup.objects.filter(name__in=group_names)}
    logger.info(f"Currently {len(existing_groups)} existing groups")

    groups = []
    groups_to_create = []
    for group_name in group_names:
        logger.info(f"Handling group: {group_name}")
        if group_name in existing_groups:
            groups.append(existing_groups[group_name])
        else:
            groups_to_create.append(ChannelGroup(
                name=group_name,
            ))

    if groups_to_create:
        logger.info(f"Creating {len(groups_to_create)} groups")
        created = ChannelGroup.bulk_create_and_fetch(groups_to_create)
        logger.info(f"Created {len(created)} groups")
        groups.extend(created)

    relations = []
    for group in groups:
        relations.append(ChannelGroupM3UAccount(
            channel_group=group,
            m3u_account=account,
        ))

    ChannelGroupM3UAccount.objects.bulk_create(
        relations,
        ignore_conflicts=True
    )

@shared_task
def process_m3u_batch(account_id, batch, group_names, hash_keys):
    """Processes a batch of M3U streams using bulk operations."""
    account = M3UAccount.objects.get(id=account_id)
    existing_groups = {group.name: group for group in ChannelGroup.objects.filter(
        m3u_account__m3u_account=account,  # Filter by the M3UAccount
        m3u_account__enabled=True  # Filter by the enabled flag in the join table
    )}

    streams_to_create = []
    streams_to_update = []
    stream_hashes = {}

    # compiled_filters = [(f.filter_type, re.compile(f.regex_pattern, re.IGNORECASE)) for f in filters]

    logger.debug(f"Processing batch of {len(batch)}")
    for stream_info in batch:
        name, url = stream_info["name"], stream_info["url"]
        tvg_id, tvg_logo = stream_info["attributes"].get("tvg-id", ""), stream_info["attributes"].get("tvg-logo", "")
        group_title = stream_info["attributes"].get("group-title", "Default Group")

        # Filter out disabled groups for this account
        if group_title not in existing_groups:
            logger.debug(f"Skipping stream in disabled group: {group_title}")
            continue

        # if any(url.lower().endswith(ext) for ext in SKIP_EXTS) or len(url) > 2000:
        #     continue

        # if _matches_filters(name, group_title, account.filters.all()):
        #     continue

        # if any(compiled_pattern.search(current_info['name']) for ftype, compiled_pattern in compiled_filters if ftype == 'name'):
        #     excluded_count += 1
        #     current_info = None
        #     continue

        try:
            stream_hash = Stream.generate_hash_key(name, url, tvg_id, hash_keys)
            if redis_client.exists(f"m3u_refresh:{stream_hash}"):
                # duplicate already processed by another batch
                continue

            redis_client.set(f"m3u_refresh:{stream_hash}", "true")
            stream_props = {
                "name": name,
                "url": url,
                "logo_url": tvg_logo,
                "tvg_id": tvg_id,
                "m3u_account": account,
                "channel_group": existing_groups[group_title],
                "stream_hash": stream_hash,
            }

            if stream_hash not in stream_hashes:
                stream_hashes[stream_hash] = stream_props
        except Exception as e:
            logger.error(f"Failed to process stream {name}: {e}")
            logger.error(json.dumps(stream_info))

    existing_streams = {s.stream_hash: s for s in Stream.objects.filter(stream_hash__in=stream_hashes.keys())}

    for stream_hash, stream_props in stream_hashes.items():
        if stream_hash in existing_streams:
            obj = existing_streams[stream_hash]
            changed = False
            for key, value in stream_props.items():
                if hasattr(obj, key) and getattr(obj, key) == value:
                    continue
                changed = True
                setattr(obj, key, value)

            obj.last_seen = timezone.now()
            if changed:
                streams_to_update.append(obj)
                del existing_streams[stream_hash]
            else:
                existing_streams[stream_hash] = obj
        else:
            stream_props["last_seen"] = timezone.now()
            streams_to_create.append(Stream(**stream_props))

    try:
        if streams_to_create:
            Stream.objects.bulk_create(streams_to_create, ignore_conflicts=True)
        if streams_to_update:
            Stream.objects.bulk_update(streams_to_update, stream_props.keys())
        if len(existing_streams.keys()) > 0:
            Stream.objects.bulk_update(existing_streams.values(), ["last_seen"])
    except Exception as e:
        logger.error(f"Bulk create failed: {str(e)}")


    return f"Batch processed: {len(streams_to_create)} created, {len(streams_to_update)} updated."

def cleanup_streams(account_id):
    account = M3UAccount.objects.get(id=account_id, is_active=True)
    existing_groups = ChannelGroup.objects.filter(
        m3u_account__m3u_account=account,
        m3u_account__enabled=True,
    ).values_list('id', flat=True)
    logger.info(f"Found {len(existing_groups)} active groups")
    streams = Stream.objects.filter(m3u_account=account)

    streams_to_delete = Stream.objects.filter(
        m3u_account=account
    ).exclude(
        channel_group__in=existing_groups  # Exclude products having any of the excluded tags
    )

    # Delete the filtered products
    streams_to_delete.delete()

    logger.info(f"Cleanup complete")

def refresh_m3u_groups(account_id):
    if not acquire_lock('refresh_m3u_account_groups', account_id):
        return f"Task already running for account_id={account_id}.", None

    # Record start time
    start_time = time.time()
    send_progress_update(0, account_id)

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
    except M3UAccount.DoesNotExist:
        release_lock('refresh_m3u_account_groups', account_id)
        return f"M3UAccount with ID={account_id} not found or inactive."

    lines = fetch_m3u_lines(account)
    extinf_data = []
    groups = set(["Default Group"])

    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            parsed = parse_extinf_line(line)
            if parsed:
                if "group-title" in parsed["attributes"]:
                    groups.add(parsed["attributes"]["group-title"])

                extinf_data.append(parsed)
        elif extinf_data and line.startswith("http"):
            # Associate URL with the last EXTINF line
            extinf_data[-1]["url"] = line

    groups = list(groups)
    cache_path = os.path.join(m3u_dir, f"{account_id}.json")
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump({
            "extinf_data": extinf_data,
            "groups": groups,
        }, f)

    process_groups(account, groups)

    release_lock('refresh_m3u_account_groups`', account_id)

    return extinf_data, groups

@shared_task
def refresh_single_m3u_account(account_id, use_cache=False):
    """Splits M3U processing into chunks and dispatches them as parallel tasks."""
    if not acquire_lock('refresh_single_m3u_account', account_id):
        return f"Task already running for account_id={account_id}."

    # Record start time
    start_time = time.time()
    send_progress_update(0, account_id)

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
        filters = list(account.filters.all())
    except M3UAccount.DoesNotExist:
        release_lock('refresh_single_m3u_account', account_id)
        return f"M3UAccount with ID={account_id} not found or inactive."

    # Fetch M3U lines and handle potential issues
    # lines = fetch_m3u_lines(account)  # Extracted fetch logic into separate function
    extinf_data = []
    groups = None

    cache_path = os.path.join(m3u_dir, f"{account_id}.json")
    if use_cache and os.path.exists(cache_path):
        with open(cache_path, 'r') as file:
            data = json.load(file)

        extinf_data = data['extinf_data']
        groups = data['groups']

    if not extinf_data:
        try:
            extinf_data, groups = refresh_m3u_groups(account_id)
        except:
            return "Failed to update m3u account"

    hash_keys = CoreSettings.get_m3u_hash_key().split(",")

    # Break into batches and process in parallel
    batches = [extinf_data[i:i + BATCH_SIZE] for i in range(0, len(extinf_data), BATCH_SIZE)]
    task_group = group(process_m3u_batch.s(account_id, batch, groups, hash_keys) for batch in batches)

    total_batches = len(batches)
    completed_batches = 0
    logger.debug(f"Dispatched {len(batches)} parallel tasks for account_id={account_id}.")

    # result = task_group.apply_async()
    result = task_group.apply_async()

    while completed_batches < total_batches:
        for async_result in result:
            if async_result.ready():  # If the task has completed
                task_result = async_result.result  # The result of the task
                logger.debug(f"Task completed with result: {task_result}")
                completed_batches += 1

                # Calculate progress
                progress = int((completed_batches / total_batches) * 100)

                # Send progress update via Channels
                # Don't send 100% because we want to clean up after
                if progress == 100:
                    progress = 99

                send_progress_update(progress, account_id)

                # Optionally remove completed task from the group to prevent processing it again
                result.remove(async_result)
            else:
                logger.debug(f"Task is still running.")

    # Run cleanup
    cleanup_streams(account_id)
    send_progress_update(100, account_id)

    end_time = time.time()

    # Calculate elapsed time
    elapsed_time = end_time - start_time

    print(f"Function took {elapsed_time} seconds to execute.")

    release_lock('refresh_single_m3u_account', account_id)

    cursor = 0
    while True:
        cursor, keys = redis_client.scan(cursor, match=f"m3u_refresh:*", count=BATCH_SIZE)
        if keys:
            redis_client.delete(*keys)  # Delete the matching keys
        if cursor == 0:
            break

    return f"Dispatched jobs complete."

def send_progress_update(progress, account_id):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'updates',
        {
            'type': 'update',
            "data": {"progress": progress, "type": "m3u_refresh", "account": account_id}
        }
    )
