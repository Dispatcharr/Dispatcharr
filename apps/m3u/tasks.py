# apps/m3u/tasks.py
import logging
import re
import regex
import requests
import os
import gc
import gzip, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from celery import shared_task
from django.conf import settings
from django.db import models, transaction
from .models import M3UAccount
from apps.channels.models import Stream, ChannelGroup, ChannelGroupM3UAccount
from django.utils import timezone
import time
import json
from core.utils import (
    acquire_task_lock,
    release_task_lock,
    TaskLockRenewer,
    natural_sort_key,
    log_system_event,
    ensure_custom_properties_dict,
)
from core.models import CoreSettings, UserAgent
from core.xtream_codes import Client as XCClient
from core.utils import send_websocket_update
from .utils import normalize_stream_url

logger = logging.getLogger(__name__)

BATCH_SIZE = 1500  # Optimized batch size for threading
m3u_dir = os.path.join(settings.MEDIA_ROOT, "cached_m3u")

_NON_TERMINAL_REFRESH_STATUSES = frozenset({
    M3UAccount.Status.FETCHING,
    M3UAccount.Status.PARSING,
})


def _release_task_db_connection():
    """Return the Celery worker's DB connection to a clean state after ORM errors."""
    from django.db import close_old_connections
    close_old_connections()


def _db_query_with_retry(fn, *, label="DB query", max_retries=2):
    """
    Run an ORM read with one connection reset + retry on transient failures.

    Poisoned Celery worker connections often surface as OperationalError or as
    ``IndexError: list index out of range`` inside Django's row converters.
    """
    from django.db import InterfaceError, OperationalError

    transient_errors = (OperationalError, InterfaceError, IndexError)
    for attempt in range(max_retries):
        try:
            return fn()
        except transient_errors as exc:
            if attempt + 1 >= max_retries:
                raise
            logger.warning(
                "%s failed (%s), resetting DB connection (%s/%s)",
                label,
                exc,
                attempt + 1,
                max_retries,
            )
            _release_task_db_connection()


def _get_active_m3u_account(account_id):
    return _db_query_with_retry(
        lambda: M3UAccount.objects.get(id=account_id, is_active=True),
        label=f"load active M3U account {account_id}",
    )


def _set_m3u_account_status(
    account_id,
    status,
    last_message=None,
    *,
    notify_error=False,
    ws_action="parsing",
    ws_error=None,
):
    """Update account status using a fresh connection (safe after DB failures)."""
    _release_task_db_connection()
    update = {"status": status}
    if last_message is not None:
        update["last_message"] = last_message
    try:
        M3UAccount.objects.filter(id=account_id).update(**update)
        if notify_error:
            send_m3u_update(
                account_id,
                ws_action,
                100,
                status="error",
                error=ws_error or last_message,
            )
    except Exception as e:
        logger.error(
            f"Failed to set account {account_id} status to {status}: {e}"
        )


def _ensure_m3u_refresh_terminal_status(account_id):
    """Mark refresh as failed when the task exits while still in progress."""
    _release_task_db_connection()
    try:
        current_status = (
            M3UAccount.objects.filter(id=account_id)
            .values_list("status", flat=True)
            .first()
        )
        if current_status in _NON_TERMINAL_REFRESH_STATUSES:
            message = "Refresh did not complete successfully"
            M3UAccount.objects.filter(id=account_id).update(
                status=M3UAccount.Status.ERROR,
                last_message=message,
            )
            send_m3u_update(
                account_id, "parsing", 100, status="error", error=message
            )
    except Exception as e:
        logger.debug(
            f"Could not verify terminal refresh status for account {account_id}: {e}"
        )

_EXTINF_ATTR_RE = re.compile(r'([^\s=]+)\s*=\s*(["\'])(.*?)\2')


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
                    account.server_url, headers=headers, stream=True,
                    timeout=(30, 60),  # 30s connect, 60s read between chunks
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
                has_content = False

                # Stream directly to a temp file to avoid holding the entire
                # M3U in memory (large files can be 100MB+, which would use
                # ~3x that in RAM in certain approaches).
                temp_path = file_path + ".tmp"
                try:
                    send_m3u_update(account.id, "downloading", 0)
                    with open(temp_path, "wb") as tmp_file:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                tmp_file.write(chunk)
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
                    logger.info(f"Download completed. Has content: {has_content}, Content length: {downloaded} bytes")
                    if not has_content or downloaded == 0:
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

                    # Validate the file by reading only the first portion from
                    # disk — no need to load the entire file into memory just
                    # to check the header.
                    VALIDATION_READ_SIZE = 32768  # 32KB covers headers comfortably
                    try:
                        with open(temp_path, "rb") as vf:
                            head_bytes = vf.read(VALIDATION_READ_SIZE)
                        head_str = head_bytes.decode('utf-8', errors='ignore')
                        head_lines = head_str.strip().split('\n')

                        # Count total lines efficiently without loading full file
                        with open(temp_path, "rb") as vf:
                            total_lines = sum(1 for _ in vf)

                        # Log first few lines for debugging (be careful not to log too much)
                        preview_lines = head_lines[:5]
                        logger.info(f"Content preview (first 5 lines): {preview_lines}")
                        logger.info(f"Total lines in content: {total_lines}")

                        # Check if it's a valid M3U file (should start with #EXTM3U or contain M3U-like content)
                        is_valid_m3u = False

                        # First, check if this looks like an error response disguised as 200 OK
                        head_lower = head_str.lower()
                        if any(error_indicator in head_lower for error_indicator in [
                            '<html', '<!doctype html', 'error', 'not found', '404', '403', '500',
                            'access denied', 'unauthorized', 'forbidden', 'invalid', 'expired'
                        ]):
                            logger.warning(f"Content appears to be an error response disguised as HTTP 200: {head_str[:200]!r}")
                            # Continue with M3U validation, but this gives us a clue

                        if head_lines and head_lines[0].strip().upper().startswith('#EXTM3U'):
                            is_valid_m3u = True
                            logger.info("Content validated as M3U: starts with #EXTM3U")
                        elif any(line.strip().startswith('#EXTINF:') for line in head_lines):
                            is_valid_m3u = True
                            logger.info("Content validated as M3U: contains #EXTINF entries")
                        elif any(line.strip().startswith('http') for line in head_lines):
                            # Has HTTP URLs, might be a simple M3U without headers
                            is_valid_m3u = True
                            logger.info("Content validated as M3U: contains HTTP URLs")
                        elif any(line.strip().startswith(('rtsp', 'rtp', 'udp')) for line in head_lines):
                            # Has RTSP/RTP/UDP URLs, might be a simple M3U without headers
                            is_valid_m3u = True
                            logger.info("Content validated as M3U: contains RTSP/RTP/UDP URLs")

                        if not is_valid_m3u:
                            # Log what we actually received for debugging
                            logger.error(f"Invalid M3U content received. First 200 characters: {head_str[:200]!r}")

                            # Try to provide more specific error messages based on content
                            if '<html' in head_lower or '<!doctype html' in head_lower:
                                error_msg = f"Server returned HTML page instead of M3U file from URL: {account.server_url}. This usually indicates an error or authentication issue."
                            elif 'error' in head_lower or 'not found' in head_lower:
                                error_msg = f"Server returned an error message instead of M3U file from URL: {account.server_url}. Content: {head_str[:100]}"
                            elif len(head_str.strip()) == 0:
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
                        with open(temp_path, "rb") as vf:
                            first_bytes = vf.read(200)
                        logger.error(f"Non-text content received. First 200 bytes: {first_bytes!r}")
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

                    # Validation passed — promote temp file to final path
                    os.replace(temp_path, file_path)

                    # Final update with 100% progress
                    dl_size = downloaded / 1024 / 1024
                    final_msg = f"Download complete. Size: {dl_size:.2f} MB, Time: {time.time() - start_time:.1f}s"
                    account.last_message = final_msg
                    account.save(update_fields=["last_message"])
                    send_m3u_update(account.id, "downloading", 100, message=final_msg)

                finally:
                    # Clean up temp file on any failure path
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
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


def parse_is_adult(value):
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return False


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

    # Single pass: extract all attributes AND track the last attribute position.
    # Keys are normalised to lowercase so downstream code can use plain dict.get()
    attrs = {}
    last_attr_end = 0

    for match in _EXTINF_ATTR_RE.finditer(content):
        attrs[match.group(1).lower()] = match.group(3)
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

    # Per the base #EXTINF spec, the comma text is the canonical human-readable title.
    # Fall back to tvc-guide-title, then tvg-name (which some providers use as an EPG key,
    # not a display label), and finally the raw content if everything else is empty.
    name = display_name or attrs.get("tvc-guide-title") or attrs.get("tvg-name") or content.strip()
    return {"attributes": attrs, "display_name": display_name, "name": name}


def iter_m3u_entries(lines):
    """
    Generator that yields fully-assembled M3U stream entries from raw lines.

    Each yielded dict is guaranteed to contain a ``url`` key in addition to the
    fields produced by :func:`parse_extinf_line` (``attributes``, ``display_name``,
    ``name``).  Recognised extended-tag lines that appear *between* an ``#EXTINF``
    and its URL are accumulated into the pending entry so they are available for
    downstream processing:

    - ``#EXTGRP`` — sets ``attributes["group-title"]`` when no ``group-title``
      attribute was present on the ``#EXTINF`` line (explicit attribute wins).
    - ``#EXTVLCOPT`` — stored as a list under the ``vlc_opts`` key.

    Unknown directives (``#KODIPROP``, etc.) and blank lines are
    silently skipped while keeping the pending entry intact.  A second ``#EXTINF``
    before a URL discards the first entry with a warning.  A trailing ``#EXTINF``
    at end-of-file with no URL is also discarded.

    Adding support for a new directive requires only a new ``elif`` branch here;
    no other code needs to change.
    """
    pending = None
    pending_line_num = None
    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            if pending is not None:
                logger.warning(
                    f"Line {pending_line_num}: #EXTINF had no URL (next #EXTINF at line {line_num}); "
                    f"discarding entry: {list(pending['attributes'].items())[:3]}"
                )
            parsed = parse_extinf_line(line)
            if parsed is None:
                logger.warning(f"Line {line_num}: Failed to parse #EXTINF: {line[:200]}")
            pending = parsed  # None if malformed; URL branch guards on `pending is not None`
            pending_line_num = line_num

        elif line.startswith("#EXTGRP:"):
            # Only apply when group-title is absent — explicit attribute wins.
            if pending is not None and "group-title" not in pending["attributes"]:
                pending["attributes"]["group-title"] = line[len("#EXTGRP:"):].strip()
            # else: #EXTGRP outside an entry, or group-title already set — silently skip

        elif line.startswith("#EXTVLCOPT:"):
            if pending is not None:
                pending.setdefault("vlc_opts", []).append(line[len("#EXTVLCOPT:"):])
            # else: #EXTVLCOPT outside an entry — silently skip

        elif pending is not None and line.startswith(("http", "rtsp", "rtp", "udp")):
            pending["url"] = normalize_stream_url(line) if line.startswith("udp") else line
            yield pending
            pending = None
            pending_line_num = None

        # else: unknown directive or bare content — skip, keeping pending intact

    if pending is not None:
        logger.warning(
            f"Line {pending_line_num}: #EXTINF at end of file had no URL; "
            f"discarding entry: {list(pending['attributes'].items())[:3]}"
        )


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
def process_groups(account, groups, scan_start_time=None):
    """Process groups and update their relationships with the M3U account.

    Args:
        account: M3UAccount instance
        groups: Dict of group names to custom properties
        scan_start_time: Timestamp when the scan started (for consistent last_seen marking)
    """
    # Use scan_start_time if provided, otherwise current time
    # This ensures consistency with stream processing and cleanup logic
    if scan_start_time is None:
        scan_start_time = timezone.now()

    existing_groups = {
        group.name: group
        for group in ChannelGroup.objects.filter(name__in=groups.keys())
    }
    logger.info(f"Currently {len(existing_groups)} existing groups")

    # Check if we should auto-enable new groups based on account settings
    account_custom_props = ensure_custom_properties_dict(account.custom_properties)
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

    relations_to_create = []
    relations_to_update = []

    for group in all_group_objs:
        custom_props = groups.get(group.name, {})

        if group.name in existing_relationships:
            # Update existing relationship if xc_id has changed (preserve other custom properties)
            existing_rel = existing_relationships[group.name]

            # Get existing custom properties (now JSONB, no need to parse)
            existing_custom_props = ensure_custom_properties_dict(
                existing_rel.custom_properties
            )

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
                existing_rel.last_seen = scan_start_time
                existing_rel.is_stale = False
                relations_to_update.append(existing_rel)
                logger.debug(f"Updated xc_id for group '{group.name}' from '{existing_xc_id}' to '{new_xc_id}' - account {account.id}")
            else:
                # Update last_seen even if xc_id hasn't changed
                if isinstance(existing_rel.custom_properties, str):
                    existing_rel.custom_properties = existing_custom_props
                existing_rel.last_seen = scan_start_time
                existing_rel.is_stale = False
                relations_to_update.append(existing_rel)
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
                    last_seen=scan_start_time,
                    is_stale=False,
                )
            )

    # Bulk create new relationships
    if relations_to_create:
        ChannelGroupM3UAccount.objects.bulk_create(relations_to_create, ignore_conflicts=True)
        logger.debug(f"Created {len(relations_to_create)} new group relationships for account {account.id}")

    # Bulk update existing relationships
    if relations_to_update:
        ChannelGroupM3UAccount.objects.bulk_update(relations_to_update, ['custom_properties', 'last_seen', 'is_stale'])
        logger.info(f"Updated {len(relations_to_update)} existing group relationships for account {account.id}")


def cleanup_stale_group_relationships(account, scan_start_time):
    """
    Remove group relationships that haven't been seen since the stale retention period.
    This follows the same logic as stream cleanup for consistency.
    """
    # Calculate cutoff date for stale group relationships
    stale_cutoff = scan_start_time - timezone.timedelta(days=account.stale_stream_days)
    logger.info(
        f"Removing group relationships not seen since {stale_cutoff} for M3U account {account.id}"
    )

    # Find stale relationships
    stale_relationships = ChannelGroupM3UAccount.objects.filter(
        m3u_account=account,
        last_seen__lt=stale_cutoff
    ).select_related('channel_group')

    relations_to_delete = list(stale_relationships)
    deleted_count = len(relations_to_delete)

    if deleted_count > 0:
        logger.info(
            f"Found {deleted_count} stale group relationships for account {account.id}: "
            f"{[rel.channel_group.name for rel in relations_to_delete]}"
        )

        # Delete the stale relationships
        stale_relationships.delete()

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
    else:
        logger.debug(f"No stale group relationships found for account {account.id}")

    return deleted_count


def collect_xc_streams(account_id, enabled_groups):
    """Collect all XC streams in a single API call and filter by enabled groups."""
    account = M3UAccount.objects.get(id=account_id)
    all_streams = []
    filtered_count = 0

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
            for stream in all_xc_streams:
                # Fall back to a generated name if the provider returns null/empty
                stream_name = stream.get("name") or f"{account.name} - {stream.get('stream_id', 'Unknown')}"
                if not stream.get("name"):
                    logger.warning(
                        f"XC stream has null/empty name; using generated name '{stream_name}' "
                        f"(stream_id={stream.get('stream_id', 'unknown')})"
                    )

                # Get the category_id for this stream
                category_id = str(stream.get("category_id", ""))

                # Only include streams from enabled categories
                if category_id in enabled_category_ids:
                    group_info = enabled_category_ids[category_id]

                    # Convert XC stream to our standard format with all properties preserved
                    stream_data = {
                        "name": stream_name,
                        "url": xc_client.get_stream_url(stream["stream_id"]),
                        "attributes": {
                            "tvg-id": stream.get("epg_channel_id", ""),
                            "tvg-logo": stream.get("stream_icon", ""),
                            "group-title": group_info["name"],
                            # Preserve all XC stream properties as custom attributes
                            "stream_id": str(stream.get("stream_id", "")),
                            "num": stream.get("num"),
                            "category_id": category_id,
                            "stream_type": stream.get("stream_type", ""),
                            "added": stream.get("added", ""),
                            "is_adult": str(stream.get("is_adult", "0")),
                            "custom_sid": stream.get("custom_sid", ""),
                            # Include any other properties that might be present
                            **{k: str(v) for k, v in stream.items() if k not in [
                                "name", "stream_id", "epg_channel_id", "stream_icon",
                                "category_id", "stream_type", "added", "is_adult", "custom_sid", "num"
                            ] and v is not None}
                        }
                    }
                    all_streams.append(stream_data)
                    filtered_count += 1

            # Drop the full provider catalog before returning; only filtered rows are needed.
            del all_xc_streams
            gc.collect()

    except Exception as e:
        logger.error(f"Failed to fetch XC streams: {str(e)}")
        return []

    logger.info(
        f"Filtered {filtered_count} streams from {len(enabled_category_ids)} enabled categories"
    )
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
                        name = stream.get("name") or f"{account.name} - {stream.get('stream_id', 'Unknown')}"
                        if not stream.get("name"):
                            logger.warning(
                                f"XC stream has null/empty name in category {group_name}; "
                                f"using generated name '{name}' (stream_id={stream.get('stream_id', 'unknown')})"
                            )
                        raw_stream_id = stream.get("stream_id", "")
                        provider_stream_id = None
                        if raw_stream_id:
                            try:
                                provider_stream_id = int(raw_stream_id)
                            except (ValueError, TypeError):
                                pass
                        url = xc_client.get_stream_url(stream["stream_id"])
                        tvg_id = stream.get("epg_channel_id", "")
                        tvg_logo = stream.get("stream_icon", "")
                        group_title = group_name
                        stream_chno = stream.get("num")
                        # Convert stream_chno to float if valid, otherwise None
                        if stream_chno is not None:
                            try:
                                stream_chno = float(stream_chno)
                            except (ValueError, TypeError):
                                stream_chno = None

                        stream_hash = Stream.generate_hash_key(
                            name, url, tvg_id, hash_keys, m3u_id=account_id, group=group_title,
                            account_type='XC', stream_id=provider_stream_id
                        )
                        # Derive denormalized catch-up fields from the XC
                        # API response at import time so output views can
                        # read them as zero-cost column reads.
                        _tv_archive = str(stream.get("tv_archive", "0"))
                        _is_catchup = _tv_archive in ("1", "True")
                        try:
                            _catchup_days = int(stream.get("tv_archive_duration", 0) or 0)
                        except (TypeError, ValueError):
                            _catchup_days = 0

                        stream_props = {
                            "name": name,
                            "url": url,
                            "logo_url": tvg_logo,
                            "tvg_id": tvg_id,
                            "m3u_account": account,
                            "channel_group_id": int(group_id),
                            "stream_hash": stream_hash,
                            "custom_properties": stream,
                            "is_adult": parse_is_adult(stream.get("is_adult", 0)),
                            "is_stale": False,
                            "stream_id": provider_stream_id,
                            "stream_chno": stream_chno,
                            "is_catchup": _is_catchup,
                            "catchup_days": _catchup_days,
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
                'id', 'stream_hash', 'name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'last_seen', 'updated_at', 'm3u_account', 'stream_id', 'stream_chno', 'channel_group_id'
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
                    obj.custom_properties != stream_props["custom_properties"] or
                    obj.is_adult != stream_props["is_adult"] or
                    obj.stream_id != stream_props["stream_id"] or
                    obj.stream_chno != stream_props["stream_chno"] or
                    obj.channel_group_id != stream_props["channel_group_id"]
                )

                if changed:
                    for key, value in stream_props.items():
                        setattr(obj, key, value)
                    obj.last_seen = timezone.now()
                    obj.updated_at = timezone.now()  # Update timestamp only for changed streams
                    obj.is_stale = False
                    streams_to_update.append(obj)
                else:
                    # Always update last_seen, even if nothing else changed
                    obj.last_seen = timezone.now()
                    obj.is_stale = False
                    # Don't update updated_at for unchanged streams
                    streams_to_update.append(obj)

                # Remove from existing_streams since we've processed it
                del existing_streams[stream_hash]
            else:
                stream_props["last_seen"] = timezone.now()
                stream_props["updated_at"] = (
                    timezone.now()
                )  # Set initial updated_at for new streams
                stream_props["is_stale"] = False
                streams_to_create.append(Stream(**stream_props))

        try:
            with transaction.atomic():
                if streams_to_create:
                    Stream.objects.bulk_create(streams_to_create, ignore_conflicts=True)

                if streams_to_update:
                    # Simplified bulk update for better performance
                    Stream.objects.bulk_update(
                        streams_to_update,
                        ['name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'is_adult', 'last_seen', 'updated_at', 'is_stale', 'stream_id', 'stream_chno', 'channel_group_id', 'is_catchup', 'catchup_days'],
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

    name_max_length = Stream._meta.get_field('name').max_length

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

            # Truncate name if it exceeds the model field limit
            if name and len(name) > name_max_length:
                logger.warning(f"Stream name too long ({len(name)} > {name_max_length}), truncating: {name[:80]}...")
                name = name[:name_max_length]

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

            # Determine provider-specific fields first
            provider_stream_id = None
            channel_num = None
            account_type_for_hash = None

            if account.account_type == M3UAccount.Types.XC:
                account_type_for_hash = 'XC'
                raw_stream_id = stream_info["attributes"].get("stream_id", "")
                if raw_stream_id:
                    try:
                        provider_stream_id = int(raw_stream_id)
                    except (ValueError, TypeError):
                        pass
                raw_num = stream_info["attributes"].get("num")
                if raw_num is not None:
                    try:
                        channel_num = float(raw_num)
                    except (ValueError, TypeError):
                        pass
            else:
                # For standard M3U accounts, check for tvg-chno or channel-number
                tvg_chno = get_case_insensitive_attr(stream_info["attributes"], "tvg-chno", None)
                if tvg_chno is None:
                    tvg_chno = get_case_insensitive_attr(stream_info["attributes"], "channel-number", None)
                if tvg_chno is not None:
                    try:
                        channel_num = float(tvg_chno)
                    except (ValueError, TypeError):
                        pass

            # Generate hash once with all parameters
            stream_hash = Stream.generate_hash_key(
                name, url, tvg_id, hash_keys, m3u_id=account_id, group=group_title,
                account_type=account_type_for_hash, stream_id=provider_stream_id
            )

            # Derive catch-up fields from stream attributes (M3U files
            # may carry tv_archive via custom attributes).
            _attrs = stream_info["attributes"]
            _tv_archive_m3u = str(_attrs.get("tv_archive", "0"))
            _is_catchup_m3u = _tv_archive_m3u in ("1", "True")
            try:
                _catchup_days_m3u = int(_attrs.get("tv_archive_duration", 0) or 0)
            except (TypeError, ValueError):
                _catchup_days_m3u = 0

            stream_props = {
                "name": name,
                "url": url,
                "logo_url": tvg_logo,
                "tvg_id": tvg_id,
                "m3u_account": account,
                "channel_group_id": int(groups.get(group_title)),
                "stream_hash": stream_hash,
                "custom_properties": {**_attrs, "vlc_opts": stream_info["vlc_opts"]} if "vlc_opts" in stream_info else _attrs,
                "is_adult": parse_is_adult(_attrs.get("is_adult", 0)),
                "is_stale": False,
                "stream_id": provider_stream_id,
                "stream_chno": channel_num,
                "is_catchup": _is_catchup_m3u,
                "catchup_days": _catchup_days_m3u,
            }

            if stream_hash not in stream_hashes:
                stream_hashes[stream_hash] = stream_props
        except Exception as e:
            logger.error(f"Failed to process stream {name}: {e}")
            logger.error(json.dumps(stream_info))

    existing_streams = {
        s.stream_hash: s
        for s in Stream.objects.filter(stream_hash__in=stream_hashes.keys()).select_related('m3u_account').only(
            'id', 'stream_hash', 'name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'last_seen', 'updated_at', 'm3u_account', 'stream_id', 'stream_chno', 'channel_group_id'
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
                obj.custom_properties != stream_props["custom_properties"] or
                obj.is_adult != stream_props["is_adult"] or
                obj.stream_id != stream_props["stream_id"] or
                obj.stream_chno != stream_props["stream_chno"] or
                obj.channel_group_id != stream_props["channel_group_id"]
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
                obj.is_adult = stream_props["is_adult"]
                obj.stream_id = stream_props["stream_id"]
                obj.stream_chno = stream_props["stream_chno"]
                obj.channel_group_id = stream_props["channel_group_id"]
                obj.updated_at = timezone.now()

            # Always mark as not stale since we saw it in this refresh
            obj.is_stale = False

            streams_to_update.append(obj)
        else:
            # New stream
            stream_props["last_seen"] = timezone.now()
            stream_props["updated_at"] = timezone.now()
            stream_props["is_stale"] = False
            streams_to_create.append(Stream(**stream_props))

    try:
        with transaction.atomic():
            if streams_to_create:
                Stream.objects.bulk_create(streams_to_create, ignore_conflicts=True)

            if streams_to_update:
                # Update all streams in a single bulk operation
                Stream.objects.bulk_update(
                    streams_to_update,
                    ['name', 'url', 'logo_url', 'tvg_id', 'custom_properties', 'is_adult', 'last_seen', 'updated_at', 'is_stale', 'stream_id', 'stream_chno', 'channel_group_id', 'is_catchup', 'catchup_days'],
                    batch_size=200
                )
    except Exception as e:
        logger.error(f"Bulk operation failed: {str(e)}")

    retval = f"M3U account: {account_id}, Batch processed: {len(streams_to_create)} created, {len(streams_to_update)} updated."

    # Clean up database connections for threading
    connections.close_all()

    # Free batch data structures (reference-counted deallocation)
    del streams_to_create, streams_to_update, stream_hashes, existing_streams
    gc.collect()

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
def refresh_m3u_groups(account_id, use_cache=False, full_refresh=False, scan_start_time=None):
    """Refresh M3U groups for an account.

    Args:
        account_id: ID of the M3U account
        use_cache: Whether to use cached M3U file
        full_refresh: Whether this is part of a full refresh
        scan_start_time: Timestamp when the scan started (for consistent last_seen marking)
    """
    if not acquire_task_lock("refresh_m3u_account_groups", account_id):
        return f"Task already running for account_id={account_id}.", None

    lock_renewer = TaskLockRenewer("refresh_m3u_account_groups", account_id)
    lock_renewer.start()

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
    except M3UAccount.DoesNotExist:
        lock_renewer.stop()
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
            lock_renewer.stop()
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
            lock_renewer.stop()
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

                    # Queue async profile refresh task to run in background
                    # This prevents any delay in the main refresh process
                    try:
                        logger.info(f"Queueing background profile refresh for account {account.name}")
                        refresh_account_profiles.delay(account.id)
                    except Exception as e:
                        logger.warning(f"Failed to queue profile refresh task: {str(e)}")
                        # Don't fail the main refresh if profile refresh can't be queued

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
                            lock_renewer.stop()
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
                        # Determine if this is an authentication error or category retrieval error
                        error_str = str(e).lower()
                        # Check for authentication-related keywords or HTTP status codes commonly used for auth failures
                        is_auth_error = any(keyword in error_str for keyword in [
                            'auth', 'credential', 'login', 'unauthorized', 'forbidden',
                            '401', '403', '512', '513'  # HTTP status codes: 401 Unauthorized, 403 Forbidden, 512-513 (non-standard auth failure)
                        ])

                        if is_auth_error:
                            error_msg = f"Failed to authenticate with XC server: {str(e)}"
                        else:
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
                        lock_renewer.stop()
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
                lock_renewer.stop()
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
            lock_renewer.stop()
            release_task_lock("refresh_m3u_account_groups", account_id)
            return error_msg, None
    else:
        lines, success = fetch_m3u_lines(account, use_cache)
        if not success:
            # If fetch failed, don't continue processing
            lock_renewer.stop()
            release_task_lock("refresh_m3u_account_groups", account_id)
            return f"Failed to fetch M3U data for account_id={account_id}.", None

        # Log basic file structure for debugging
        logger.debug(f"Processing {len(lines)} lines from M3U file")

        valid_stream_count = 0

        for entry in iter_m3u_entries(lines):
            valid_stream_count += 1
            group_title_attr = get_case_insensitive_attr(entry["attributes"], "group-title", "")
            if group_title_attr and group_title_attr not in groups:
                logger.debug(f"Found new group for M3U account {account_id}: '{group_title_attr}'")
                groups[group_title_attr] = {}
            extinf_data.append(entry)

            if valid_stream_count % 1000 == 0:
                logger.debug(f"Processed {valid_stream_count} valid streams so far for M3U account: {account_id}")

        logger.info(f"M3U parsing complete - Valid streams: {valid_stream_count}")

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

    process_groups(account, groups, scan_start_time)

    lock_renewer.stop()
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


def _next_available_number(used_numbers, start, end=None):
    """
    Return the smallest integer >= start that is not present in `used_numbers`.

    When `end` is provided (inclusive upper bound for range-constrained groups),
    returns None if the search exceeds that bound instead of running
    indefinitely. The search is O(cluster size) per call against the set;
    maintaining the cursor monotonically across calls keeps the
    "next_available" numbering mode from becoming O(N^2) on large groups.
    """
    n = start
    while n in used_numbers:
        n += 1
        if end is not None and n > end:
            return None
    if end is not None and n > end:
        return None
    return n


def _pick_target_number(
    mode,
    stream,
    used_numbers,
    fixed_cursor,
    fallback_start,
    end_number=None,
):
    """
    Return the channel number a stream should claim under the group's numbering
    mode, or None if the range is exhausted. Shared by the renumber and create
    passes. Each mode reads only the fields its UI exposes:

    - provider: the provider number is authoritative and used as-is when free.
      Start (`channel_numbering_fallback`) and End bound only the fallback for
      streams with no provider number; `auto_sync_channel_start` does not apply.
    - next_available: lowest free number from 1; End does not apply (its UI has
      no range, so a stale End must not cap it).
    - fixed: sequential from the cursor, bounded by End.
    """
    if mode == "provider":
        chno = stream.stream_chno
        if chno is not None and chno not in used_numbers:
            return chno
        # No usable provider number: fall back into the configured range.
        return _next_available_number(used_numbers, fallback_start, end=end_number)
    if mode == "next_available":
        return _next_available_number(used_numbers, 1)
    return _next_available_number(used_numbers, fixed_cursor, end=end_number)


def _range_exhausted_error(mode, start_number, end_number, fallback_start):
    """User-facing range text for RANGE_EXHAUSTED failures."""
    range_start = (
        int(fallback_start) if mode == "provider" else int(start_number)
    )
    return f"Channel number range {range_start}-{int(end_number)} is full"


def _classify_sync_failure(exc):
    """
    Map an exception raised during per-stream sync to a coarse typed
    reason used by the completion notification's grouped failure list.
    Keeps the bucket count small so the modal stays readable; the
    underlying exception text is preserved verbatim in ``error``.
    """
    from django.db import IntegrityError

    if isinstance(exc, IntegrityError):
        return "INTEGRITY_ERROR"
    return "OTHER"


def rollup_channel_catchup_fields(account_id):
    """Roll up denormalized catch-up fields from streams to channels.

    Updates ``is_catchup`` and ``catchup_days`` on every Channel that has
    at least one Stream belonging to *account_id* (auto-created or manually
    assigned), then self-heals any channel left flagged with no catch-up
    stream at all.

    Called from the account-refresh pipeline after streams have been
    written so that both new and existing channels reflect the current
    ``tv_archive`` flags.  Intentionally separate from
    ``sync_auto_channels`` because it applies to manual channels too and
    has no dependency on auto-channel logic.

    Uses a single-pass CTE (``bool_or`` + ``MAX``) instead of correlated
    subqueries so the work stays O(channelstream rows for this account)
    rather than O(channels * subqueries).
    """
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("""
            WITH agg AS (
                SELECT
                    cs.channel_id,
                    bool_or(s.is_catchup)  AS any_catchup,
                    -- Only catch-up streams contribute their archive depth:
                    -- a non-catchup stream may carry a stale catchup_days value.
                    MAX(s.catchup_days) FILTER (WHERE s.is_catchup) AS max_days
                FROM dispatcharr_channels_channelstream cs
                JOIN dispatcharr_channels_stream s ON s.id = cs.stream_id
                WHERE cs.channel_id IN (
                    SELECT DISTINCT cs2.channel_id
                    FROM dispatcharr_channels_channelstream cs2
                    JOIN dispatcharr_channels_stream s2 ON s2.id = cs2.stream_id
                    WHERE s2.m3u_account_id = %s
                )
                GROUP BY cs.channel_id
            )
            UPDATE dispatcharr_channels_channel c
            SET
                is_catchup   = COALESCE(agg.any_catchup, FALSE),
                catchup_days = COALESCE(agg.max_days, 0)
            FROM agg
            WHERE c.id = agg.channel_id
        """, [account_id])

        # Self-heal: reset channels still flagged as catch-up that no longer
        # have ANY catch-up stream. The CTE above only reaches channels that
        # still hold at least one stream from this account, so a channel whose
        # last stream was just removed (stale cleanup, manual unassignment)
        # falls outside its scope. The ChannelStream post_delete signal
        # normally resets those rows already — this pass guarantees the
        # invariant regardless of how the link rows disappeared (raw SQL,
        # signal-less bulk operations, historic staleness). Idempotent and
        # cheap: ``is_catchup`` is indexed and TRUE on a small minority of
        # channels.
        cur.execute("""
            UPDATE dispatcharr_channels_channel c
            SET is_catchup = FALSE, catchup_days = 0
            WHERE c.is_catchup = TRUE
              AND NOT EXISTS (
                  SELECT 1
                  FROM dispatcharr_channels_channelstream cs
                  JOIN dispatcharr_channels_stream s ON s.id = cs.stream_id
                  WHERE cs.channel_id = c.id AND s.is_catchup = TRUE
              )
        """)


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
        channels_failed = 0
        # Per-failure context for the completion notification. Each entry
        # carries a typed ``reason`` so the modal can group counts by
        # cause; the cap keeps the WebSocket payload bounded but is sized
        # generously to cover realistic multi-provider failure sets.
        # Full per-stream detail still goes to ``logger.warning`` for
        # power-user diagnostics regardless of the cap.
        failed_stream_details = []
        FAILURE_LOG_LIMIT = 1000

        # Group range reservations (start+end) are advisory and NOT seeded
        # here: two groups with overlapping ranges must cooperate, so only
        # actually-occupied numbers constrain assignment.
        # Hidden auto-created channels stay in the seed because the renumber
        # loop iterates current provider streams (which excludes hidden
        # ones); excluding them here would let sync reclaim their numbers.
        used_numbers = set(
            Channel.objects.exclude(
                auto_created=True,
                auto_created_by=account,
                hidden_from_output=False,
            ).values_list("channel_number", flat=True)
        )
        # Override pins are global reservations: effective_channel_number
        # uses the override, so the picker must treat those numbers as
        # taken or sync can produce duplicate effective channel numbers.
        from apps.channels.models import ChannelOverride

        used_numbers.update(
            ChannelOverride.objects.filter(
                channel_number__isnull=False
            ).values_list("channel_number", flat=True)
        )
        used_numbers.discard(None)

        for group_relation in auto_sync_groups:
            channel_group = group_relation.channel_group
            start_number = group_relation.auto_sync_channel_start or 1.0
            # Optional upper bound; _next_available_number returns None when
            # exhausted, which the per-stream loop converts to a failure.
            end_number = group_relation.auto_sync_channel_end

            # Get force_dummy_epg, group_override, and regex patterns from group custom_properties
            group_custom_props = {}
            force_dummy_epg = False  # Backward compatibility: legacy option to disable EPG
            override_group_id = None
            name_regex_pattern = None
            name_replace_pattern = None
            name_match_regex = None
            name_match_exclude_regex = None
            channel_profile_ids = None
            channel_sort_order = None
            channel_sort_reverse = False
            stream_profile_id = None
            custom_logo_id = None
            custom_epg_id = None  # New option: select specific EPG source (takes priority over force_dummy_epg)
            channel_numbering_mode = "fixed"  # Default mode
            channel_numbering_fallback = 1  # Default fallback for provider mode
            group_custom_props = ensure_custom_properties_dict(
                group_relation.custom_properties
            )
            if group_custom_props:
                force_dummy_epg = group_custom_props.get("force_dummy_epg", False)
                override_group_id = group_custom_props.get("group_override")
                name_regex_pattern = group_custom_props.get("name_regex_pattern")
                name_replace_pattern = group_custom_props.get(
                    "name_replace_pattern"
                )
                name_match_regex = group_custom_props.get("name_match_regex")
                name_match_exclude_regex = group_custom_props.get(
                    "name_match_exclude_regex"
                )
                channel_profile_ids = group_custom_props.get("channel_profile_ids")
                custom_epg_id = group_custom_props.get("custom_epg_id")
                channel_sort_order = group_custom_props.get("channel_sort_order")
                channel_sort_reverse = group_custom_props.get(
                    "channel_sort_reverse", False
                )
                stream_profile_id = group_custom_props.get("stream_profile_id")
                custom_logo_id = group_custom_props.get("custom_logo_id")
                channel_numbering_mode = group_custom_props.get("channel_numbering_mode", "fixed")
                channel_numbering_fallback = group_custom_props.get("channel_numbering_fallback", 1)

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
                f"Processing auto sync for group: {channel_group.name} (mode: {channel_numbering_mode}, start: {start_number})"
            )

            # Get all current streams in this group for this M3U account, filter out stale streams
            current_streams = Stream.objects.filter(
                m3u_account=account,
                channel_group=channel_group,
                last_seen__gte=scan_start_time,
            )

            # Filter streams in Python using the same `regex` module as the
            # preview API. This ensures auto-sync accepts the same patterns
            # the user tested in the frontend (e.g. `(?)` as a no-op inline
            # modifier), and avoids passing potentially incompatible syntax
            # to PostgreSQL's regex engine.
            streams_is_list = False
            if name_match_regex:
                try:
                    match_re = regex.compile(name_match_regex, regex.IGNORECASE)
                    current_streams = [s for s in current_streams if match_re.search(s.name)]
                    streams_is_list = True
                except regex.error as e:
                    logger.warning(
                        f"Invalid name_match_regex '{name_match_regex}' for group '{channel_group.name}': {e}. Skipping name filter."
                    )

            # Exclude regex runs after the include filter so the two
            # compose: include narrows, exclude removes from what's left.
            if name_match_exclude_regex:
                try:
                    exclude_re = regex.compile(name_match_exclude_regex, regex.IGNORECASE)
                    current_streams = [s for s in current_streams if not exclude_re.search(s.name)]
                    streams_is_list = True
                except regex.error as e:
                    logger.warning(
                        f"Invalid name_match_exclude_regex '{name_match_exclude_regex}' for group '{channel_group.name}': {e}. Skipping exclude filter."
                    )

            # --- APPLY CHANNEL SORT ORDER ---
            if channel_sort_order and channel_sort_order != "":
                if channel_sort_order == "name":
                    if not streams_is_list:
                        current_streams = list(current_streams)
                        streams_is_list = True
                    current_streams.sort(
                        key=lambda stream: natural_sort_key(stream.name),
                        reverse=channel_sort_reverse,
                    )
                elif channel_sort_order == "tvg_id":
                    if streams_is_list:
                        current_streams.sort(
                            key=lambda s: (s.tvg_id or ""),
                            reverse=channel_sort_reverse,
                        )
                    else:
                        order_prefix = "-" if channel_sort_reverse else ""
                        current_streams = current_streams.order_by(f"{order_prefix}tvg_id")
                elif channel_sort_order == "updated_at":
                    if streams_is_list:
                        current_streams.sort(
                            key=lambda s: (s.updated_at or ""),
                            reverse=channel_sort_reverse,
                        )
                    else:
                        order_prefix = "-" if channel_sort_reverse else ""
                        current_streams = current_streams.order_by(
                            f"{order_prefix}updated_at"
                        )
                else:
                    logger.warning(
                        f"Unknown channel_sort_order '{channel_sort_order}' for group '{channel_group.name}'. Using provider order."
                    )
                    if streams_is_list:
                        current_streams.sort(
                            key=lambda s: s.id,
                            reverse=channel_sort_reverse,
                        )
                    else:
                        order_prefix = "-" if channel_sort_reverse else ""
                        current_streams = current_streams.order_by(f"{order_prefix}id")
            else:
                # Provider order (default) - can still be reversed
                if streams_is_list:
                    current_streams.sort(
                        key=lambda s: s.id,
                        reverse=channel_sort_reverse,
                    )
                else:
                    order_prefix = "-" if channel_sort_reverse else ""
                    current_streams = current_streams.order_by(f"{order_prefix}id")

            # Scoped to this group so the loop below runs in O(group size).
            # Multi-stream channels are deduped by channel_id so every
            # stream_id maps to the same in-memory Channel instance and
            # post-loop bulk_update writes the merged state.
            existing_channel_map = {}
            existing_channels_by_id = {}
            existing_channel_streams = (
                ChannelStream.objects.filter(
                    channel__auto_created=True,
                    channel__auto_created_by=account,
                    stream__m3u_account=account,
                    stream__channel_group=channel_group,
                )
                .select_related("channel")
            )
            for cs in existing_channel_streams:
                if cs.stream_id and cs.channel_id:
                    canonical = existing_channels_by_id.setdefault(
                        cs.channel_id, cs.channel
                    )
                    existing_channel_map[cs.stream_id] = canonical

            # Track which streams we've processed
            processed_stream_ids = set()

            # Check if we have streams - handle both QuerySet and list cases
            has_streams = (
                len(current_streams) > 0
                if streams_is_list
                else current_streams.exists()
            )

            # Bulk pre-fetch collapses N+1 Logo/EPGData lookups into a
            # pair of in_bulk() calls.
            from apps.channels.models import Logo
            from apps.epg.models import EPGSource

            # Resolve the group's custom EPG source once.
            custom_epg_source = None
            custom_dummy_epg_data = None
            if custom_epg_id:
                try:
                    custom_epg_source = EPGSource.objects.get(id=custom_epg_id)
                    if custom_epg_source.source_type == "dummy":
                        custom_dummy_epg_data = (
                            EPGData.objects.filter(
                                epg_source=custom_epg_source
                            ).first()
                        )
                        if not custom_dummy_epg_data:
                            logger.warning(
                                f"No EPGData found for dummy EPG source "
                                f"{custom_epg_source.name} (ID: {custom_epg_id})"
                            )
                except EPGSource.DoesNotExist:
                    logger.warning(
                        f"Custom EPG source with ID {custom_epg_id} not found "
                        f"for group '{channel_group.name}', falling back to "
                        f"auto-match"
                    )

            # Resolve the group's custom logo once.
            custom_logo = None
            if custom_logo_id:
                try:
                    custom_logo = Logo.objects.get(id=custom_logo_id)
                except Logo.DoesNotExist:
                    logger.warning(
                        f"Custom logo with ID {custom_logo_id} not found for "
                        f"group '{channel_group.name}', falling back to stream "
                        f"logos"
                    )

            logo_cache_by_url = {}
            epg_cache_by_tvg_id = {}
            if has_streams:
                # Collect unique URLs / tvg_ids in one DB call each.
                stream_iter = (
                    current_streams
                    if streams_is_list
                    else list(current_streams.values("logo_url", "tvg_id"))
                )
                unique_logo_urls = {
                    s.get("logo_url") if isinstance(s, dict) else getattr(s, "logo_url", None)
                    for s in stream_iter
                }
                unique_logo_urls.discard(None)
                unique_logo_urls.discard("")
                if unique_logo_urls:
                    logo_cache_by_url = {
                        lg.url: lg
                        for lg in Logo.objects.filter(url__in=unique_logo_urls)
                    }

                unique_tvg_ids = {
                    s.get("tvg_id") if isinstance(s, dict) else getattr(s, "tvg_id", None)
                    for s in stream_iter
                }
                unique_tvg_ids.discard(None)
                unique_tvg_ids.discard("")
                # Skip the EPG cache when force_dummy_epg with no
                # custom source override; the resolver always returns None.
                want_epg_cache = unique_tvg_ids and (
                    not force_dummy_epg or custom_epg_id
                )
                if want_epg_cache:
                    # Scope to the group's pinned source so foreign-source
                    # tvg_id matches do not leak in.
                    epg_q = EPGData.objects.filter(tvg_id__in=unique_tvg_ids)
                    if (
                        custom_epg_source is not None
                        and custom_epg_source.source_type != "dummy"
                    ):
                        epg_q = epg_q.filter(epg_source=custom_epg_source)
                    epg_cache_by_tvg_id = {d.tvg_id: d for d in epg_q}

            def _resolve_logo_for_stream(stream):
                """Return a Logo for stream.logo_url, creating it once if needed."""
                url = getattr(stream, "logo_url", None)
                if not url:
                    return None
                cached = logo_cache_by_url.get(url)
                if cached is not None:
                    return cached
                created, _ = Logo.objects.get_or_create(
                    url=url,
                    defaults={"name": stream.name or stream.tvg_id or "Unknown"},
                )
                logo_cache_by_url[url] = created
                return created

            def _resolve_epg_for_stream(stream):
                """Return the EPGData row that should be assigned to this
                stream's channel. Encodes all four group-level EPG modes:

                  1. custom dummy source:           single shared EPGData
                  2. custom non-dummy source:       cache lookup, scoped to
                                                    that source
                  3. force_dummy_epg with no custom: None (clear EPG)
                  4. default auto-match:            cache lookup, any source

                The cache (epg_cache_by_tvg_id) is built once above with the
                correct scope so the per-stream lookup is a dict access.
                """
                if custom_epg_source is not None:
                    if custom_epg_source.source_type == "dummy":
                        return custom_dummy_epg_data
                    tvg_id = getattr(stream, "tvg_id", None)
                    if not tvg_id:
                        return None
                    return epg_cache_by_tvg_id.get(tvg_id)
                if force_dummy_epg:
                    return None
                tvg_id = getattr(stream, "tvg_id", None)
                if not tvg_id:
                    return None
                return epg_cache_by_tvg_id.get(tvg_id)

            if not has_streams:
                logger.debug(f"No streams found in group {channel_group.name}")
                # No streams left in the group: drop the visible auto
                # channels. Hidden channels are preserved so the hide
                # flag survives temporary provider drops (event/PPV).
                channels_to_delete = [
                    ch
                    for ch in existing_channel_map.values()
                    if not ch.hidden_from_output
                ]
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

            current_channel_number = start_number

            # Renumber existing channels to match sort order. Compact
            # mode skips this; the end-of-iteration pack is the source
            # of truth and would overwrite the renumber.
            compact_mode = bool(group_custom_props.get("compact_numbering"))
            channels_to_renumber = []
            temp_channel_number = start_number

            for stream in current_streams if not compact_mode else []:
                if stream.id in existing_channel_map:
                    channel = existing_channel_map[stream.id]

                    target_number = _pick_target_number(
                        channel_numbering_mode,
                        stream,
                        used_numbers,
                        temp_channel_number,
                        channel_numbering_fallback,
                        end_number=end_number,
                    )

                    # Range exhausted: leave the channel at its existing
                    # number. The renumber pass is sort-optimization only;
                    # no failure record needed.
                    if target_number is None:
                        # Preserve the channel's current number in used_numbers
                        if channel.channel_number is not None:
                            used_numbers.add(channel.channel_number)
                        continue

                    # Add this number to used_numbers so we don't reuse it in this batch
                    used_numbers.add(target_number)

                    if channel.channel_number != target_number:
                        channel.channel_number = target_number
                        channels_to_renumber.append(channel)
                        logger.debug(
                            f"Will renumber channel '{channel.name}' to {target_number}"
                        )

                    # Only increment temp_channel_number in fixed mode
                    if channel_numbering_mode == "fixed":
                        temp_channel_number += 1.0
                        if temp_channel_number % 1 != 0:  # Has decimal
                            temp_channel_number = int(temp_channel_number) + 1.0

            # Bulk update channel numbers if any need renumbering
            if channels_to_renumber:
                Channel.objects.bulk_update(
                    channels_to_renumber, ["channel_number"], batch_size=500
                )
                logger.info(
                    f"Renumbered {len(channels_to_renumber)} channels to maintain sort order"
                )

            # Range enforcement runs in fixed mode only: it is the one mode with
            # a user-set [start, end]. Provider numbers are authoritative and
            # next_available has no range, so their channels are never deleted
            # for falling outside start/end.
            #
            # Channels outside the range are deleted (hidden ones preserved);
            # the creation loop below re-adds the freed streams inside the range,
            # so the net effect is a renumber, not a failure. Runs first so the
            # freed slots are available.
            if end_number is not None and channel_numbering_mode == "fixed":
                overflow_delete_ids = []
                for stream_id, ch in list(existing_channel_map.items()):
                    if ch.hidden_from_output:
                        continue
                    num = ch.channel_number
                    if num is None:
                        continue
                    if num < start_number or num > end_number:
                        overflow_delete_ids.append(ch.id)
                        existing_channel_map.pop(stream_id, None)
                        used_numbers.discard(num)
                if overflow_delete_ids:
                    deleted = Channel.objects.filter(
                        id__in=overflow_delete_ids
                    ).delete()
                    removed_count = (
                        deleted[1].get("dispatcharr_channels.Channel", 0)
                        if isinstance(deleted, tuple) and len(deleted) > 1
                        else len(overflow_delete_ids)
                    )
                    channels_deleted += removed_count
                    logger.info(
                        f"Deleted {removed_count} channels outside the "
                        f"range {int(start_number)}-{int(end_number)} for "
                        f"group '{channel_group.name}'"
                    )

            # Reset channel number counter for processing new channels
            current_channel_number = start_number

            # Per-channel changes are buffered and bulk_update'd once after the
            # loop. update_fields is set explicitly so post_save signals only
            # fire for receivers whose tracked field actually changed.
            existing_dirty_channels = []
            existing_dirty_ids = set()
            existing_dirty_field_set = set()
            # Subset of channels whose epg_data actually changed in this
            # pass. Used by the dispatcher below to fire the EPG parse
            # task only for those, not for every channel in
            # existing_dirty_channels.
            epg_dirty_channel_ids = set()

            # New channels are buffered and bulk_create'd after the loop.
            # bulk_create skips post_save, so the EPG parse task is dispatched
            # once per unique epg_data_id below rather than per channel.
            # Pairs are (Channel(), Stream) so the post-loop step can attach
            # ChannelStream rows using the IDs Postgres returns.
            new_channels_pending = []

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
                        # Track only the fields that actually changed, so the
                        # eventual UPDATE writes one column per change instead
                        # of every column on every channel. The dirty list is
                        # accumulated and bulk_update'd after the loop -
                        # which avoids issuing an UPDATE per channel and
                        # avoids firing the EPG post_save signal on saves
                        # that didn't touch epg_data.
                        dirty_fields = []

                        if existing_channel.name != new_name:
                            existing_channel.name = new_name
                            dirty_fields.append("name")

                        if existing_channel.tvg_id != stream.tvg_id:
                            existing_channel.tvg_id = stream.tvg_id
                            dirty_fields.append("tvg_id")

                        if existing_channel.tvc_guide_stationid != tvc_guide_stationid:
                            existing_channel.tvc_guide_stationid = tvc_guide_stationid
                            dirty_fields.append("tvc_guide_stationid")

                        # The group override may direct sync to a different
                        # ChannelGroup than the one currently on the row.
                        if existing_channel.channel_group_id != target_group.id:
                            existing_channel.channel_group = target_group
                            dirty_fields.append("channel_group")

                        # Logo: custom group setting wins; otherwise stream logo
                        current_logo = (
                            custom_logo
                            if custom_logo_id and custom_logo is not None
                            else _resolve_logo_for_stream(stream)
                        )
                        current_logo_id = current_logo.id if current_logo else None
                        if existing_channel.logo_id != current_logo_id:
                            existing_channel.logo = current_logo
                            dirty_fields.append("logo")

                        # EPG: handled centrally by _resolve_epg_for_stream
                        current_epg_data = _resolve_epg_for_stream(stream)
                        current_epg_id = (
                            current_epg_data.id if current_epg_data else None
                        )
                        if existing_channel.epg_data_id != current_epg_id:
                            existing_channel.epg_data = current_epg_data
                            dirty_fields.append("epg_data")
                            if current_epg_id is not None:
                                epg_dirty_channel_ids.add(existing_channel.id)

                        # Stream profile: only set if group has one configured
                        if (
                            stream_profile_to_assign is not None
                            and existing_channel.stream_profile_id
                            != stream_profile_to_assign.id
                        ):
                            existing_channel.stream_profile = stream_profile_to_assign
                            dirty_fields.append("stream_profile")

                        if dirty_fields:
                            # Multi-stream channels appear once per stream;
                            # dedupe by id so bulk_update does not double-fire
                            # and channels_updated does not double-count.
                            if existing_channel.id not in existing_dirty_ids:
                                existing_dirty_channels.append(existing_channel)
                                existing_dirty_ids.add(existing_channel.id)
                                channels_updated += 1
                            existing_dirty_field_set.update(dirty_fields)

                    else:
                        # Range exhaustion is surfaced to the user via the
                        # completion notification, not swallowed.
                        target_number = _pick_target_number(
                            channel_numbering_mode,
                            stream,
                            used_numbers,
                            current_channel_number,
                            channel_numbering_fallback,
                            end_number=end_number,
                        )

                        if target_number is None:
                            channels_failed += 1
                            if len(failed_stream_details) < FAILURE_LOG_LIMIT:
                                failed_stream_details.append({
                                    "stream_name": stream.name,
                                    "stream_id": stream.id,
                                    "group": channel_group.name,
                                    "reason": "RANGE_EXHAUSTED",
                                    "error": _range_exhausted_error(
                                        channel_numbering_mode,
                                        start_number,
                                        end_number,
                                        channel_numbering_fallback,
                                    ),
                                })
                            processed_stream_ids.add(stream.id)
                            continue

                        # Add this number to used_numbers
                        used_numbers.add(target_number)

                        # Resolve every FK BEFORE the create call so the
                        # initial INSERT carries the complete row.
                        new_logo = (
                            custom_logo
                            if custom_logo_id and custom_logo is not None
                            else _resolve_logo_for_stream(stream)
                        )
                        new_epg_data = _resolve_epg_for_stream(stream)

                        new_channels_pending.append(
                            (
                                Channel(
                                    channel_number=target_number,
                                    name=new_name,
                                    tvg_id=stream.tvg_id,
                                    tvc_guide_stationid=tvc_guide_stationid,
                                    channel_group=target_group,
                                    user_level=0,
                                    auto_created=True,
                                    auto_created_by=account,
                                    logo=new_logo,
                                    epg_data=new_epg_data,
                                    stream_profile=stream_profile_to_assign,
                                ),
                                stream,
                            )
                        )

                    # Increment channel number for next iteration (only in fixed mode)
                    if channel_numbering_mode == "fixed":
                        current_channel_number += 1.0
                        if current_channel_number % 1 != 0:  # Has decimal
                            current_channel_number = int(current_channel_number) + 1.0

                except Exception as e:
                    logger.error(
                        f"Error processing auto channel for stream {stream.name}: {str(e)}"
                    )
                    channels_failed += 1
                    if len(failed_stream_details) < FAILURE_LOG_LIMIT:
                        failed_stream_details.append({
                            "stream_name": stream.name,
                            "stream_id": stream.id,
                            "group": channel_group.name,
                            "reason": _classify_sync_failure(e),
                            "error": str(e),
                        })
                    continue

            # Bulk-create channels, then dependent rows using the IDs
            # Postgres returns. bulk_create skips post_save, so the EPG
            # parse task is dispatched explicitly per-epg_data_id below
            # to avoid flooding Celery at scale.
            if new_channels_pending:
                channel_objs = [pair[0] for pair in new_channels_pending]
                streams_for_new = [pair[1] for pair in new_channels_pending]
                Channel.objects.bulk_create(channel_objs, batch_size=500)

                ChannelStream.objects.bulk_create(
                    [
                        ChannelStream(
                            channel_id=channel_objs[i].id,
                            stream_id=streams_for_new[i].id,
                            order=0,
                        )
                        for i in range(len(channel_objs))
                    ],
                    batch_size=500,
                )

                if profiles_to_assign:
                    ChannelProfileMembership.objects.bulk_create(
                        [
                            ChannelProfileMembership(
                                channel_id=ch.id,
                                channel_profile_id=profile.id,
                                enabled=True,
                            )
                            for ch in channel_objs
                            for profile in profiles_to_assign
                        ],
                        ignore_conflicts=True,
                        batch_size=500,
                    )

                channels_created += len(channel_objs)

                from apps.epg.tasks import dispatch_program_refresh_for_epg_ids

                unique_epg_ids = {
                    ch.epg_data_id for ch in channel_objs if ch.epg_data_id
                }
                parse_dispatched = dispatch_program_refresh_for_epg_ids(unique_epg_ids)

                logger.debug(
                    f"Bulk created {len(channel_objs)} channels in group "
                    f"'{channel_group.name}'; dispatched "
                    f"{parse_dispatched} EPG refresh task(s) for "
                    f"{len(unique_epg_ids)} unique EPG id(s)"
                )

            # bulk_update writes only the columns named in `fields` and
            # bypasses post_save, so the EPG refresh signal cannot fire here.
            # Dispatch one parse task per unique EPGData id when epg_data was
            # in the dirty set, mirroring the new-channel path above.
            if existing_dirty_channels:
                Channel.objects.bulk_update(
                    existing_dirty_channels,
                    fields=list(existing_dirty_field_set),
                    batch_size=500,
                )
                if epg_dirty_channel_ids:
                    from apps.epg.tasks import dispatch_program_refresh_for_epg_ids

                    unique_epg_ids = {
                        ch.epg_data_id
                        for ch in existing_dirty_channels
                        if ch.id in epg_dirty_channel_ids and ch.epg_data_id
                    }
                    dispatch_program_refresh_for_epg_ids(unique_epg_ids)
                logger.debug(
                    f"Bulk updated {len(existing_dirty_channels)} existing "
                    f"channels (fields: {sorted(existing_dirty_field_set)})"
                )

            # Reconcile ChannelProfileMembership in two writes: one
            # bulk_update for enable-flips, one bulk_create for missing
            # rows. Avoids a per-channel save loop.
            existing_channel_ids = [
                c.id for c in existing_channel_map.values()
            ]
            target_profile_ids = {p.id for p in profiles_to_assign}
            if existing_channel_ids:
                membership_rows = list(
                    ChannelProfileMembership.objects.filter(
                        channel_id__in=existing_channel_ids
                    ).only("id", "channel_id", "channel_profile_id", "enabled")
                )
                memberships_by_channel = {}
                for m in membership_rows:
                    memberships_by_channel.setdefault(m.channel_id, []).append(m)

                rows_to_flip = []
                rows_to_create = []
                for ch_id in existing_channel_ids:
                    rows = memberships_by_channel.get(ch_id, [])
                    have_for_target = set()
                    for m in rows:
                        if m.channel_profile_id in target_profile_ids:
                            have_for_target.add(m.channel_profile_id)
                            if not m.enabled:
                                m.enabled = True
                                rows_to_flip.append(m)
                        else:
                            if m.enabled:
                                m.enabled = False
                                rows_to_flip.append(m)
                    missing = target_profile_ids - have_for_target
                    for pid in missing:
                        rows_to_create.append(
                            ChannelProfileMembership(
                                channel_id=ch_id,
                                channel_profile_id=pid,
                                enabled=True,
                            )
                        )

                if rows_to_flip:
                    ChannelProfileMembership.objects.bulk_update(
                        rows_to_flip, ["enabled"], batch_size=500
                    )
                if rows_to_create:
                    ChannelProfileMembership.objects.bulk_create(
                        rows_to_create, ignore_conflicts=True, batch_size=500
                    )
                if rows_to_flip or rows_to_create:
                    logger.debug(
                        f"Reconciled memberships for "
                        f"{len(existing_channel_ids)} channels "
                        f"({len(rows_to_flip)} flipped, "
                        f"{len(rows_to_create)} created)"
                    )

            # Delete channels whose streams have all disappeared.
            # Hidden channels are preserved so event/PPV holds across
            # provider drops.
            channel_streams_in_group = {}
            for stream_id, channel in existing_channel_map.items():
                channel_streams_in_group.setdefault(channel.id, []).append(
                    (stream_id, channel)
                )
            channels_to_delete = []
            for ch_id, pairs in channel_streams_in_group.items():
                channel = pairs[0][1]
                if channel.hidden_from_output:
                    continue
                stream_ids = {sid for sid, _ in pairs}
                if not (stream_ids & processed_stream_ids):
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

            # Compact-mode pack: hidden channels release their number and
            # visible channels pack contiguously into [start, end]. Runs
            # after create/update/delete so the channel set is stable.
            if compact_mode:
                from apps.channels.compact_numbering import repack_group

                pack_result = repack_group(group_relation)
                if pack_result["failed"]:
                    channels_failed += pack_result["failed"]
                    if (
                        len(failed_stream_details) < FAILURE_LOG_LIMIT
                    ):
                        failed_stream_details.append(
                            {
                                "stream_name": None,
                                "stream_id": None,
                                "group": channel_group.name,
                                "reason": "RANGE_EXHAUSTED",
                                "error": (
                                    f"Compact pack: {pack_result['failed']} "
                                    f"visible channel(s) could not fit in range "
                                    f"{int(start_number)}"
                                    + (
                                        f"-{int(end_number)}"
                                        if end_number
                                        else "+"
                                    )
                                ),
                            }
                        )
                logger.debug(
                    f"Compact pack for group '{channel_group.name}': "
                    f"{pack_result['assigned']} assigned, "
                    f"{pack_result['released']} released, "
                    f"{pack_result['failed']} failed"
                )

        # Cleanup mode read from account.custom_properties.orphan_channel_cleanup:
        # "always" (default; key absent) removes every orphan auto channel;
        # "preserve_customized" keeps those with a ChannelOverride row;
        # "never" disables cleanup. Hidden channels are preserved across all
        # modes so event/PPV channels that come and go are not silently lost.
        cleanup_mode = ensure_custom_properties_dict(account.custom_properties).get(
            "orphan_channel_cleanup", "always"
        )
        if cleanup_mode != "never":
            orphaned_channels = Channel.objects.filter(
                auto_created=True,
                auto_created_by=account,
                hidden_from_output=False,
            ).exclude(
                id__in=ChannelStream.objects.filter(
                    stream__m3u_account=account,
                    stream__isnull=False,
                ).values_list("channel_id", flat=True)
            )
            if cleanup_mode == "preserve_customized":
                orphaned_channels = orphaned_channels.filter(override__isnull=True)

            _, per_model = orphaned_channels.delete()
            deleted_channels = per_model.get("dispatcharr_channels.Channel", 0)
            if deleted_channels:
                channels_deleted += deleted_channels
                logger.info(
                    f"Deleted {deleted_channels} orphaned auto channels with no valid streams (mode={cleanup_mode})"
                )

        logger.info(
            f"Auto channel sync complete for account {account.name}: "
            f"{channels_created} created, {channels_updated} updated, "
            f"{channels_deleted} deleted, {channels_failed} failed"
        )
        return {
            "status": "ok",
            "channels_created": channels_created,
            "channels_updated": channels_updated,
            "channels_deleted": channels_deleted,
            "channels_failed": channels_failed,
            "failed_stream_details": failed_stream_details,
        }

    except Exception as e:
        logger.error(f"Error in auto channel sync for account {account_id}: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "channels_created": 0,
            "channels_updated": 0,
            "channels_deleted": 0,
            "channels_failed": 0,
            "failed_stream_details": [],
        }


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

    from core.xtream_codes import normalize_server_url

    base_url = normalize_server_url(account.server_url)
    base_username = account.username
    base_password = account.password    # Build a complete URL with credentials (similar to how IPTV URLs are structured)
    # Format: http://server.com:port/live/username/password/1234.ts
    if base_url and base_username and base_password:
        clean_server_url = base_url.rstrip('/')

        # Build the complete URL with embedded credentials
        complete_url = f"{clean_server_url}/live/{base_username}/{base_password}/1234.ts"
        logger.debug(f"Built complete URL: {complete_url}")

        # Apply profile-specific transformations if profile is provided
        if profile and profile.search_pattern and profile.replace_pattern:
            try:
                # Handle backreferences: convert JS-style $<name> -> \g<name>, $1 -> \1
                # regex module accepts JS-style (?<name>...) named groups natively
                safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', profile.replace_pattern)
                safe_replace_pattern = regex.sub(r'\$(\d+)', r'\\\1', safe_replace_pattern)

                # Apply transformation to the complete URL
                transformed_complete_url = regex.sub(profile.search_pattern, safe_replace_pattern, complete_url)
                logger.info(f"Transformed complete URL: {complete_url} -> {transformed_complete_url}")

                # Extract components from the transformed URL
                # Pattern: http://server.com:port/live/username/password/1234.ts
                parsed_url = urllib.parse.urlparse(transformed_complete_url)
                path_parts = [part for part in parsed_url.path.split('/') if part]

                if len(path_parts) >= 4 and path_parts[-1] == '1234.ts':
                    # Extract username and password from the known structure:
                    # .../{live}/{username}/{password}/1234.ts
                    # Using negative indices so sub-paths in the server URL don't shift extraction
                    transformed_username = path_parts[-3]
                    transformed_password = path_parts[-2]

                    # Rebuild server URL: preserve any sub-path that precedes
                    # /live/username/password/1234.ts (path_parts[:-4]).
                    base_path_parts = path_parts[:-4]
                    base_path = ('/' + '/'.join(base_path_parts)) if base_path_parts else ''
                    transformed_url = f"{parsed_url.scheme}://{parsed_url.netloc}{base_path}"

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
                        if not isinstance(profile_account_info, dict):
                            raise TypeError(
                                f"Unexpected account info type: {type(profile_account_info).__name__}"
                            )

                        # Merge with existing custom_properties if they exist
                        profile.custom_properties = {
                            **ensure_custom_properties_dict(
                                profile.custom_properties
                            ),
                            **profile_account_info,
                        }
                        profile.save(update_fields=['custom_properties', 'exp_date'])

                        profiles_updated += 1
                        logger.info(f"Updated account information for profile '{profile.name}' ({profiles_updated}/{profiles.count()})")
                    else:
                        profiles_failed += 1
                        logger.warning(f"Failed to authenticate profile '{profile.name}' with transformed credentials")

            except Exception as profile_error:
                profiles_failed += 1
                logger.error(f"Failed to update account information for profile '{profile.name}': {str(profile_error)}")
                _release_task_db_connection()
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
    finally:
        _release_task_db_connection()


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
        profile.custom_properties = {
            **ensure_custom_properties_dict(profile.custom_properties),
            **account_info,
        }
        profile.save(update_fields=['custom_properties', 'exp_date'])

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
@shared_task(time_limit=3600, soft_time_limit=3500)
def refresh_single_m3u_account(account_id):
    """Splits M3U processing into chunks and dispatches them as parallel tasks."""
    if not acquire_task_lock("refresh_single_m3u_account", account_id):
        return f"Task already running for account_id={account_id}."

    # Keep the lock alive while this long-running task is working.
    # Without renewal, the 300s lock TTL can expire during large
    # downloads/parses, allowing duplicate tasks to start.
    lock_renewer = TaskLockRenewer("refresh_single_m3u_account", account_id)
    lock_renewer.start()

    _release_task_db_connection()

    try:
        return _refresh_single_m3u_account_impl(account_id)
    except Exception as e:
        logger.error(
            f"refresh_single_m3u_account failed for account {account_id}: {e}",
            exc_info=True,
        )
        _set_m3u_account_status(
            account_id,
            M3UAccount.Status.ERROR,
            f"Error processing M3U: {str(e)[:500]}",
            notify_error=True,
            ws_error=str(e)[:500],
        )
    finally:
        _ensure_m3u_refresh_terminal_status(account_id)
        _release_task_db_connection()
        lock_renewer.stop()
        release_task_lock("refresh_single_m3u_account", account_id)


def _refresh_single_m3u_account_impl(account_id):
    """Implementation of M3U account refresh with guaranteed memory cleanup."""
    # Record start time
    refresh_start_timestamp = timezone.now()  # For the cleanup function
    start_time = time.time()  # For tracking elapsed time as float
    streams_created = 0
    streams_updated = 0
    streams_deleted = 0

    try:
        account = _get_active_m3u_account(account_id)
        if not account.is_active:
            logger.debug(f"Account {account_id} is not active, skipping.")
            return

        # Set status to fetching and replace stale completion messages.
        _set_m3u_account_status(
            account_id,
            M3UAccount.Status.FETCHING,
            "Refresh in progress...",
        )
        account = _get_active_m3u_account(account_id)

        filters = list(account.filters.all())

        # Check if VOD is enabled for this account
        vod_enabled = ensure_custom_properties_dict(account.custom_properties).get(
            'enable_vod', False
        )

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
            del data  # Free top-level dict; extinf_data/groups retain their references
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
            result = refresh_m3u_groups(account_id, full_refresh=True, scan_start_time=refresh_start_timestamp)
            logger.trace(f"refresh_m3u_groups result: {result}")

            # Check for completely empty result or missing groups
            if not result or result[1] is None:
                logger.error(
                    f"Failed to refresh M3U groups for account {account_id}: {result}"
                )
                error_msg = (
                    "Failed to refresh M3U groups - download failed or other error"
                )
                _set_m3u_account_status(
                    account_id,
                    M3UAccount.Status.ERROR,
                    error_msg,
                    notify_error=True,
                    ws_error=error_msg,
                )
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
                error_msg = "No streams found in M3U source"
                _set_m3u_account_status(
                    account_id,
                    M3UAccount.Status.ERROR,
                    error_msg,
                    notify_error=True,
                    ws_error=error_msg,
                )
        except Exception as e:
            logger.error(f"Exception in refresh_m3u_groups: {str(e)}", exc_info=True)
            error_msg = f"Error refreshing M3U groups: {str(e)[:500]}"
            _set_m3u_account_status(
                account_id,
                M3UAccount.Status.ERROR,
                error_msg,
                notify_error=True,
                ws_error=error_msg,
            )
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
        error_msg = "No data available for processing"
        _set_m3u_account_status(
            account_id,
            M3UAccount.Status.ERROR,
            error_msg,
            notify_error=True,
            ws_error=error_msg,
        )
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
                    finally:
                        batches[batch_idx] = None

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
                custom_props = ensure_custom_properties_dict(rel.custom_properties)
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

                # Free the original list; batches hold independent sliced copies
                del all_xc_streams

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
                        finally:
                            batches[batch_idx] = None

                logger.info(f"XC thread-based processing completed for account {account_id}")

        # Ensure all database transactions are committed before cleanup
        logger.info(
            f"All thread processing completed, ensuring DB transactions are committed before cleanup"
        )
        # Force a simple DB query to ensure connection sync
        Stream.objects.filter(
            id=-1
        ).exists()  # This will never find anything but ensures DB sync

        # Mark streams that weren't seen in this refresh as stale (pending deletion)
        stale_stream_count = Stream.objects.filter(
            m3u_account=account,
            last_seen__lt=refresh_start_timestamp
        ).update(is_stale=True)
        logger.info(f"Marked {stale_stream_count} streams as stale for account {account_id}")

        # Mark group relationships that weren't seen in this refresh as stale (pending deletion)
        stale_group_count = ChannelGroupM3UAccount.objects.filter(
            m3u_account=account,
            last_seen__lt=refresh_start_timestamp
        ).update(is_stale=True)
        logger.info(f"Marked {stale_group_count} group relationships as stale for account {account_id}")

        # Now run cleanup
        streams_deleted = cleanup_streams(account_id, refresh_start_timestamp)

        # Cleanup stale group relationships (follows same retention policy as streams)
        cleanup_stale_group_relationships(account, refresh_start_timestamp)

        # Run auto channel sync after successful refresh
        auto_sync_message = ""
        auto_sync_result = {}
        try:
            auto_sync_result = sync_auto_channels(
                account_id, scan_start_time=str(refresh_start_timestamp)
            ) or {}
            logger.info(
                f"Auto channel sync result for account {account_id}: {auto_sync_result}"
            )
            if auto_sync_result.get("status") == "ok":
                created = auto_sync_result.get("channels_created", 0)
                updated = auto_sync_result.get("channels_updated", 0)
                deleted = auto_sync_result.get("channels_deleted", 0)
                failed = auto_sync_result.get("channels_failed", 0)
                if created or updated or deleted or failed:
                    parts = []
                    if created:
                        parts.append(f"{created} channel(s) created")
                    if updated:
                        parts.append(f"{updated} updated")
                    if deleted:
                        parts.append(f"{deleted} deleted")
                    if failed:
                        parts.append(f"{failed} failed")
                    auto_sync_message = f" Auto-sync: {', '.join(parts)}."
            elif auto_sync_result.get("status") == "error":
                auto_sync_message = (
                    f" Auto-sync error: {auto_sync_result.get('error', 'unknown')}."
                )
        except Exception as e:
            logger.error(
                f"Error running auto channel sync for account {account_id}: {str(e)}"
            )

        # Roll up catch-up fields from streams to channels.  Runs after
        # sync_auto_channels so new and existing channels both reflect the
        # current tv_archive flags from the just-completed stream refresh.
        # Covers manual channels too, so it lives here rather than inside
        # sync_auto_channels which only manages auto-created channels.
        try:
            rollup_channel_catchup_fields(account_id)
            logger.debug(f"Catch-up field rollup complete for account {account_id}")
        except Exception as e:
            logger.error(f"Error rolling up catch-up fields for account {account_id}: {str(e)}")

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
            # Structured auto-sync counts so the frontend can render a
            # warning card when anything failed, without parsing the
            # free-text last_message.
            channels_created=auto_sync_result.get("channels_created", 0),
            channels_updated=auto_sync_result.get("channels_updated", 0),
            channels_deleted=auto_sync_result.get("channels_deleted", 0),
            channels_failed=auto_sync_result.get("channels_failed", 0),
            failed_stream_details=auto_sync_result.get("failed_stream_details", []),
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
        raise
    finally:
        # Free large data structures regardless of success or failure
        if 'existing_groups' in locals():
            del existing_groups
        if 'extinf_data' in locals():
            del extinf_data
        if 'groups' in locals():
            del groups
        if 'batches' in locals():
            del batches
        if 'all_xc_streams' in locals():
            del all_xc_streams
        if 'data' in locals():
            del data
        if 'filtered_groups' in locals():
            del filtered_groups
        if 'channel_group_relationships' in locals():
            del channel_group_relationships

        # Remove cache file after processing (success or failure)
        cache_path = os.path.join(m3u_dir, f"{account_id}.json")
        try:
            os.remove(cache_path)
        except OSError:
            pass

        _release_task_db_connection()

    return f"Dispatched jobs complete."


def send_m3u_update(account_id, action, progress, **kwargs):
    # Start with the base data dictionary
    data = {
        "progress": progress,
        "type": "m3u_refresh",
        "account": account_id,
        "action": action,
    }

    # Only fetch the account when we actually need to fill in missing fields.
    # Many callers in tight loops already pass status/message; skip the DB hit then.
    if "status" not in kwargs or "message" not in kwargs:
        try:
            account = M3UAccount.objects.only("status", "last_message").get(id=account_id)
            if "status" not in kwargs:
                data["status"] = account.status
            if "message" not in kwargs and account.last_message:
                data["message"] = account.last_message
        except Exception:
            pass

    # Add the additional key-value pairs from kwargs
    data.update(kwargs)
    send_websocket_update("updates", "update", data, collect_garbage=False)

    # Explicitly clear data reference to help garbage collection
    data = None


def evaluate_profile_expiration_notification(profile):
    """
    Evaluate a single M3UAccountProfile's expiration date and create, update,
    or delete the corresponding SystemNotification accordingly.

    Returns the notification key that should remain active (warning or expired),
    or None if the profile is not expiring soon and any stale notifications were removed.
    This return value is used by the bulk task to track active keys for stale cleanup.
    """
    from core.models import SystemNotification
    from core.utils import send_websocket_notification, send_notification_dismissed

    exp = profile.exp_date
    if not exp:
        return None

    now = timezone.now()
    warning_threshold = now + timezone.timedelta(days=7)
    warning_key = f"xc-exp-warning-{profile.id}"
    expired_key = f"xc-exp-expired-{profile.id}"

    if exp <= now:
        # Already expired — delete warning, create/update expired notification
        deleted_warning = list(
            SystemNotification.objects.filter(notification_key=warning_key)
            .values_list("notification_key", flat=True)
        )
        SystemNotification.objects.filter(notification_key=warning_key).delete()
        for key in deleted_warning:
            send_notification_dismissed(key)

        notification, created = SystemNotification.objects.update_or_create(
            notification_key=expired_key,
            defaults={
                "notification_type": SystemNotification.NotificationType.WARNING,
                "priority": SystemNotification.Priority.HIGH,
                "title": f"Account Expired: {profile.name}",
                "message": (
                    f'Profile "{profile.name}" on M3U account '
                    f'"{profile.m3u_account.name}" has expired '
                    f"(expired {exp.strftime('%Y-%m-%d %H:%M UTC')})."
                ),
                "action_data": {
                    "profile_id": profile.id,
                    "account_id": profile.m3u_account.id,
                    "account_name": profile.m3u_account.name,
                    "profile_name": profile.name,
                    "exp_date": exp.isoformat(),
                },
                "is_active": True,
                "admin_only": True,
            },
        )
        send_websocket_notification(notification)
        return expired_key

    elif exp <= warning_threshold:
        # Expiring within 7 days — delete expired notification, create/update warning
        deleted_expired = list(
            SystemNotification.objects.filter(notification_key=expired_key)
            .values_list("notification_key", flat=True)
        )
        SystemNotification.objects.filter(notification_key=expired_key).delete()
        for key in deleted_expired:
            send_notification_dismissed(key)

        days_left = (exp - now).days
        if days_left == 0:
            expires_in_str = "today"
        elif days_left == 1:
            expires_in_str = "in 1 day"
        else:
            expires_in_str = f"in {days_left} days"

        notification, created = SystemNotification.objects.update_or_create(
            notification_key=warning_key,
            defaults={
                "notification_type": SystemNotification.NotificationType.WARNING,
                "priority": SystemNotification.Priority.NORMAL,
                "title": f"Account Expiring: {profile.name}",
                "message": (
                    f'Profile "{profile.name}" on M3U account '
                    f'"{profile.m3u_account.name}" expires {expires_in_str} '
                    f"(expires {exp.strftime('%Y-%m-%d %H:%M UTC')})."
                ),
                "action_data": {
                    "profile_id": profile.id,
                    "account_id": profile.m3u_account.id,
                    "account_name": profile.m3u_account.name,
                    "profile_name": profile.name,
                    "exp_date": exp.isoformat(),
                },
                "is_active": True,
                "admin_only": True,
            },
        )
        send_websocket_notification(notification)
        return warning_key

    else:
        # Not expiring soon — delete any stale notifications
        deleted_keys = list(
            SystemNotification.objects.filter(
                notification_key__in=[warning_key, expired_key]
            ).values_list("notification_key", flat=True)
        )
        SystemNotification.objects.filter(
            notification_key__in=[warning_key, expired_key]
        ).delete()
        for key in deleted_keys:
            send_notification_dismissed(key)
        return None


@shared_task
def check_account_expirations():
    """
    Daily task: check all account profiles for upcoming expirations.
    Creates/updates SystemNotifications for profiles expiring within 7 days.
    Uses separate notification keys for warning vs expired so users can
    dismiss the 7-day warning and still receive the expired notification.
    """
    from apps.m3u.models import M3UAccountProfile
    from core.models import SystemNotification
    from core.utils import send_notification_dismissed

    # Find all active profiles with an exp_date that is set
    expiring_profiles = (
        M3UAccountProfile.objects.filter(
            m3u_account__is_active=True,
            is_active=True,
            exp_date__isnull=False,
        )
        .select_related("m3u_account")
    )

    active_notification_keys = set()

    for profile in expiring_profiles:
        active_key = evaluate_profile_expiration_notification(profile)
        if active_key:
            active_notification_keys.add(active_key)

    # Delete stale notifications for profiles whose expiration was extended
    stale = SystemNotification.objects.filter(
        is_active=True,
    ).filter(
        models.Q(notification_key__startswith="xc-exp-warning-") |
        models.Q(notification_key__startswith="xc-exp-expired-")
    ).exclude(notification_key__in=active_notification_keys)
    stale_keys = list(stale.values_list("notification_key", flat=True))
    stale.delete()
    for key in stale_keys:
        send_notification_dismissed(key)

    logger.info(
        f"Account expiration check complete: {len(active_notification_keys)} active notifications"
    )
