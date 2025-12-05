# apps/m3u/tasks.py
import logging
import re
import requests
import os
import gc
import gzip, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from core.utils import (
    RedisClient,
    acquire_task_lock,
    release_task_lock,
    natural_sort_key,
    log_system_event,
)
from core.models import CoreSettings, UserAgent
from asgiref.sync import async_to_sync
from core.xtream_codes import Client as XCClient
from core.utils import send_websocket_update
from .utils import normalize_stream_url

logger = logging.getLogger(__name__)

BATCH_SIZE = 1500  # Optimized batch size for threading
m3u_dir = os.path.join(settings.MEDIA_ROOT, "cached_m3u")


def fetch_m3u_lines(account, use_cache=False):
    os.makedirs(m3u_dir, exist_ok=True)
    file_path = os.path.join(m3u_dir, f"{account.id}.m3u")

    """Fetch M3U file lines efficiently."""
    if account.server_url:
        if not use_cache or not os.path.exists(file_path):
            try:
                # Try to get account-specific user agent first
                user_agent_obj = account.get_user_agent()
                user_agent = (
                    user_agent_obj.user_agent
                    if user_agent_obj
                    else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )

                logger.debug(
                    f"Using user agent: {user_agent} for M3U account: {account.name}"
                )
                headers = {"User-Agent": user_agent}
                logger.info(f"Fetching from URL {account.server_url}")

                # Set account status to FETCHING before starting download
                account.status = M3UAccount.Status.FETCHING
                account.last_message = "Starting download..."
                account.save(update_fields=["status", "last_message"])

                response = requests.get(
                    account.server_url, headers=headers, stream=True
                )

                # Log the actual response details for debugging
                logger.debug(f"HTTP Response: {response.status_code} from {account.server_url}")
                logger.debug(f"Content-Type: {response.headers.get('content-type', 'Not specified')}")
                logger.debug(f"Content-Length: {response.headers.get('content-length', 'Not specified')}")
                logger.debug(f"Response headers: {dict(response.headers)}")

                # Check if we've been redirected to a different URL
                if hasattr(response, 'url') and response.url != account.server_url:
                    logger.warning(f"Request was redirected from {account.server_url} to {response.url}")

                # Check for ANY non-success status code FIRST (before raise_for_status)
                if response.status_code < 200 or response.status_code >= 300:
                    # For error responses, read the content immediately (not streaming)
                    try:
                        response_content = response.text[:1000]  # Capture up to 1000 characters
                        logger.error(f"Error response content: {response_content!r}")
                    except Exception as e:
                        logger.error(f"Could not read error response content: {e}")
                        response_content = "Could not read error response content"

                    # Provide specific messages for known non-standard codes
                    if response.status_code == 884:
                        error_msg = f"Server returned HTTP 884 (authentication/authorization failure) from URL: {account.server_url}. Server message: {response_content}"
                    elif response.status_code >= 800:
                        error_msg = f"Server returned non-standard HTTP status {response.status_code} from URL: {account.server_url}. Server message: {response_content}"
                    elif response.status_code == 404:
                        error_msg = f"M3U file not found (404) at URL: {account.server_url}. Server message: {response_content}"
                    elif response.status_code == 403:
                        error_msg = f"Access forbidden (403) to M3U file at URL: {account.server_url}. Server message: {response_content}"
                    elif response.status_code == 401:
                        error_msg = f"Authentication required (401) for M3U file at URL: {account.server_url}. Server message: {response_content}"
                    elif response.status_code == 500:
                        error_msg = f"Server error (500) while fetching M3U file from URL: {account.server_url}. Server message: {response_content}"
                    else:
                        error_msg = f"HTTP error ({response.status_code}) while fetching M3U file from URL: {account.server_url}. Server message: {response_content}"

                    logger.error(error_msg)
                    account.status = M3UAccount.Status.ERROR
                    account.last_message = error_msg
                    account.save(update_fields=["status", "last_message"])
                    send_m3u_update(
                        account.id,
                        "downloading",
                        100,
                        status="error",
                        error=error_msg,
                    )
                    return [], False

                # Only call raise_for_status if we have a success code (this should not raise now)
                response.raise_for_status()

                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                start_time = time.time()
                last_update_time = start_time
                progress = 0
                temp_content = b""  # Store content temporarily to validate before saving
                has_content = False

                # First, let's collect the content and validate it
                send_m3u_update(account.id, "downloading", 0)
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_content += chunk
                        has_content = True

                        downloaded += len(chunk)
                        elapsed_time = time.time() - start_time

                        # Calculate download speed in KB/s
                        speed = downloaded / elapsed_time / 1024  # in KB/s

                        # Calculate progress percentage
                        if total_size and total_size > 0:
                            progress = (downloaded / total_size) * 100

                        # Time remaining (in seconds)
                        time_remaining = (
                            (total_size - downloaded) / (speed * 1024)
                            if speed > 0
                            else 0
                        )

                        current_time = time.time()
                        if current_time - last_update_time >= 0.5:
                            last_update_time = current_time
                            if progress > 0:
                                # Update the account's last_message with detailed progress info
                                progress_msg = f"Downloading: {progress:.1f}% - {speed:.1f} KB/s - {time_remaining:.1f}s remaining"
                                account.last_message = progress_msg
                                account.save(update_fields=["last_message"])

                                send_m3u_update(
                                    account.id,
                                    "downloading",
                                    progress,
                                    speed=speed,
                                    elapsed_time=elapsed_time,
                                    time_remaining=time_remaining,
                                    message=progress_msg,
                                )

                # Check if we actually received any content
                logger.info(f"Download completed. Has content: {has_content}, Content length: {len(temp_content)} bytes")
                if not has_content or len(temp_content) == 0:
                    error_msg = f"Server responded successfully (HTTP {response.status_code}) but provided empty M3U file from URL: {account.server_url}"
                    logger.error(error_msg)
                    account.status = M3UAccount.Status.ERROR
                    account.last_message = error_msg
                    account.save(update_fields=["status", "last_message"])
                    send_m3u_update(
                        account.id,
                        "downloading",
                        100,
                        status="error",
                        error=error_msg,
                    )
                    return [], False

                # Basic validation: check if content looks like an M3U file
                try:
                    content_str = temp_content.decode('utf-8', errors='ignore')
                    content_lines = content_str.strip().split('\n')

                    # Log first few lines for debugging (be careful not to log too much)
                    preview_lines = content_lines[:5]
                    logger.info(f"Content preview (first 5 lines): {preview_lines}")
                    logger.info(f"Total lines in content: {len(content_lines)}")

                    # Check if it's a valid M3U file (should start with #EXTM3U or contain M3U-like content)
                    is_valid_m3u = False

                    # First, check if this looks like an error response disguised as 200 OK
                    content_lower = content_str.lower()
                    if any(error_indicator in content_lower for error_indicator in [
                        '<html', '<!doctype html', 'error', 'not found', '404', '403', '500',
                        'access denied', 'unauthorized', 'forbidden', 'invalid', 'expired'
                    ]):
                        logger.warning(f"Content appears to be an error response disguised as HTTP 200: {content_str[:200]!r}")
                        # Continue with M3U validation, but this gives us a clue

                    if content_lines and content_lines[0].strip().upper().startswith('#EXTM3U'):
                        is_valid_m3u = True
                        logger.info("Content validated as M3U: starts with #EXTM3U")
                    elif any(line.strip().startswith('#EXTINF:') for line in content_lines):
                        is_valid_m3u = True
                        logger.info("Content validated as M3U: contains #EXTINF entries")
                    elif any(line.strip().startswith('http') for line in content_lines):
                        # Has HTTP URLs, might be a simple M3U without headers
                        is_valid_m3u = True
                        logger.info("Content validated as M3U: contains HTTP URLs")
                    elif any(line.strip().startswith(('rtsp', 'rtp', 'udp')) for line in content_lines):
                        # Has RTSP/RTP/UDP URLs, might be a simple M3U without headers
                        is_valid_m3u = True
                        logger.info("Content validated as M3U: contains RTSP/RTP/UDP URLs")

                    if not is_valid_m3u:
                        # Log what we actually received for debugging
                        logger.error(f"Invalid M3U content received. First 200 characters: {content_str[:200]!r}")

                        # Try to provide more specific error messages based on content
                        if '<html' in content_lower or '<!doctype html' in content_lower:
                            error_msg = f"Server returned HTML page instead of M3U file from URL: {account.server_url}. This usually indicates an error or authentication issue."
                        elif 'error' in content_lower or 'not found' in content_lower:
                            error_msg = f"Server returned an error message instead of M3U file from URL: {account.server_url}. Content: {content_str[:100]}"
                        elif len(content_str.strip()) == 0:
                            error_msg = f"Server returned completely empty response from URL: {account.server_url}"
                        else:
                            error_msg = f"Server provided invalid M3U content from URL: {account.server_url}. Content does not appear to be a valid M3U file."
                        logger.error(error_msg)
                        account.status = M3UAccount.Status.ERROR
                        account.last_message = error_msg
                        account.save(update_fields=["status", "last_message"])
                        send_m3u_update(
                            account.id,
                            "downloading",
                            100,
                            status="error",
                            error=error_msg,
                        )
                        return [], False

                except UnicodeDecodeError:
                    logger.error(f"Non-text content received. First 200 bytes: {temp_content[:200]!r}")
                    error_msg = f"Server provided non-text content from URL: {account.server_url}. Unable to process as M3U file."
                    logger.error(error_msg)
                    account.status = M3UAccount.Status.ERROR
                    account.last_message = error_msg
                    account.save(update_fields=["status", "last_message"])
                    send_m3u_update(
                        account.id,
                        "downloading",
                        100,
                        status="error",
                        error=error_msg,
                    )
                    return [], False

                # Content is valid, save it to file
                with open(file_path, "wb") as file:
                    file.write(temp_content)

                # Final update with 100% progress
                final_msg = f"Download complete. Size: {total_size/1024/1024:.2f} MB, Time: {time.time() - start_time:.1f}s"
                account.last_message = final_msg
                account.save(update_fields=["last_message"])
                send_m3u_update(account.id, "downloading", 100, message=final_msg)
            except requests.exceptions.HTTPError as e:
                # Handle HTTP errors specifically with more context
                status_code = e.response.status_code if e.response else "unknown"

                # Try to capture the error response content
                response_content = ""
                if e.response:
                    try:
                        response_content = e.response.text[:500]  # Limit to first 500 characters
                        logger.error(f"HTTP error response content: {response_content!r}")
                    except Exception as content_error:
                        logger.error(f"Could not read HTTP error response content: {content_error}")
                        response_content = "Could not read error response content"

                if status_code == 404:
                    error_msg = f"M3U file not found (404) at URL: {account.server_url}. Server message: {response_content}"
                elif status_code == 403:
                    error_msg = f"Access forbidden (403) to M3U file at URL: {account.server_url}. Server message: {response_content}"
                elif status_code == 401:
                    error_msg = f"Authentication required (401) for M3U file at URL: {account.server_url}. Server message: {response_content}"
                elif status_code == 500:
                    error_msg = f"Server error (500) while fetching M3U file from URL: {account.server_url}. Server message: {response_content}"
                else:
                    error_msg = f"HTTP error ({status_code}) while fetching M3U file from URL: {account.server_url}. Server message: {response_content}"

                logger.error(error_msg)
                account.status = M3UAccount.Status.ERROR
                account.last_message = error_msg
                account.save(update_fields=["status", "last_message"])
                send_m3u_update(
                    account.id,
                    "downloading",
                    100,
                    status="error",
                    error=error_msg,
                )
                return [], False
            except requests.exceptions.RequestException as e:
                # Handle other request errors (connection, timeout, etc.)
                if "timeout" in str(e).lower():
                    error_msg = f"Timeout while fetching M3U file from URL: {account.server_url}"
                elif "connection" in str(e).lower():
                    error_msg = f"Connection error while fetching M3U file from URL: {account.server_url}"
                else:
                    error_msg = f"Network error while fetching M3U file from URL: {account.server_url} - {str(e)}"

                logger.error(error_msg)
                account.status = M3UAccount.Status.ERROR
                account.last_message = error_msg
                account.save(update_fields=["status", "last_message"])
                send_m3u_update(
                    account.id,
                    "downloading",
                    100,
                    status="error",
                    error=error_msg,
                )
                return [], False
            except Exception as e:
                # Handle any other unexpected errors
                error_msg = f"Unexpected error while fetching M3U file from URL: {account.server_url} - {str(e)}"
                logger.error(error_msg)
                account.status = M3UAccount.Status.ERROR
                account.last_message = error_msg
                account.save(update_fields=["status", "last_message"])
                send_m3u_update(
                    account.id,
                    "downloading",
                    100,
                    status="error",
                    error=error_msg,
                )
                return [], False

        # Check if the file exists and is not empty (fallback check - should not happen with new validation)
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            error_msg = f"M3U file is unexpectedly missing or empty after validation: {file_path}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=["status", "last_message"])
            send_m3u_update(
                account.id, "downloading", 100, status="error", error=error_msg
            )
            return [], False  # Return empty list and False for success

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.readlines(), True
        except Exception as e:
            error_msg = f"Error reading M3U file: {str(e)}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=["status", "last_message"])
            send_m3u_update(
                account.id, "downloading", 100, status="error", error=error_msg
            )
            return [], False

    elif account.file_path:
        try:
            if account.file_path.endswith(".gz"):
                with gzip.open(account.file_path, "rt", encoding="utf-8") as f:
                    return f.readlines(), True

            elif account.file_path.endswith(".zip"):
                with zipfile.ZipFile(account.file_path, "r") as zip_file:
                    for name in zip_file.namelist():
                        if name.endswith(".m3u"):
                            with zip_file.open(name) as f:
                                return [
                                    line.decode("utf-8") for line in f.readlines()
                                ], True

                    error_msg = (
                        f"No .m3u file found in ZIP archive: {account.file_path}"
                    )
                    logger.warning(error_msg)
                    account.status = M3UAccount.Status.ERROR
                    account.last_message = error_msg
                    account.save(update_fields=["status", "last_message"])
                    send_m3u_update(
                        account.id, "downloading", 100, status="error", error=error_msg
                    )
                    return [], False

            else:
                with open(account.file_path, "r", encoding="utf-8") as f:
                    return f.readlines(), True

        except (IOError, OSError, zipfile.BadZipFile, gzip.BadGzipFile) as e:
            error_msg = f"Error opening file {account.file_path}: {e}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=["status", "last_message"])
            send_m3u_update(
                account.id, "downloading", 100, status="error", error=error_msg
            )
            return [], False

    # Neither server_url nor uploaded_file is available
    error_msg = "No M3U source available (missing URL and file)"
    logger.error(error_msg)
    account.status = M3UAccount.Status.ERROR
    account.last_message = error_msg
    account.save(update_fields=["status", "last_message"])
    send_m3u_update(account.id, "downloading", 100, status="error", error=error_msg)
    return [], False


def get_case_insensitive_attr(attributes, key, default=""):
    """Get attribute value using case-insensitive key lookup."""
    for attr_key, attr_value in attributes.items():
        if attr_key.lower() == key.lower():
            return attr_value
    return default


def parse_extinf_line(line: str) -> dict:
    """
    Parse an EXTINF line from an M3U file.
    This function removes the "#EXTINF:" prefix, then extracts all key="value" attributes,
    and treats everything after the last attribute as the display name.

    Returns a dictionary with:
      - 'attributes': a dict of attribute key/value pairs (e.g. tvg-id, tvg-logo, group-title)
      - 'display_name': the text after the attributes (the fallback display name)
      - 'name': the value from tvg-name (if present) or the display name otherwise.
    """
    if not line.startswith("#EXTINF:"):
        return None
    content = line[len("#EXTINF:") :].strip()

    # Single pass: extract all attributes AND track the last attribute position
    # This regex matches both key="value" and key='value' patterns
    attrs = {}
    last_attr_end = 0

    # Use a single regex that handles both quote types
    for match in re.finditer(r'([^\s]+)=(["\'])([^\2]*?)\2', content):
        key = match.group(1)
        value = match.group(3)
        attrs[key] = value
        last_attr_end = match.end()

    # Everything after the last attribute (skipping leading comma and whitespace) is the display name
    if last_attr_end > 0:
        remaining = content[last_attr_end:].strip()
        # Remove leading comma if present
        if remaining.startswith(','):
            remaining = remaining[1:].strip()
        display_name = remaining
    else:
        # No attributes found, try the old comma-split method as fallback
        parts = content.split(',', 1)
        if len(parts) == 2:
            display_name = parts[1].strip()
        else:
            display_name = content.strip()

    # Use tvg-name attribute if available; otherwise try tvc-guide-title, then fall back to display name.
    name = get_case_insensitive_attr(attrs, "tvg-name", None)
    if not name:
        name = get_case_insensitive_attr(attrs, "tvc-guide-title", None)
    if not name:
        name = display_name
    return {"attributes": attrs, "display_name": display_name, "name": name}


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
def process_groups(account, groups):
    existing_groups = {
        group.name: group
        for group in ChannelGroup.objects.filter(name__in=groups.keys())
    }
    logger.info(f"Currently {len(existing_groups)} existing groups")

    # Check if we should auto-enable new groups based on account settings
    account_custom_props = account.custom_properties or {}
    auto_enable_new_groups_live = account_custom_props.get("auto_enable_new_groups_live", True)

    # Separate existing groups from groups that need to be created
    existing_group_objs = []
    groups_to_create = []

    for group_name, custom_props in groups.items():
        if group_name in existing_groups:
            existing_group_objs.append(existing_groups[group_name])
        else:
            groups_to_create.append(ChannelGroup(name=group_name))

    # Create new groups and fetch them back with IDs
    newly_created_group_objs = []
    if groups_to_create:
        logger.info(f"Creating {len(groups_to_create)} new groups for account {account.id}")
        newly_created_group_objs = list(ChannelGroup.bulk_create_and_fetch(groups_to_create))
        logger.debug(f"Successfully created {len(newly_created_group_objs)} new groups")

    # Combine all groups
    all_group_objs = existing_group_objs + newly_created_group_objs

    # Get existing relationships for this account
    existing_relationships = {
        rel.channel_group.name: rel
        for rel in ChannelGroupM3UAccount.objects.filter(
            m3u_account=account,
            channel_group__name__in=groups.keys()
        ).select_related('channel_group')
    }

    # Get ALL existing relationships for this account to identify orphaned ones
    all_existing_relationships = {
        rel.channel_group.name: rel
        for rel in ChannelGroupM3UAccount.objects.filter(
            m3u_account=account
        ).select_related('channel_group')
    }

    relations_to_create = []
    relations_to_update = []
    relations_to_delete = []

    # Find orphaned relationships (groups that no longer exist in the source)
    current_group_names = set(groups.keys())
    for group_name, rel in all_existing_relationships.items():
        if group_name not in current_group_names:
            relations_to_delete.append(rel)
            logger.debug(f"Marking relationship for deletion: group '{group_name}' no longer exists in source for account {account.id}")

    for group in all_group_objs:
        custom_props = groups.get(group.name, {})

        if group.name in existing_relationships:
            # Update existing relationship if xc_id has changed (preserve other custom properties)
            existing_rel = existing_relationships[group.name]

            # Get existing custom properties (now JSONB, no need to parse)
            existing_custom_props = existing_rel.custom_properties or {}

            # Get the new xc_id from groups data
            new_xc_id = custom_props.get("xc_id")
            existing_xc_id = existing_custom_props.get("xc_id")

            # Only update if xc_id has changed
            if new_xc_id != existing_xc_id:
                # Merge new xc_id with existing custom properties to preserve user settings
                updated_custom_props = existing_custom_props.copy()
                if new_xc_id is not None:
                    updated_custom_props["xc_id"] = new_xc_id
                elif "xc_id" in updated_custom_props:
                    # Remove xc_id if it's no longer provided (e.g., converting from XC to standard)
                    del updated_custom_props["xc_id"]

                existing_rel.custom_properties = updated_custom_props
                relations_to_update.append(existing_rel)
                logger.debug(f"Updated xc_id for group '{group.name}' from '{existing_xc_id}' to '{new_xc_id}' - account {account.id}")
            else:
                logger.debug(f"xc_id unchanged for group '{group.name}' - account {account.id}")
        else:
            # Create new relationship - this group is new to this M3U account
            # Use the auto_enable setting to determine if it should start enabled
            if not auto_enable_new_groups_live:
                logger.info(f"Group '{group.name}' is new to account {account.id} - creating relationship but DISABLED (auto_enable_new_groups_live=False)")

            relations_to_create.append(
                ChannelGroupM3UAccount(
                    channel_group=group,
                    m3u_account=account,
                    custom_properties=custom_props,
                    enabled=auto_enable_new_groups_live,
                )
            )

    # Bulk create new relationships
    if relations_to_create:
        ChannelGroupM3UAccount.objects.bulk_create(relations_to_create, ignore_conflicts=True)
        logger.debug(f"Created {len(relations_to_create)} new group relationships for account {account.id}")

    # Bulk update existing relationships
    if relations_to_update:
        ChannelGroupM3UAccount.objects.bulk_update(relations_to_update, ['custom_properties'])
        logger.info(f"Updated {len(relations_to_update)} existing group relationships with new xc_id values for account {account.id}")

    # Delete orphaned relationships
    if relations_to_delete:
        ChannelGroupM3UAccount.objects.filter(
            id__in=[rel.id for rel in relations_to_delete]
        ).delete()
        logger.info(f"Deleted {len(relations_to_delete)} orphaned group relationships for account {account.id}: {[rel.channel_group.name for rel in relations_to_delete]}")

        # Check if any of the deleted relationships left groups with no remaining associations
        orphaned_group_ids = []
        for rel in relations_to_delete:
            group = rel.channel_group

            # Check if this group has any remaining M3U account relationships
            remaining_m3u_relationships = ChannelGroupM3UAccount.objects.filter(
                channel_group=group
            ).exists()

            # Check if this group has any direct channels (not through M3U accounts)
            has_direct_channels = group.related_channels().exists()

            # If no relationships and no direct channels, it's safe to delete
            if not remaining_m3u_relationships and not has_direct_channels:
                orphaned_group_ids.append(group.id)
                logger.debug(f"Group '{group.name}' has no remaining associations and will be deleted")

        # Delete truly orphaned groups
        if orphaned_group_ids:
            deleted_groups = list(ChannelGroup.objects.filter(id__in=orphaned_group_ids).values_list('name', flat=True))
            ChannelGroup.objects.filter(id__in=orphaned_group_ids).delete()
            logger.info(f"Deleted {len(orphaned_group_ids)} orphaned groups that had no remaining associations: {deleted_groups}")


def collect_xc_streams(account_id, enabled_groups):
    """Collect all XC streams in a single API call and filter by enabled groups."""
    account = M3UAccount.objects.get(id=account_id)
    all_streams = []

    # Create a mapping from category_id to group info for filtering
    enabled_category_ids = {}
    for group_name, props in enabled_groups.items():
        if "xc_id" in props:
            enabled_category_ids[str(props["xc_id"])] = {
                "name": group_name,
                "props": props
            }

    try:
        with XCClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent(),
        ) as xc_client:

            # Fetch ALL live streams in a single API call (much more efficient)
            logger.info("Fetching ALL live streams from XC provider...")
            all_xc_streams = xc_client.get_all_live_streams()  # Get all streams without category filter

            if not all_xc_streams:
                logger.warning("No live streams returned from XC provider")
                return []

            logger.info(f"Retrieved {len(all_xc_streams)} total live streams from provider")

            # Filter streams based on enabled categories
            filtered_count = 0
            for stream in all_xc_streams:
                # Get the category_id for this stream
                category_id = str(stream.get("category_id", ""))

                # Only include streams from enabled categories
                if category_id in enabled_category_ids:
                    group_info = enabled_category_ids[category_id]

                    # Convert XC stream to our standard format with all properties preserved
                    stream_data = {
                        "name": stream["name"],
                        "url": xc_client.get_stream_url(stream["stream_id"]),
                        "attributes": {
                            "tvg-id": stream.get("epg_channel_id", ""),
                            "tvg-logo": stream.get("stream_icon", ""),
                            "group-title": group_info["name"],
                            # Preserve all XC stream properties as custom attributes
                            "stream_id": str(stream.get("stream_id", "")),
                            "category_id": category_id,
                            "stream_type": stream.get("stream_type", ""),
                            "added": stream.get("added", ""),
                            "is_adult": str(stream.get("is_adult", "0")),
                            "custom_sid": stream.get("custom_sid", ""),
                            # Include any other properties that might be present
                            **{k: str(v) for k, v in stream.items() if k not in [
                                "name", "stream_id", "epg_channel_id", "stream_icon",
                                "category_id", "stream_type", "added", "is_adult", "custom_sid"
                            ] and v is not None}
                        }
                    }
                    all_streams.append(stream_data)
                    filtered_count += 1

    except Exception as e:
        logger.error(f"Failed to fetch XC streams: {str(e)}")
        return []

    logger.info(f"Filtered {filtered_count} streams from {len(enabled_category_ids)} enabled categories")
    return all_streams

def process_xc_category_direct(account_id, batch, groups, hash_keys):
    from django.db import connections

    # Ensure clean database connections for threading
    connections.close_all()

    account = M3UAccount.objects.get(id=account_id)

    streams_to_create = []
    streams_to_update = []
    stream_hashes = {}

    try:
        with XCClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent(),
        ) as xc_client:
            # Log the batch details to help with debugging
            logger.debug(f"Processing XC batch: {batch}")

            for group_name, props in batch.items():
                # Check if we have a valid xc_id for this group
                if "xc_id" not in props:
                    logger.error(
                        f"Missing xc_id for group {group_name} in batch {batch}"
                    )
                    continue

                # Get actual group ID from the mapping
                group_id = groups.get(group_name)
                if not group_id:
                    logger.error(f"Group {group_name} not found in enabled groups")
                    continue

                try:
                    logger.debug(
                        f"Fetching streams for XC category: {group_name} (ID: {props['xc_id']})"
                    )
                    streams = xc_client.get_live_category_streams(props["xc_id"])

                    if not streams:
                        logger.warning(
                            f"No streams found for XC category {group_name} (ID: {props['xc_id']})"
                        )
                        continue

                    logger.debug(
                        f"Found {len(streams)} streams for category {group_name}"
                    )

                    for stream in streams:
                        name = stream["name"]
                        url = xc_client.get_stream_url(stream["stream_id"])
                        tvg_id = stream.get("epg_channel_id", "")
                        tvg_logo = stream.get("stream_icon", "")
                        group_title = group_name

                        stream_hash = Stream.generate_hash_key(
                            name, url, tvg_id, hash_keys, m3u_id=account_id
                        )
                        stream_props = {
                            "name": name,
                            "url": url,
                            "logo_url": tvg_logo,
                            "tvg_id": tvg_id,
                            "m3u_account": account,
                            "channel_group_id": int(group_id),
                            "stream_hash": stream_hash,
                            "custom_properties": stream,
                        }

                        if stream_hash not in stream_hashes:
                            stream_hashes[stream_hash] = stream_props
                except Exception as e:
                    logger.error(
                        f"Error processing XC category {group_name} (ID: {props['xc_id']}): {str(e)}"
                    )
                    continue

        # Process all found streams
        existing_streams = {
            s.stream_hash: s
            for s in Stream.objects.filter(stream_hash__in=stream_hashes.keys()).select_related('m3u_account').only(
                'id', 'stream_hash', 'name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'last_seen', 'updated_at', 'm3u_account'
            )
        }

        for stream_hash, stream_props in stream_hashes.items():
            if stream_hash in existing_streams:
                obj = existing_streams[stream_hash]
                # Optimized field comparison for XC streams
                changed = (
                    obj.name != stream_props["name"] or
                    obj.url != stream_props["url"] or
                    obj.logo_url != stream_props["logo_url"] or
                    obj.tvg_id != stream_props["tvg_id"] or
                    obj.custom_properties != stream_props["custom_properties"]
                )

                if changed:
                    for key, value in stream_props.items():
                        setattr(obj, key, value)
                    obj.last_seen = timezone.now()
                    obj.updated_at = timezone.now()  # Update timestamp only for changed streams
                    streams_to_update.append(obj)
                else:
                    # Always update last_seen, even if nothing else changed
                    obj.last_seen = timezone.now()
                    # Don't update updated_at for unchanged streams
                    streams_to_update.append(obj)

                # Remove from existing_streams since we've processed it
                del existing_streams[stream_hash]
            else:
                stream_props["last_seen"] = timezone.now()
                stream_props["updated_at"] = (
                    timezone.now()
                )  # Set initial updated_at for new streams
                streams_to_create.append(Stream(**stream_props))

        try:
            with transaction.atomic():
                if streams_to_create:
                    Stream.objects.bulk_create(streams_to_create, ignore_conflicts=True)

                if streams_to_update:
                    # Simplified bulk update for better performance
                    Stream.objects.bulk_update(
                        streams_to_update,
                        ['name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'last_seen', 'updated_at'],
                        batch_size=150  # Smaller batch size for XC processing
                    )

                # Update last_seen for any remaining existing streams that weren't processed
                if len(existing_streams.keys()) > 0:
                    Stream.objects.bulk_update(existing_streams.values(), ["last_seen"])
        except Exception as e:
            logger.error(f"Bulk operation failed for XC streams: {str(e)}")

        retval = f"Batch processed: {len(streams_to_create)} created, {len(streams_to_update)} updated."

    except Exception as e:
        logger.error(f"XC category processing error: {str(e)}")
        retval = f"Error processing XC batch: {str(e)}"
    finally:
        # Clean up database connections for threading
        connections.close_all()

    # Aggressive garbage collection
    del streams_to_create, streams_to_update, stream_hashes, existing_streams
    gc.collect()

    return retval


def process_m3u_batch_direct(account_id, batch, groups, hash_keys):
    """Processes a batch of M3U streams using bulk operations with thread-safe DB connections."""
    from django.db import connections

    # Ensure clean database connections for threading
    connections.close_all()

    account = M3UAccount.objects.get(id=account_id)

    compiled_filters = [
        (
            re.compile(
                f.regex_pattern,
                (
                    re.IGNORECASE
                    if (f.custom_properties or {}).get(
                        "case_sensitive", True
                    )
                    == False
                    else 0
                ),
            ),
            f,
        )
        for f in account.filters.order_by("order")
    ]

    streams_to_create = []
    streams_to_update = []
    stream_hashes = {}

    logger.debug(f"Processing batch of {len(batch)} for M3U account {account_id}")
    if compiled_filters:
        logger.debug(f"Using compiled filters: {[f[1].regex_pattern for f in compiled_filters]}")
    for stream_info in batch:
        try:
            name, url = stream_info["name"], stream_info["url"]

            # Validate URL length - maximum of 4096 characters
            if url and len(url) > 4096:
                logger.warning(f"Skipping stream '{name}': URL too long ({len(url)} characters, max 4096)")
                continue

            tvg_id, tvg_logo = get_case_insensitive_attr(
                stream_info["attributes"], "tvg-id", ""
            ), get_case_insensitive_attr(stream_info["attributes"], "tvg-logo", "")
            group_title = get_case_insensitive_attr(
                stream_info["attributes"], "group-title", "Default Group"
            )
            logger.debug(f"Processing stream: {name} - {url} in group {group_title}")
            include = True
            for pattern, filter in compiled_filters:
                logger.trace(f"Checking filter pattern {pattern}")
                target = name
                if filter.filter_type == "url":
                    target = url
                elif filter.filter_type == "group":
                    target = group_title

                if pattern.search(target or ""):
                    logger.debug(
                        f"Stream {name} - {url} matches filter pattern {filter.regex_pattern}"
                    )
                    include = not filter.exclude
                    break

            if not include:
                logger.debug(f"Stream excluded by filter, skipping.")
                continue

            # Filter out disabled groups for this account
            if group_title not in groups:
                logger.debug(
                    f"Skipping stream in disabled or excluded group: {group_title}"
                )
                continue

            stream_hash = Stream.generate_hash_key(name, url, tvg_id, hash_keys, m3u_id=account_id)
            stream_props = {
                "name": name,
                "url": url,
                "logo_url": tvg_logo,
                "tvg_id": tvg_id,
                "m3u_account": account,
                "channel_group_id": int(groups.get(group_title)),
                "stream_hash": stream_hash,
                "custom_properties": stream_info["attributes"],
            }

            if stream_hash not in stream_hashes:
                stream_hashes[stream_hash] = stream_props
        except Exception as e:
            logger.error(f"Failed to process stream {name}: {e}")
            logger.error(json.dumps(stream_info))

    existing_streams = {
        s.stream_hash: s
        for s in Stream.objects.filter(stream_hash__in=stream_hashes.keys()).select_related('m3u_account').only(
            'id', 'stream_hash', 'name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'last_seen', 'updated_at', 'm3u_account'
        )
    }

    for stream_hash, stream_props in stream_hashes.items():
        if stream_hash in existing_streams:
            obj = existing_streams[stream_hash]
            # Optimized field comparison
            changed = (
                obj.name != stream_props["name"] or
                obj.url != stream_props["url"] or
                obj.logo_url != stream_props["logo_url"] or
                obj.tvg_id != stream_props["tvg_id"] or
                obj.custom_properties != stream_props["custom_properties"]
            )

            # Always update last_seen
            obj.last_seen = timezone.now()

            if changed:
                # Only update fields that changed and set updated_at
                obj.name = stream_props["name"]
                obj.url = stream_props["url"]
                obj.logo_url = stream_props["logo_url"]
                obj.tvg_id = stream_props["tvg_id"]
                obj.custom_properties = stream_props["custom_properties"]
                obj.updated_at = timezone.now()

            streams_to_update.append(obj)
        else:
            # New stream
            stream_props["last_seen"] = timezone.now()
            stream_props["updated_at"] = timezone.now()
            streams_to_create.append(Stream(**stream_props))

    try:
        with transaction.atomic():
            if streams_to_create:
                Stream.objects.bulk_create(streams_to_create, ignore_conflicts=True)

            if streams_to_update:
                # Update all streams in a single bulk operation
                Stream.objects.bulk_update(
                    streams_to_update,
                    ['name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'last_seen', 'updated_at'],
                    batch_size=200
                )
    except Exception as e:
        logger.error(f"Bulk operation failed: {str(e)}")

    retval = f"M3U account: {account_id}, Batch processed: {len(streams_to_create)} created, {len(streams_to_update)} updated."

    # Aggressive garbage collection
    # del streams_to_create, streams_to_update, stream_hashes, existing_streams
    # from core.utils import cleanup_memory
    # cleanup_memory(log_usage=True, force_collection=True)

    # Clean up database connections for threading
    connections.close_all()

    return retval


def cleanup_streams(account_id, scan_start_time=timezone.now):
    account = M3UAccount.objects.get(id=account_id, is_active=True)
    existing_groups = ChannelGroup.objects.filter(
        m3u_accounts__m3u_account=account,
        m3u_accounts__enabled=True,
    ).values_list("id", flat=True)
    logger.info(
        f"Found {len(existing_groups)} active groups for M3U account {account_id}"
    )

    # Calculate cutoff date for stale streams
    stale_cutoff = scan_start_time - timezone.timedelta(days=account.stale_stream_days)
    logger.info(
        f"Removing streams not seen since {stale_cutoff} for M3U account {account_id}"
    )

    # Delete streams that are not in active groups
    streams_to_delete = Stream.objects.filter(m3u_account=account).exclude(
        channel_group__in=existing_groups
    )

    # Also delete streams that haven't been seen for longer than stale_stream_days
    stale_streams = Stream.objects.filter(
        m3u_account=account, last_seen__lt=stale_cutoff
    )

    deleted_count = streams_to_delete.count()
    stale_count = stale_streams.count()

    streams_to_delete.delete()
    stale_streams.delete()

    total_deleted = deleted_count + stale_count
    logger.info(
        f"Cleanup for M3U account {account_id} complete: {deleted_count} streams removed due to group filter, {stale_count} removed as stale"
    )

    # Return the total count of deleted streams
    return total_deleted


@shared_task
def refresh_m3u_groups(account_id, use_cache=False, full_refresh=False):
    if not acquire_task_lock("refresh_m3u_account_groups", account_id):
        return f"Task already running for account_id={account_id}.", None

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
    except M3UAccount.DoesNotExist:
        release_task_lock("refresh_m3u_account_groups", account_id)
        return f"M3UAccount with ID={account_id} not found or inactive.", None

    extinf_data = []
    groups = {"Default Group": {}}

    if account.account_type == M3UAccount.Types.XC:
        # Log detailed information about the account
        logger.info(
            f"Processing XC account {account_id} with URL: {account.server_url}"
        )
        logger.debug(
            f"Username: {account.username}, Has password: {'Yes' if account.password else 'No'}"
        )

        # Validate required fields
        if not account.server_url:
            error_msg = "Missing server URL for Xtream Codes account"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=["status", "last_message"])
            send_m3u_update(
                account_id, "processing_groups", 100, status="error", error=error_msg
            )
            release_task_lock("refresh_m3u_account_groups", account_id)
            return error_msg, None

        if not account.username or not account.password:
            error_msg = "Missing username or password for Xtream Codes account"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=["status", "last_message"])
            send_m3u_update(
                account_id, "processing_groups", 100, status="error", error=error_msg
            )
            release_task_lock("refresh_m3u_account_groups", account_id)
            return error_msg, None

        try:
            # Ensure server URL is properly formatted
            server_url = account.server_url.rstrip("/")
            if not (
                server_url.startswith("http://") or server_url.startswith("https://")
            ):
                server_url = f"http://{server_url}"

            # User agent handling - completely rewritten
            try:
                # Debug the user agent issue
                logger.debug(f"Getting user agent for account {account.id}")

                # Use a hardcoded user agent string to avoid any issues with object structure
                user_agent_string = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )

                try:
                    # Try to get the user agent directly from the database
                    if account.user_agent_id:
                        ua_obj = UserAgent.objects.get(id=account.user_agent_id)
                        if (
                            ua_obj
                            and hasattr(ua_obj, "user_agent")
                            and ua_obj.user_agent
                        ):
                            user_agent_string = ua_obj.user_agent
                            logger.debug(
                                f"Using user agent from account: {user_agent_string}"
                            )
                    else:
                        # Get default user agent from CoreSettings
                        default_ua_id = CoreSettings.get_default_user_agent_id()
                        logger.debug(
                            f"Default user agent ID from settings: {default_ua_id}"
                        )
                        if default_ua_id:
                            ua_obj = UserAgent.objects.get(id=default_ua_id)
                            if (
                                ua_obj
                                and hasattr(ua_obj, "user_agent")
                                and ua_obj.user_agent
                            ):
                                user_agent_string = ua_obj.user_agent
                                logger.debug(
                                    f"Using default user agent: {user_agent_string}"
                                )
                except Exception as e:
                    logger.warning(
                        f"Error getting user agent, using fallback: {str(e)}"
                    )

                logger.debug(f"Final user agent string: {user_agent_string}")
            except Exception as e:
                user_agent_string = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                logger.warning(
                    f"Exception in user agent handling, using fallback: {str(e)}"
                )

            logger.info(
                f"Creating XCClient with URL: {account.server_url}, Username: {account.username}, User-Agent: {user_agent_string}"
            )

            # Create XCClient with explicit error handling
            try:
                with XCClient(
                    account.server_url, account.username, account.password, user_agent_string
                ) as xc_client:
                    logger.info(f"XCClient instance created successfully")

                    # Authenticate with detailed error handling
                    try:
                        logger.debug(f"Authenticating with XC server {server_url}")
                        auth_result = xc_client.authenticate()
                        logger.debug(f"Authentication response: {auth_result}")

                        # Queue async profile refresh task to run in background
                        # This prevents any delay in the main refresh process
                        try:
                            logger.info(f"Queueing background profile refresh for account {account.name}")
                            refresh_account_profiles.delay(account.id)
                        except Exception as e:
                            logger.warning(f"Failed to queue profile refresh task: {str(e)}")
                            # Don't fail the main refresh if profile refresh can't be queued

                    except Exception as e:
                        error_msg = f"Failed to authenticate with XC server: {str(e)}"
                        logger.error(error_msg)
                        account.status = M3UAccount.Status.ERROR
                        account.last_message = error_msg
                        account.save(update_fields=["status", "last_message"])
                        send_m3u_update(
                            account_id,
                            "processing_groups",
                            100,
                            status="error",
                            error=error_msg,
                        )
                        release_task_lock("refresh_m3u_account_groups", account_id)
                        return error_msg, None

                    # Get categories with detailed error handling
                    try:
                        logger.info(f"Getting live categories from XC server")
                        xc_categories = xc_client.get_live_categories()
                        logger.info(
                            f"Found {len(xc_categories)} categories: {xc_categories}"
                        )

                        # Validate response
                        if not isinstance(xc_categories, list):
                            error_msg = (
                                f"Unexpected response from XC server: {xc_categories}"
                            )
                            logger.error(error_msg)
                            account.status = M3UAccount.Status.ERROR
                            account.last_message = error_msg
                            account.save(update_fields=["status", "last_message"])
                            send_m3u_update(
                                account_id,
                                "processing_groups",
                                100,
                                status="error",
                                error=error_msg,
                            )
                            release_task_lock("refresh_m3u_account_groups", account_id)
                            return error_msg, None

                        if len(xc_categories) == 0:
                            logger.warning("No categories found in XC server response")

                        for category in xc_categories:
                            cat_name = category.get("category_name", "Unknown Category")
                            cat_id = category.get("category_id", "0")
                            logger.info(f"Adding category: {cat_name} (ID: {cat_id})")
                            groups[cat_name] = {
                                "xc_id": cat_id,
                            }
                    except Exception as e:
                        error_msg = f"Failed to get categories from XC server: {str(e)}"
                        logger.error(error_msg)
                        account.status = M3UAccount.Status.ERROR
                        account.last_message = error_msg
                        account.save(update_fields=["status", "last_message"])
                        send_m3u_update(
                            account_id,
                            "processing_groups",
                            100,
                            status="error",
                            error=error_msg,
                        )
                        release_task_lock("refresh_m3u_account_groups", account_id)
                        return error_msg, None

            except Exception as e:
                error_msg = f"Failed to create XC Client: {str(e)}"
                logger.error(error_msg)
                account.status = M3UAccount.Status.ERROR
                account.last_message = error_msg
                account.save(update_fields=["status", "last_message"])
                send_m3u_update(
                    account_id,
                    "processing_groups",
                    100,
                    status="error",
                    error=error_msg,
                )
                release_task_lock("refresh_m3u_account_groups", account_id)
                return error_msg, None
        except Exception as e:
            error_msg = f"Unexpected error occurred in XC Client: {str(e)}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=["status", "last_message"])
            send_m3u_update(
                account_id, "processing_groups", 100, status="error", error=error_msg
            )
            release_task_lock("refresh_m3u_account_groups", account_id)
            return error_msg, None
    else:
        # Here's the key change - use the success flag from fetch_m3u_lines
        lines, success = fetch_m3u_lines(account, use_cache)
        if not success:
            # If fetch failed, don't continue processing
            release_task_lock("refresh_m3u_account_groups", account_id)
            return f"Failed to fetch M3U data for account_id={account_id}.", None

        # Log basic file structure for debugging
        logger.debug(f"Processing {len(lines)} lines from M3U file")

        line_count = 0
        extinf_count = 0
        url_count = 0
        valid_stream_count = 0
        problematic_lines = []

        for line_index, line in enumerate(lines):
            line_count += 1
            line = line.strip()

            if line.startswith("#EXTINF"):
                extinf_count += 1
                parsed = parse_extinf_line(line)
                if parsed:
                    group_title_attr = get_case_insensitive_attr(
                        parsed["attributes"], "group-title", ""
                    )
                    if group_title_attr:
                        group_name = group_title_attr
                        # Log new groups as they're discovered
                        if group_name not in groups:
                            logger.debug(
                                f"Found new group for M3U account {account_id}: '{group_name}'"
                            )
                        groups[group_name] = {}

                    extinf_data.append(parsed)
                else:
                    # Log problematic EXTINF lines
                    logger.warning(
                        f"Failed to parse EXTINF at line {line_index+1}: {line[:200]}"
                    )
                    problematic_lines.append((line_index + 1, line[:200]))

            elif extinf_data and (line.startswith("http") or line.startswith("rtsp") or line.startswith("rtp") or line.startswith("udp")):
                url_count += 1
                # Normalize UDP URLs only (e.g., remove VLC-specific @ prefix)
                normalized_url = normalize_stream_url(line) if line.startswith("udp") else line
                # Associate URL with the last EXTINF line
                extinf_data[-1]["url"] = normalized_url
                valid_stream_count += 1

                # Periodically log progress for large files
                if valid_stream_count % 1000 == 0:
                    logger.debug(
                        f"Processed {valid_stream_count} valid streams so far for M3U account: {account_id}"
                    )

        # Log summary statistics
        logger.info(
            f"M3U parsing complete - Lines: {line_count}, EXTINF: {extinf_count}, URLs: {url_count}, Valid streams: {valid_stream_count}"
        )

        if problematic_lines:
            logger.warning(
                f"Found {len(problematic_lines)} problematic lines during parsing"
            )
            for i, (line_num, content) in enumerate(
                problematic_lines[:10]
            ):  # Log max 10 examples
                logger.warning(f"Problematic line #{i+1} at line {line_num}: {content}")
            if len(problematic_lines) > 10:
                logger.warning(
                    f"... and {len(problematic_lines) - 10} more problematic lines"
                )

        # Log group statistics
        logger.info(
            f"Found {len(groups)} groups in M3U file: {', '.join(list(groups.keys())[:20])}"
            + ("..." if len(groups) > 20 else "")
        )

        # Cache processed data
        cache_path = os.path.join(m3u_dir, f"{account_id}.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "extinf_data": extinf_data,
                    "groups": groups,
                },
                f,
            )
            logger.debug(f"Cached parsed M3U data to {cache_path}")

    send_m3u_update(account_id, "processing_groups", 0)

    process_groups(account, groups)

    release_task_lock("refresh_m3u_account_groups", account_id)

    if not full_refresh:
        # Use update() instead of save() to avoid triggering signals
        M3UAccount.objects.filter(id=account_id).update(
            status=M3UAccount.Status.PENDING_SETUP,
            last_message="M3U groups loaded. Please select groups or refresh M3U to complete setup.",
        )
        send_m3u_update(
            account_id,
            "processing_groups",
            100,
            status="pending_setup",
            message="M3U groups loaded. Please select groups or refresh M3U to complete setup.",
        )

    return extinf_data, groups


def delete_m3u_refresh_task_by_id(account_id):
    """
    Delete the periodic task associated with an M3U account ID.
    Can be called directly or from the post_delete signal.
    Returns True if a task was found and deleted, False otherwise.
    """
    try:
        task = None
        task_name = f"m3u_account-refresh-{account_id}"

        # Look for task by name
        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule

            task = PeriodicTask.objects.get(name=task_name)
            logger.debug(f"Found task by name: {task.id} for M3UAccount {account_id}")
        except PeriodicTask.DoesNotExist:
            logger.warning(f"No PeriodicTask found with name {task_name}")
            return False

        # Now delete the task and its interval
        if task:
            # Store interval info before deleting the task
            interval_id = None
            if hasattr(task, "interval") and task.interval:
                interval_id = task.interval.id

                # Count how many TOTAL tasks use this interval (including this one)
                tasks_with_same_interval = PeriodicTask.objects.filter(
                    interval_id=interval_id
                ).count()
                logger.debug(
                    f"Interval {interval_id} is used by {tasks_with_same_interval} tasks total"
                )

            # Delete the task first
            task_id = task.id
            task.delete()
            logger.debug(f"Successfully deleted periodic task {task_id}")

            # Now check if we should delete the interval
            # We only delete if it was the ONLY task using this interval
            if interval_id and tasks_with_same_interval == 1:
                try:
                    interval = IntervalSchedule.objects.get(id=interval_id)
                    logger.debug(
                        f"Deleting interval schedule {interval_id} (not shared with other tasks)"
                    )
                    interval.delete()
                    logger.debug(f"Successfully deleted interval {interval_id}")
                except IntervalSchedule.DoesNotExist:
                    logger.warning(f"Interval {interval_id} no longer exists")
            elif interval_id:
                logger.debug(
                    f"Not deleting interval {interval_id} as it's shared with {tasks_with_same_interval-1} other tasks"
                )

            return True
        return False
    except Exception as e:
        logger.error(
            f"Error deleting periodic task for M3UAccount {account_id}: {str(e)}",
            exc_info=True,
        )
        return False


@shared_task
def sync_auto_channels(account_id, scan_start_time=None):
    """
    Automatically create/update/delete channels to match streams in groups with auto_channel_sync enabled.
    Preserves existing channel UUIDs to maintain M3U link integrity.
    Called after M3U refresh completes successfully.
    """
    from apps.channels.models import (
        Channel,
        ChannelGroup,
        ChannelGroupM3UAccount,
        Stream,
        ChannelStream,
    )
    from apps.epg.models import EPGData
    from django.utils import timezone

    try:
        account = M3UAccount.objects.get(id=account_id)
        logger.info(f"Starting auto channel sync for M3U account {account.name}")

        # Always use scan_start_time as the cutoff for last_seen
        if scan_start_time is not None:
            if isinstance(scan_start_time, str):
                scan_start_time = timezone.datetime.fromisoformat(scan_start_time)
        else:
            scan_start_time = timezone.now()

        # Get groups with auto sync enabled for this account
        auto_sync_groups = ChannelGroupM3UAccount.objects.filter(
            m3u_account=account, enabled=True, auto_channel_sync=True
        ).select_related("channel_group")

        channels_created = 0
        channels_updated = 0
        channels_deleted = 0

        for group_relation in auto_sync_groups:
            channel_group = group_relation.channel_group
            start_number = group_relation.auto_sync_channel_start or 1.0

            # Get force_dummy_epg, group_override, and regex patterns from group custom_properties
            group_custom_props = {}
            force_dummy_epg = False  # Backward compatibility: legacy option to disable EPG
            override_group_id = None
            name_regex_pattern = None
            name_replace_pattern = None
            name_match_regex = None
            channel_profile_ids = None
            channel_sort_order = None
            channel_sort_reverse = False
            stream_profile_id = None
            custom_logo_id = None
            custom_epg_id = None  # New option: select specific EPG source (takes priority over force_dummy_epg)
            if group_relation.custom_properties:
                group_custom_props = group_relation.custom_properties
                force_dummy_epg = group_custom_props.get("force_dummy_epg", False)
                override_group_id = group_custom_props.get("group_override")
                name_regex_pattern = group_custom_props.get("name_regex_pattern")
                name_replace_pattern = group_custom_props.get(
                    "name_replace_pattern"
                )
                name_match_regex = group_custom_props.get("name_match_regex")
                channel_profile_ids = group_custom_props.get("channel_profile_ids")
                custom_epg_id = group_custom_props.get("custom_epg_id")
                channel_sort_order = group_custom_props.get("channel_sort_order")
                channel_sort_reverse = group_custom_props.get(
                    "channel_sort_reverse", False
                )
                stream_profile_id = group_custom_props.get("stream_profile_id")
                custom_logo_id = group_custom_props.get("custom_logo_id")

            # Determine which group to use for created channels
            target_group = channel_group
            if override_group_id:
                try:
                    target_group = ChannelGroup.objects.get(id=override_group_id)
                    logger.info(
                        f"Using override group '{target_group.name}' instead of '{channel_group.name}' for auto-created channels"
                    )
                except ChannelGroup.DoesNotExist:
                    logger.warning(
                        f"Override group with ID {override_group_id} not found, using original group '{channel_group.name}'"
                    )

            logger.info(
                f"Processing auto sync for group: {channel_group.name} (start: {start_number})"
            )

            # Get all current streams in this group for this M3U account, filter out stale streams
            current_streams = Stream.objects.filter(
                m3u_account=account,
                channel_group=channel_group,
                last_seen__gte=scan_start_time,
            )

            # --- FILTER STREAMS BY NAME MATCH REGEX IF SPECIFIED ---
            if name_match_regex:
                try:
                    current_streams = current_streams.filter(
                        name__iregex=name_match_regex
                    )
                except re.error as e:
                    logger.warning(
                        f"Invalid name_match_regex '{name_match_regex}' for group '{channel_group.name}': {e}. Skipping name filter."
                    )

            # --- APPLY CHANNEL SORT ORDER ---
            streams_is_list = False  # Track if we converted to list
            if channel_sort_order and channel_sort_order != "":
                if channel_sort_order == "name":
                    # Use natural sorting for names to handle numbers correctly
                    current_streams = list(current_streams)
                    current_streams.sort(
                        key=lambda stream: natural_sort_key(stream.name),
                        reverse=channel_sort_reverse,
                    )
                    streams_is_list = True
                elif channel_sort_order == "tvg_id":
                    order_prefix = "-" if channel_sort_reverse else ""
                    current_streams = current_streams.order_by(f"{order_prefix}tvg_id")
                elif channel_sort_order == "updated_at":
                    order_prefix = "-" if channel_sort_reverse else ""
                    current_streams = current_streams.order_by(
                        f"{order_prefix}updated_at"
                    )
                else:
                    logger.warning(
                        f"Unknown channel_sort_order '{channel_sort_order}' for group '{channel_group.name}'. Using provider order."
                    )
                    order_prefix = "-" if channel_sort_reverse else ""
                    current_streams = current_streams.order_by(f"{order_prefix}id")
            else:
                # Provider order (default) - can still be reversed
                order_prefix = "-" if channel_sort_reverse else ""
                current_streams = current_streams.order_by(f"{order_prefix}id")

            # Get existing auto-created channels for this account (regardless of current group)
            # We'll find them by their stream associations instead of just group location
            existing_channels = Channel.objects.filter(
                auto_created=True, auto_created_by=account
            ).select_related("logo", "epg_data")

            # Create mapping of existing channels by their associated stream
            # This approach finds channels even if they've been moved to different groups
            existing_channel_map = {}
            for channel in existing_channels:
                # Get streams associated with this channel that belong to our M3U account and original group
                channel_streams = ChannelStream.objects.filter(
                    channel=channel,
                    stream__m3u_account=account,
                    stream__channel_group=channel_group,  # Match streams from the original group
                ).select_related("stream")

                # Map each of our M3U account's streams to this channel
                for channel_stream in channel_streams:
                    if channel_stream.stream:
                        existing_channel_map[channel_stream.stream.id] = channel

            # Track which streams we've processed
            processed_stream_ids = set()

            # Check if we have streams - handle both QuerySet and list cases
            has_streams = (
                len(current_streams) > 0
                if streams_is_list
                else current_streams.exists()
            )

            if not has_streams:
                logger.debug(f"No streams found in group {channel_group.name}")
                # Delete all existing auto channels if no streams
                channels_to_delete = [ch for ch in existing_channel_map.values()]
                if channels_to_delete:
                    deleted_count = len(channels_to_delete)
                    Channel.objects.filter(
                        id__in=[ch.id for ch in channels_to_delete]
                    ).delete()
                    channels_deleted += deleted_count
                    logger.debug(
                        f"Deleted {deleted_count} auto channels (no streams remaining)"
                    )
                continue

            # Prepare profiles to assign to new channels
            from apps.channels.models import ChannelProfile, ChannelProfileMembership

            if (
                channel_profile_ids
                and isinstance(channel_profile_ids, list)
                and len(channel_profile_ids) > 0
            ):
                # Convert all to int (in case they're strings)
                try:
                    profile_ids = [int(pid) for pid in channel_profile_ids]
                except Exception:
                    profile_ids = []
                profiles_to_assign = list(
                    ChannelProfile.objects.filter(id__in=profile_ids)
                )
            else:
                profiles_to_assign = list(ChannelProfile.objects.all())

            # Get stream profile to assign if specified
            from core.models import StreamProfile
            stream_profile_to_assign = None
            if stream_profile_id:
                try:
                    stream_profile_to_assign = StreamProfile.objects.get(id=int(stream_profile_id))
                    logger.info(
                        f"Will assign stream profile '{stream_profile_to_assign.name}' to auto-synced streams in group '{channel_group.name}'"
                    )
                except (StreamProfile.DoesNotExist, ValueError, TypeError):
                    logger.warning(
                        f"Stream profile with ID {stream_profile_id} not found for group '{channel_group.name}', streams will use default profile"
                    )
                    stream_profile_to_assign = None

            # Process each current stream
            current_channel_number = start_number

            # Always renumber all existing channels to match current sort order
            # This ensures channels are always in the correct sequence
            channels_to_renumber = []
            temp_channel_number = start_number

            # Get all channel numbers that are already in use by other channels (not auto-created by this account)
            used_numbers = set(
                Channel.objects.exclude(
                    auto_created=True, auto_created_by=account
                ).values_list("channel_number", flat=True)
            )

            for stream in current_streams:
                if stream.id in existing_channel_map:
                    channel = existing_channel_map[stream.id]

                    # Find next available number starting from temp_channel_number
                    target_number = temp_channel_number
                    while target_number in used_numbers:
                        target_number += 1

                    # Add this number to used_numbers so we don't reuse it in this batch
                    used_numbers.add(target_number)

                    if channel.channel_number != target_number:
                        channel.channel_number = target_number
                        channels_to_renumber.append(channel)
                        logger.debug(
                            f"Will renumber channel '{channel.name}' to {target_number}"
                        )

                    temp_channel_number += 1.0
                    if temp_channel_number % 1 != 0:  # Has decimal
                        temp_channel_number = int(temp_channel_number) + 1.0

            # Bulk update channel numbers if any need renumbering
            if channels_to_renumber:
                Channel.objects.bulk_update(channels_to_renumber, ["channel_number"])
                logger.info(
                    f"Renumbered {len(channels_to_renumber)} channels to maintain sort order"
                )

            # Reset channel number counter for processing new channels
            current_channel_number = start_number

            for stream in current_streams:
                processed_stream_ids.add(stream.id)
                try:
                    # Parse custom properties for additional info
                    stream_custom_props = stream.custom_properties or {}
                    tvc_guide_stationid = stream_custom_props.get("tvc-guide-stationid")

                    # --- REGEX FIND/REPLACE LOGIC ---
                    original_name = stream.name
                    new_name = original_name
                    if name_regex_pattern is not None:
                        # If replace is None, treat as empty string (remove match)
                        replace = (
                            name_replace_pattern
                            if name_replace_pattern is not None
                            else ""
                        )
                        try:
                            # Convert $1, $2, etc. to \1, \2, etc. for consistency with M3U profiles
                            safe_replace_pattern = re.sub(r'\$(\d+)', r'\\\1', replace)
                            new_name = re.sub(
                                name_regex_pattern, safe_replace_pattern, original_name
                            )
                        except re.error as e:
                            logger.warning(
                                f"Regex error for group '{channel_group.name}': {e}. Using original name."
                            )
                            new_name = original_name

                    # Check if we already have a channel for this stream
                    existing_channel = existing_channel_map.get(stream.id)

                    if existing_channel:
                        # Update existing channel if needed (channel number already handled above)
                        channel_updated = False

                        # Use new_name instead of stream.name
                        if existing_channel.name != new_name:
                            existing_channel.name = new_name
                            channel_updated = True

                        if existing_channel.tvg_id != stream.tvg_id:
                            existing_channel.tvg_id = stream.tvg_id
                            channel_updated = True

                        if existing_channel.tvc_guide_stationid != tvc_guide_stationid:
                            existing_channel.tvc_guide_stationid = tvc_guide_stationid
                            channel_updated = True

                        # Check if channel group needs to be updated (in case override was added/changed)
                        if existing_channel.channel_group != target_group:
                            existing_channel.channel_group = target_group
                            channel_updated = True
                            logger.info(
                                f"Moved auto channel '{existing_channel.name}' from '{existing_channel.channel_group.name if existing_channel.channel_group else 'None'}' to '{target_group.name}'"
                            )

                        # Handle logo updates
                        current_logo = None
                        if custom_logo_id:
                            # Use the custom logo specified in group settings
                            from apps.channels.models import Logo
                            try:
                                current_logo = Logo.objects.get(id=custom_logo_id)
                            except Logo.DoesNotExist:
                                logger.warning(
                                    f"Custom logo with ID {custom_logo_id} not found for existing channel, falling back to stream logo"
                                )
                                # Fall back to stream logo if custom logo not found
                                if stream.logo_url:
                                    current_logo, _ = Logo.objects.get_or_create(
                                        url=stream.logo_url,
                                        defaults={
                                            "name": stream.name or stream.tvg_id or "Unknown"
                                        },
                                    )
                        elif stream.logo_url:
                            # No custom logo configured, use stream logo
                            from apps.channels.models import Logo

                            current_logo, _ = Logo.objects.get_or_create(
                                url=stream.logo_url,
                                defaults={
                                    "name": stream.name or stream.tvg_id or "Unknown"
                                },
                            )

                        if existing_channel.logo != current_logo:
                            existing_channel.logo = current_logo
                            channel_updated = True

                        # Handle EPG data updates
                        current_epg_data = None
                        if custom_epg_id:
                            # Use the custom EPG specified in group settings (e.g., a dummy EPG)
                            from apps.epg.models import EPGSource
                            try:
                                epg_source = EPGSource.objects.get(id=custom_epg_id)
                                # For dummy EPGs, select the first (and typically only) EPGData entry from this source
                                if epg_source.source_type == 'dummy':
                                    current_epg_data = EPGData.objects.filter(
                                        epg_source=epg_source
                                    ).first()
                                    if not current_epg_data:
                                        logger.warning(
                                            f"No EPGData found for dummy EPG source {epg_source.name} (ID: {custom_epg_id})"
                                        )
                                else:
                                    # For non-dummy sources, try to find existing EPGData by tvg_id
                                    if stream.tvg_id:
                                        current_epg_data = EPGData.objects.filter(
                                            tvg_id=stream.tvg_id,
                                            epg_source=epg_source
                                        ).first()
                            except EPGSource.DoesNotExist:
                                logger.warning(
                                    f"Custom EPG source with ID {custom_epg_id} not found for existing channel, falling back to auto-match"
                                )
                                # Fall back to auto-match by tvg_id
                                if stream.tvg_id and not force_dummy_epg:
                                    current_epg_data = EPGData.objects.filter(
                                        tvg_id=stream.tvg_id
                                    ).first()
                        elif stream.tvg_id and not force_dummy_epg:
                            # Auto-match EPG by tvg_id (original behavior)
                            current_epg_data = EPGData.objects.filter(
                                tvg_id=stream.tvg_id
                            ).first()
                        # If force_dummy_epg is True and no custom_epg_id, current_epg_data stays None

                        if existing_channel.epg_data != current_epg_data:
                            existing_channel.epg_data = current_epg_data
                            channel_updated = True

                        # Handle stream profile updates for the channel
                        if stream_profile_to_assign and existing_channel.stream_profile != stream_profile_to_assign:
                            existing_channel.stream_profile = stream_profile_to_assign
                            channel_updated = True

                        if channel_updated:
                            existing_channel.save()
                            channels_updated += 1
                            logger.debug(
                                f"Updated auto channel: {existing_channel.channel_number} - {existing_channel.name}"
                            )

                        # Update channel profile memberships for existing channels
                        current_memberships = set(
                            ChannelProfileMembership.objects.filter(
                                channel=existing_channel, enabled=True
                            ).values_list("channel_profile_id", flat=True)
                        )

                        target_profile_ids = set(
                            profile.id for profile in profiles_to_assign
                        )

                        # Only update if memberships have changed
                        if current_memberships != target_profile_ids:
                            # Disable all current memberships
                            ChannelProfileMembership.objects.filter(
                                channel=existing_channel
                            ).update(enabled=False)

                            # Enable/create memberships for target profiles
                            for profile in profiles_to_assign:
                                membership, created = (
                                    ChannelProfileMembership.objects.get_or_create(
                                        channel_profile=profile,
                                        channel=existing_channel,
                                        defaults={"enabled": True},
                                    )
                                )
                                if not created and not membership.enabled:
                                    membership.enabled = True
                                    membership.save()

                            logger.debug(
                                f"Updated profile memberships for auto channel: {existing_channel.name}"
                            )

                    else:
                        # Create new channel
                        # Find next available channel number
                        target_number = current_channel_number
                        while target_number in used_numbers:
                            target_number += 1

                        # Add this number to used_numbers
                        used_numbers.add(target_number)

                        channel = Channel.objects.create(
                            channel_number=target_number,
                            name=new_name,
                            tvg_id=stream.tvg_id,
                            tvc_guide_stationid=tvc_guide_stationid,
                            channel_group=target_group,
                            user_level=0,
                            auto_created=True,
                            auto_created_by=account,
                        )

                        # Associate the stream with the channel
                        ChannelStream.objects.create(
                            channel=channel, stream=stream, order=0
                        )

                        # Assign to correct profiles
                        memberships = [
                            ChannelProfileMembership(
                                channel_profile=profile, channel=channel, enabled=True
                            )
                            for profile in profiles_to_assign
                        ]
                        if memberships:
                            ChannelProfileMembership.objects.bulk_create(memberships)

                        # Try to match EPG data
                        if custom_epg_id:
                            # Use the custom EPG specified in group settings (e.g., a dummy EPG)
                            from apps.epg.models import EPGSource
                            try:
                                epg_source = EPGSource.objects.get(id=custom_epg_id)
                                # For dummy EPGs, select the first (and typically only) EPGData entry from this source
                                if epg_source.source_type == 'dummy':
                                    epg_data = EPGData.objects.filter(
                                        epg_source=epg_source
                                    ).first()
                                    if epg_data:
                                        channel.epg_data = epg_data
                                        channel.save(update_fields=["epg_data"])
                                    else:
                                        logger.warning(
                                            f"No EPGData found for dummy EPG source {epg_source.name} (ID: {custom_epg_id})"
                                        )
                                else:
                                    # For non-dummy sources, try to find existing EPGData by tvg_id
                                    if stream.tvg_id:
                                        epg_data = EPGData.objects.filter(
                                            tvg_id=stream.tvg_id,
                                            epg_source=epg_source
                                        ).first()
                                        if epg_data:
                                            channel.epg_data = epg_data
                                            channel.save(update_fields=["epg_data"])
                            except EPGSource.DoesNotExist:
                                logger.warning(
                                    f"Custom EPG source with ID {custom_epg_id} not found, falling back to auto-match"
                                )
                                # Fall back to auto-match by tvg_id
                                if stream.tvg_id and not force_dummy_epg:
                                    epg_data = EPGData.objects.filter(
                                        tvg_id=stream.tvg_id
                                    ).first()
                                    if epg_data:
                                        channel.epg_data = epg_data
                                        channel.save(update_fields=["epg_data"])
                        elif stream.tvg_id and not force_dummy_epg:
                            # Auto-match EPG by tvg_id (original behavior)
                            epg_data = EPGData.objects.filter(
                                tvg_id=stream.tvg_id
                            ).first()
                            if epg_data:
                                channel.epg_data = epg_data
                                channel.save(update_fields=["epg_data"])
                        elif force_dummy_epg:
                            # Force dummy EPG with no custom EPG selected (set to None)
                            channel.epg_data = None
                            channel.save(update_fields=["epg_data"])

                        # Handle logo
                        if custom_logo_id:
                            # Use the custom logo specified in group settings
                            from apps.channels.models import Logo
                            try:
                                custom_logo = Logo.objects.get(id=custom_logo_id)
                                channel.logo = custom_logo
                                channel.save(update_fields=["logo"])
                            except Logo.DoesNotExist:
                                logger.warning(
                                    f"Custom logo with ID {custom_logo_id} not found, falling back to stream logo"
                                )
                                # Fall back to stream logo if custom logo not found
                                if stream.logo_url:
                                    logo, _ = Logo.objects.get_or_create(
                                        url=stream.logo_url,
                                        defaults={
                                            "name": stream.name or stream.tvg_id or "Unknown"
                                        },
                                    )
                                    channel.logo = logo
                                    channel.save(update_fields=["logo"])
                        elif stream.logo_url:
                            from apps.channels.models import Logo

                            logo, _ = Logo.objects.get_or_create(
                                url=stream.logo_url,
                                defaults={
                                    "name": stream.name or stream.tvg_id or "Unknown"
                                },
                            )
                            channel.logo = logo
                            channel.save(update_fields=["logo"])

                        # Handle stream profile assignment
                        if stream_profile_to_assign:
                            channel.stream_profile = stream_profile_to_assign
                            channel.save(update_fields=['stream_profile'])
                        channels_created += 1
                        logger.debug(
                            f"Created auto channel: {channel.channel_number} - {channel.name}"
                        )

                    # Increment channel number for next iteration
                    current_channel_number += 1.0
                    if current_channel_number % 1 != 0:  # Has decimal
                        current_channel_number = int(current_channel_number) + 1.0

                except Exception as e:
                    logger.error(
                        f"Error processing auto channel for stream {stream.name}: {str(e)}"
                    )
                    continue

            # Delete channels for streams that no longer exist
            channels_to_delete = []
            for stream_id, channel in existing_channel_map.items():
                if stream_id not in processed_stream_ids:
                    channels_to_delete.append(channel)

            if channels_to_delete:
                deleted_count = len(channels_to_delete)
                Channel.objects.filter(
                    id__in=[ch.id for ch in channels_to_delete]
                ).delete()
                channels_deleted += deleted_count
                logger.debug(
                    f"Deleted {deleted_count} auto channels for removed streams"
                )

        # Additional cleanup: Remove auto-created channels that no longer have any valid streams
        # This handles the case where streams were deleted due to stale retention policy
        orphaned_channels = Channel.objects.filter(
            auto_created=True,
            auto_created_by=account
        ).exclude(
            # Exclude channels that still have valid stream associations
            id__in=ChannelStream.objects.filter(
                stream__m3u_account=account,
                stream__isnull=False
            ).values_list('channel_id', flat=True)
        )

        orphaned_count = orphaned_channels.count()
        if orphaned_count > 0:
            orphaned_channels.delete()
            channels_deleted += orphaned_count
            logger.info(
                f"Deleted {orphaned_count} orphaned auto channels with no valid streams"
            )

        logger.info(
            f"Auto channel sync complete for account {account.name}: {channels_created} created, {channels_updated} updated, {channels_deleted} deleted"
        )
        return f"Auto sync: {channels_created} channels created, {channels_updated} updated, {channels_deleted} deleted"

    except Exception as e:
        logger.error(f"Error in auto channel sync for account {account_id}: {str(e)}")
        return f"Auto sync error: {str(e)}"


def get_transformed_credentials(account, profile=None):
    """
    Get transformed credentials for XtreamCodes API calls.

    Args:
        account: M3UAccount instance
        profile: M3UAccountProfile instance (optional, if not provided will use primary profile)

    Returns:
        tuple: (transformed_url, transformed_username, transformed_password)
    """
    import re
    import urllib.parse

    # If no profile is provided, find the primary active profile
    if profile is None:
        try:
            from apps.m3u.models import M3UAccountProfile
            profile = M3UAccountProfile.objects.filter(
                m3u_account=account,
                is_active=True
            ).first()
            if profile:
                logger.debug(f"Using primary profile '{profile.name}' for URL transformation")
            else:
                logger.debug(f"No active profiles found for account {account.name}, using base credentials")
        except Exception as e:
            logger.warning(f"Could not get primary profile for account {account.name}: {e}")
            profile = None

    base_url = account.server_url
    base_username = account.username
    base_password = account.password    # Build a complete URL with credentials (similar to how IPTV URLs are structured)
    # Format: http://server.com:port/live/username/password/1234.ts
    if base_url and base_username and base_password:
        # Remove trailing slash from server URL if present
        clean_server_url = base_url.rstrip('/')

        # Build the complete URL with embedded credentials
        complete_url = f"{clean_server_url}/live/{base_username}/{base_password}/1234.ts"
        logger.debug(f"Built complete URL: {complete_url}")

        # Apply profile-specific transformations if profile is provided
        if profile and profile.search_pattern and profile.replace_pattern:
            try:
                # Handle backreferences in the replacement pattern
                safe_replace_pattern = re.sub(r'\$(\d+)', r'\\\1', profile.replace_pattern)

                # Apply transformation to the complete URL
                transformed_complete_url = re.sub(profile.search_pattern, safe_replace_pattern, complete_url)
                logger.info(f"Transformed complete URL: {complete_url} -> {transformed_complete_url}")

                # Extract components from the transformed URL
                # Pattern: http://server.com:port/live/username/password/1234.ts
                parsed_url = urllib.parse.urlparse(transformed_complete_url)
                path_parts = [part for part in parsed_url.path.split('/') if part]

                if len(path_parts) >= 2:
                    # Extract username and password from path
                    transformed_username = path_parts[1]
                    transformed_password = path_parts[2]

                    # Rebuild server URL without the username/password path
                    transformed_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                    if parsed_url.port:
                        transformed_url = f"{parsed_url.scheme}://{parsed_url.hostname}:{parsed_url.port}"

                    logger.debug(f"Extracted transformed credentials:")
                    logger.debug(f"  Server URL: {transformed_url}")
                    logger.debug(f"  Username: {transformed_username}")
                    logger.debug(f"  Password: {transformed_password}")

                    return transformed_url, transformed_username, transformed_password
                else:
                    logger.warning(f"Could not extract credentials from transformed URL: {transformed_complete_url}")
                    return base_url, base_username, base_password

            except Exception as e:
                logger.error(f"Error transforming URL for profile {profile.name if profile else 'unknown'}: {e}")
                return base_url, base_username, base_password
        else:
            # No profile or no transformation patterns
            return base_url, base_username, base_password
    else:
        logger.warning(f"Missing credentials for account {account.name}")
        return base_url, base_username, base_password


@shared_task
def refresh_account_profiles(account_id):
    """Refresh account information for all active profiles of an XC account.

    This task runs asynchronously in the background after account refresh completes.
    It includes rate limiting delays between profile authentications to prevent provider bans.
    """
    from django.conf import settings
    import time

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)

        if account.account_type != M3UAccount.Types.XC:
            logger.debug(f"Account {account_id} is not XC type, skipping profile refresh")
            return f"Account {account_id} is not an XtreamCodes account"

        from apps.m3u.models import M3UAccountProfile

        profiles = M3UAccountProfile.objects.filter(
            m3u_account=account,
            is_active=True
        )

        if not profiles.exists():
            logger.info(f"No active profiles found for account {account.name}")
            return f"No active profiles for account {account_id}"

        # Get user agent for this account
        try:
            user_agent_string = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            if account.user_agent_id:
                from core.models import UserAgent
                ua_obj = UserAgent.objects.get(id=account.user_agent_id)
                if ua_obj and hasattr(ua_obj, "user_agent") and ua_obj.user_agent:
                    user_agent_string = ua_obj.user_agent
        except Exception as e:
            logger.warning(f"Error getting user agent, using fallback: {str(e)}")
        logger.debug(f"Using user agent for profile refresh: {user_agent_string}")
        # Get rate limiting delay from settings
        profile_delay = getattr(settings, 'XC_PROFILE_REFRESH_DELAY', 2.5)

        profiles_updated = 0
        profiles_failed = 0

        logger.info(f"Starting background refresh for {profiles.count()} profiles of account {account.name}")

        for idx, profile in enumerate(profiles):
            try:
                # Add delay between profiles to prevent rate limiting (except for first profile)
                if idx > 0:
                    logger.info(f"Waiting {profile_delay}s before refreshing next profile to avoid rate limiting")
                    time.sleep(profile_delay)

                # Get transformed credentials for this specific profile
                profile_url, profile_username, profile_password = get_transformed_credentials(account, profile)

                # Create a separate XC client for this profile's credentials
                with XCClient(
                    profile_url,
                    profile_username,
                    profile_password,
                    user_agent_string
                ) as profile_client:
                    # Authenticate with this profile's credentials
                    if profile_client.authenticate():
                        # Get account information specific to this profile's credentials
                        profile_account_info = profile_client.get_account_info()

                        # Merge with existing custom_properties if they exist
                        existing_props = profile.custom_properties or {}
                        existing_props.update(profile_account_info)
                        profile.custom_properties = existing_props
                        profile.save(update_fields=['custom_properties'])

                        profiles_updated += 1
                        logger.info(f"Updated account information for profile '{profile.name}' ({profiles_updated}/{profiles.count()})")
                    else:
                        profiles_failed += 1
                        logger.warning(f"Failed to authenticate profile '{profile.name}' with transformed credentials")

            except Exception as profile_error:
                profiles_failed += 1
                logger.error(f"Failed to update account information for profile '{profile.name}': {str(profile_error)}")
                # Continue with other profiles even if one fails

        result_msg = f"Profile refresh complete for account {account.name}: {profiles_updated} updated, {profiles_failed} failed"
        logger.info(result_msg)
        return result_msg

    except M3UAccount.DoesNotExist:
        error_msg = f"Account {account_id} not found"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Error refreshing profiles for account {account_id}: {str(e)}"
        logger.error(error_msg)
        return error_msg


@shared_task
def refresh_account_info(profile_id):
    """Refresh only the account information for a specific M3U profile."""
    if not acquire_task_lock("refresh_account_info", profile_id):
        return f"Account info refresh task already running for profile_id={profile_id}."

    try:
        from apps.m3u.models import M3UAccountProfile
        import re

        profile = M3UAccountProfile.objects.get(id=profile_id)
        account = profile.m3u_account

        if account.account_type != M3UAccount.Types.XC:
            release_task_lock("refresh_account_info", profile_id)
            return f"Profile {profile_id} belongs to account {account.id} which is not an XtreamCodes account."

        # Get transformed credentials using the helper function
        transformed_url, transformed_username, transformed_password = get_transformed_credentials(account, profile)

        # Initialize XtreamCodes client with extracted/transformed credentials
        client = XCClient(
            transformed_url,
            transformed_username,
            transformed_password,
            account.get_user_agent(),
        )        # Authenticate and get account info
        auth_result = client.authenticate()
        if not auth_result:
            error_msg = f"Authentication failed for profile {profile.name} ({profile_id})"
            logger.error(error_msg)

            # Send error notification to frontend via websocket
            send_websocket_update(
                "updates",
                "update",
                {
                    "type": "account_info_refresh_error",
                    "profile_id": profile_id,
                    "profile_name": profile.name,
                    "error": "Authentication failed with the provided credentials",
                    "message": f"Failed to authenticate profile '{profile.name}'. Please check the credentials."
                }
            )

            release_task_lock("refresh_account_info", profile_id)
            return error_msg

        # Get account information
        account_info = client.get_account_info()

        # Update only this specific profile with the new account info
        if not profile.custom_properties:
            profile.custom_properties = {}
        profile.custom_properties.update(account_info)
        profile.save()

        # Send success notification to frontend via websocket
        send_websocket_update(
            "updates",
            "update",
            {
                "type": "account_info_refresh_success",
                "profile_id": profile_id,
                "profile_name": profile.name,
                "message": f"Account information successfully refreshed for profile '{profile.name}'"
            }
        )

        release_task_lock("refresh_account_info", profile_id)
        return f"Account info refresh completed for profile {profile_id} ({profile.name})."

    except M3UAccountProfile.DoesNotExist:
        error_msg = f"Profile {profile_id} not found"
        logger.error(error_msg)

        send_websocket_update(
            "updates",
            "update",
            {
                "type": "account_refresh_error",
                "profile_id": profile_id,
                "error": "Profile not found",
                "message": f"Profile {profile_id} not found"
            }
        )

        release_task_lock("refresh_account_info", profile_id)
        return error_msg
    except Exception as e:
        error_msg = f"Error refreshing account info for profile {profile_id}: {str(e)}"
        logger.error(error_msg)

        send_websocket_update(
            "updates",
            "update",
            {
                "type": "account_refresh_error",
                "profile_id": profile_id,
                "error": str(e),
                "message": f"Failed to refresh account info: {str(e)}"
            }
        )

        release_task_lock("refresh_account_info", profile_id)
        return error_msg
@shared_task
def refresh_single_m3u_account(account_id):
    """Splits M3U processing into chunks and dispatches them as parallel tasks."""
    if not acquire_task_lock("refresh_single_m3u_account", account_id):
        return f"Task already running for account_id={account_id}."

    # Record start time
    refresh_start_timestamp = timezone.now()  # For the cleanup function
    start_time = time.time()  # For tracking elapsed time as float
    streams_created = 0
    streams_updated = 0
    streams_deleted = 0

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
        if not account.is_active:
            logger.debug(f"Account {account_id} is not active, skipping.")
            release_task_lock("refresh_single_m3u_account", account_id)
            return

        # Set status to fetching
        account.status = M3UAccount.Status.FETCHING
        account.save(update_fields=['status'])

        filters = list(account.filters.all())

        # Check if VOD is enabled for this account
        vod_enabled = False
        if account.custom_properties:
            custom_props = account.custom_properties or {}
            vod_enabled = custom_props.get('enable_vod', False)

    except M3UAccount.DoesNotExist:
        # The M3U account doesn't exist, so delete the periodic task if it exists
        logger.warning(
            f"M3U account with ID {account_id} not found, but task was triggered. Cleaning up orphaned task."
        )

        # Call the helper function to delete the task
        if delete_m3u_refresh_task_by_id(account_id):
            logger.info(
                f"Successfully cleaned up orphaned task for M3U account {account_id}"
            )
        else:
            logger.debug(f"No orphaned task found for M3U account {account_id}")

        release_task_lock("refresh_single_m3u_account", account_id)
        return f"M3UAccount with ID={account_id} not found or inactive, task cleaned up"

    # Fetch M3U lines and handle potential issues
    extinf_data = []
    groups = None

    cache_path = os.path.join(m3u_dir, f"{account_id}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as file:
                data = json.load(file)

            extinf_data = data["extinf_data"]
            groups = data["groups"]
        except json.JSONDecodeError as e:
            # Handle corrupted JSON file
            logger.error(
                f"Error parsing cached M3U data for account {account_id}: {str(e)}"
            )

            # Backup the corrupted file for potential analysis
            backup_path = f"{cache_path}.corrupted"
            try:
                os.rename(cache_path, backup_path)
                logger.info(f"Renamed corrupted cache file to {backup_path}")
            except OSError as rename_err:
                logger.warning(
                    f"Failed to rename corrupted cache file: {str(rename_err)}"
                )

            # Reset the data to empty structures
            extinf_data = []
            groups = None
        except Exception as e:
            logger.error(f"Unexpected error reading cached M3U data: {str(e)}")
            extinf_data = []
            groups = None

    if not extinf_data:
        try:
            logger.info(f"Calling refresh_m3u_groups for account {account_id}")
            result = refresh_m3u_groups(account_id, full_refresh=True)
            logger.trace(f"refresh_m3u_groups result: {result}")

            # Check for completely empty result or missing groups
            if not result or result[1] is None:
                logger.error(
                    f"Failed to refresh M3U groups for account {account_id}: {result}"
                )
                release_task_lock("refresh_single_m3u_account", account_id)
                return "Failed to update m3u account - download failed or other error"

            extinf_data, groups = result

            # XC accounts can have empty extinf_data but valid groups
            try:
                account = M3UAccount.objects.get(id=account_id)
                is_xc_account = account.account_type == M3UAccount.Types.XC
            except M3UAccount.DoesNotExist:
                is_xc_account = False

            # For XC accounts, empty extinf_data is normal at this stage
            if not extinf_data and not is_xc_account:
                logger.error(f"No streams found for non-XC account {account_id}")
                account.status = M3UAccount.Status.ERROR
                account.last_message = "No streams found in M3U source"
                account.save(update_fields=["status", "last_message"])
                send_m3u_update(
                    account_id, "parsing", 100, status="error", error="No streams found"
                )
        except Exception as e:
            logger.error(f"Exception in refresh_m3u_groups: {str(e)}", exc_info=True)
            account.status = M3UAccount.Status.ERROR
            account.last_message = f"Error refreshing M3U groups: {str(e)}"
            account.save(update_fields=["status", "last_message"])
            send_m3u_update(
                account_id,
                "parsing",
                100,
                status="error",
                error=f"Error refreshing M3U groups: {str(e)}",
            )
            release_task_lock("refresh_single_m3u_account", account_id)
            return "Failed to update m3u account"

    # Only proceed with parsing if we actually have data and no errors were encountered
    # Get account type to handle XC accounts differently
    try:
        is_xc_account = account.account_type == M3UAccount.Types.XC
    except Exception:
        is_xc_account = False

    # Modified validation logic for different account types
    if (not groups) or (not is_xc_account and not extinf_data):
        logger.error(f"No data to process for account {account_id}")
        account.status = M3UAccount.Status.ERROR
        account.last_message = "No data available for processing"
        account.save(update_fields=["status", "last_message"])
        send_m3u_update(
            account_id,
            "parsing",
            100,
            status="error",
            error="No data available for processing",
        )
        release_task_lock("refresh_single_m3u_account", account_id)
        return "Failed to update m3u account, no data available"

    hash_keys = CoreSettings.get_m3u_hash_key().split(",")

    existing_groups = {
        group.name: group.id
        for group in ChannelGroup.objects.filter(
            m3u_accounts__m3u_account=account,  # Filter by the M3UAccount
            m3u_accounts__enabled=True,  # Filter by the enabled flag in the join table
        )
    }

    try:
        # Set status to parsing
        account.status = M3UAccount.Status.PARSING
        account.save(update_fields=["status"])

        # Commit any pending transactions before threading
        from django.db import transaction
        transaction.commit()

        # Initialize stream counters
        streams_created = 0
        streams_updated = 0

        if account.account_type == M3UAccount.Types.STADNARD:
            logger.debug(
                f"Processing Standard account ({account_id}) with groups: {existing_groups}"
            )
            # Break into batches and process with threading - use global batch size
            batches = [
                extinf_data[i : i + BATCH_SIZE]
                for i in range(0, len(extinf_data), BATCH_SIZE)
            ]

            logger.info(f"Processing {len(extinf_data)} streams in {len(batches)} thread batches")

            # Use 2 threads for optimal database connection handling
            max_workers = min(2, len(batches))
            logger.debug(f"Using {max_workers} threads for processing")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit batch processing tasks using direct functions (now thread-safe)
                future_to_batch = {
                    executor.submit(process_m3u_batch_direct, account_id, batch, existing_groups, hash_keys): i
                    for i, batch in enumerate(batches)
                }

                completed_batches = 0
                total_batches = len(batches)

                # Process completed batches as they finish
                for future in as_completed(future_to_batch):
                    batch_idx = future_to_batch[future]
                    try:
                        result = future.result()
                        completed_batches += 1

                        # Extract stream counts from result
                        if isinstance(result, str):
                            try:
                                created_match = re.search(r"(\d+) created", result)
                                updated_match = re.search(r"(\d+) updated", result)
                                if created_match and updated_match:
                                    created_count = int(created_match.group(1))
                                    updated_count = int(updated_match.group(1))
                                    streams_created += created_count
                                    streams_updated += updated_count
                            except (AttributeError, ValueError):
                                pass

                        # Send progress update
                        progress = int((completed_batches / total_batches) * 100)
                        current_elapsed = time.time() - start_time

                        if progress > 0:
                            estimated_total = (current_elapsed / progress) * 100
                            time_remaining = max(0, estimated_total - current_elapsed)
                        else:
                            time_remaining = 0

                        send_m3u_update(
                            account_id,
                            "parsing",
                            progress,
                            elapsed_time=current_elapsed,
                            time_remaining=time_remaining,
                            streams_processed=streams_created + streams_updated,
                        )

                        logger.debug(f"Thread batch {completed_batches}/{total_batches} completed")

                    except Exception as e:
                        logger.error(f"Error in thread batch {batch_idx}: {str(e)}")
                        completed_batches += 1  # Still count it to avoid hanging

            logger.info(f"Thread-based processing completed for account {account_id}")
        else:
            # For XC accounts, get the groups with their custom properties containing xc_id
            logger.debug(f"Processing XC account with groups: {existing_groups}")

            # Get the ChannelGroupM3UAccount entries with their custom_properties
            channel_group_relationships = ChannelGroupM3UAccount.objects.filter(
                m3u_account=account, enabled=True
            ).select_related("channel_group")

            filtered_groups = {}
            for rel in channel_group_relationships:
                group_name = rel.channel_group.name
                group_id = rel.channel_group.id

                # Load the custom properties with the xc_id
                custom_props = rel.custom_properties or {}
                if "xc_id" in custom_props:
                    filtered_groups[group_name] = {
                        "xc_id": custom_props["xc_id"],
                        "channel_group_id": group_id,
                    }
                    logger.debug(
                        f"Added group {group_name} with xc_id {custom_props['xc_id']}"
                    )
                else:
                    logger.warning(
                        f"No xc_id found in custom properties for group {group_name}"
                    )

            logger.info(
                f"Filtered {len(filtered_groups)} groups for processing: {filtered_groups}"
            )

            # Collect all XC streams in a single API call and filter by enabled categories
            logger.info("Fetching all XC streams from provider and filtering by enabled categories...")
            all_xc_streams = collect_xc_streams(account_id, filtered_groups)

            if not all_xc_streams:
                logger.warning("No streams collected from XC groups")
            else:
                # Now batch by stream count (like standard M3U processing)
                batches = [
                    all_xc_streams[i : i + BATCH_SIZE]
                    for i in range(0, len(all_xc_streams), BATCH_SIZE)
                ]

                logger.info(f"Processing {len(all_xc_streams)} XC streams in {len(batches)} batches")

                # Use threading for XC stream processing - now with consistent batch sizes
                max_workers = min(4, len(batches))
                logger.debug(f"Using {max_workers} threads for XC stream processing")

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit stream batch processing tasks (reuse standard M3U processing)
                    future_to_batch = {
                        executor.submit(process_m3u_batch_direct, account_id, batch, existing_groups, hash_keys): i
                        for i, batch in enumerate(batches)
                    }

                    completed_batches = 0
                    total_batches = len(batches)

                    # Process completed batches as they finish
                    for future in as_completed(future_to_batch):
                        batch_idx = future_to_batch[future]
                        try:
                            result = future.result()
                            completed_batches += 1

                            # Extract stream counts from result
                            if isinstance(result, str):
                                try:
                                    created_match = re.search(r"(\d+) created", result)
                                    updated_match = re.search(r"(\d+) updated", result)
                                    if created_match and updated_match:
                                        created_count = int(created_match.group(1))
                                        updated_count = int(updated_match.group(1))
                                        streams_created += created_count
                                        streams_updated += updated_count
                                except (AttributeError, ValueError):
                                    pass

                            # Send progress update
                            progress = int((completed_batches / total_batches) * 100)
                            current_elapsed = time.time() - start_time

                            if progress > 0:
                                estimated_total = (current_elapsed / progress) * 100
                                time_remaining = max(0, estimated_total - current_elapsed)
                            else:
                                time_remaining = 0

                            send_m3u_update(
                                account_id,
                                "parsing",
                                progress,
                                elapsed_time=current_elapsed,
                                time_remaining=time_remaining,
                                streams_processed=streams_created + streams_updated,
                            )

                            logger.debug(f"XC thread batch {completed_batches}/{total_batches} completed")

                        except Exception as e:
                            logger.error(f"Error in XC thread batch {batch_idx}: {str(e)}")
                            completed_batches += 1  # Still count it to avoid hanging

                logger.info(f"XC thread-based processing completed for account {account_id}")

        # Ensure all database transactions are committed before cleanup
        logger.info(
            f"All thread processing completed, ensuring DB transactions are committed before cleanup"
        )
        # Force a simple DB query to ensure connection sync
        Stream.objects.filter(
            id=-1
        ).exists()  # This will never find anything but ensures DB sync

        # Now run cleanup
        streams_deleted = cleanup_streams(account_id, refresh_start_timestamp)

        # Run auto channel sync after successful refresh
        auto_sync_message = ""
        try:
            sync_result = sync_auto_channels(
                account_id, scan_start_time=str(refresh_start_timestamp)
            )
            logger.info(
                f"Auto channel sync result for account {account_id}: {sync_result}"
            )
            if sync_result and "created" in sync_result:
                auto_sync_message = f" {sync_result}."
        except Exception as e:
            logger.error(
                f"Error running auto channel sync for account {account_id}: {str(e)}"
            )

        # Calculate elapsed time
        elapsed_time = time.time() - start_time

        # Calculate total streams processed
        streams_processed = streams_created + streams_updated

        # Set status to success and update timestamp BEFORE sending the final update
        account.status = M3UAccount.Status.SUCCESS
        account.last_message = (
            f"Processing completed in {elapsed_time:.1f} seconds. "
            f"Streams: {streams_created} created, {streams_updated} updated, {streams_deleted} removed. "
            f"Total processed: {streams_processed}.{auto_sync_message}"
        )
        account.updated_at = timezone.now()
        account.save(update_fields=["status", "last_message", "updated_at"])

        # Log system event for M3U refresh
        log_system_event(
            event_type='m3u_refresh',
            account_name=account.name,
            elapsed_time=round(elapsed_time, 2),
            streams_created=streams_created,
            streams_updated=streams_updated,
            streams_deleted=streams_deleted,
            total_processed=streams_processed,
        )

        # Send final update with complete metrics and explicitly include success status
        send_m3u_update(
            account_id,
            "parsing",
            100,
            status="success",  # Explicitly set status to success
            elapsed_time=elapsed_time,
            time_remaining=0,
            streams_processed=streams_processed,
            streams_created=streams_created,
            streams_updated=streams_updated,
            streams_deleted=streams_deleted,
            message=account.last_message,
        )

        # Trigger VOD refresh if enabled and account is XtreamCodes type
        if vod_enabled and account.account_type == M3UAccount.Types.XC:
            logger.info(f"VOD is enabled for account {account_id}, triggering VOD refresh")
            try:
                from apps.vod.tasks import refresh_vod_content
                refresh_vod_content.delay(account_id)
                logger.info(f"VOD refresh task queued for account {account_id}")
            except Exception as e:
                logger.error(f"Failed to queue VOD refresh for account {account_id}: {str(e)}")

    except Exception as e:
        logger.error(f"Error processing M3U for account {account_id}: {str(e)}")
        account.status = M3UAccount.Status.ERROR
        account.last_message = f"Error processing M3U: {str(e)}"
        account.save(update_fields=["status", "last_message"])
        raise  # Re-raise the exception for Celery to handle

    release_task_lock("refresh_single_m3u_account", account_id)

    # Aggressive garbage collection
    # Only delete variables if they exist
    if 'existing_groups' in locals():
        del existing_groups
    if 'extinf_data' in locals():
        del extinf_data
    if 'groups' in locals():
        del groups
    if 'batches' in locals():
        del batches

    from core.utils import cleanup_memory

    cleanup_memory(log_usage=True, force_collection=True)

    # Clean up cache file since we've fully processed it
    if os.path.exists(cache_path):
        os.remove(cache_path)

    return f"Dispatched jobs complete."


def send_m3u_update(account_id, action, progress, **kwargs):
    # Start with the base data dictionary
    data = {
        "progress": progress,
        "type": "m3u_refresh",
        "account": account_id,
        "action": action,
    }

    # Add the status and message if not already in kwargs
    try:
        account = M3UAccount.objects.get(id=account_id)
        if account:
            if "status" not in kwargs:
                data["status"] = account.status
            if "message" not in kwargs and account.last_message:
                data["message"] = account.last_message
    except:
        pass  # If account can't be retrieved, continue without these fields

    # Add the additional key-value pairs from kwargs
    data.update(kwargs)
    send_websocket_update("updates", "update", data, collect_garbage=False)

    # Explicitly clear data reference to help garbage collection
    data = None
