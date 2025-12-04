# apps/epg/tasks.py

import logging
import gzip
import os
import uuid
import requests
import time  # Add import for tracking download progress
from datetime import datetime, timedelta, timezone as dt_timezone
import gc  # Add garbage collection module
import json
from lxml import etree  # Using lxml exclusively
import psutil  # Add import for memory tracking
import zipfile

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.channels.models import Channel
from core.models import UserAgent, CoreSettings

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import EPGSource, EPGData, ProgramData
from core.utils import acquire_task_lock, release_task_lock, send_websocket_update, cleanup_memory, log_system_event

logger = logging.getLogger(__name__)


def validate_icon_url_fast(icon_url, max_length=None):
    """
    Fast validation for icon URLs during parsing.
    Returns None if URL is too long, original URL otherwise.
    If max_length is None, gets it dynamically from the EPGData model field.
    """
    if max_length is None:
        # Get max_length dynamically from the model field
        max_length = EPGData._meta.get_field('icon_url').max_length

    if icon_url and len(icon_url) > max_length:
        logger.warning(f"Icon URL too long ({len(icon_url)} > {max_length}), skipping: {icon_url[:100]}...")
        return None
    return icon_url


MAX_EXTRACT_CHUNK_SIZE = 65536 # 64kb (base2)


def send_epg_update(source_id, action, progress, **kwargs):
    """Send WebSocket update about EPG download/parsing progress"""
    # Start with the base data dictionary
    data = {
        "progress": progress,
        "type": "epg_refresh",
        "source": source_id,
        "action": action,
    }

    # Add the additional key-value pairs from kwargs
    data.update(kwargs)

    # Use the standardized update function with garbage collection for program parsing
    # This is a high-frequency operation that needs more aggressive memory management
    collect_garbage = action == "parsing_programs" and progress % 10 == 0
    send_websocket_update('updates', 'update', data, collect_garbage=collect_garbage)

    # Explicitly clear references
    data = None

    # For high-frequency parsing, occasionally force additional garbage collection
    # to prevent memory buildup
    if action == "parsing_programs" and progress % 50 == 0:
        gc.collect()


def delete_epg_refresh_task_by_id(epg_id):
    """
    Delete the periodic task associated with an EPG source ID.
    Can be called directly or from the post_delete signal.
    Returns True if a task was found and deleted, False otherwise.
    """
    try:
        task = None
        task_name = f"epg_source-refresh-{epg_id}"

        # Look for task by name
        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule
            task = PeriodicTask.objects.get(name=task_name)
            logger.info(f"Found task by name: {task.id} for EPGSource {epg_id}")
        except PeriodicTask.DoesNotExist:
            logger.warning(f"No PeriodicTask found with name {task_name}")
            return False

        # Now delete the task and its interval
        if task:
            # Store interval info before deleting the task
            interval_id = None
            if hasattr(task, 'interval') and task.interval:
                interval_id = task.interval.id

                # Count how many TOTAL tasks use this interval (including this one)
                tasks_with_same_interval = PeriodicTask.objects.filter(interval_id=interval_id).count()
                logger.info(f"Interval {interval_id} is used by {tasks_with_same_interval} tasks total")

            # Delete the task first
            task_id = task.id
            task.delete()
            logger.info(f"Successfully deleted periodic task {task_id}")

            # Now check if we should delete the interval
            # We only delete if it was the ONLY task using this interval
            if interval_id and tasks_with_same_interval == 1:
                try:
                    interval = IntervalSchedule.objects.get(id=interval_id)
                    logger.info(f"Deleting interval schedule {interval_id} (not shared with other tasks)")
                    interval.delete()
                    logger.info(f"Successfully deleted interval {interval_id}")
                except IntervalSchedule.DoesNotExist:
                    logger.warning(f"Interval {interval_id} no longer exists")
            elif interval_id:
                logger.info(f"Not deleting interval {interval_id} as it's shared with {tasks_with_same_interval-1} other tasks")

            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting periodic task for EPGSource {epg_id}: {str(e)}", exc_info=True)
        return False


@shared_task
def refresh_all_epg_data():
    logger.info("Starting refresh_epg_data task.")
    # Exclude dummy EPG sources from refresh - they don't need refreshing
    active_sources = EPGSource.objects.filter(is_active=True).exclude(source_type='dummy')
    logger.debug(f"Found {active_sources.count()} active EPGSource(s) (excluding dummy EPGs).")

    for source in active_sources:
        refresh_epg_data(source.id)
        # Force garbage collection between sources
        gc.collect()

    logger.info("Finished refresh_epg_data task.")
    return "EPG data refreshed."


@shared_task
def refresh_epg_data(source_id):
    if not acquire_task_lock('refresh_epg_data', source_id):
        logger.debug(f"EPG refresh for {source_id} already running")
        return

    source = None
    try:
        # Try to get the EPG source
        try:
            source = EPGSource.objects.get(id=source_id)
        except EPGSource.DoesNotExist:
            # The EPG source doesn't exist, so delete the periodic task if it exists
            logger.warning(f"EPG source with ID {source_id} not found, but task was triggered. Cleaning up orphaned task.")

            # Call the shared function to delete the task
            if delete_epg_refresh_task_by_id(source_id):
                logger.info(f"Successfully cleaned up orphaned task for EPG source {source_id}")
            else:
                logger.info(f"No orphaned task found for EPG source {source_id}")

            # Release the lock and exit
            release_task_lock('refresh_epg_data', source_id)
            # Force garbage collection before exit
            gc.collect()
            return f"EPG source {source_id} does not exist, task cleaned up"

        # The source exists but is not active, just skip processing
        if not source.is_active:
            logger.info(f"EPG source {source_id} is not active. Skipping.")
            release_task_lock('refresh_epg_data', source_id)
            # Force garbage collection before exit
            gc.collect()
            return

        # Skip refresh for dummy EPG sources - they don't need refreshing
        if source.source_type == 'dummy':
            logger.info(f"Skipping refresh for dummy EPG source {source.name} (ID: {source_id})")
            release_task_lock('refresh_epg_data', source_id)
            gc.collect()
            return

        # Continue with the normal processing...
        logger.info(f"Processing EPGSource: {source.name} (type: {source.source_type})")
        if source.source_type == 'xmltv':
            fetch_success = fetch_xmltv(source)
            if not fetch_success:
                logger.error(f"Failed to fetch XMLTV for source {source.name}")
                release_task_lock('refresh_epg_data', source_id)
                # Force garbage collection before exit
                gc.collect()
                return

            parse_channels_success = parse_channels_only(source)
            if not parse_channels_success:
                logger.error(f"Failed to parse channels for source {source.name}")
                release_task_lock('refresh_epg_data', source_id)
                # Force garbage collection before exit
                gc.collect()
                return

            parse_programs_for_source(source)

        elif source.source_type == 'schedules_direct':
            fetch_schedules_direct(source)

        source.save(update_fields=['updated_at'])
        # After successful EPG refresh, evaluate DVR series rules to schedule new episodes
        try:
            from apps.channels.tasks import evaluate_series_rules
            evaluate_series_rules.delay()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error in refresh_epg_data for source {source_id}: {e}", exc_info=True)
        try:
            if source:
                source.status = 'error'
                source.last_message = f"Error refreshing EPG data: {str(e)}"
                source.save(update_fields=['status', 'last_message'])
                send_epg_update(source_id, "refresh", 100, status="error", error=str(e))
        except Exception as inner_e:
            logger.error(f"Error updating source status: {inner_e}")
    finally:
        # Clear references to ensure proper garbage collection
        source = None
        # Force garbage collection before releasing the lock
        gc.collect()
        release_task_lock('refresh_epg_data', source_id)


def fetch_xmltv(source):
    # Handle cases with local file but no URL
    if not source.url and source.file_path and os.path.exists(source.file_path):
        logger.info(f"Using existing local file for EPG source: {source.name} at {source.file_path}")

        # Check if the existing file is compressed and we need to extract it
        if source.file_path.endswith(('.gz', '.zip')) and not source.file_path.endswith('.xml'):
            try:
                # Define the path for the extracted file in the cache directory
                cache_dir = os.path.join(settings.MEDIA_ROOT, "cached_epg")
                os.makedirs(cache_dir, exist_ok=True)
                xml_path = os.path.join(cache_dir, f"{source.id}.xml")

                # Extract to the cache location keeping the original
                extracted_path = extract_compressed_file(source.file_path, xml_path, delete_original=False)

                if extracted_path:
                    logger.info(f"Extracted mapped compressed file to: {extracted_path}")
                    # Update to use extracted_file_path instead of changing file_path
                    source.extracted_file_path = extracted_path
                    source.save(update_fields=['extracted_file_path'])
                else:
                    logger.error(f"Failed to extract mapped compressed file. Using original file: {source.file_path}")
            except Exception as e:
                logger.error(f"Failed to extract existing compressed file: {e}")
                # Continue with the original file if extraction fails

        # Set the status to success in the database
        source.status = 'success'
        source.save(update_fields=['status'])

        # Send a download complete notification
        send_epg_update(source.id, "downloading", 100, status="success")

        # Return True to indicate successful fetch, processing will continue with parse_channels_only
        return True

    # Handle cases where no URL is provided and no valid file path exists
    if not source.url:
        # Update source status for missing URL
        source.status = 'error'
        source.last_message = "No URL provided and no valid local file exists"
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "downloading", 100, status="error", error="No URL provided and no valid local file exists")
        return False

    logger.info(f"Fetching XMLTV data from source: {source.name}")
    try:
        # Get default user agent from settings
        default_user_agent_setting = CoreSettings.objects.filter(key='default-user-agent').first()
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0"  # Fallback default
        if default_user_agent_setting and default_user_agent_setting.value:
            try:
                user_agent_obj = UserAgent.objects.filter(id=int(default_user_agent_setting.value)).first()
                if user_agent_obj and user_agent_obj.user_agent:
                    user_agent = user_agent_obj.user_agent
                    logger.debug(f"Using default user agent: {user_agent}")
            except (ValueError, Exception) as e:
                logger.warning(f"Error retrieving default user agent, using fallback: {e}")

        headers = {
            'User-Agent': user_agent
        }

        # Update status to fetching before starting download
        source.status = 'fetching'
        source.save(update_fields=['status'])

        # Send initial download notification
        send_epg_update(source.id, "downloading", 0)

        # Use streaming response to track download progress
        with requests.get(source.url, headers=headers, stream=True, timeout=60) as response:
            # Handle 404 specifically
            if response.status_code == 404:
                logger.error(f"EPG URL not found (404): {source.url}")
                # Update status to error in the database
                source.status = 'error'
                source.last_message = f"EPG source '{source.name}' returned 404 error - will retry on next scheduled run"
                source.save(update_fields=['status', 'last_message'])

                # Notify users through the WebSocket about the EPG fetch failure
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    'updates',
                    {
                        'type': 'update',
                        'data': {
                            "success": False,
                            "type": "epg_fetch_error",
                            "source_id": source.id,
                            "source_name": source.name,
                            "error_code": 404,
                            "message": f"EPG source '{source.name}' returned 404 error - will retry on next scheduled run"
                        }
                    }
                )
                # Ensure we update the download progress to 100 with error status
                send_epg_update(source.id, "downloading", 100, status="error", error="URL not found (404)")
                return False

            # For all other error status codes
            if response.status_code >= 400:
                error_message = f"HTTP error {response.status_code}"
                user_message = f"EPG source '{source.name}' encountered HTTP error {response.status_code}"

                # Update status to error in the database
                source.status = 'error'
                source.last_message = user_message
                source.save(update_fields=['status', 'last_message'])

                # Notify users through the WebSocket
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    'updates',
                    {
                        'type': 'update',
                        'data': {
                            "success": False,
                            "type": "epg_fetch_error",
                            "source_id": source.id,
                            "source_name": source.name,
                            "error_code": response.status_code,
                            "message": user_message
                        }
                    }
                )
                # Update download progress
                send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
                return False

            response.raise_for_status()
            logger.debug("XMLTV data fetched successfully.")

            # Define base paths for consistent file naming
            cache_dir = os.path.join(settings.MEDIA_ROOT, "cached_epg")
            os.makedirs(cache_dir, exist_ok=True)

            # Create temporary download file with .tmp extension
            temp_download_path = os.path.join(cache_dir, f"{source.id}.tmp")

            # Check if we have content length for progress tracking
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_update_time = start_time
            update_interval = 0.5  # Only update every 0.5 seconds

            # Download to temporary file
            with open(temp_download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=16384):  # Increased chunk size for better performance
                    if chunk:
                        f.write(chunk)

                        downloaded += len(chunk)
                        elapsed_time = time.time() - start_time

                        # Calculate download speed in KB/s
                        speed = downloaded / elapsed_time / 1024 if elapsed_time > 0 else 0

                        # Calculate progress percentage
                        if total_size and total_size > 0:
                            progress = min(100, int((downloaded / total_size) * 100))
                        else:
                            # If no content length header, estimate progress
                            progress = min(95, int((downloaded / (10 * 1024 * 1024)) * 100))  # Assume 10MB if unknown

                        # Time remaining (in seconds)
                        time_remaining = (total_size - downloaded) / (speed * 1024) if speed > 0 and total_size > 0 else 0

                        # Only send updates at specified intervals to avoid flooding
                        current_time = time.time()
                        if current_time - last_update_time >= update_interval and progress > 0:
                            last_update_time = current_time
                            send_epg_update(
                                source.id,
                                "downloading",
                                progress,
                                speed=round(speed, 2),
                                elapsed_time=round(elapsed_time, 1),
                                time_remaining=round(time_remaining, 1),
                                downloaded=f"{downloaded / (1024 * 1024):.2f} MB"
                            )

                        # Explicitly delete the chunk to free memory immediately
                        del chunk

            # Send completion notification
            send_epg_update(source.id, "downloading", 100)

            # Determine the appropriate file extension based on content detection
            with open(temp_download_path, 'rb') as f:
                content_sample = f.read(1024)  # Just need the first 1KB to detect format

            # Use our helper function to detect the format
            format_type, is_compressed, file_extension = detect_file_format(
                file_path=source.url,  # Original URL as a hint
                content=content_sample  # Actual file content for detection
            )

            logger.debug(f"File format detection results: type={format_type}, compressed={is_compressed}, extension={file_extension}")

            # Ensure consistent final paths
            compressed_path = os.path.join(cache_dir, f"{source.id}{file_extension}" if is_compressed else f"{source.id}.compressed")
            xml_path = os.path.join(cache_dir, f"{source.id}.xml")

            # Clean up old files before saving new ones
            if os.path.exists(compressed_path):
                try:
                    os.remove(compressed_path)
                    logger.debug(f"Removed old compressed file: {compressed_path}")
                except OSError as e:
                    logger.warning(f"Failed to remove old compressed file: {e}")

            if os.path.exists(xml_path):
                try:
                    os.remove(xml_path)
                    logger.debug(f"Removed old XML file: {xml_path}")
                except OSError as e:
                    logger.warning(f"Failed to remove old XML file: {e}")

            # Rename the temp file to appropriate final path
            if is_compressed:
                try:
                    os.rename(temp_download_path, compressed_path)
                    logger.debug(f"Renamed temp file to compressed file: {compressed_path}")
                    current_file_path = compressed_path
                except OSError as e:
                    logger.error(f"Failed to rename temp file to compressed file: {e}")
                    current_file_path = temp_download_path  # Fall back to using temp file
            else:
                try:
                    os.rename(temp_download_path, xml_path)
                    logger.debug(f"Renamed temp file to XML file: {xml_path}")
                    current_file_path = xml_path
                except OSError as e:
                    logger.error(f"Failed to rename temp file to XML file: {e}")
                    current_file_path = temp_download_path  # Fall back to using temp file

            # Now extract the file if it's compressed
            if is_compressed:
                try:
                    logger.info(f"Extracting compressed file {current_file_path}")
                    send_epg_update(source.id, "extracting", 0, message="Extracting downloaded file")

                    # Always extract to the standard XML path - set delete_original to True to clean up
                    extracted = extract_compressed_file(current_file_path, xml_path, delete_original=True)

                    if extracted:
                        logger.info(f"Successfully extracted to {xml_path}, compressed file deleted")
                        send_epg_update(source.id, "extracting", 100, message=f"File extracted successfully, temporary file removed")
                        # Update to store only the extracted file path since the compressed file is now gone
                        source.file_path = xml_path
                        source.extracted_file_path = None
                    else:
                        logger.error("Extraction failed, using compressed file")
                        send_epg_update(source.id, "extracting", 100, status="error", message="Extraction failed, using compressed file")
                        # Use the compressed file
                        source.file_path = current_file_path
                        source.extracted_file_path = None
                except Exception as e:
                    logger.error(f"Error extracting file: {str(e)}", exc_info=True)
                    send_epg_update(source.id, "extracting", 100, status="error", message=f"Error during extraction: {str(e)}")
                    # Use the compressed file if extraction fails
                    source.file_path = current_file_path
                    source.extracted_file_path = None
            else:
                # It's already an XML file
                source.file_path = current_file_path
                source.extracted_file_path = None

            # Update the source's file paths
            source.save(update_fields=['file_path', 'status', 'extracted_file_path'])

            # Update status to parsing
            source.status = 'parsing'
            source.save(update_fields=['status'])

            logger.info(f"Cached EPG file saved to {source.file_path}")
            return True

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Get error details
        status_code = e.response.status_code if hasattr(e, 'response') and e.response else 'unknown'
        error_message = str(e)

        # Create a user-friendly message
        user_message = f"EPG source '{source.name}' encountered HTTP error {status_code}"

        # Add specific handling for common HTTP errors
        if status_code == 404:
            user_message = f"EPG source '{source.name}' URL not found (404) - will retry on next scheduled run"
        elif status_code == 401 or status_code == 403:
            user_message = f"EPG source '{source.name}' access denied (HTTP {status_code}) - check credentials"
        elif status_code == 429:
            user_message = f"EPG source '{source.name}' rate limited (429) - try again later"
        elif status_code >= 500:
            user_message = f"EPG source '{source.name}' server error (HTTP {status_code}) - will retry later"

        # Update source status to error with the error message
        source.status = 'error'
        source.last_message = user_message
        source.save(update_fields=['status', 'last_message'])

        # Notify users through the WebSocket about the EPG fetch failure
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'updates',
            {
                'type': 'update',
                'data': {
                    "success": False,
                    "type": "epg_fetch_error",
                    "source_id": source.id,
                    "source_name": source.name,
                    "error_code": status_code,
                    "message": user_message,
                    "details": error_message
                }
            }
        )

        # Ensure we update the download progress to 100 with error status
        send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
        return False
    except requests.exceptions.ConnectionError as e:
        # Handle connection errors separately
        error_message = str(e)
        user_message = f"Connection error: Unable to connect to EPG source '{source.name}'"
        logger.error(f"Connection error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Update source status
        source.status = 'error'
        source.last_message = user_message
        source.save(update_fields=['status', 'last_message'])

        # Send notifications
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'updates',
            {
                'type': 'update',
                'data': {
                    "success": False,
                    "type": "epg_fetch_error",
                    "source_id": source.id,
                    "source_name": source.name,
                    "error_code": "connection_error",
                    "message": user_message
                }
            }
        )
        send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
        return False
    except requests.exceptions.Timeout as e:
        # Handle timeout errors specifically
        error_message = str(e)
        user_message = f"Timeout error: EPG source '{source.name}' took too long to respond"
        logger.error(f"Timeout error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Update source status
        source.status = 'error'
        source.last_message = user_message
        source.save(update_fields=['status', 'last_message'])

        # Send notifications
        send_epg_update(source.id, "downloading", 100, status="error", error=user_message)
        return False
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error fetching XMLTV from {source.name}: {e}", exc_info=True)

        # Update source status for general exceptions too
        source.status = 'error'
        source.last_message = f"Error: {error_message}"
        source.save(update_fields=['status', 'last_message'])

        # Ensure we update the download progress to 100 with error status
        send_epg_update(source.id, "downloading", 100, status="error", error=f"Error: {error_message}")
        return False


def extract_compressed_file(file_path, output_path=None, delete_original=False):
    """
    Extracts a compressed file (.gz or .zip) to an XML file.

    Args:
        file_path: Path to the compressed file
        output_path: Specific path where the file should be extracted (optional)
        delete_original: Whether to delete the original compressed file after successful extraction

    Returns:
        Path to the extracted XML file, or None if extraction failed
    """
    try:
        if output_path is None:
            base_path = os.path.splitext(file_path)[0]
            extracted_path = f"{base_path}.xml"
        else:
            extracted_path = output_path

        # Make sure the output path doesn't already exist
        if os.path.exists(extracted_path):
            try:
                os.remove(extracted_path)
                logger.info(f"Removed existing extracted file: {extracted_path}")
            except Exception as e:
                logger.warning(f"Failed to remove existing extracted file: {e}")
                # If we can't delete the existing file and no specific output was requested,
                # create a unique filename instead
                if output_path is None:
                    base_path = os.path.splitext(file_path)[0]
                    extracted_path = f"{base_path}_{uuid.uuid4().hex[:8]}.xml"

        # Use our detection helper to determine the file format instead of relying on extension
        with open(file_path, 'rb') as f:
            content_sample = f.read(4096)  # Read a larger sample to ensure accurate detection

        format_type, is_compressed, _ = detect_file_format(file_path=file_path, content=content_sample)

        if format_type == 'gzip':
            logger.debug(f"Extracting gzip file: {file_path}")
            try:
                # First check if the content is XML by reading a sample
                with gzip.open(file_path, 'rb') as gz_file:
                    content_sample = gz_file.read(4096)  # Read first 4KB for detection
                    detected_format, _, _ = detect_file_format(content=content_sample)

                    if detected_format != 'xml':
                        logger.warning(f"GZIP file does not appear to contain XML content: {file_path} (detected as: {detected_format})")
                        # Continue anyway since GZIP only contains one file

                    # Reset file pointer and extract the content
                    gz_file.seek(0)
                    with open(extracted_path, 'wb') as out_file:
                        while True:
                            chunk = gz_file.read(MAX_EXTRACT_CHUNK_SIZE)
                            if not chunk or len(chunk) == 0:
                                break
                            out_file.write(chunk)
            except Exception as e:
                logger.error(f"Error extracting GZIP file: {e}", exc_info=True)
                return None

            logger.info(f"Successfully extracted gzip file to: {extracted_path}")

            # Delete original compressed file if requested
            if delete_original:
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted original compressed file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete original compressed file {file_path}: {e}")

            return extracted_path

        elif format_type == 'zip':
            logger.debug(f"Extracting zip file: {file_path}")
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                # Find the first XML file in the ZIP archive
                xml_files = [f for f in zip_file.namelist() if f.lower().endswith('.xml')]

                if not xml_files:
                    logger.info("No files with .xml extension found in ZIP archive, checking content of all files")
                    # Check content of each file to see if any are XML without proper extension
                    for filename in zip_file.namelist():
                        if not filename.endswith('/'):  # Skip directories
                            try:
                                # Read a sample of the file content
                                content_sample = zip_file.read(filename, 4096)  # Read up to 4KB for detection
                                format_type, _, _ = detect_file_format(content=content_sample)
                                if format_type == 'xml':
                                    logger.info(f"Found XML content in file without .xml extension: {filename}")
                                    xml_files = [filename]
                                    break
                            except Exception as e:
                                logger.warning(f"Error reading file {filename} from ZIP: {e}")

                if not xml_files:
                    logger.error("No XML file found in ZIP archive")
                    return None

                # Extract the first XML file
                with open(extracted_path, 'wb') as out_file:
                    with zip_file.open(xml_files[0], "r") as xml_file:
                        while True:
                            chunk = xml_file.read(MAX_EXTRACT_CHUNK_SIZE)
                            if not chunk or len(chunk) == 0:
                                break
                            out_file.write(chunk)

            logger.info(f"Successfully extracted zip file to: {extracted_path}")

            # Delete original compressed file if requested
            if delete_original:
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted original compressed file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete original compressed file {file_path}: {e}")

            return extracted_path

        else:
            logger.error(f"Unsupported or unrecognized compressed file format: {file_path} (detected as: {format_type})")
            return None

    except Exception as e:
        logger.error(f"Error extracting {file_path}: {str(e)}", exc_info=True)
        return None


def parse_channels_only(source):
    # Use extracted file if available, otherwise use the original file path
    file_path = source.extracted_file_path if source.extracted_file_path else source.file_path
    if not file_path:
        file_path = source.get_cache_file()

    # Send initial parsing notification
    send_epg_update(source.id, "parsing_channels", 0)

    process = None
    should_log_memory = False

    try:
        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(f"EPG file does not exist at path: {file_path}")

            # Update the source's file_path to the default cache location
            new_path = source.get_cache_file()
            logger.info(f"Updating file_path from '{file_path}' to '{new_path}'")
            source.file_path = new_path
            source.save(update_fields=['file_path'])

            # If the source has a URL, fetch the data before continuing
            if source.url:
                logger.info(f"Fetching new EPG data from URL: {source.url}")
                fetch_success = fetch_xmltv(source)  # Store the result

                # Only proceed if fetch was successful AND file exists
                if not fetch_success:
                    logger.error(f"Failed to fetch EPG data from URL: {source.url}")
                    # Update status to error
                    source.status = 'error'
                    source.last_message = f"Failed to fetch EPG data from URL"
                    source.save(update_fields=['status', 'last_message'])
                    # Send error notification
                    send_epg_update(source.id, "parsing_channels", 100, status="error", error="Failed to fetch EPG data")
                    return False

                # Verify the file was downloaded successfully
                if not os.path.exists(source.file_path):
                    logger.error(f"Failed to fetch EPG data, file still missing at: {source.file_path}")
                    # Update status to error
                    source.status = 'error'
                    source.last_message = f"Failed to fetch EPG data, file missing after download"
                    source.save(update_fields=['status', 'last_message'])
                    send_epg_update(source.id, "parsing_channels", 100, status="error", error="File not found after download")
                    return False

                # Update file_path with the new location
                file_path = source.file_path
            else:
                logger.error(f"No URL provided for EPG source {source.name}, cannot fetch new data")
                # Update status to error
                source.status = 'error'
                source.last_message = f"No URL provided, cannot fetch EPG data"
                source.save(update_fields=['updated_at'])

        # Initialize process variable for memory tracking only in debug mode
        try:
            process = None
            # Get current log level as a number
            current_log_level = logger.getEffectiveLevel()

            # Only track memory usage when log level is DEBUG (10) or more verbose
            # This is more future-proof than string comparisons
            should_log_memory = current_log_level <= logging.DEBUG or settings.DEBUG

            if should_log_memory:
                process = psutil.Process()
                initial_memory = process.memory_info().rss / 1024 / 1024
                logger.debug(f"[parse_channels_only] Initial memory usage: {initial_memory:.2f} MB")
        except (ImportError, NameError):
            process = None
            should_log_memory = False
            logger.warning("psutil not available for memory tracking")

        # Replace full dictionary load with more efficient lookup set
        existing_tvg_ids = set()
        existing_epgs = {}  # Initialize the dictionary that will lazily load objects
        last_id = 0
        chunk_size = 5000

        while True:
            tvg_id_chunk = set(EPGData.objects.filter(
                epg_source=source,
                id__gt=last_id
            ).order_by('id').values_list('tvg_id', flat=True)[:chunk_size])

            if not tvg_id_chunk:
                break

            existing_tvg_ids.update(tvg_id_chunk)
            last_id = EPGData.objects.filter(tvg_id__in=tvg_id_chunk).order_by('-id')[0].id
        # Update progress to show file read starting
        send_epg_update(source.id, "parsing_channels", 10)

        # Stream parsing instead of loading entire file at once
        # This can be simplified since we now always have XML files
        epgs_to_create = []
        epgs_to_update = []
        total_channels = 0
        processed_channels = 0
        batch_size = 500  # Process in batches to limit memory usage
        progress = 0  # Initialize progress variable here
        icon_url_max_length = EPGData._meta.get_field('icon_url').max_length  # Get max length for icon_url field

        # Track memory at key points
        if process:
            logger.debug(f"[parse_channels_only] Memory before opening file: {process.memory_info().rss / 1024 / 1024:.2f} MB")

        try:
            # Attempt to count existing channels in the database
            try:
                total_channels = EPGData.objects.filter(epg_source=source).count()
                logger.info(f"Found {total_channels} existing channels for this source")
            except Exception as e:
                logger.error(f"Error counting channels: {e}")
                total_channels = 500  # Default estimate
            if process:
                logger.debug(f"[parse_channels_only] Memory after closing initial file: {process.memory_info().rss / 1024 / 1024:.2f} MB")

            # Update progress after counting
            send_epg_update(source.id, "parsing_channels", 25, total_channels=total_channels)

            # Open the file - no need to check file type since it's always XML now
            logger.debug(f"Opening file for channel parsing: {file_path}")
            source_file = open(file_path, 'rb')

            if process:
                logger.debug(f"[parse_channels_only] Memory after opening file: {process.memory_info().rss / 1024 / 1024:.2f} MB")

            # Change iterparse to look for both channel and programme elements
            logger.debug(f"Creating iterparse context for channels and programmes")
            channel_parser = etree.iterparse(source_file, events=('end',), tag=('channel', 'programme'), remove_blank_text=True, recover=True)
            if process:
                logger.debug(f"[parse_channels_only] Memory after creating iterparse: {process.memory_info().rss / 1024 / 1024:.2f} MB")

            channel_count = 0
            total_elements_processed = 0  # Track total elements processed, not just channels
            for _, elem in channel_parser:
                total_elements_processed += 1
                # Only process channel elements
                if elem.tag == 'channel':
                    channel_count += 1
                    tvg_id = elem.get('id', '').strip()
                    if tvg_id:
                        display_name = None
                        icon_url = None
                        for child in elem:
                            if display_name is None and child.tag == 'display-name' and child.text:
                                display_name = child.text.strip()
                            elif child.tag == 'icon':
                                raw_icon_url = child.get('src', '').strip()
                                icon_url = validate_icon_url_fast(raw_icon_url, icon_url_max_length)
                            if display_name and icon_url:
                                break  # No need to continue if we have both

                        if not display_name:
                            display_name = tvg_id

                        # Use lazy loading approach to reduce memory usage
                        if tvg_id in existing_tvg_ids:
                            # Only fetch the object if we need to update it and it hasn't been loaded yet
                            if tvg_id not in existing_epgs:
                                try:
                                    # This loads the full EPG object from the database and caches it
                                    existing_epgs[tvg_id] = EPGData.objects.get(tvg_id=tvg_id, epg_source=source)
                                except EPGData.DoesNotExist:
                                    # Handle race condition where record was deleted
                                    existing_tvg_ids.remove(tvg_id)
                                    epgs_to_create.append(EPGData(
                                        tvg_id=tvg_id,
                                        name=display_name,
                                        icon_url=icon_url,
                                        epg_source=source,
                                    ))
                                    logger.debug(f"[parse_channels_only] Added new channel to epgs_to_create 1: {tvg_id} - {display_name}")
                                    processed_channels += 1
                                    continue

                            # We use the cached object to check if the name or icon_url has changed
                            epg_obj = existing_epgs[tvg_id]
                            needs_update = False
                            if epg_obj.name != display_name:
                                epg_obj.name = display_name
                                needs_update = True
                            if epg_obj.icon_url != icon_url:
                                epg_obj.icon_url = icon_url
                                needs_update = True

                            if needs_update:
                                epgs_to_update.append(epg_obj)
                                logger.debug(f"[parse_channels_only] Added channel to update to epgs_to_update: {tvg_id} - {display_name}")
                            else:
                                # No changes needed, just clear the element
                                logger.debug(f"[parse_channels_only] No changes needed for channel {tvg_id} - {display_name}")
                        else:
                            # This is a new channel that doesn't exist in our database
                            epgs_to_create.append(EPGData(
                                tvg_id=tvg_id,
                                name=display_name,
                                icon_url=icon_url,
                                epg_source=source,
                            ))
                            logger.debug(f"[parse_channels_only] Added new channel to epgs_to_create 2: {tvg_id} - {display_name}")

                    processed_channels += 1

                    # Batch processing
                    if len(epgs_to_create) >= batch_size:
                        logger.info(f"[parse_channels_only] Bulk creating {len(epgs_to_create)} EPG entries")
                        EPGData.objects.bulk_create(epgs_to_create, ignore_conflicts=True)
                        if process:
                            logger.info(f"[parse_channels_only] Memory after bulk_create: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                        del epgs_to_create  # Explicit deletion
                        epgs_to_create = []
                        cleanup_memory(log_usage=should_log_memory, force_collection=True)
                        if process:
                            logger.info(f"[parse_channels_only] Memory after gc.collect(): {process.memory_info().rss / 1024 / 1024:.2f} MB")

                    if len(epgs_to_update) >= batch_size:
                        logger.info(f"[parse_channels_only] Bulk updating {len(epgs_to_update)} EPG entries")
                        if process:
                            logger.info(f"[parse_channels_only] Memory before bulk_update: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                        EPGData.objects.bulk_update(epgs_to_update, ["name", "icon_url"])
                        if process:
                            logger.info(f"[parse_channels_only] Memory after bulk_update: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                        epgs_to_update = []
                        # Force garbage collection
                        cleanup_memory(log_usage=should_log_memory, force_collection=True)

                    # Periodically clear the existing_epgs cache to prevent memory buildup
                    if processed_channels % 1000 == 0:
                        logger.info(f"[parse_channels_only] Clearing existing_epgs cache at {processed_channels} channels")
                        existing_epgs.clear()
                        cleanup_memory(log_usage=should_log_memory, force_collection=True)
                        if process:
                            logger.info(f"[parse_channels_only] Memory after clearing cache: {process.memory_info().rss / 1024 / 1024:.2f} MB")

                    # Send progress updates
                    if processed_channels % 100 == 0 or processed_channels == total_channels:
                        progress = 25 + int((processed_channels / total_channels) * 65) if total_channels > 0 else 90
                        send_epg_update(
                            source.id,
                            "parsing_channels",
                            progress,
                            processed=processed_channels,
                            total=total_channels
                        )
                    if processed_channels > total_channels:
                        logger.debug(f"[parse_channels_only] Processed channel {tvg_id} - processed {processed_channels - total_channels} additional channels")
                    else:
                        logger.debug(f"[parse_channels_only] Processed channel {tvg_id} - processed {processed_channels}/{total_channels}")
                    if process:
                        logger.debug(f"[parse_channels_only] Memory before elem cleanup: {process.memory_info().rss / 1024 / 1024:.2f} MB")
                    # Clear memory
                    try:
                        # First clear the element's content
                        clear_element(elem)

                    except Exception as e:
                        # Just log the error and continue - don't let cleanup errors stop processing
                        logger.debug(f"[parse_channels_only] Non-critical error during XML element cleanup: {e}")
                    if process:
                        logger.debug(f"[parse_channels_only] Memory after elem cleanup: {process.memory_info().rss / 1024 / 1024:.2f} MB")

                    logger.debug(f"[parse_channels_only] Total elements processed: {total_elements_processed}")

                else:
                    logger.trace(f"[parse_channels_only] Skipping non-channel element: {elem.get('channel', 'unknown')} - {elem.get('start', 'unknown')} {elem.tag}")
                    clear_element(elem)
                    continue

        except (etree.XMLSyntaxError, Exception) as xml_error:
            logger.error(f"[parse_channels_only] XML parsing failed: {xml_error}")
            # Update status to error
            source.status = 'error'
            source.last_message = f"Error parsing XML file: {str(xml_error)}"
            source.save(update_fields=['status', 'last_message'])
            send_epg_update(source.id, "parsing_channels", 100, status="error", error=str(xml_error))
            return False
        if process:
            logger.info(f"[parse_channels_only] Processed {processed_channels} channels current memory: {process.memory_info().rss / 1024 / 1024:.2f} MB")
        else:
            logger.info(f"[parse_channels_only] Processed {processed_channels} channels")
        # Process any remaining items
        if epgs_to_create:
            EPGData.objects.bulk_create(epgs_to_create, ignore_conflicts=True)
            logger.debug(f"[parse_channels_only] Created final batch of {len(epgs_to_create)} EPG entries")

        if epgs_to_update:
            EPGData.objects.bulk_update(epgs_to_update, ["name", "icon_url"])
            logger.debug(f"[parse_channels_only] Updated final batch of {len(epgs_to_update)} EPG entries")
        if process:
            logger.debug(f"[parse_channels_only] Memory after final batch creation: {process.memory_info().rss / 1024 / 1024:.2f} MB")

        # Update source status with channel count
        source.status = 'success'
        source.last_message = f"Successfully parsed {processed_channels} channels"
        source.save(update_fields=['status', 'last_message'])

        # Send completion notification
        send_epg_update(
            source.id,
            "parsing_channels",
            100,
            status="success",
            channels_count=processed_channels
        )

        send_websocket_update('updates', 'update', {"success": True, "type": "epg_channels"})

        logger.info(f"Finished parsing channel info. Found {processed_channels} channels.")

        return True

    except FileNotFoundError:
        logger.error(f"EPG file not found at: {file_path}")
        # Update status to error
        source.status = 'error'
        source.last_message = f"EPG file not found: {file_path}"
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "parsing_channels", 100, status="error", error="File not found")
        return False
    except Exception as e:
        logger.error(f"Error reading EPG file {file_path}: {e}", exc_info=True)
        # Update status to error
        source.status = 'error'
        source.last_message = f"Error parsing EPG file: {str(e)}"
        source.save(update_fields=['status', 'last_message'])
        send_epg_update(source.id, "parsing_channels", 100, status="error", error=str(e))
        return False
    finally:
        # Cleanup memory and close file
        if process:
            logger.debug(f"[parse_channels_only] Memory before cleanup: {process.memory_info().rss / 1024 / 1024:.2f} MB")
        try:
            # Output any errors in the channel_parser error log
            if 'channel_parser' in locals() and hasattr(channel_parser, 'error_log') and len(channel_parser.error_log) > 0:
                logger.debug(f"XML parser errors found ({len(channel_parser.error_log)} total):")
                for i, error in enumerate(channel_parser.error_log):
                    logger.debug(f"  Error {i+1}: {error}")
            if 'channel_parser' in locals():
                del channel_parser
            if 'elem' in locals():
                del elem
            if 'parent' in locals():
                del parent

            if 'source_file' in locals():
                source_file.close()
                del source_file
            # Clear remaining large data structures
            existing_epgs.clear()
            epgs_to_create.clear()
            epgs_to_update.clear()
            existing_epgs = None
            epgs_to_create = None
            epgs_to_update = None
            cleanup_memory(log_usage=should_log_memory, force_collection=True)
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")

        try:
            if process:
                final_memory = process.memory_info().rss / 1024 / 1024
                logger.debug(f"[parse_channels_only] Final memory usage: {final_memory:.2f} MB")
                process = None
        except:
            pass



@shared_task
def parse_programs_for_tvg_id(epg_id):
    if not acquire_task_lock('parse_epg_programs', epg_id):
        logger.info(f"Program parse for {epg_id} already in progress, skipping duplicate task")
        return "Task already running"

    source_file = None
    program_parser = None
    programs_to_create = []
    programs_processed = 0
    try:
        # Add memory tracking only in trace mode or higher
        try:
            process = None
            # Get current log level as a number
            current_log_level = logger.getEffectiveLevel()

            # Only track memory usage when log level is TRACE or more verbose or if running in DEBUG mode
            should_log_memory = current_log_level <= 5 or settings.DEBUG

            if should_log_memory:
                process = psutil.Process()
                initial_memory = process.memory_info().rss / 1024 / 1024
                logger.info(f"[parse_programs_for_tvg_id] Initial memory usage: {initial_memory:.2f} MB")
                mem_before = initial_memory
        except ImportError:
            process = None
            should_log_memory = False

        epg = EPGData.objects.get(id=epg_id)
        epg_source = epg.epg_source

        # Skip program parsing for dummy EPG sources - they don't have program data files
        if epg_source.source_type == 'dummy':
            logger.info(f"Skipping program parsing for dummy EPG source {epg_source.name} (ID: {epg_id})")
            release_task_lock('parse_epg_programs', epg_id)
            return

        if not Channel.objects.filter(epg_data=epg).exists():
            logger.info(f"No channels matched to EPG {epg.tvg_id}")
            release_task_lock('parse_epg_programs', epg_id)
            return

        logger.info(f"Refreshing program data for tvg_id: {epg.tvg_id}")

        # Optimize deletion with a single delete query instead of chunking
        # This is faster for most database engines
        ProgramData.objects.filter(epg=epg).delete()

        file_path = epg_source.extracted_file_path if epg_source.extracted_file_path else epg_source.file_path
        if not file_path:
            file_path = epg_source.get_cache_file()

        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(f"EPG file not found at: {file_path}")

            if epg_source.url:
                # Update the file path in the database
                new_path = epg_source.get_cache_file()
                logger.info(f"Updating file_path from '{file_path}' to '{new_path}'")
                epg_source.file_path = new_path
                epg_source.save(update_fields=['file_path'])
                logger.info(f"Fetching new EPG data from URL: {epg_source.url}")
            else:
                logger.info(f"EPG source does not have a URL, using existing file path: {file_path} to rebuild cache")

            # Fetch new data before continuing
            if epg_source:

                # Properly check the return value from fetch_xmltv
                fetch_success = fetch_xmltv(epg_source)

                # If fetch was not successful or the file still doesn't exist, abort
                if not fetch_success:
                    logger.error(f"Failed to fetch EPG data, cannot parse programs for tvg_id: {epg.tvg_id}")
                    # Update status to error if not already set
                    epg_source.status = 'error'
                    epg_source.last_message = f"Failed to download EPG data, cannot parse programs"
                    epg_source.save(update_fields=['status', 'last_message'])
                    send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="Failed to download EPG file")
                    release_task_lock('parse_epg_programs', epg_id)
                    return

                # Also check if the file exists after download
                if not os.path.exists(epg_source.file_path):
                    logger.error(f"Failed to fetch EPG data, file still missing at: {epg_source.file_path}")
                    epg_source.status = 'error'
                    epg_source.last_message = f"Failed to download EPG data, file missing after download"
                    epg_source.save(update_fields=['status', 'last_message'])
                    send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="File not found after download")
                    release_task_lock('parse_epg_programs', epg_id)
                    return

                # Update file_path with the new location
                if epg_source.extracted_file_path:
                    file_path = epg_source.extracted_file_path
                else:
                    file_path = epg_source.file_path
            else:
                logger.error(f"No URL provided for EPG source {epg_source.name}, cannot fetch new data")
                # Update status to error
                epg_source.status = 'error'
                epg_source.last_message = f"No URL provided, cannot fetch EPG data"
                epg_source.save(update_fields=['status', 'last_message'])
                send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="No URL provided")
                release_task_lock('parse_epg_programs', epg_id)
                return

        # Use streaming parsing to reduce memory usage
        # No need to check file type anymore since it's always XML
        logger.debug(f"Parsing programs for tvg_id={epg.tvg_id} from {file_path}")

        # Memory usage tracking
        if process:
            try:
                mem_before = process.memory_info().rss / 1024 / 1024
                logger.debug(f"[parse_programs_for_tvg_id] Memory before parsing {epg.tvg_id} -  {mem_before:.2f} MB")
            except Exception as e:
                logger.warning(f"Error tracking memory: {e}")
                mem_before = 0

        programs_to_create = []
        batch_size = 1000  # Process in batches to limit memory usage

        try:
            # Open the file directly - no need to check compression
            logger.debug(f"Opening file for parsing: {file_path}")
            source_file = open(file_path, 'rb')

            # Stream parse the file using lxml's iterparse
            program_parser = etree.iterparse(source_file, events=('end',), tag='programme',  remove_blank_text=True, recover=True)

            for _, elem in program_parser:
                if elem.get('channel') == epg.tvg_id:
                    try:
                        start_time = parse_xmltv_time(elem.get('start'))
                        end_time = parse_xmltv_time(elem.get('stop'))
                        title = None
                        desc = None
                        sub_title = None

                        # Efficiently process child elements
                        for child in elem:
                            if child.tag == 'title':
                                title = child.text or 'No Title'
                            elif child.tag == 'desc':
                                desc = child.text or ''
                            elif child.tag == 'sub-title':
                                sub_title = child.text or ''

                        if not title:
                            title = 'No Title'

                        # Extract custom properties
                        custom_props = extract_custom_properties(elem)
                        custom_properties_json = None

                        if custom_props:
                            logger.trace(f"Number of custom properties: {len(custom_props)}")
                            custom_properties_json = custom_props

                        programs_to_create.append(ProgramData(
                            epg=epg,
                            start_time=start_time,
                            end_time=end_time,
                            title=title,
                            description=desc,
                            sub_title=sub_title,
                            tvg_id=epg.tvg_id,
                            custom_properties=custom_properties_json
                        ))
                        programs_processed += 1
                        # Clear the element to free memory
                        clear_element(elem)
                        # Batch processing
                        if len(programs_to_create) >= batch_size:
                            ProgramData.objects.bulk_create(programs_to_create)
                            logger.debug(f"Saved batch of {len(programs_to_create)} programs for {epg.tvg_id}")
                            programs_to_create = []
                            # Only call gc.collect() every few batches
                            if programs_processed % (batch_size * 5) == 0:
                                gc.collect()

                    except Exception as e:
                        logger.error(f"Error processing program for {epg.tvg_id}: {e}", exc_info=True)
                else:
                    # Immediately clean up non-matching elements to reduce memory pressure
                    if elem is not None:
                        clear_element(elem)
                    continue

            # Make sure to close the file and release parser resources
            if source_file:
                source_file.close()
                source_file = None

            if program_parser:
                program_parser = None

            gc.collect()

        except zipfile.BadZipFile as zip_error:
            logger.error(f"Bad ZIP file: {zip_error}")
            raise
        except etree.XMLSyntaxError as xml_error:
            logger.error(f"XML syntax error parsing program data: {xml_error}")
            raise
        except Exception as e:
            logger.error(f"Error parsing XML for programs: {e}", exc_info=True)
            raise
        finally:
            # Ensure file is closed even if an exception occurs
            if source_file:
                source_file.close()
                source_file = None
             # Memory tracking after processing
            if process:
                try:
                    mem_after = process.memory_info().rss / 1024 / 1024
                    logger.info(f"[parse_programs_for_tvg_id] Memory after parsing 1 {epg.tvg_id} - {programs_processed} programs: {mem_after:.2f} MB (change: {mem_after-mem_before:.2f} MB)")
                except Exception as e:
                    logger.warning(f"Error tracking memory: {e}")

        # Process any remaining items
        if programs_to_create:
            ProgramData.objects.bulk_create(programs_to_create)
            logger.debug(f"Saved final batch of {len(programs_to_create)} programs for {epg.tvg_id}")
            programs_to_create = None
            custom_props = None
            custom_properties_json = None


        logger.info(f"Completed program parsing for tvg_id={epg.tvg_id}.")
    finally:
        # Reset internal caches and pools that lxml might be keeping
        try:
            etree.clear_error_log()
        except:
            pass
        # Explicit cleanup of all potentially large objects
        if source_file:
            try:
                source_file.close()
            except:
                pass
        source_file = None
        program_parser = None
        programs_to_create = None

        epg_source = None
        # Add comprehensive cleanup before releasing lock
        cleanup_memory(log_usage=should_log_memory, force_collection=True)
         # Memory tracking after processing
        if process:
            try:
                mem_after = process.memory_info().rss / 1024 / 1024
                logger.info(f"[parse_programs_for_tvg_id] Final memory usage {epg.tvg_id} - {programs_processed} programs: {mem_after:.2f} MB (change: {mem_after-mem_before:.2f} MB)")
            except Exception as e:
                logger.warning(f"Error tracking memory: {e}")
            process = None
        epg = None
        programs_processed = None
        release_task_lock('parse_epg_programs', epg_id)



def parse_programs_for_source(epg_source, tvg_id=None):
    """
    Parse programs for all MAPPED channels from an EPG source in a single pass.

    This is an optimized version that:
    1. Only processes EPG entries that are actually mapped to channels
    2. Parses the XML file ONCE instead of once per channel
    3. Skips programmes for unmapped channels entirely during parsing

    This dramatically improves performance when an EPG source has many channels
    but only a fraction are mapped.
    """
    # Send initial programs parsing notification
    send_epg_update(epg_source.id, "parsing_programs", 0)
    should_log_memory = False
    process = None
    initial_memory = 0
    source_file = None

    # Add memory tracking only in trace mode or higher
    try:
        # Get current log level as a number
        current_log_level = logger.getEffectiveLevel()

        # Only track memory usage when log level is TRACE or more verbose
        should_log_memory = current_log_level <= 5 or settings.DEBUG  # Assuming TRACE is level 5 or lower

        if should_log_memory:
            process = psutil.Process()
            initial_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"[parse_programs_for_source] Initial memory usage: {initial_memory:.2f} MB")
    except ImportError:
        logger.warning("psutil not available for memory tracking")
        process = None
        should_log_memory = False

    try:
        # Only get EPG entries that are actually mapped to channels
        mapped_epg_ids = set(
            Channel.objects.filter(
                epg_data__epg_source=epg_source,
                epg_data__isnull=False
            ).values_list('epg_data_id', flat=True)
        )

        if not mapped_epg_ids:
            total_epg_count = EPGData.objects.filter(epg_source=epg_source).count()
            logger.info(f"No channels mapped to any EPG entries from source: {epg_source.name} "
                       f"(source has {total_epg_count} EPG entries, 0 mapped)")
            # Update status - this is not an error, just no mapped entries
            epg_source.status = 'success'
            epg_source.last_message = f"No channels mapped to this EPG source ({total_epg_count} entries available)"
            epg_source.save(update_fields=['status', 'last_message'])
            send_epg_update(epg_source.id, "parsing_programs", 100, status="success")
            return True

        # Get the mapped EPG entries with their tvg_ids
        mapped_epgs = EPGData.objects.filter(id__in=mapped_epg_ids).values('id', 'tvg_id')
        tvg_id_to_epg_id = {epg['tvg_id']: epg['id'] for epg in mapped_epgs if epg['tvg_id']}
        mapped_tvg_ids = set(tvg_id_to_epg_id.keys())

        total_epg_count = EPGData.objects.filter(epg_source=epg_source).count()
        mapped_count = len(mapped_tvg_ids)

        logger.info(f"Parsing programs for {mapped_count} MAPPED channels from source: {epg_source.name} "
                   f"(skipping {total_epg_count - mapped_count} unmapped EPG entries)")

        # Get the file path
        file_path = epg_source.extracted_file_path if epg_source.extracted_file_path else epg_source.file_path
        if not file_path:
            file_path = epg_source.get_cache_file()

        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(f"EPG file not found at: {file_path}")

            if epg_source.url:
                # Update the file path in the database
                new_path = epg_source.get_cache_file()
                logger.info(f"Updating file_path from '{file_path}' to '{new_path}'")
                epg_source.file_path = new_path
                epg_source.save(update_fields=['file_path'])
                logger.info(f"Fetching new EPG data from URL: {epg_source.url}")

                # Fetch new data before continuing
                fetch_success = fetch_xmltv(epg_source)

                if not fetch_success:
                    logger.error(f"Failed to fetch EPG data for source: {epg_source.name}")
                    epg_source.status = 'error'
                    epg_source.last_message = f"Failed to download EPG data"
                    epg_source.save(update_fields=['status', 'last_message'])
                    send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="Failed to download EPG file")
                    return False

                # Update file_path with the new location
                file_path = epg_source.extracted_file_path if epg_source.extracted_file_path else epg_source.file_path
            else:
                logger.error(f"No URL provided for EPG source {epg_source.name}, cannot fetch new data")
                epg_source.status = 'error'
                epg_source.last_message = f"No URL provided, cannot fetch EPG data"
                epg_source.save(update_fields=['status', 'last_message'])
                send_epg_update(epg_source.id, "parsing_programs", 100, status="error", error="No URL provided")
                return False

        # SINGLE PASS PARSING: Parse the XML file once and collect all programs in memory
        # We parse FIRST, then do an atomic delete+insert to avoid race conditions
        # where clients might see empty/partial EPG data during the transition
        all_programs_to_create = []
        programs_by_channel = {tvg_id: 0 for tvg_id in mapped_tvg_ids}  # Track count per channel
        total_programs = 0
        skipped_programs = 0
        last_progress_update = 0

        try:
            logger.debug(f"Opening file for single-pass parsing: {file_path}")
            source_file = open(file_path, 'rb')

            # Stream parse the file using lxml's iterparse
            program_parser = etree.iterparse(source_file, events=('end',), tag='programme', remove_blank_text=True, recover=True)

            for _, elem in program_parser:
                channel_id = elem.get('channel')

                # Skip programmes for unmapped channels immediately
                if channel_id not in mapped_tvg_ids:
                    skipped_programs += 1
                    # Clear element to free memory
                    clear_element(elem)
                    continue

                # This programme is for a mapped channel - process it
                try:
                    start_time = parse_xmltv_time(elem.get('start'))
                    end_time = parse_xmltv_time(elem.get('stop'))
                    title = None
                    desc = None
                    sub_title = None

                    # Efficiently process child elements
                    for child in elem:
                        if child.tag == 'title':
                            title = child.text or 'No Title'
                        elif child.tag == 'desc':
                            desc = child.text or ''
                        elif child.tag == 'sub-title':
                            sub_title = child.text or ''

                    if not title:
                        title = 'No Title'

                    # Extract custom properties
                    custom_props = extract_custom_properties(elem)
                    custom_properties_json = custom_props if custom_props else None

                    epg_id = tvg_id_to_epg_id[channel_id]
                    all_programs_to_create.append(ProgramData(
                        epg_id=epg_id,
                        start_time=start_time,
                        end_time=end_time,
                        title=title,
                        description=desc,
                        sub_title=sub_title,
                        tvg_id=channel_id,
                        custom_properties=custom_properties_json
                    ))
                    total_programs += 1
                    programs_by_channel[channel_id] += 1

                    # Clear the element to free memory
                    clear_element(elem)

                    # Send progress update (estimate based on programs processed)
                    if total_programs - last_progress_update >= 5000:
                        last_progress_update = total_programs
                        # Cap at 70% during parsing phase (save 30% for DB operations)
                        progress = min(70, 10 + int((total_programs / max(total_programs + 10000, 1)) * 60))
                        send_epg_update(epg_source.id, "parsing_programs", progress,
                                      processed=total_programs, channels=mapped_count)

                    # Periodic garbage collection during parsing
                    if total_programs % 5000 == 0:
                        gc.collect()

                except Exception as e:
                    logger.error(f"Error processing program for {channel_id}: {e}", exc_info=True)
                    clear_element(elem)
                    continue

        except etree.XMLSyntaxError as xml_error:
            logger.error(f"XML syntax error parsing program data: {xml_error}")
            epg_source.status = EPGSource.STATUS_ERROR
            epg_source.last_message = f"XML parsing error: {str(xml_error)}"
            epg_source.save(update_fields=['status', 'last_message'])
            send_epg_update(epg_source.id, "parsing_programs", 100, status="error", message=str(xml_error))
            return False
        except Exception as e:
            logger.error(f"Error parsing XML for programs: {e}", exc_info=True)
            raise
        finally:
            if source_file:
                source_file.close()
                source_file = None

        # Now perform atomic delete + bulk insert
        # This ensures clients never see empty/partial EPG data
        logger.info(f"Parsed {total_programs} programs, performing atomic database update...")
        send_epg_update(epg_source.id, "parsing_programs", 75, message="Updating database...")

        batch_size = 1000
        try:
            with transaction.atomic():
                # Delete existing programs for mapped EPGs
                deleted_count = ProgramData.objects.filter(epg_id__in=mapped_epg_ids).delete()[0]
                logger.debug(f"Deleted {deleted_count} existing programs")

                # Clean up orphaned programs for unmapped EPG entries
                unmapped_epg_ids = list(EPGData.objects.filter(
                    epg_source=epg_source
                ).exclude(id__in=mapped_epg_ids).values_list('id', flat=True))

                if unmapped_epg_ids:
                    orphaned_count = ProgramData.objects.filter(epg_id__in=unmapped_epg_ids).delete()[0]
                    if orphaned_count > 0:
                        logger.info(f"Cleaned up {orphaned_count} orphaned programs for {len(unmapped_epg_ids)} unmapped EPG entries")

                # Bulk insert all new programs in batches within the same transaction
                for i in range(0, len(all_programs_to_create), batch_size):
                    batch = all_programs_to_create[i:i + batch_size]
                    ProgramData.objects.bulk_create(batch)

                    # Update progress during insertion
                    progress = 75 + int((i / len(all_programs_to_create)) * 20) if all_programs_to_create else 95
                    if i % (batch_size * 5) == 0:
                        send_epg_update(epg_source.id, "parsing_programs", min(95, progress),
                                      message=f"Inserting programs... {i}/{len(all_programs_to_create)}")

            logger.info(f"Atomic update complete: deleted {deleted_count}, inserted {total_programs} programs")

        except Exception as db_error:
            logger.error(f"Database error during atomic update: {db_error}", exc_info=True)
            epg_source.status = EPGSource.STATUS_ERROR
            epg_source.last_message = f"Database error: {str(db_error)}"
            epg_source.save(update_fields=['status', 'last_message'])
            send_epg_update(epg_source.id, "parsing_programs", 100, status="error", message=str(db_error))
            return False
        finally:
            # Clear the large list to free memory
            all_programs_to_create = None
            gc.collect()

        # Count channels that actually got programs
        channels_with_programs = sum(1 for count in programs_by_channel.values() if count > 0)

        # Success message
        epg_source.status = EPGSource.STATUS_SUCCESS
        epg_source.last_message = (
            f"Parsed {total_programs:,} programs for {channels_with_programs} channels "
            f"(skipped {skipped_programs:,} programmes for {total_epg_count - mapped_count} unmapped channels)"
        )
        epg_source.updated_at = timezone.now()
        epg_source.save(update_fields=['status', 'last_message', 'updated_at'])

        # Log system event for EPG refresh
        log_system_event(
            event_type='epg_refresh',
            source_name=epg_source.name,
            programs=total_programs,
            channels=channels_with_programs,
            skipped_programs=skipped_programs,
            unmapped_channels=total_epg_count - mapped_count,
        )

        # Send completion notification with status
        send_epg_update(epg_source.id, "parsing_programs", 100,
                      status="success",
                      message=epg_source.last_message)

        logger.info(f"Completed parsing programs for source: {epg_source.name} - "
                   f"{total_programs:,} programs for {channels_with_programs} channels, "
                   f"skipped {skipped_programs:,} programmes for unmapped channels")
        return True

    except Exception as e:
        logger.error(f"Error in parse_programs_for_source: {e}", exc_info=True)
        # Update status to error
        epg_source.status = EPGSource.STATUS_ERROR
        epg_source.last_message = f"Error parsing programs: {str(e)}"
        epg_source.save(update_fields=['status', 'last_message'])
        send_epg_update(epg_source.id, "parsing_programs", 100,
                      status="error",
                      message=epg_source.last_message)
        return False
    finally:
        # Final memory cleanup and tracking
        if source_file:
            try:
                source_file.close()
            except:
                pass
            source_file = None

        # Explicitly release any remaining large data structures
        programs_to_create = None
        programs_by_channel = None
        mapped_epg_ids = None
        mapped_tvg_ids = None
        tvg_id_to_epg_id = None
        gc.collect()

        # Add comprehensive memory cleanup at the end
        cleanup_memory(log_usage=should_log_memory, force_collection=True)
        if process:
            final_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"[parse_programs_for_source] Final memory usage: {final_memory:.2f} MB difference: {final_memory - initial_memory:.2f} MB")
            # Explicitly clear the process object to prevent potential memory leaks
            process = None
def fetch_schedules_direct(source):
    logger.info(f"Fetching Schedules Direct data from source: {source.name}")
    try:
        # Get default user agent from settings
        default_user_agent_setting = CoreSettings.objects.filter(key='default-user-agent').first()
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0"  # Fallback default

        if default_user_agent_setting and default_user_agent_setting.value:
            try:
                user_agent_obj = UserAgent.objects.filter(id=int(default_user_agent_setting.value)).first()
                if user_agent_obj and user_agent_obj.user_agent:
                    user_agent = user_agent_obj.user_agent
                    logger.debug(f"Using default user agent: {user_agent}")
            except (ValueError, Exception) as e:
                logger.warning(f"Error retrieving default user agent, using fallback: {e}")

        api_url = ''
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {source.api_key}',
            'User-Agent': user_agent
        }
        logger.debug(f"Requesting subscriptions from Schedules Direct using URL: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        subscriptions = response.json()
        logger.debug(f"Fetched subscriptions: {subscriptions}")

        for sub in subscriptions:
            tvg_id = sub.get('stationID')
            logger.debug(f"Processing subscription for tvg_id: {tvg_id}")
            schedules_url = f"/schedules/{tvg_id}"
            logger.debug(f"Requesting schedules from URL: {schedules_url}")
            sched_response = requests.get(schedules_url, headers=headers, timeout=30)
            sched_response.raise_for_status()
            schedules = sched_response.json()
            logger.debug(f"Fetched schedules: {schedules}")

            epg_data, created = EPGData.objects.get_or_create(
                tvg_id=tvg_id,
                defaults={'name': tvg_id}
            )
            if created:
                logger.info(f"Created new EPGData for tvg_id '{tvg_id}'.")
            else:
                logger.debug(f"Found existing EPGData for tvg_id '{tvg_id}'.")

            for sched in schedules.get('schedules', []):
                title = sched.get('title', 'No Title')
                desc = sched.get('description', '')
                start_time = parse_schedules_direct_time(sched.get('startTime'))
                end_time = parse_schedules_direct_time(sched.get('endTime'))
                obj, created = ProgramData.objects.update_or_create(
                    epg=epg_data,
                    start_time=start_time,
                    title=title,
                    defaults={
                        'end_time': end_time,
                        'description': desc,
                        'sub_title': ''
                    }
                )
                if created:
                    logger.info(f"Created ProgramData '{title}' for tvg_id '{tvg_id}'.")
                else:
                    logger.info(f"Updated ProgramData '{title}' for tvg_id '{tvg_id}'.")
    except Exception as e:
        logger.error(f"Error fetching Schedules Direct data from {source.name}: {e}", exc_info=True)


# -------------------------------
# Helper parse functions
# -------------------------------
def parse_xmltv_time(time_str):
    try:
        # Basic format validation
        if len(time_str) < 14:
            logger.warning(f"XMLTV timestamp too short: '{time_str}', using as-is")
            dt_obj = datetime.strptime(time_str, '%Y%m%d%H%M%S')
            return timezone.make_aware(dt_obj, timezone=dt_timezone.utc)

        # Parse base datetime
        dt_obj = datetime.strptime(time_str[:14], '%Y%m%d%H%M%S')

        # Handle timezone if present
        if len(time_str) >= 20:  # Has timezone info
            tz_sign = time_str[15]
            tz_hours = int(time_str[16:18])
            tz_minutes = int(time_str[18:20])

            # Create a timezone object
            if tz_sign == '+':
                tz_offset = dt_timezone(timedelta(hours=tz_hours, minutes=tz_minutes))
            elif tz_sign == '-':
                tz_offset = dt_timezone(timedelta(hours=-tz_hours, minutes=-tz_minutes))
            else:
                tz_offset = dt_timezone.utc

            # Make datetime aware with correct timezone
            aware_dt = datetime.replace(dt_obj, tzinfo=tz_offset)
            # Convert to UTC
            aware_dt = aware_dt.astimezone(dt_timezone.utc)

            logger.trace(f"Parsed XMLTV time '{time_str}' to {aware_dt}")
            return aware_dt
        else:
            # No timezone info, assume UTC
            aware_dt = timezone.make_aware(dt_obj, timezone=dt_timezone.utc)
            logger.trace(f"Parsed XMLTV time without timezone '{time_str}' as UTC: {aware_dt}")
            return aware_dt

    except Exception as e:
        logger.error(f"Error parsing XMLTV time '{time_str}': {e}", exc_info=True)
        raise


def parse_schedules_direct_time(time_str):
    try:
        dt_obj = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%SZ')
        aware_dt = timezone.make_aware(dt_obj, timezone=dt_timezone.utc)
        logger.debug(f"Parsed Schedules Direct time '{time_str}' to {aware_dt}")
        return aware_dt
    except Exception as e:
        logger.error(f"Error parsing Schedules Direct time '{time_str}': {e}", exc_info=True)
        raise


# Helper function to extract custom properties - moved to a separate function to clean up the code
def extract_custom_properties(prog):
    # Create a new dictionary for each call
    custom_props = {}

    # Extract categories with a single comprehension to reduce intermediate objects
    categories = [cat.text.strip() for cat in prog.findall('category') if cat.text and cat.text.strip()]
    if categories:
        custom_props['categories'] = categories

    # Extract keywords (new)
    keywords = [kw.text.strip() for kw in prog.findall('keyword') if kw.text and kw.text.strip()]
    if keywords:
        custom_props['keywords'] = keywords

    # Extract episode numbers
    for ep_num in prog.findall('episode-num'):
        system = ep_num.get('system', '')
        if system == 'xmltv_ns' and ep_num.text:
            # Parse XMLTV episode-num format (season.episode.part)
            parts = ep_num.text.split('.')
            if len(parts) >= 2:
                if parts[0].strip() != '':
                    try:
                        season = int(parts[0]) + 1  # XMLTV format is zero-based
                        custom_props['season'] = season
                    except ValueError:
                        pass
                if parts[1].strip() != '':
                    try:
                        episode = int(parts[1]) + 1  # XMLTV format is zero-based
                        custom_props['episode'] = episode
                    except ValueError:
                        pass
        elif system == 'onscreen' and ep_num.text:
            # Just store the raw onscreen format
            custom_props['onscreen_episode'] = ep_num.text.strip()
        elif system == 'dd_progid' and ep_num.text:
            # Store the dd_progid format
            custom_props['dd_progid'] = ep_num.text.strip()
        # Add support for other systems like thetvdb.com, themoviedb.org, imdb.com
        elif system in ['thetvdb.com', 'themoviedb.org', 'imdb.com'] and ep_num.text:
            custom_props[f'{system}_id'] = ep_num.text.strip()

    # Extract ratings more efficiently
    rating_elem = prog.find('rating')
    if rating_elem is not None:
        value_elem = rating_elem.find('value')
        if value_elem is not None and value_elem.text:
            custom_props['rating'] = value_elem.text.strip()
            if rating_elem.get('system'):
                custom_props['rating_system'] = rating_elem.get('system')

    # Extract star ratings (new)
    star_ratings = []
    for star_rating in prog.findall('star-rating'):
        value_elem = star_rating.find('value')
        if value_elem is not None and value_elem.text:
            rating_data = {'value': value_elem.text.strip()}
            if star_rating.get('system'):
                rating_data['system'] = star_rating.get('system')
            star_ratings.append(rating_data)
    if star_ratings:
        custom_props['star_ratings'] = star_ratings

    # Extract credits more efficiently
    credits_elem = prog.find('credits')
    if credits_elem is not None:
        credits = {}
        for credit_type in ['director', 'actor', 'writer', 'adapter', 'producer', 'composer', 'editor', 'presenter', 'commentator', 'guest']:
            if credit_type == 'actor':
                # Handle actors with roles and guest status
                actors = []
                for actor_elem in credits_elem.findall('actor'):
                    if actor_elem.text and actor_elem.text.strip():
                        actor_data = {'name': actor_elem.text.strip()}
                        if actor_elem.get('role'):
                            actor_data['role'] = actor_elem.get('role')
                        if actor_elem.get('guest') == 'yes':
                            actor_data['guest'] = True
                        actors.append(actor_data)
                if actors:
                    credits['actor'] = actors
            else:
                names = [e.text.strip() for e in credits_elem.findall(credit_type) if e.text and e.text.strip()]
                if names:
                    credits[credit_type] = names
        if credits:
            custom_props['credits'] = credits

    # Extract other common program metadata
    date_elem = prog.find('date')
    if date_elem is not None and date_elem.text:
        custom_props['date'] = date_elem.text.strip()

    country_elem = prog.find('country')
    if country_elem is not None and country_elem.text:
        custom_props['country'] = country_elem.text.strip()

    # Extract language information (new)
    language_elem = prog.find('language')
    if language_elem is not None and language_elem.text:
        custom_props['language'] = language_elem.text.strip()

    orig_language_elem = prog.find('orig-language')
    if orig_language_elem is not None and orig_language_elem.text:
        custom_props['original_language'] = orig_language_elem.text.strip()

    # Extract length (new)
    length_elem = prog.find('length')
    if length_elem is not None and length_elem.text:
        try:
            length_value = int(length_elem.text.strip())
            length_units = length_elem.get('units', 'minutes')
            custom_props['length'] = {'value': length_value, 'units': length_units}
        except ValueError:
            pass

    # Extract video information (new)
    video_elem = prog.find('video')
    if video_elem is not None:
        video_info = {}
        for video_attr in ['present', 'colour', 'aspect', 'quality']:
            attr_elem = video_elem.find(video_attr)
            if attr_elem is not None and attr_elem.text:
                video_info[video_attr] = attr_elem.text.strip()
        if video_info:
            custom_props['video'] = video_info

    # Extract audio information (new)
    audio_elem = prog.find('audio')
    if audio_elem is not None:
        audio_info = {}
        for audio_attr in ['present', 'stereo']:
            attr_elem = audio_elem.find(audio_attr)
            if attr_elem is not None and attr_elem.text:
                audio_info[audio_attr] = attr_elem.text.strip()
        if audio_info:
            custom_props['audio'] = audio_info

    # Extract subtitles information (new)
    subtitles = []
    for subtitle_elem in prog.findall('subtitles'):
        subtitle_data = {}
        if subtitle_elem.get('type'):
            subtitle_data['type'] = subtitle_elem.get('type')
        lang_elem = subtitle_elem.find('language')
        if lang_elem is not None and lang_elem.text:
            subtitle_data['language'] = lang_elem.text.strip()
        if subtitle_data:
            subtitles.append(subtitle_data)

    if subtitles:
        custom_props['subtitles'] = subtitles

    # Extract reviews (new)
    reviews = []
    for review_elem in prog.findall('review'):
        if review_elem.text and review_elem.text.strip():
            review_data = {'content': review_elem.text.strip()}
            if review_elem.get('type'):
                review_data['type'] = review_elem.get('type')
            if review_elem.get('source'):
                review_data['source'] = review_elem.get('source')
            if review_elem.get('reviewer'):
                review_data['reviewer'] = review_elem.get('reviewer')
            reviews.append(review_data)
    if reviews:
        custom_props['reviews'] = reviews

    # Extract images (new)
    images = []
    for image_elem in prog.findall('image'):
        if image_elem.text and image_elem.text.strip():
            image_data = {'url': image_elem.text.strip()}
            for attr in ['type', 'size', 'orient', 'system']:
                if image_elem.get(attr):
                    image_data[attr] = image_elem.get(attr)
            images.append(image_data)
    if images:
        custom_props['images'] = images

    icon_elem = prog.find('icon')
    if icon_elem is not None and icon_elem.get('src'):
        custom_props['icon'] = icon_elem.get('src')

    # Simpler approach for boolean flags - expanded list
    for kw in ['previously-shown', 'premiere', 'new', 'live', 'last-chance']:
        if prog.find(kw) is not None:
            custom_props[kw.replace('-', '_')] = True

    # Extract premiere and last-chance text content if available
    premiere_elem = prog.find('premiere')
    if premiere_elem is not None:
        custom_props['premiere'] = True
        if premiere_elem.text and premiere_elem.text.strip():
            custom_props['premiere_text'] = premiere_elem.text.strip()

    last_chance_elem = prog.find('last-chance')
    if last_chance_elem is not None:
        custom_props['last_chance'] = True
        if last_chance_elem.text and last_chance_elem.text.strip():
            custom_props['last_chance_text'] = last_chance_elem.text.strip()

    # Extract previously-shown details
    prev_shown_elem = prog.find('previously-shown')
    if prev_shown_elem is not None:
        custom_props['previously_shown'] = True
        prev_shown_data = {}
        if prev_shown_elem.get('start'):
            prev_shown_data['start'] = prev_shown_elem.get('start')
        if prev_shown_elem.get('channel'):
            prev_shown_data['channel'] = prev_shown_elem.get('channel')
        if prev_shown_data:
            custom_props['previously_shown_details'] = prev_shown_data

    return custom_props


def clear_element(elem):
    """Clear an XML element and its parent to free memory."""
    try:
        elem.clear()
        parent = elem.getparent()
        if parent is not None:
            while elem.getprevious() is not None:
                del parent[0]
            parent.remove(elem)
    except Exception as e:
        logger.warning(f"Error clearing XML element: {e}", exc_info=True)


def detect_file_format(file_path=None, content=None):
    """
    Detect file format by examining content or file path.

    Args:
        file_path: Path to file (optional)
        content: Raw file content bytes (optional)

    Returns:
        tuple: (format_type, is_compressed, file_extension)
        format_type: 'gzip', 'zip', 'xml', or 'unknown'
        is_compressed: Boolean indicating if the file is compressed
        file_extension: Appropriate file extension including dot (.gz, .zip, .xml)
    """
    # Default return values
    format_type = 'unknown'
    is_compressed = False
    file_extension = '.tmp'

    # First priority: check content magic numbers as they're most reliable
    if content:
        # We only need the first few bytes for magic number detection
        header = content[:20] if len(content) >= 20 else content

        # Check for gzip magic number (1f 8b)
        if len(header) >= 2 and header[:2] == b'\x1f\x8b':
            return 'gzip', True, '.gz'

        # Check for zip magic number (PK..)
        if len(header) >= 2 and header[:2] == b'PK':
            return 'zip', True, '.zip'

        # Check for XML - either standard XML header or XMLTV-specific tag
        if len(header) >= 5 and (b'<?xml' in header or b'<tv>' in header):
            return 'xml', False, '.xml'

    # Second priority: check file extension - focus on the final extension for compression
    if file_path:
        logger.debug(f"Detecting file format for: {file_path}")

        # Handle compound extensions like .xml.gz - prioritize compression extensions
        lower_path = file_path.lower()

        # Check for compression extensions explicitly
        if lower_path.endswith('.gz') or lower_path.endswith('.gzip'):
            return 'gzip', True, '.gz'
        elif lower_path.endswith('.zip'):
            return 'zip', True, '.zip'
        elif lower_path.endswith('.xml'):
            return 'xml', False, '.xml'

        # Fallback to mimetypes only if direct extension check doesn't work
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        logger.debug(f"Guessed MIME type: {mime_type}")
        if mime_type:
            if mime_type == 'application/gzip' or mime_type == 'application/x-gzip':
                return 'gzip', True, '.gz'
            elif mime_type == 'application/zip':
                return 'zip', True, '.zip'
            elif mime_type == 'application/xml' or mime_type == 'text/xml':
                return 'xml', False, '.xml'

    # If we reach here, we couldn't reliably determine the format
    return format_type, is_compressed, file_extension


def generate_dummy_epg(source):
    """
    DEPRECATED: This function is no longer used.

    Dummy EPG programs are now generated on-demand when they are requested
    (during XMLTV export or EPG grid display), rather than being pre-generated
    and stored in the database.

    See: apps/output/views.py - generate_custom_dummy_programs()

    This function remains for backward compatibility but should not be called.
    """
    logger.warning(f"generate_dummy_epg() called for {source.name} but this function is deprecated. "
                   f"Dummy EPG programs are now generated on-demand.")
    return True
