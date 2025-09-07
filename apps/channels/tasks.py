# apps/channels/tasks.py
import logging
import os
import select
import re
import requests
import time
import json
import subprocess
from datetime import datetime
import gc

from celery import shared_task
from django.utils.text import slugify

from apps.channels.models import Channel
from apps.epg.models import EPGData
from core.models import CoreSettings

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import tempfile

logger = logging.getLogger(__name__)

# Words we remove to help with fuzzy + embedding matching
COMMON_EXTRANEOUS_WORDS = [
    "tv", "channel", "network", "television",
    "east", "west", "hd", "uhd", "24/7",
    "1080p", "720p", "540p", "480p",
    "film", "movie", "movies"
]

def normalize_name(name: str) -> str:
    """
    A more aggressive normalization that:
      - Lowercases
      - Removes bracketed/parenthesized text
      - Removes punctuation
      - Strips extraneous words
      - Collapses extra spaces
    """
    if not name:
        return ""

    norm = name.lower()
    norm = re.sub(r"\[.*?\]", "", norm)
    norm = re.sub(r"\(.*?\)", "", norm)
    norm = re.sub(r"[^\w\s]", "", norm)
    tokens = norm.split()
    tokens = [t for t in tokens if t not in COMMON_EXTRANEOUS_WORDS]
    norm = " ".join(tokens).strip()
    return norm

@shared_task
def match_epg_channels():
    """
    Goes through all Channels and tries to find a matching EPGData row by:
      1) If channel.tvg_id is valid in EPGData, skip.
      2) If channel has a tvg_id but not found in EPGData, attempt direct EPGData lookup.
      3) Otherwise, perform name-based fuzzy matching with optional region-based bonus.
      4) If a match is found, we set channel.tvg_id
      5) Summarize and log results.
    """
    try:
        logger.info("Starting EPG matching logic...")

        # Attempt to retrieve a "preferred-region" if configured
        try:
            region_obj = CoreSettings.objects.get(key="preferred-region")
            region_code = region_obj.value.strip().lower()
        except CoreSettings.DoesNotExist:
            region_code = None

        matched_channels = []
        channels_to_update = []

        # Get channels that don't have EPG data assigned
        channels_without_epg = Channel.objects.filter(epg_data__isnull=True)
        logger.info(f"Found {channels_without_epg.count()} channels without EPG data")

        channels_json = []
        for channel in channels_without_epg:
            # Normalize TVG ID - strip whitespace and convert to lowercase
            normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
            if normalized_tvg_id:
                logger.info(f"Processing channel {channel.id} '{channel.name}' with TVG ID='{normalized_tvg_id}'")

            channels_json.append({
                "id": channel.id,
                "name": channel.name,
                "tvg_id": normalized_tvg_id,  # Use normalized TVG ID
                "original_tvg_id": channel.tvg_id,  # Keep original for reference
                "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
                "norm_chan": normalize_name(normalized_tvg_id if normalized_tvg_id else channel.name)
            })

        # Similarly normalize EPG data TVG IDs
        epg_json = []
        for epg in EPGData.objects.all():
            normalized_tvg_id = epg.tvg_id.strip().lower() if epg.tvg_id else ""
            epg_json.append({
                'id': epg.id,
                'tvg_id': normalized_tvg_id,  # Use normalized TVG ID
                'original_tvg_id': epg.tvg_id,  # Keep original for reference
                'name': epg.name,
                'norm_name': normalize_name(epg.name),
                'epg_source_id': epg.epg_source.id if epg.epg_source else None,
            })

        # Log available EPG data TVG IDs for debugging
        unique_epg_tvg_ids = set(e['tvg_id'] for e in epg_json if e['tvg_id'])
        logger.info(f"Available EPG TVG IDs: {', '.join(sorted(unique_epg_tvg_ids))}")

        payload = {
            "channels": channels_json,
            "epg_data": epg_json,
            "region_code": region_code,
        }

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(json.dumps(payload).encode('utf-8'))
            temp_file_path = temp_file.name

        # After writing to the file but before subprocess
        # Explicitly delete the large data structures
        del payload
        gc.collect()

        process = subprocess.Popen(
            ['python', '/app/scripts/epg_match.py', temp_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout = ''
        block_size = 1024

        while True:
            # Monitor stdout and stderr for readability
            readable, _, _ = select.select([process.stdout, process.stderr], [], [], 1) # timeout of 1 second

            if not readable: # timeout expired
                if process.poll() is not None: # check if process finished
                    break
                else: # process still running, continue
                    continue

            for stream in readable:
                if stream == process.stdout:
                    stdout += stream.read(block_size)
                elif stream == process.stderr:
                    error = stream.readline()
                    if error:
                        logger.info(error.strip())

            if process.poll() is not None:
                break

        process.wait()
        os.remove(temp_file_path)

        if process.returncode != 0:
            return f"Failed to process EPG matching"

        result = json.loads(stdout)
        # This returns lists of dicts, not model objects
        channels_to_update_dicts = result["channels_to_update"]
        matched_channels = result["matched_channels"]

        # Explicitly clean up large objects
        del stdout, result
        gc.collect()

        # Convert your dict-based 'channels_to_update' into real Channel objects
        if channels_to_update_dicts:
            # Extract IDs of the channels that need updates
            channel_ids = [d["id"] for d in channels_to_update_dicts]

            # Fetch them from DB
            channels_qs = Channel.objects.filter(id__in=channel_ids)
            channels_list = list(channels_qs)

            # Build a map from channel_id -> epg_data_id (or whatever fields you need)
            epg_mapping = {
                d["id"]: d["epg_data_id"] for d in channels_to_update_dicts
            }

            # Populate each Channel object with the updated epg_data_id
            for channel_obj in channels_list:
                # The script sets 'epg_data_id' in the returned dict
                # We either assign directly, or fetch the EPGData instance if needed.
                channel_obj.epg_data_id = epg_mapping.get(channel_obj.id)

            # Now we have real model objects, so bulk_update will work
            Channel.objects.bulk_update(channels_list, ["epg_data"])

        total_matched = len(matched_channels)
        if total_matched:
            logger.info(f"Match Summary: {total_matched} channel(s) matched.")
            for (cid, cname, tvg) in matched_channels:
                logger.info(f"  - Channel ID={cid}, Name='{cname}' => tvg_id='{tvg}'")
        else:
            logger.info("No new channels were matched.")

        logger.info("Finished EPG matching logic.")

        # Send update with additional information for refreshing UI
        channel_layer = get_channel_layer()
        associations = [
            {"channel_id": chan["id"], "epg_data_id": chan["epg_data_id"]}
            for chan in channels_to_update_dicts
        ]

        async_to_sync(channel_layer.group_send)(
            'updates',
            {
                'type': 'update',
                "data": {
                    "success": True,
                    "type": "epg_match",
                    "refresh_channels": True,  # Flag to tell frontend to refresh channels
                    "matches_count": total_matched,
                    "message": f"EPG matching complete: {total_matched} channel(s) matched",
                    "associations": associations  # Add the associations data
                }
            }
        )

        return f"Done. Matched {total_matched} channel(s)."
    finally:
        # Final cleanup
        gc.collect()
        # Use our standardized cleanup function for more thorough memory management
        from core.utils import cleanup_memory
        cleanup_memory(log_usage=True, force_collection=True)


@shared_task
def run_recording(channel_id, start_time_str, end_time_str):
    channel = Channel.objects.get(id=channel_id)

    start_time = datetime.fromisoformat(start_time_str)
    end_time = datetime.fromisoformat(end_time_str)

    duration_seconds = int((end_time - start_time).total_seconds())
    filename = f'{slugify(channel.name)}-{start_time.strftime("%Y-%m-%d_%H-%M-%S")}.mp4'

    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        "updates",
        {
            "type": "update",
            "data": {"success": True, "type": "recording_started", "channel": channel.name}
        },
    )

    logger.info(f"Starting recording for channel {channel.name}")
    backend_host = os.environ.get("BACKEND_HOST", "backend")
    backend_port = os.environ.get("BACKEND_PORT", "5656")
    with requests.get(f"http://{backend_host}:{backend_port}/proxy/ts/stream/{channel.uuid}", headers={
        'User-Agent': 'Dispatcharr-DVR',
    }, stream=True) as response:
        # Raise an exception for bad responses (4xx, 5xx)
        response.raise_for_status()

        # Open the file in write-binary mode
        with open(f"/data/recordings/{filename}", 'wb') as file:
            start_time = time.time()  # Start the timer
            for chunk in response.iter_content(chunk_size=8192):  # 8KB chunks
                if time.time() - start_time > duration_seconds:
                    print(f"Timeout reached: {duration_seconds} seconds")
                    break
                # Write the chunk to the file
                file.write(chunk)

        async_to_sync(channel_layer.group_send)(
            "updates",
            {
                "type": "update",
                "data": {"success": True, "type": "recording_ended", "channel": channel.name}
            },
        )

        # After the loop, the file and response are closed automatically.
        logger.info(f"Finished recording for channel {channel.name}")
