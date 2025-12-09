# apps/channels/tasks.py
import logging
import os
import select
import re
import requests
import time
import json
import subprocess
import signal
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
import gc

from celery import shared_task
from django.utils.text import slugify
from rapidfuzz import fuzz

from apps.channels.models import Channel
from apps.epg.models import EPGData
from core.models import CoreSettings

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import tempfile
from urllib.parse import quote

logger = logging.getLogger(__name__)

# PostgreSQL btree index has a limit of ~2704 bytes (1/3 of 8KB page size)
# We use 2000 as a safe maximum to account for multibyte characters
def validate_logo_url(logo_url, max_length=2000):
    """
    Fast validation for logo URLs during bulk creation.
    Returns None if URL is too long (would exceed PostgreSQL btree index limit),
    original URL otherwise.

    PostgreSQL btree indexes have a maximum size of ~2704 bytes. URLs longer than
    this cannot be indexed and would cause database errors. These are typically
    base64-encoded images embedded in URLs.
    """
    if logo_url and len(logo_url) > max_length:
        logger.warning(f"Logo URL too long ({len(logo_url)} > {max_length}), skipping: {logo_url[:100]}...")
        return None
    return logo_url

def send_epg_matching_progress(total_channels, matched_channels, current_channel_name="", stage="matching"):
    """
    Send EPG matching progress via WebSocket
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            progress_data = {
                'type': 'epg_matching_progress',
                'total': total_channels,
                'matched': len(matched_channels) if isinstance(matched_channels, list) else matched_channels,
                'remaining': total_channels - (len(matched_channels) if isinstance(matched_channels, list) else matched_channels),
                'current_channel': current_channel_name,
                'stage': stage,
                'progress_percent': round((len(matched_channels) if isinstance(matched_channels, list) else matched_channels) / total_channels * 100, 1) if total_channels > 0 else 0
            }

            async_to_sync(channel_layer.group_send)(
                "updates",
                {
                    "type": "update",
                    "data": {
                        "type": "epg_matching_progress",
                        **progress_data
                    }
                }
            )
    except Exception as e:
        logger.warning(f"Failed to send EPG matching progress: {e}")

# Lazy loading for ML models - only imported/loaded when needed
_ml_model_cache = {
    'sentence_transformer': None
}

def get_sentence_transformer():
    """Lazy load the sentence transformer model only when needed"""
    if _ml_model_cache['sentence_transformer'] is None:
        try:
            from sentence_transformers import SentenceTransformer
            from sentence_transformers import util

            model_name = "sentence-transformers/all-MiniLM-L6-v2"
            cache_dir = "/data/models"

            # Check environment variable to disable downloads
            disable_downloads = os.environ.get('DISABLE_ML_DOWNLOADS', 'false').lower() == 'true'

            if disable_downloads:
                # Check if model exists before attempting to load
                hf_model_path = os.path.join(cache_dir, f"models--{model_name.replace('/', '--')}")
                if not os.path.exists(hf_model_path):
                    logger.warning("ML model not found and downloads disabled (DISABLE_ML_DOWNLOADS=true). Skipping ML matching.")
                    return None, None

            # Ensure cache directory exists
            os.makedirs(cache_dir, exist_ok=True)

            # Let sentence-transformers handle all cache detection and management
            logger.info(f"Loading sentence transformer model (cache: {cache_dir})")
            _ml_model_cache['sentence_transformer'] = SentenceTransformer(
                model_name,
                cache_folder=cache_dir
            )

            return _ml_model_cache['sentence_transformer'], util
        except ImportError:
            logger.warning("sentence-transformers not available - ML-enhanced matching disabled")
            return None, None
        except Exception as e:
            logger.error(f"Failed to load sentence transformer: {e}")
            return None, None
    else:
        from sentence_transformers import util
        return _ml_model_cache['sentence_transformer'], util

# ML matching thresholds (same as original script)
BEST_FUZZY_THRESHOLD = 85
LOWER_FUZZY_THRESHOLD = 40
EMBED_SIM_THRESHOLD = 0.65

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

    # Extract and preserve important call signs from parentheses before removing them
    # This captures call signs like (KVLY), (KING), (KARE), etc.
    call_sign_match = re.search(r"\(([A-Z]{3,5})\)", name)
    preserved_call_sign = ""
    if call_sign_match:
        preserved_call_sign = " " + call_sign_match.group(1).lower()

    # Now remove all parentheses content
    norm = re.sub(r"\(.*?\)", "", norm)

    # Add back the preserved call sign
    norm = norm + preserved_call_sign

    norm = re.sub(r"[^\w\s]", "", norm)
    tokens = norm.split()
    tokens = [t for t in tokens if t not in COMMON_EXTRANEOUS_WORDS]
    norm = " ".join(tokens).strip()
    return norm

def match_channels_to_epg(channels_data, epg_data, region_code=None, use_ml=True, send_progress=True):
    """
    EPG matching logic that finds the best EPG matches for channels using
    multiple matching strategies including fuzzy matching and ML models.

    Automatically uses conservative thresholds for bulk matching (multiple channels)
    to avoid bad matches that create user cleanup work, and aggressive thresholds
    for single channel matching where users specifically requested a match attempt.
    """
    channels_to_update = []
    matched_channels = []
    total_channels = len(channels_data)

    # Send initial progress
    if send_progress:
        send_epg_matching_progress(total_channels, 0, stage="starting")

    # Try to get ML models if requested (but don't load yet - lazy loading)
    st_model, util = None, None
    epg_embeddings = None
    ml_available = use_ml

    # Automatically determine matching strategy based on number of channels
    is_bulk_matching = len(channels_data) > 1

    # Adjust matching thresholds based on operation type
    if is_bulk_matching:
        # Conservative thresholds for bulk matching to avoid creating cleanup work
        FUZZY_HIGH_CONFIDENCE = 90      # Only very high fuzzy scores
        FUZZY_MEDIUM_CONFIDENCE = 70    # Higher threshold for ML enhancement
        ML_HIGH_CONFIDENCE = 0.75       # Higher ML confidence required
        ML_LAST_RESORT = 0.65          # More conservative last resort
        FUZZY_LAST_RESORT_MIN = 50     # Higher fuzzy minimum for last resort
        logger.info(f"Using conservative thresholds for bulk matching ({total_channels} channels)")
    else:
        # More aggressive thresholds for single channel matching (user requested specific match)
        FUZZY_HIGH_CONFIDENCE = 85      # Original threshold
        FUZZY_MEDIUM_CONFIDENCE = 40    # Original threshold
        ML_HIGH_CONFIDENCE = 0.65       # Original threshold
        ML_LAST_RESORT = 0.50          # Original desperate threshold
        FUZZY_LAST_RESORT_MIN = 20     # Original minimum
        logger.info("Using aggressive thresholds for single channel matching")    # Process each channel
    for index, chan in enumerate(channels_data):
        normalized_tvg_id = chan.get("tvg_id", "")
        fallback_name = chan["tvg_id"].strip() if chan["tvg_id"] else chan["name"]

        # Send progress update every 5 channels or for the first few
        if send_progress and (index < 5 or index % 5 == 0 or index == total_channels - 1):
            send_epg_matching_progress(
                total_channels,
                len(matched_channels),
                current_channel_name=chan["name"][:50],  # Truncate long names
                stage="matching"
            )
        normalized_tvg_id = chan.get("tvg_id", "")
        fallback_name = chan["tvg_id"].strip() if chan["tvg_id"] else chan["name"]

        # Step 1: Exact TVG ID match
        epg_by_tvg_id = next((epg for epg in epg_data if epg["tvg_id"] == normalized_tvg_id), None)
        if normalized_tvg_id and epg_by_tvg_id:
            chan["epg_data_id"] = epg_by_tvg_id["id"]
            channels_to_update.append(chan)
            matched_channels.append((chan['id'], fallback_name, epg_by_tvg_id["tvg_id"]))
            logger.info(f"Channel {chan['id']} '{fallback_name}' => EPG found by exact tvg_id={epg_by_tvg_id['tvg_id']}")
            continue

        # Step 2: Secondary TVG ID check (legacy compatibility)
        if chan["tvg_id"]:
            epg_match = [epg["id"] for epg in epg_data if epg["tvg_id"] == chan["tvg_id"]]
            if epg_match:
                chan["epg_data_id"] = epg_match[0]
                channels_to_update.append(chan)
                matched_channels.append((chan['id'], fallback_name, chan["tvg_id"]))
                logger.info(f"Channel {chan['id']} '{chan['name']}' => EPG found by secondary tvg_id={chan['tvg_id']}")
                continue

        # Step 2.5: Exact Gracenote ID match
        normalized_gracenote_id = chan.get("gracenote_id", "")
        if normalized_gracenote_id:
            epg_by_gracenote_id = next((epg for epg in epg_data if epg["tvg_id"] == normalized_gracenote_id), None)
            if epg_by_gracenote_id:
                chan["epg_data_id"] = epg_by_gracenote_id["id"]
                channels_to_update.append(chan)
                matched_channels.append((chan['id'], fallback_name, f"gracenote:{epg_by_gracenote_id['tvg_id']}"))
                logger.info(f"Channel {chan['id']} '{fallback_name}' => EPG found by exact gracenote_id={normalized_gracenote_id}")
                continue

        # Step 3: Name-based fuzzy matching
        if not chan["norm_chan"]:
            logger.debug(f"Channel {chan['id']} '{chan['name']}' => empty after normalization, skipping")
            continue

        best_score = 0
        best_epg = None

        # Debug: show what we're matching against
        logger.debug(f"Fuzzy matching '{chan['norm_chan']}' against EPG entries...")

        # Find best fuzzy match
        for row in epg_data:
            if not row.get("norm_name"):
                continue

            base_score = fuzz.ratio(chan["norm_chan"], row["norm_name"])
            bonus = 0

            # Apply region-based bonus/penalty
            if region_code and row.get("tvg_id"):
                combined_text = row["tvg_id"].lower() + " " + row["name"].lower()
                dot_regions = re.findall(r'\.([a-z]{2})', combined_text)

                if dot_regions:
                    if region_code in dot_regions:
                        bonus = 15  # Bigger bonus for matching region
                    else:
                        bonus = -15  # Penalty for different region
                elif region_code in combined_text:
                    bonus = 10

            score = base_score + bonus

            # Debug the best few matches
            if score > 50:  # Only show decent matches
                logger.debug(f"  EPG '{row['name']}' (norm: '{row['norm_name']}') => score: {score} (base: {base_score}, bonus: {bonus})")

            # When scores are equal, prefer higher priority EPG source
            row_priority = row.get('epg_source_priority', 0)
            best_priority = best_epg.get('epg_source_priority', 0) if best_epg else -1

            if score > best_score or (score == best_score and row_priority > best_priority):
                best_score = score
                best_epg = row

        # Log the best score we found
        if best_epg:
            logger.info(f"Channel {chan['id']} '{chan['name']}' => best match: '{best_epg['name']}' (score: {best_score})")
        else:
            logger.debug(f"Channel {chan['id']} '{chan['name']}' => no EPG entries with valid norm_name found")
            continue

        # High confidence match - accept immediately
        if best_score >= FUZZY_HIGH_CONFIDENCE:
            chan["epg_data_id"] = best_epg["id"]
            channels_to_update.append(chan)
            matched_channels.append((chan['id'], chan['name'], best_epg["tvg_id"]))
            logger.info(f"Channel {chan['id']} '{chan['name']}' => matched tvg_id={best_epg['tvg_id']} (score={best_score})")

        # Medium confidence - use ML if available (lazy load models here)
        elif best_score >= FUZZY_MEDIUM_CONFIDENCE and ml_available:
            # Lazy load ML models only when we actually need them
            if st_model is None:
                st_model, util = get_sentence_transformer()

            # Lazy generate embeddings only when we actually need them
            if epg_embeddings is None and st_model and any(row.get("norm_name") for row in epg_data):
                try:
                    logger.info("Generating embeddings for EPG data using ML model (lazy loading)")
                    epg_embeddings = st_model.encode(
                        [row["norm_name"] for row in epg_data if row.get("norm_name")],
                        convert_to_tensor=True
                    )
                except Exception as e:
                    logger.warning(f"Failed to generate embeddings: {e}")
                    epg_embeddings = None

            if epg_embeddings is not None and st_model:
                try:
                    # Generate embedding for this channel
                    chan_embedding = st_model.encode(chan["norm_chan"], convert_to_tensor=True)

                    # Calculate similarity with all EPG embeddings
                    sim_scores = util.cos_sim(chan_embedding, epg_embeddings)[0]
                    top_index = int(sim_scores.argmax())
                    top_value = float(sim_scores[top_index])

                    if top_value >= ML_HIGH_CONFIDENCE:
                        # Find the EPG entry that corresponds to this embedding index
                        epg_with_names = [epg for epg in epg_data if epg.get("norm_name")]
                        matched_epg = epg_with_names[top_index]

                        chan["epg_data_id"] = matched_epg["id"]
                        channels_to_update.append(chan)
                        matched_channels.append((chan['id'], chan['name'], matched_epg["tvg_id"]))
                        logger.info(f"Channel {chan['id']} '{chan['name']}' => matched EPG tvg_id={matched_epg['tvg_id']} (fuzzy={best_score}, ML-sim={top_value:.2f})")
                    else:
                        logger.info(f"Channel {chan['id']} '{chan['name']}' => fuzzy={best_score}, ML-sim={top_value:.2f} < {ML_HIGH_CONFIDENCE}, trying last resort...")

                        # Last resort: try ML with very low fuzzy threshold
                        if top_value >= ML_LAST_RESORT:  # Dynamic last resort threshold
                            epg_with_names = [epg for epg in epg_data if epg.get("norm_name")]
                            matched_epg = epg_with_names[top_index]

                            chan["epg_data_id"] = matched_epg["id"]
                            channels_to_update.append(chan)
                            matched_channels.append((chan['id'], chan['name'], matched_epg["tvg_id"]))
                            logger.info(f"Channel {chan['id']} '{chan['name']}' => LAST RESORT match EPG tvg_id={matched_epg['tvg_id']} (fuzzy={best_score}, ML-sim={top_value:.2f})")
                        else:
                            logger.info(f"Channel {chan['id']} '{chan['name']}' => even last resort ML-sim {top_value:.2f} < {ML_LAST_RESORT}, skipping")

                except Exception as e:
                    logger.warning(f"ML matching failed for channel {chan['id']}: {e}")
                    # Fall back to non-ML decision
                    logger.info(f"Channel {chan['id']} '{chan['name']}' => fuzzy score {best_score} below threshold, skipping")

        # Last resort: Try ML matching even with very low fuzzy scores
        elif best_score >= FUZZY_LAST_RESORT_MIN and ml_available:
            # Lazy load ML models for last resort attempts
            if st_model is None:
                st_model, util = get_sentence_transformer()

            # Lazy generate embeddings for last resort attempts
            if epg_embeddings is None and st_model and any(row.get("norm_name") for row in epg_data):
                try:
                    logger.info("Generating embeddings for EPG data using ML model (last resort lazy loading)")
                    epg_embeddings = st_model.encode(
                        [row["norm_name"] for row in epg_data if row.get("norm_name")],
                        convert_to_tensor=True
                    )
                except Exception as e:
                    logger.warning(f"Failed to generate embeddings for last resort: {e}")
                    epg_embeddings = None

            if epg_embeddings is not None and st_model:
                try:
                    logger.info(f"Channel {chan['id']} '{chan['name']}' => trying ML as last resort (fuzzy={best_score})")
                    # Generate embedding for this channel
                    chan_embedding = st_model.encode(chan["norm_chan"], convert_to_tensor=True)

                    # Calculate similarity with all EPG embeddings
                    sim_scores = util.cos_sim(chan_embedding, epg_embeddings)[0]
                    top_index = int(sim_scores.argmax())
                    top_value = float(sim_scores[top_index])

                    if top_value >= ML_LAST_RESORT:  # Dynamic threshold for desperate attempts
                        # Find the EPG entry that corresponds to this embedding index
                        epg_with_names = [epg for epg in epg_data if epg.get("norm_name")]
                        matched_epg = epg_with_names[top_index]

                        chan["epg_data_id"] = matched_epg["id"]
                        channels_to_update.append(chan)
                        matched_channels.append((chan['id'], chan['name'], matched_epg["tvg_id"]))
                        logger.info(f"Channel {chan['id']} '{chan['name']}' => DESPERATE LAST RESORT match EPG tvg_id={matched_epg['tvg_id']} (fuzzy={best_score}, ML-sim={top_value:.2f})")
                    else:
                        logger.info(f"Channel {chan['id']} '{chan['name']}' => desperate last resort ML-sim {top_value:.2f} < {ML_LAST_RESORT}, giving up")
                except Exception as e:
                    logger.warning(f"Last resort ML matching failed for channel {chan['id']}: {e}")
                    logger.info(f"Channel {chan['id']} '{chan['name']}' => best fuzzy score={best_score} < {FUZZY_MEDIUM_CONFIDENCE}, giving up")
        else:
            # No ML available or very low fuzzy score
            logger.info(f"Channel {chan['id']} '{chan['name']}' => best fuzzy score={best_score} < {FUZZY_MEDIUM_CONFIDENCE}, no ML fallback available")

    # Clean up ML models from memory after matching (infrequent operation)
    if _ml_model_cache['sentence_transformer'] is not None:
        logger.info("Cleaning up ML models from memory")
        _ml_model_cache['sentence_transformer'] = None
        gc.collect()

    # Send final progress update
    if send_progress:
        send_epg_matching_progress(
            total_channels,
            len(matched_channels),
            stage="completed"
        )

    return {
        "channels_to_update": channels_to_update,
        "matched_channels": matched_channels
    }

@shared_task
def match_epg_channels():
    """
    Uses integrated EPG matching instead of external script.
    Provides the same functionality with better performance and maintainability.
    """
    try:
        logger.info("Starting integrated EPG matching...")

        # Get region preference
        try:
            region_obj = CoreSettings.objects.get(key="preferred-region")
            region_code = region_obj.value.strip().lower()
        except CoreSettings.DoesNotExist:
            region_code = None

        # Get channels that don't have EPG data assigned
        channels_without_epg = Channel.objects.filter(epg_data__isnull=True)
        logger.info(f"Found {channels_without_epg.count()} channels without EPG data")

        channels_data = []
        for channel in channels_without_epg:
            normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
            normalized_gracenote_id = channel.tvc_guide_stationid.strip().lower() if channel.tvc_guide_stationid else ""
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "tvg_id": normalized_tvg_id,
                "original_tvg_id": channel.tvg_id,
                "gracenote_id": normalized_gracenote_id,
                "original_gracenote_id": channel.tvc_guide_stationid,
                "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
                "norm_chan": normalize_name(channel.name)  # Always use channel name for fuzzy matching!
            })

        # Get all EPG data from active sources, ordered by source priority (highest first) so we prefer higher priority matches
        epg_data = []
        for epg in EPGData.objects.select_related('epg_source').filter(epg_source__is_active=True):
            normalized_tvg_id = epg.tvg_id.strip().lower() if epg.tvg_id else ""
            epg_data.append({
                'id': epg.id,
                'tvg_id': normalized_tvg_id,
                'original_tvg_id': epg.tvg_id,
                'name': epg.name,
                'norm_name': normalize_name(epg.name),
                'epg_source_id': epg.epg_source.id if epg.epg_source else None,
                'epg_source_priority': epg.epg_source.priority if epg.epg_source else 0,
            })

        # Sort EPG data by source priority (highest first) so we prefer higher priority matches
        epg_data.sort(key=lambda x: x['epg_source_priority'], reverse=True)

        logger.info(f"Processing {len(channels_data)} channels against {len(epg_data)} EPG entries (from active sources only)")

        # Run EPG matching with progress updates - automatically uses conservative thresholds for bulk operations
        result = match_channels_to_epg(channels_data, epg_data, region_code, use_ml=True, send_progress=True)
        channels_to_update_dicts = result["channels_to_update"]
        matched_channels = result["matched_channels"]

        # Update channels in database
        if channels_to_update_dicts:
            channel_ids = [d["id"] for d in channels_to_update_dicts]
            channels_qs = Channel.objects.filter(id__in=channel_ids)
            channels_list = list(channels_qs)

            # Create mapping from channel_id to epg_data_id
            epg_mapping = {d["id"]: d["epg_data_id"] for d in channels_to_update_dicts}

            # Update each channel with matched EPG data
            for channel_obj in channels_list:
                epg_data_id = epg_mapping.get(channel_obj.id)
                if epg_data_id:
                    try:
                        epg_data_obj = EPGData.objects.get(id=epg_data_id)
                        channel_obj.epg_data = epg_data_obj
                    except EPGData.DoesNotExist:
                        logger.error(f"EPG data {epg_data_id} not found for channel {channel_obj.id}")

            # Bulk update all channels
            Channel.objects.bulk_update(channels_list, ["epg_data"])

        total_matched = len(matched_channels)
        if total_matched:
            logger.info(f"Match Summary: {total_matched} channel(s) matched.")
            for (cid, cname, tvg) in matched_channels:
                logger.info(f"  - Channel ID={cid}, Name='{cname}' => tvg_id='{tvg}'")
        else:
            logger.info("No new channels were matched.")

        logger.info("Finished integrated EPG matching.")

        # Send WebSocket update
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
                    "refresh_channels": True,
                    "matches_count": total_matched,
                    "message": f"EPG matching complete: {total_matched} channel(s) matched",
                    "associations": associations
                }
            }
        )

        return f"Done. Matched {total_matched} channel(s)."

    finally:
        # Clean up ML models from memory after bulk matching
        if _ml_model_cache['sentence_transformer'] is not None:
            logger.info("Cleaning up ML models from memory")
            _ml_model_cache['sentence_transformer'] = None

        # Memory cleanup
        gc.collect()
        from core.utils import cleanup_memory
        cleanup_memory(log_usage=True, force_collection=True)


@shared_task
def match_selected_channels_epg(channel_ids):
    """
    Match EPG data for only the specified selected channels.
    Uses the same integrated EPG matching logic but processes only selected channels.
    """
    try:
        logger.info(f"Starting integrated EPG matching for {len(channel_ids)} selected channels...")

        # Get region preference
        try:
            region_obj = CoreSettings.objects.get(key="preferred-region")
            region_code = region_obj.value.strip().lower()
        except CoreSettings.DoesNotExist:
            region_code = None

        # Get only the specified channels that don't have EPG data assigned
        channels_without_epg = Channel.objects.filter(
            id__in=channel_ids,
            epg_data__isnull=True
        )
        logger.info(f"Found {channels_without_epg.count()} selected channels without EPG data")

        if not channels_without_epg.exists():
            logger.info("No selected channels need EPG matching.")

            # Send WebSocket update
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'updates',
                {
                    'type': 'update',
                    "data": {
                        "success": True,
                        "type": "epg_match",
                        "refresh_channels": True,
                        "matches_count": 0,
                        "message": "No selected channels need EPG matching",
                        "associations": []
                    }
                }
            )
            return "No selected channels needed EPG matching."

        channels_data = []
        for channel in channels_without_epg:
            normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
            normalized_gracenote_id = channel.tvc_guide_stationid.strip().lower() if channel.tvc_guide_stationid else ""
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "tvg_id": normalized_tvg_id,
                "original_tvg_id": channel.tvg_id,
                "gracenote_id": normalized_gracenote_id,
                "original_gracenote_id": channel.tvc_guide_stationid,
                "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
                "norm_chan": normalize_name(channel.name)
            })

        # Get all EPG data from active sources, ordered by source priority (highest first) so we prefer higher priority matches
        epg_data = []
        for epg in EPGData.objects.select_related('epg_source').filter(epg_source__is_active=True):
            normalized_tvg_id = epg.tvg_id.strip().lower() if epg.tvg_id else ""
            epg_data.append({
                'id': epg.id,
                'tvg_id': normalized_tvg_id,
                'original_tvg_id': epg.tvg_id,
                'name': epg.name,
                'norm_name': normalize_name(epg.name),
                'epg_source_id': epg.epg_source.id if epg.epg_source else None,
                'epg_source_priority': epg.epg_source.priority if epg.epg_source else 0,
            })

        # Sort EPG data by source priority (highest first) so we prefer higher priority matches
        epg_data.sort(key=lambda x: x['epg_source_priority'], reverse=True)

        logger.info(f"Processing {len(channels_data)} selected channels against {len(epg_data)} EPG entries (from active sources only)")

        # Run EPG matching with progress updates - automatically uses appropriate thresholds
        result = match_channels_to_epg(channels_data, epg_data, region_code, use_ml=True, send_progress=True)
        channels_to_update_dicts = result["channels_to_update"]
        matched_channels = result["matched_channels"]

        # Update channels in database
        if channels_to_update_dicts:
            channel_ids_to_update = [d["id"] for d in channels_to_update_dicts]
            channels_qs = Channel.objects.filter(id__in=channel_ids_to_update)
            channels_list = list(channels_qs)

            # Create mapping from channel_id to epg_data_id
            epg_mapping = {d["id"]: d["epg_data_id"] for d in channels_to_update_dicts}

            # Update each channel with matched EPG data
            for channel_obj in channels_list:
                epg_data_id = epg_mapping.get(channel_obj.id)
                if epg_data_id:
                    try:
                        epg_data_obj = EPGData.objects.get(id=epg_data_id)
                        channel_obj.epg_data = epg_data_obj
                    except EPGData.DoesNotExist:
                        logger.error(f"EPG data {epg_data_id} not found for channel {channel_obj.id}")

            # Bulk update all channels
            Channel.objects.bulk_update(channels_list, ["epg_data"])

        total_matched = len(matched_channels)
        if total_matched:
            logger.info(f"Selected Channel Match Summary: {total_matched} channel(s) matched.")
            for (cid, cname, tvg) in matched_channels:
                logger.info(f"  - Channel ID={cid}, Name='{cname}' => tvg_id='{tvg}'")
        else:
            logger.info("No selected channels were matched.")

        logger.info("Finished integrated EPG matching for selected channels.")

        # Send WebSocket update
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
                    "refresh_channels": True,
                    "matches_count": total_matched,
                    "message": f"EPG matching complete: {total_matched} selected channel(s) matched",
                    "associations": associations
                }
            }
        )

        return f"Done. Matched {total_matched} selected channel(s)."

    finally:
        # Clean up ML models from memory after bulk matching
        if _ml_model_cache['sentence_transformer'] is not None:
            logger.info("Cleaning up ML models from memory")
            _ml_model_cache['sentence_transformer'] = None

        # Memory cleanup
        gc.collect()
        from core.utils import cleanup_memory
        cleanup_memory(log_usage=True, force_collection=True)


@shared_task
def match_single_channel_epg(channel_id):
    """
    Try to match a single channel with EPG data using the integrated matching logic
    that includes both fuzzy and ML-enhanced matching. Returns a dict with match status and message.
    """
    try:
        from apps.channels.models import Channel
        from apps.epg.models import EPGData

        logger.info(f"Starting integrated single channel EPG matching for channel ID {channel_id}")

        # Get the channel
        try:
            channel = Channel.objects.get(id=channel_id)
        except Channel.DoesNotExist:
            return {"matched": False, "message": "Channel not found"}

        # If channel already has EPG data, skip
        if channel.epg_data:
            return {"matched": False, "message": f"Channel '{channel.name}' already has EPG data assigned"}

        # Prepare single channel data for matching (same format as bulk matching)
        normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
        normalized_gracenote_id = channel.tvc_guide_stationid.strip().lower() if channel.tvc_guide_stationid else ""
        channel_data = {
            "id": channel.id,
            "name": channel.name,
            "tvg_id": normalized_tvg_id,
            "original_tvg_id": channel.tvg_id,
            "gracenote_id": normalized_gracenote_id,
            "original_gracenote_id": channel.tvc_guide_stationid,
            "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
            "norm_chan": normalize_name(channel.name)  # Always use channel name for fuzzy matching!
        }

        logger.info(f"Channel data prepared: name='{channel.name}', tvg_id='{normalized_tvg_id}', gracenote_id='{normalized_gracenote_id}', norm_chan='{channel_data['norm_chan']}'")

        # Debug: Test what the normalization does to preserve call signs
        test_name = "NBC 11 (KVLY) - Fargo"  # Example for testing
        test_normalized = normalize_name(test_name)
        logger.debug(f"DEBUG normalization example: '{test_name}' → '{test_normalized}' (call sign preserved)")

        # Get all EPG data for matching from active sources - must include norm_name field
        # Ordered by source priority (highest first) so we prefer higher priority matches
        epg_data_list = []
        for epg in EPGData.objects.select_related('epg_source').filter(epg_source__is_active=True, name__isnull=False).exclude(name=''):
            normalized_epg_tvg_id = epg.tvg_id.strip().lower() if epg.tvg_id else ""
            epg_data_list.append({
                'id': epg.id,
                'tvg_id': normalized_epg_tvg_id,
                'original_tvg_id': epg.tvg_id,
                'name': epg.name,
                'norm_name': normalize_name(epg.name),
                'epg_source_id': epg.epg_source.id if epg.epg_source else None,
                'epg_source_priority': epg.epg_source.priority if epg.epg_source else 0,
            })

        # Sort EPG data by source priority (highest first) so we prefer higher priority matches
        epg_data_list.sort(key=lambda x: x['epg_source_priority'], reverse=True)

        if not epg_data_list:
            return {"matched": False, "message": "No EPG data available for matching (from active sources)"}

        logger.info(f"Matching single channel '{channel.name}' against {len(epg_data_list)} EPG entries")

        # Send progress for single channel matching
        send_epg_matching_progress(1, 0, current_channel_name=channel.name, stage="matching")

        # Use the EPG matching function - automatically uses aggressive thresholds for single channel
        result = match_channels_to_epg([channel_data], epg_data_list, send_progress=False)
        channels_to_update = result.get("channels_to_update", [])
        matched_channels = result.get("matched_channels", [])

        if channels_to_update:
            # Find our channel in the results
            channel_match = None
            for update in channels_to_update:
                if update["id"] == channel.id:
                    channel_match = update
                    break

            if channel_match:
                # Apply the match to the channel
                try:
                    epg_data = EPGData.objects.get(id=channel_match['epg_data_id'])
                    channel.epg_data = epg_data
                    channel.save(update_fields=["epg_data"])

                    # Find match details from matched_channels for better reporting
                    match_details = None
                    for match_info in matched_channels:
                        if match_info[0] == channel.id:  # matched_channels format: (channel_id, channel_name, epg_info)
                            match_details = match_info
                            break

                    success_msg = f"Channel '{channel.name}' matched with EPG '{epg_data.name}'"
                    if match_details:
                        success_msg += f" (matched via: {match_details[2]})"

                    logger.info(success_msg)

                    # Send completion progress for single channel
                    send_epg_matching_progress(1, 1, current_channel_name=channel.name, stage="completed")

                    # Clean up ML models from memory after single channel matching
                    if _ml_model_cache['sentence_transformer'] is not None:
                        logger.info("Cleaning up ML models from memory")
                        _ml_model_cache['sentence_transformer'] = None
                        gc.collect()

                    return {
                        "matched": True,
                        "message": success_msg,
                        "epg_name": epg_data.name,
                        "epg_id": epg_data.id
                    }
                except EPGData.DoesNotExist:
                    return {"matched": False, "message": "Matched EPG data not found"}

        # No match found
        # Send completion progress for single channel (failed)
        send_epg_matching_progress(1, 0, current_channel_name=channel.name, stage="completed")

        # Clean up ML models from memory after single channel matching
        if _ml_model_cache['sentence_transformer'] is not None:
            logger.info("Cleaning up ML models from memory")
            _ml_model_cache['sentence_transformer'] = None
            gc.collect()

        return {
            "matched": False,
            "message": f"No suitable EPG match found for channel '{channel.name}'"
        }

    except Exception as e:
        logger.error(f"Error in integrated single channel EPG matching: {e}", exc_info=True)

        # Clean up ML models from memory even on error
        if _ml_model_cache['sentence_transformer'] is not None:
            logger.info("Cleaning up ML models from memory after error")
            _ml_model_cache['sentence_transformer'] = None
            gc.collect()

        return {"matched": False, "message": f"Error during matching: {str(e)}"}


def evaluate_series_rules_impl(tvg_id: str | None = None):
    """Synchronous implementation of series rule evaluation; returns details for debugging."""
    from django.utils import timezone
    from apps.channels.models import Recording, Channel
    from apps.epg.models import EPGData, ProgramData

    rules = CoreSettings.get_dvr_series_rules()
    result = {"scheduled": 0, "details": []}
    if not isinstance(rules, list) or not rules:
        return result

    # Optionally filter for tvg_id
    if tvg_id:
        rules = [r for r in rules if str(r.get("tvg_id")) == str(tvg_id)]
        if not rules:
            result["details"].append({"tvg_id": tvg_id, "status": "no_rule"})
            return result

    now = timezone.now()
    horizon = now + timedelta(days=7)

    # Preload existing recordings' program ids to avoid duplicates
    existing_program_ids = set()
    for rec in Recording.objects.all().only("custom_properties"):
        try:
            pid = rec.custom_properties.get("program", {}).get("id") if rec.custom_properties else None
            if pid is not None:
                # Normalize to string for consistent comparisons
                existing_program_ids.add(str(pid))
        except Exception:
            continue

    for rule in rules:
        rv_tvg = str(rule.get("tvg_id") or "").strip()
        mode = (rule.get("mode") or "all").lower()
        series_title = (rule.get("title") or "").strip()
        norm_series = normalize_name(series_title) if series_title else None
        if not rv_tvg:
            result["details"].append({"tvg_id": rv_tvg, "status": "invalid_rule"})
            continue

        epg = EPGData.objects.filter(tvg_id=rv_tvg).first()
        if not epg:
            result["details"].append({"tvg_id": rv_tvg, "status": "no_epg_match"})
            continue

        programs_qs = ProgramData.objects.filter(
                epg=epg,
                start_time__gte=now,
                start_time__lte=horizon,
            )
        if series_title:
            programs_qs = programs_qs.filter(title__iexact=series_title)
        programs = list(programs_qs.order_by("start_time"))
        # Fallback: if no direct matches and we have a title, try normalized comparison in Python
        if series_title and not programs:
            all_progs = ProgramData.objects.filter(
                epg=epg,
                start_time__gte=now,
                start_time__lte=horizon,
            ).only("id", "title", "start_time", "end_time", "custom_properties", "tvg_id")
            programs = [p for p in all_progs if normalize_name(p.title) == norm_series]

        channel = Channel.objects.filter(epg_data=epg).order_by("channel_number").first()
        if not channel:
            result["details"].append({"tvg_id": rv_tvg, "status": "no_channel_for_epg"})
            continue

        #
        # Many providers list multiple future airings of the same episode
        # (e.g., prime-time and a late-night repeat). Previously we scheduled
        # a recording for each airing which shows up as duplicates in the DVR.
        #
        # To avoid that, we collapse programs to the earliest airing per
        # unique episode using the best identifier available:
        #  - season+episode from ProgramData.custom_properties
        #  - onscreen_episode (e.g., S08E03)
        #  - sub_title (episode name), scoped by tvg_id+series title
        # If none of the above exist, we fall back to keeping each program
        # (usually movies or specials without episode identifiers).
        #
        def _episode_key(p: "ProgramData"):
            try:
                props = p.custom_properties or {}
                season = props.get("season")
                episode = props.get("episode")
                onscreen = props.get("onscreen_episode")
            except Exception:
                season = episode = onscreen = None
            base = f"{p.tvg_id or ''}|{(p.title or '').strip().lower()}"  # series scope
            if season is not None and episode is not None:
                return f"{base}|s{season}e{episode}"
            if onscreen:
                return f"{base}|{str(onscreen).strip().lower()}"
            if p.sub_title:
                return f"{base}|{p.sub_title.strip().lower()}"
            # No reliable episode identity; use the program id to avoid over-merging
            return f"id:{p.id}"

        # Optionally filter to only brand-new episodes before grouping
        if mode == "new":
            filtered = []
            for p in programs:
                try:
                    if (p.custom_properties or {}).get("new"):
                        filtered.append(p)
                except Exception:
                    pass
            programs = filtered

        # Pick the earliest airing for each episode key
        earliest_by_key = {}
        for p in programs:
            k = _episode_key(p)
            cur = earliest_by_key.get(k)
            if cur is None or p.start_time < cur.start_time:
                earliest_by_key[k] = p

        unique_programs = list(earliest_by_key.values())

        created_here = 0
        for prog in unique_programs:
            try:
                # Skip if already scheduled by program id
                if str(prog.id) in existing_program_ids:
                    continue
                # Extra guard: skip if a recording exists for the same channel + timeslot
                try:
                    from django.db.models import Q
                    if Recording.objects.filter(
                        channel=channel,
                        start_time=prog.start_time,
                        end_time=prog.end_time,
                    ).filter(Q(custom_properties__program__id=prog.id) | Q(custom_properties__program__title=prog.title)).exists():
                        continue
                except Exception:
                    continue  # already scheduled/recorded

                # Apply global DVR pre/post offsets (in minutes)
                try:
                    pre_min = int(CoreSettings.get_dvr_pre_offset_minutes())
                except Exception:
                    pre_min = 0
                try:
                    post_min = int(CoreSettings.get_dvr_post_offset_minutes())
                except Exception:
                    post_min = 0

                adj_start = prog.start_time
                adj_end = prog.end_time
                try:
                    if pre_min and pre_min > 0:
                        adj_start = adj_start - timedelta(minutes=pre_min)
                except Exception:
                    pass
                try:
                    if post_min and post_min > 0:
                        adj_end = adj_end + timedelta(minutes=post_min)
                except Exception:
                    pass

                rec = Recording.objects.create(
                    channel=channel,
                    start_time=adj_start,
                    end_time=adj_end,
                    custom_properties={
                        "program": {
                            "id": prog.id,
                            "tvg_id": prog.tvg_id,
                            "title": prog.title,
                            "sub_title": prog.sub_title,
                            "description": prog.description,
                            "start_time": prog.start_time.isoformat(),
                            "end_time": prog.end_time.isoformat(),
                        }
                    },
                )
                existing_program_ids.add(str(prog.id))
                created_here += 1
                try:
                    prefetch_recording_artwork.apply_async(args=[rec.id], countdown=1)
                except Exception:
                    pass
            except Exception as e:
                result["details"].append({"tvg_id": rv_tvg, "status": "error", "error": str(e)})
                continue
        result["scheduled"] += created_here
        result["details"].append({"tvg_id": rv_tvg, "title": series_title, "status": "ok", "created": created_here})

    # Notify frontend to refresh
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'updates',
            {'type': 'update', 'data': {"success": True, "type": "recordings_refreshed", "scheduled": result["scheduled"]}},
        )
    except Exception:
        pass

    return result


@shared_task
def evaluate_series_rules(tvg_id: str | None = None):
    return evaluate_series_rules_impl(tvg_id)


def reschedule_upcoming_recordings_for_offset_change_impl():
    """Recalculate start/end for all future EPG-based recordings using current DVR offsets.

    Only recordings that have not yet started (start_time > now) and that were
    scheduled from EPG data (custom_properties.program present) are updated.
    """
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from apps.channels.models import Recording

    now = timezone.now()

    try:
        pre_min = int(CoreSettings.get_dvr_pre_offset_minutes())
    except Exception:
        pre_min = 0
    try:
        post_min = int(CoreSettings.get_dvr_post_offset_minutes())
    except Exception:
        post_min = 0

    changed = 0
    scanned = 0

    for rec in Recording.objects.filter(start_time__gt=now).iterator():
        scanned += 1
        try:
            cp = rec.custom_properties or {}
            program = cp.get("program") if isinstance(cp, dict) else None
            if not isinstance(program, dict):
                continue
            base_start = program.get("start_time")
            base_end = program.get("end_time")
            if not base_start or not base_end:
                continue
            start_dt = parse_datetime(str(base_start))
            end_dt = parse_datetime(str(base_end))
            if start_dt is None or end_dt is None:
                continue

            adj_start = start_dt
            adj_end = end_dt
            try:
                if pre_min and pre_min > 0:
                    adj_start = adj_start - timedelta(minutes=pre_min)
            except Exception:
                pass
            try:
                if post_min and post_min > 0:
                    adj_end = adj_end + timedelta(minutes=post_min)
            except Exception:
                pass

            if rec.start_time != adj_start or rec.end_time != adj_end:
                rec.start_time = adj_start
                rec.end_time = adj_end
                rec.save(update_fields=["start_time", "end_time"])
                changed += 1
        except Exception:
            continue

    # Notify frontend to refresh
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'updates',
            {'type': 'update', 'data': {"success": True, "type": "recordings_refreshed", "rescheduled": changed}},
        )
    except Exception:
        pass

    return {"changed": changed, "scanned": scanned, "pre": pre_min, "post": post_min}


@shared_task
def reschedule_upcoming_recordings_for_offset_change():
    return reschedule_upcoming_recordings_for_offset_change_impl()


def _notify_recordings_refresh():
    try:
        from core.utils import send_websocket_update
        send_websocket_update('updates', 'update', {"success": True, "type": "recordings_refreshed"})
    except Exception:
        pass


def purge_recurring_rule_impl(rule_id: int) -> int:
    """Remove all future recordings created by a recurring rule."""
    from django.utils import timezone
    from .models import Recording

    now = timezone.now()
    try:
        removed, _ = Recording.objects.filter(
            start_time__gte=now,
            custom_properties__rule__id=rule_id,
        ).delete()
    except Exception:
        removed = 0
    if removed:
        _notify_recordings_refresh()
    return removed


def sync_recurring_rule_impl(rule_id: int, drop_existing: bool = True, horizon_days: int = 14) -> int:
    """Ensure recordings exist for a recurring rule within the scheduling horizon."""
    from django.utils import timezone
    from .models import RecurringRecordingRule, Recording

    rule = RecurringRecordingRule.objects.filter(pk=rule_id).select_related("channel").first()
    now = timezone.now()
    removed = 0
    if drop_existing:
        removed = purge_recurring_rule_impl(rule_id)

    if not rule or not rule.enabled:
        return 0

    days = rule.cleaned_days()
    if not days:
        return 0

    tz_name = CoreSettings.get_system_time_zone()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid or unsupported time zone '%s'; falling back to Server default", tz_name)
        tz = timezone.get_current_timezone()
    start_limit = rule.start_date or now.date()
    end_limit = rule.end_date
    horizon = now + timedelta(days=horizon_days)
    start_window = max(start_limit, now.date())
    if drop_existing and end_limit:
        end_window = end_limit
    else:
        end_window = horizon.date()
        if end_limit and end_limit < end_window:
            end_window = end_limit
    if end_window < start_window:
        return 0
    total_created = 0

    for offset in range((end_window - start_window).days + 1):
        target_date = start_window + timedelta(days=offset)
        if target_date.weekday() not in days:
            continue
        if end_limit and target_date > end_limit:
            continue
        try:
            start_dt = timezone.make_aware(datetime.combine(target_date, rule.start_time), tz)
            end_dt = timezone.make_aware(datetime.combine(target_date, rule.end_time), tz)
        except Exception:
            continue
        if end_dt <= start_dt:
            end_dt = end_dt + timedelta(days=1)
        if start_dt <= now:
            continue
        exists = Recording.objects.filter(
            channel=rule.channel,
            start_time=start_dt,
            custom_properties__rule__id=rule.id,
        ).exists()
        if exists:
            continue
        description = rule.name or f"Recurring recording for {rule.channel.name}"
        cp = {
            "rule": {
                "type": "recurring",
                "id": rule.id,
                "days_of_week": days,
                "name": rule.name or "",
            },
            "status": "scheduled",
            "description": description,
            "program": {
                "title": rule.name or rule.channel.name,
                "description": description,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
            },
        }
        try:
            Recording.objects.create(
                channel=rule.channel,
                start_time=start_dt,
                end_time=end_dt,
                custom_properties=cp,
            )
            total_created += 1
        except Exception as err:
            logger.warning(f"Failed to create recurring recording for rule {rule.id}: {err}")

    if removed or total_created:
        _notify_recordings_refresh()

    return total_created


@shared_task
def rebuild_recurring_rule(rule_id: int, horizon_days: int = 14):
    return sync_recurring_rule_impl(rule_id, drop_existing=True, horizon_days=horizon_days)


@shared_task
def maintain_recurring_recordings():
    from .models import RecurringRecordingRule

    total = 0
    for rule_id in RecurringRecordingRule.objects.filter(enabled=True).values_list("id", flat=True):
        try:
            total += sync_recurring_rule_impl(rule_id, drop_existing=False)
        except Exception as err:
            logger.warning(f"Recurring rule maintenance failed for {rule_id}: {err}")
    return total


@shared_task
def purge_recurring_rule(rule_id: int):
    return purge_recurring_rule_impl(rule_id)

@shared_task
def _safe_name(s):
    try:
        import re
        s = s or ""
        # Remove forbidden filename characters and normalize spaces
        s = re.sub(r'[\\/:*?"<>|]+', '', s)
        s = s.strip()
        return s
    except Exception:
        return s or ""


def _parse_epg_tv_movie_info(program):
    """Return tuple (is_movie, season, episode, year, sub_title) from EPG ProgramData if available."""
    is_movie = False
    season = None
    episode = None
    year = None
    sub_title = program.get('sub_title') if isinstance(program, dict) else None
    try:
        from apps.epg.models import ProgramData
        prog_id = program.get('id') if isinstance(program, dict) else None
        epg_program = ProgramData.objects.filter(id=prog_id).only('custom_properties').first() if prog_id else None
        if epg_program and epg_program.custom_properties:
            cp = epg_program.custom_properties
            # Determine categories
            cats = [c.lower() for c in (cp.get('categories') or []) if isinstance(c, str)]
            is_movie = 'movie' in cats or 'film' in cats
            season = cp.get('season')
            episode = cp.get('episode')
            onscreen = cp.get('onscreen_episode')
            if (season is None or episode is None) and isinstance(onscreen, str):
                import re as _re
                m = _re.search(r'[sS](\d+)[eE](\d+)', onscreen)
                if m:
                    season = season or int(m.group(1))
                    episode = episode or int(m.group(2))
            d = cp.get('date')
            if d:
                year = str(d)[:4]
    except Exception:
        pass
    return is_movie, season, episode, year, sub_title


def _build_output_paths(channel, program, start_time, end_time):
    """
    Build (final_path, temp_ts_path, final_filename) using DVR templates.
    """
    from core.models import CoreSettings
    # Root for DVR recordings: fixed to /data/recordings inside the container
    library_root = '/data/recordings'

    is_movie, season, episode, year, sub_title = _parse_epg_tv_movie_info(program)
    show = _safe_name(program.get('title') if isinstance(program, dict) else channel.name)
    title = _safe_name(program.get('title') if isinstance(program, dict) else channel.name)
    sub_title = _safe_name(sub_title)
    season = int(season) if season is not None else 0
    episode = int(episode) if episode is not None else 0
    year = year or str(start_time.year)

    values = {
        'show': show,
        'title': title,
        'sub_title': sub_title,
        'season': season,
        'episode': episode,
        'year': year,
        'channel': _safe_name(channel.name),
        'start': start_time.strftime('%Y%m%d_%H%M%S'),
        'end': end_time.strftime('%Y%m%d_%H%M%S'),
    }

    template = CoreSettings.get_dvr_movie_template() if is_movie else CoreSettings.get_dvr_tv_template()
    # Build relative path from templates with smart fallbacks
    rel_path = None
    if not is_movie and (season == 0 or episode == 0):
        # TV fallback template when S/E are missing
        try:
            tv_fb = CoreSettings.get_dvr_tv_fallback_template()
            rel_path = tv_fb.format(**values)
        except Exception:
            # Older setting support
            try:
                fallback_root = CoreSettings.get_dvr_tv_fallback_dir()
            except Exception:
                fallback_root = "TV_Shows"
            rel_path = f"{fallback_root}/{show}/{values['start']}.mkv"
    if not rel_path:
        try:
            rel_path = template.format(**values)
        except Exception:
            rel_path = None
    # Movie-specific fallback if formatting failed or title missing
    if is_movie and not rel_path:
        try:
            m_fb = CoreSettings.get_dvr_movie_fallback_template()
            rel_path = m_fb.format(**values)
        except Exception:
            rel_path = f"Movies/{values['start']}.mkv"
    # As a last resort for TV
    if not is_movie and not rel_path:
        rel_path = f"TV_Shows/{show}/S{season:02d}E{episode:02d}.mkv"
    # Keep any leading folder like 'Recordings/' from the template so users can
    # structure their library under /data as desired.
    if not rel_path.lower().endswith('.mkv'):
        rel_path = f"{rel_path}.mkv"

    # Normalize path (strip ./)
    if rel_path.startswith('./'):
        rel_path = rel_path[2:]
    final_path = rel_path if rel_path.startswith('/') else os.path.join(library_root, rel_path)
    final_path = os.path.normpath(final_path)
    # Ensure directory exists
    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    # Derive temp TS path in same directory
    base_no_ext = os.path.splitext(os.path.basename(final_path))[0]
    temp_ts_path = os.path.join(os.path.dirname(final_path), f"{base_no_ext}.ts")
    return final_path, temp_ts_path, os.path.basename(final_path)


@shared_task
def run_recording(recording_id, channel_id, start_time_str, end_time_str):
    """
    Execute a scheduled recording for the given channel/recording.

    Enhancements:
    - Accepts recording_id so we can persist metadata back to the Recording row
    - Persists basic file info (name/path) to Recording.custom_properties
    - Attempts to capture stream stats from TS proxy (codec, resolution, fps, etc.)
    - Attempts to capture a poster (via program.custom_properties) and store a Logo reference
    """
    channel = Channel.objects.get(id=channel_id)

    start_time = datetime.fromisoformat(start_time_str)
    end_time = datetime.fromisoformat(end_time_str)

    duration_seconds = int((end_time - start_time).total_seconds())
    # Build output paths from templates
    # We need program info; will refine after we load Recording cp below
    filename = None
    final_path = None
    temp_ts_path = None

    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        "updates",
        {
            "type": "update",
            "data": {"success": True, "type": "recording_started", "channel": channel.name}
        },
    )

    logger.info(f"Starting recording for channel {channel.name}")

    # Log system event for recording start
    try:
        from core.utils import log_system_event
        log_system_event(
            'recording_start',
            channel_id=channel.uuid,
            channel_name=channel.name,
            recording_id=recording_id
        )
    except Exception as e:
        logger.error(f"Could not log recording start event: {e}")

    # Try to resolve the Recording row up front
    recording_obj = None
    try:
        from .models import Recording, Logo
        recording_obj = Recording.objects.get(id=recording_id)
        # Prime custom_properties with file info/status
        cp = recording_obj.custom_properties or {}
        cp.update({
            "status": "recording",
            "started_at": str(datetime.now()),
        })
        # Provide a predictable playback URL for the frontend
        cp["file_url"] = f"/api/channels/recordings/{recording_id}/file/"
        cp["output_file_url"] = cp["file_url"]

        # Determine program info (may include id for deeper details)
        program = cp.get("program") or {}
        final_path, temp_ts_path, filename = _build_output_paths(channel, program, start_time, end_time)
        cp["file_name"] = filename
        cp["file_path"] = final_path
        cp["_temp_file_path"] = temp_ts_path

        # Resolve poster the same way VODs do:
        # 1) Prefer image(s) from EPG Program custom_properties (images/icon)
        # 2) Otherwise reuse an existing VOD logo matching title (Movie/Series)
        # 3) Otherwise save any direct poster URL from provided program fields
        program = (cp.get("program") or {}) if isinstance(cp, dict) else {}

        def pick_best_image_from_epg_props(epg_props):
            try:
                images = epg_props.get("images") or []
                if not isinstance(images, list):
                    return None
                # Prefer poster/cover and larger sizes
                size_order = {"xxl": 6, "xl": 5, "l": 4, "m": 3, "s": 2, "xs": 1}
                def score(img):
                    t = (img.get("type") or "").lower()
                    size = (img.get("size") or "").lower()
                    return (
                        2 if t in ("poster", "cover") else 1,
                        size_order.get(size, 0)
                    )
                best = None
                for im in images:
                    if not isinstance(im, dict):
                        continue
                    url = im.get("url")
                    if not url:
                        continue
                    if best is None or score(im) > score(best):
                        best = im
                return best.get("url") if best else None
            except Exception:
                return None

        poster_logo_id = None
        poster_url = None

        # Try EPG Program custom_properties by ID
        try:
            from apps.epg.models import ProgramData
            prog_id = program.get("id")
            if prog_id:
                epg_program = ProgramData.objects.filter(id=prog_id).only("custom_properties").first()
                if epg_program and epg_program.custom_properties:
                    epg_props = epg_program.custom_properties or {}
                    poster_url = pick_best_image_from_epg_props(epg_props)
                    if not poster_url:
                        icon = epg_props.get("icon")
                        if isinstance(icon, str) and icon:
                            poster_url = icon
        except Exception as e:
            logger.debug(f"EPG image lookup failed: {e}")

        # Fallback: reuse VOD Logo by matching title
        if not poster_url and not poster_logo_id:
            try:
                from apps.vod.models import Movie, Series
                title = program.get("title") or channel.name
                vod_logo = None
                movie = Movie.objects.filter(name__iexact=title).select_related("logo").first()
                if movie and movie.logo:
                    vod_logo = movie.logo
                if not vod_logo:
                    series = Series.objects.filter(name__iexact=title).select_related("logo").first()
                    if series and series.logo:
                        vod_logo = series.logo
                if vod_logo:
                    poster_logo_id = vod_logo.id
            except Exception as e:
                logger.debug(f"VOD logo fallback failed: {e}")

        # External metadata lookups (TMDB/OMDb) when EPG/VOD didn't provide an image
        if not poster_url and not poster_logo_id:
            try:
                tmdb_key = os.environ.get('TMDB_API_KEY')
                omdb_key = os.environ.get('OMDB_API_KEY')
                title = (program.get('title') or channel.name or '').strip()
                year = None
                imdb_id = None

                # Try to derive year and imdb from EPG program custom_properties
                try:
                    from apps.epg.models import ProgramData
                    prog_id = program.get('id')
                    epg_program = ProgramData.objects.filter(id=prog_id).only('custom_properties').first() if prog_id else None
                    if epg_program and epg_program.custom_properties:
                        d = epg_program.custom_properties.get('date')
                        if d and len(str(d)) >= 4:
                            year = str(d)[:4]
                        imdb_id = epg_program.custom_properties.get('imdb.com_id') or imdb_id
                except Exception:
                    pass

                # TMDB: by IMDb ID
                if not poster_url and tmdb_key and imdb_id:
                    try:
                        url = f"https://api.themoviedb.org/3/find/{quote(imdb_id)}?api_key={tmdb_key}&external_source=imdb_id"
                        resp = requests.get(url, timeout=5)
                        if resp.ok:
                            data = resp.json() or {}
                            picks = []
                            for k in ('movie_results', 'tv_results', 'tv_episode_results', 'tv_season_results'):
                                lst = data.get(k) or []
                                picks.extend(lst)
                            poster_path = None
                            for item in picks:
                                if item.get('poster_path'):
                                    poster_path = item['poster_path']
                                    break
                            if poster_path:
                                poster_url = f"https://image.tmdb.org/t/p/w780{poster_path}"
                    except Exception:
                        pass

                # TMDB: by title (and year if available)
                if not poster_url and tmdb_key and title:
                    try:
                        q = quote(title)
                        extra = f"&year={year}" if year else ""
                        url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_key}&query={q}{extra}"
                        resp = requests.get(url, timeout=5)
                        if resp.ok:
                            data = resp.json() or {}
                            results = data.get('results') or []
                            results.sort(key=lambda x: float(x.get('popularity') or 0), reverse=True)
                            for item in results:
                                if item.get('poster_path'):
                                    poster_url = f"https://image.tmdb.org/t/p/w780{item['poster_path']}"
                                    break
                    except Exception:
                        pass

                # OMDb fallback
                if not poster_url and omdb_key:
                    try:
                        if imdb_id:
                            url = f"https://www.omdbapi.com/?apikey={omdb_key}&i={quote(imdb_id)}"
                        elif title:
                            yy = f"&y={year}" if year else ""
                            url = f"https://www.omdbapi.com/?apikey={omdb_key}&t={quote(title)}{yy}"
                        else:
                            url = None
                        if url:
                            resp = requests.get(url, timeout=5)
                            if resp.ok:
                                data = resp.json() or {}
                                p = data.get('Poster')
                                if p and p != 'N/A':
                                    poster_url = p
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"External poster lookup failed: {e}")

        # Keyless fallback providers (no API keys required)
        if not poster_url and not poster_logo_id:
            try:
                title = (program.get('title') or channel.name or '').strip()
                if title:
                    # 1) TVMaze (TV shows) - singlesearch by title
                    try:
                        url = f"https://api.tvmaze.com/singlesearch/shows?q={quote(title)}"
                        resp = requests.get(url, timeout=5)
                        if resp.ok:
                            data = resp.json() or {}
                            img = (data.get('image') or {})
                            p = img.get('original') or img.get('medium')
                            if p:
                                poster_url = p
                    except Exception:
                        pass

                    # 2) iTunes Search API (movies or tv shows)
                    if not poster_url:
                        try:
                            for media in ('movie', 'tvShow'):
                                url = f"https://itunes.apple.com/search?term={quote(title)}&media={media}&limit=1"
                                resp = requests.get(url, timeout=5)
                                if resp.ok:
                                    data = resp.json() or {}
                                    results = data.get('results') or []
                                    if results:
                                        art = results[0].get('artworkUrl100')
                                        if art:
                                            # Scale up to 600x600 by convention
                                            poster_url = art.replace('100x100', '600x600')
                                            break
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Keyless poster lookup failed: {e}")

        # Last: check direct fields on provided program object
        if not poster_url and not poster_logo_id:
            for key in ("poster", "cover", "cover_big", "image", "icon"):
                val = program.get(key)
                if isinstance(val, dict):
                    candidate = val.get("url")
                    if candidate:
                        poster_url = candidate
                        break
                elif isinstance(val, str) and val:
                    poster_url = val
                    break

        # Create or assign Logo
        if not poster_logo_id and poster_url and len(poster_url) <= 1000:
            try:
                logo, _ = Logo.objects.get_or_create(url=poster_url, defaults={"name": program.get("title") or channel.name})
                poster_logo_id = logo.id
            except Exception as e:
                logger.debug(f"Unable to persist poster to Logo: {e}")

        if poster_logo_id:
            cp["poster_logo_id"] = poster_logo_id
        if poster_url and "poster_url" not in cp:
            cp["poster_url"] = poster_url

        # Ensure destination exists so it's visible immediately
        try:
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            if not os.path.exists(final_path):
                open(final_path, 'ab').close()
        except Exception:
            pass

        recording_obj.custom_properties = cp
        recording_obj.save(update_fields=["custom_properties"])
    except Exception as e:
        logger.debug(f"Unable to prime Recording metadata: {e}")
    interrupted = False
    interrupted_reason = None
    bytes_written = 0

    from requests.exceptions import ReadTimeout, ConnectionError as ReqConnectionError, ChunkedEncodingError

    # Determine internal base URL(s) for TS streaming
    # Prefer explicit override, then try common ports for debug and docker
    explicit = os.environ.get('DISPATCHARR_INTERNAL_TS_BASE_URL')
    is_dev = (os.environ.get('DISPATCHARR_ENV', '').lower() == 'dev') or \
             (os.environ.get('DISPATCHARR_DEBUG', '').lower() == 'true') or \
             (os.environ.get('REDIS_HOST', 'redis') in ('localhost', '127.0.0.1'))
    candidates = []
    if explicit:
        candidates.append(explicit)
    if is_dev:
        # Debug container typically exposes API on 5656
        candidates.extend(['http://127.0.0.1:5656', 'http://127.0.0.1:9191'])
    # Docker service name fallback
    candidates.append(os.environ.get('DISPATCHARR_INTERNAL_API_BASE', 'http://web:9191'))
    # Last-resort localhost ports
    candidates.extend(['http://localhost:5656', 'http://localhost:9191'])

    chosen_base = None
    last_error = None
    bytes_written = 0
    interrupted = False
    interrupted_reason = None

    # We'll attempt each base until we receive some data
    for base in candidates:
        try:
            test_url = f"{base.rstrip('/')}/proxy/ts/stream/{channel.uuid}"
            logger.info(f"DVR: trying TS base {base} -> {test_url}")

            with requests.get(
                test_url,
                headers={
                    'User-Agent': 'Dispatcharr-DVR',
                },
                stream=True,
                timeout=(10, 15),
            ) as response:
                response.raise_for_status()

                # Open the file and start copying; if we get any data within a short window, accept this base
                got_any_data = False
                test_window = 3.0  # seconds to detect first bytes
                window_start = time.time()

                with open(temp_ts_path, 'wb') as file:
                    started_at = time.time()
                    for chunk in response.iter_content(chunk_size=8192):
                        if not chunk:
                            # keep-alives may be empty; continue
                            if not got_any_data and (time.time() - window_start) > test_window:
                                break
                            continue
                        # We have data
                        got_any_data = True
                        chosen_base = base
                        # Fall through to full recording loop using this same response/connection
                        file.write(chunk)
                        bytes_written += len(chunk)
                        elapsed = time.time() - started_at
                        if elapsed > duration_seconds:
                            break
                        # Continue draining the stream
                        for chunk2 in response.iter_content(chunk_size=8192):
                            if not chunk2:
                                continue
                            file.write(chunk2)
                            bytes_written += len(chunk2)
                            elapsed = time.time() - started_at
                            if elapsed > duration_seconds:
                                break
                        break  # exit outer for-loop once we switched to full drain

                # If we wrote any bytes, treat as success and stop trying candidates
                if bytes_written > 0:
                    logger.info(f"DVR: selected TS base {base}; wrote initial {bytes_written} bytes")
                    break
                else:
                    last_error = f"no_data_from_{base}"
                    logger.warning(f"DVR: no data received from {base} within {test_window}s, trying next base")
                    # Clean up empty temp file
                    try:
                        if os.path.exists(temp_ts_path) and os.path.getsize(temp_ts_path) == 0:
                            os.remove(temp_ts_path)
                    except Exception:
                        pass
        except Exception as e:
            last_error = str(e)
            logger.warning(f"DVR: attempt failed for base {base}: {e}")

    if chosen_base is None and bytes_written == 0:
        interrupted = True
        interrupted_reason = f"no_stream_data: {last_error or 'all_bases_failed'}"
    else:
        # If we ended before reaching planned duration, record reason
        actual_elapsed = 0
        try:
            actual_elapsed = os.path.getsize(temp_ts_path) and (duration_seconds)  # Best effort; we streamed until duration or disconnect above
        except Exception:
            pass
        # We cannot compute accurate elapsed here; fine to leave as is
        pass

    # If no bytes were written at all, mark detail
    if bytes_written == 0 and not interrupted:
        interrupted = True
        interrupted_reason = f"no_stream_data: {last_error or 'unknown'}"

        # Update DB status immediately so the UI reflects the change on the event below
        try:
            if recording_obj is None:
                from .models import Recording
                recording_obj = Recording.objects.get(id=recording_id)
            cp_now = recording_obj.custom_properties or {}
            cp_now.update({
                "status": "interrupted" if interrupted else "completed",
                "ended_at": str(datetime.now()),
                "file_name": filename or cp_now.get("file_name"),
                "file_path": final_path or cp_now.get("file_path"),
            })
            if interrupted and interrupted_reason:
                cp_now["interrupted_reason"] = interrupted_reason
            recording_obj.custom_properties = cp_now
            recording_obj.save(update_fields=["custom_properties"])
        except Exception as e:
            logger.debug(f"Failed to update immediate recording status: {e}")

        async_to_sync(channel_layer.group_send)(
            "updates",
            {
                "type": "update",
                "data": {"success": True, "type": "recording_ended", "channel": channel.name}
            },
        )
        # After the loop, the file and response are closed automatically.
        logger.info(f"Finished recording for channel {channel.name}")

        # Log system event for recording end
        try:
            from core.utils import log_system_event
            log_system_event(
                'recording_end',
                channel_id=channel.uuid,
                channel_name=channel.name,
                recording_id=recording_id,
                interrupted=interrupted,
                bytes_written=bytes_written
            )
        except Exception as e:
            logger.error(f"Could not log recording end event: {e}")

    # Remux TS to MKV container
    remux_success = False
    try:
        if temp_ts_path and os.path.exists(temp_ts_path):
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_ts_path, "-c", "copy", final_path
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            remux_success = os.path.exists(final_path)
            # Clean up temp file on success
            if remux_success:
                try:
                    os.remove(temp_ts_path)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"MKV remux failed: {e}")

    # Persist final metadata to Recording (status, ended_at, and stream stats if available)
    try:
        if recording_obj is None:
            from .models import Recording
            recording_obj = Recording.objects.get(id=recording_id)

        cp = recording_obj.custom_properties or {}
        cp.update({
            "ended_at": str(datetime.now()),
        })
        if interrupted:
            cp["status"] = "interrupted"
            if interrupted_reason:
                cp["interrupted_reason"] = interrupted_reason
        else:
            cp["status"] = "completed"
        cp["bytes_written"] = bytes_written
        cp["remux_success"] = remux_success

        # Try to get stream stats from TS proxy Redis metadata
        try:
            from core.utils import RedisClient
            from apps.proxy.ts_proxy.redis_keys import RedisKeys
            from apps.proxy.ts_proxy.constants import ChannelMetadataField

            r = RedisClient.get_client()
            if r is not None:
                metadata_key = RedisKeys.channel_metadata(str(channel.uuid))
                md = r.hgetall(metadata_key)
                if md:
                    def _gv(bkey):
                        return md.get(bkey.encode('utf-8'))

                    def _d(bkey, cast=str):
                        v = _gv(bkey)
                        try:
                            if v is None:
                                return None
                            s = v.decode('utf-8')
                            return cast(s) if cast is not str else s
                        except Exception:
                            return None

                    stream_info = {}
                    # Video fields
                    for key, caster in [
                        (ChannelMetadataField.VIDEO_CODEC, str),
                        (ChannelMetadataField.RESOLUTION, str),
                        (ChannelMetadataField.WIDTH, float),
                        (ChannelMetadataField.HEIGHT, float),
                        (ChannelMetadataField.SOURCE_FPS, float),
                        (ChannelMetadataField.PIXEL_FORMAT, str),
                        (ChannelMetadataField.VIDEO_BITRATE, float),
                    ]:
                        val = _d(key, caster)
                        if val is not None:
                            stream_info[key] = val

                    # Audio fields
                    for key, caster in [
                        (ChannelMetadataField.AUDIO_CODEC, str),
                        (ChannelMetadataField.SAMPLE_RATE, float),
                        (ChannelMetadataField.AUDIO_CHANNELS, str),
                        (ChannelMetadataField.AUDIO_BITRATE, float),
                    ]:
                        val = _d(key, caster)
                        if val is not None:
                            stream_info[key] = val

                    if stream_info:
                        cp["stream_info"] = stream_info
        except Exception as e:
            logger.debug(f"Unable to capture stream stats for recording: {e}")

        # Removed: local thumbnail generation. We rely on EPG/VOD/TMDB/OMDb/keyless providers only.

        recording_obj.custom_properties = cp
        recording_obj.save(update_fields=["custom_properties"])
    except Exception as e:
        logger.debug(f"Unable to finalize Recording metadata: {e}")

    # Optionally run comskip post-process
    try:
        from core.models import CoreSettings
        if CoreSettings.get_dvr_comskip_enabled():
            comskip_process_recording.delay(recording_id)
    except Exception:
        pass


@shared_task
def recover_recordings_on_startup():
    """
    On service startup, reschedule or resume recordings to handle server restarts.
    - For recordings whose window includes 'now': mark interrupted and start a new recording for the remainder.
    - For future recordings: ensure a task is scheduled at start_time.
    Uses a Redis lock to ensure only one worker runs this recovery.
    """
    try:
        from django.utils import timezone
        from .models import Recording
        from core.utils import RedisClient
        from .signals import schedule_recording_task

        redis = RedisClient.get_client()
        if redis:
            lock_key = "dvr:recover_lock"
            # Set lock with 60s TTL; only first winner proceeds
            if not redis.set(lock_key, "1", ex=60, nx=True):
                return "Recovery already in progress"

        now = timezone.now()

        # Resume in-window recordings
        active = Recording.objects.filter(start_time__lte=now, end_time__gt=now)
        for rec in active:
            try:
                cp = rec.custom_properties or {}
                # Mark interrupted due to restart; will flip to 'recording' when task starts
                cp["status"] = "interrupted"
                cp["interrupted_reason"] = "server_restarted"
                rec.custom_properties = cp
                rec.save(update_fields=["custom_properties"])

                # Start recording for remaining window
                run_recording.apply_async(
                    args=[rec.id, rec.channel_id, str(now), str(rec.end_time)], eta=now
                )
            except Exception as e:
                logger.warning(f"Failed to resume recording {rec.id}: {e}")

        # Ensure future recordings are scheduled
        upcoming = Recording.objects.filter(start_time__gt=now, end_time__gt=now)
        for rec in upcoming:
            try:
                # Schedule task at start_time
                task_id = schedule_recording_task(rec)
                if task_id:
                    rec.task_id = task_id
                    rec.save(update_fields=["task_id"])
            except Exception as e:
                logger.warning(f"Failed to schedule recording {rec.id}: {e}")

        return "Recovery complete"
    except Exception as e:
        logger.error(f"Error during DVR recovery: {e}")
        return f"Error: {e}"

@shared_task
def comskip_process_recording(recording_id: int):
    """Run comskip on the MKV to remove commercials and replace the file in place.
    Safe to call even if comskip is not installed; stores status in custom_properties.comskip.
    """
    import shutil
    from django.db import DatabaseError
    from .models import Recording
    # Helper to broadcast status over websocket
    def _ws(status: str, extra: dict | None = None):
        try:
            from core.utils import send_websocket_update
            payload = {"success": True, "type": "comskip_status", "status": status, "recording_id": recording_id}
            if extra:
                payload.update(extra)
            send_websocket_update('updates', 'update', payload)
        except Exception:
            pass

    try:
        rec = Recording.objects.get(id=recording_id)
    except Recording.DoesNotExist:
        return "not_found"

    cp = rec.custom_properties.copy() if isinstance(rec.custom_properties, dict) else {}

    def _persist_custom_properties():
        """Persist updated custom_properties without raising if the row disappeared."""
        try:
            updated = Recording.objects.filter(pk=recording_id).update(custom_properties=cp)
            if not updated:
                logger.warning(
                    "Recording %s vanished before comskip status could be saved",
                    recording_id,
                )
                return False
        except DatabaseError as db_err:
            logger.warning(
                "Failed to persist comskip status for recording %s: %s",
                recording_id,
                db_err,
            )
            return False
        except Exception as unexpected:
            logger.warning(
                "Unexpected error while saving comskip status for recording %s: %s",
                recording_id,
                unexpected,
            )
            return False
        return True
    file_path = (cp or {}).get("file_path")
    if not file_path or not os.path.exists(file_path):
        return "no_file"

    if isinstance(cp.get("comskip"), dict) and cp["comskip"].get("status") == "completed":
        return "already_processed"

    comskip_bin = shutil.which("comskip")
    if not comskip_bin:
        cp["comskip"] = {"status": "skipped", "reason": "comskip_not_installed"}
        _persist_custom_properties()
        _ws('skipped', {"reason": "comskip_not_installed"})
        return "comskip_missing"

    base, _ = os.path.splitext(file_path)
    edl_path = f"{base}.edl"

    # Notify start
    _ws('started', {"title": (cp.get('program') or {}).get('title') or os.path.basename(file_path)})

    try:
        cmd = [comskip_bin, "--output", os.path.dirname(file_path)]
        # Prefer user-specified INI, fall back to known defaults
        ini_candidates = []
        try:
            custom_ini = CoreSettings.get_dvr_comskip_custom_path()
            if custom_ini:
                ini_candidates.append(custom_ini)
        except Exception as ini_err:
            logger.debug(f"Unable to load custom comskip.ini path: {ini_err}")
        ini_candidates.extend(["/etc/comskip/comskip.ini", "/app/docker/comskip.ini"])
        selected_ini = None
        for ini_path in ini_candidates:
            if ini_path and os.path.exists(ini_path):
                selected_ini = ini_path
                cmd.extend([f"--ini={ini_path}"])
                break
        cmd.append(file_path)
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "").strip().splitlines()
        stderr_tail = stderr_tail[-5:] if stderr_tail else []
        detail = {
            "status": "error",
            "reason": "comskip_failed",
            "returncode": e.returncode,
        }
        if e.returncode and e.returncode < 0:
            try:
                detail["signal"] = signal.Signals(-e.returncode).name
            except Exception:
                detail["signal"] = f"signal_{-e.returncode}"
        if stderr_tail:
            detail["stderr"] = "\n".join(stderr_tail)
        if selected_ini:
            detail["ini_path"] = selected_ini
        cp["comskip"] = detail
        _persist_custom_properties()
        _ws('error', {"reason": "comskip_failed", "returncode": e.returncode})
        return "comskip_failed"
    except Exception as e:
        cp["comskip"] = {"status": "error", "reason": f"comskip_failed: {e}"}
        _persist_custom_properties()
        _ws('error', {"reason": str(e)})
        return "comskip_failed"

    if not os.path.exists(edl_path):
        cp["comskip"] = {"status": "error", "reason": "edl_not_found"}
        _persist_custom_properties()
        _ws('error', {"reason": "edl_not_found"})
        return "no_edl"

    # Duration via ffprobe
    def _ffprobe_duration(path):
        try:
            p = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(p.stdout.strip())
        except Exception:
            return None

    duration = _ffprobe_duration(file_path)
    if duration is None:
        cp["comskip"] = {"status": "error", "reason": "duration_unknown"}
        _persist_custom_properties()
        _ws('error', {"reason": "duration_unknown"})
        return "no_duration"

    commercials = []
    try:
        with open(edl_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        s = float(parts[0]); e = float(parts[1])
                        commercials.append((max(0.0, s), min(duration, e)))
                    except Exception:
                        pass
    except Exception:
        pass

    commercials.sort()
    keep = []
    cur = 0.0
    for s, e in commercials:
        if s > cur:
            keep.append((cur, max(cur, s)))
        cur = max(cur, e)
    if cur < duration:
        keep.append((cur, duration))

    if not commercials or sum((e - s) for s, e in commercials) <= 0.5:
        cp["comskip"] = {
            "status": "completed",
            "skipped": True,
            "edl": os.path.basename(edl_path),
        }
        if selected_ini:
            cp["comskip"]["ini_path"] = selected_ini
        _persist_custom_properties()
        _ws('skipped', {"reason": "no_commercials", "commercials": 0})
        return "no_commercials"

    workdir = os.path.dirname(file_path)
    parts = []
    try:
        for idx, (s, e) in enumerate(keep):
            seg = os.path.join(workdir, f"segment_{idx:03d}.mkv")
            dur = max(0.0, e - s)
            if dur <= 0.01:
                continue
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{s:.3f}", "-i", file_path, "-t", f"{dur:.3f}",
                "-c", "copy", "-avoid_negative_ts", "1", seg
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            parts.append(seg)

        if not parts:
            raise RuntimeError("no_parts")

        list_path = os.path.join(workdir, "concat_list.txt")
        with open(list_path, "w") as lf:
            for pth in parts:
                escaped = pth.replace("'", "'\\''")
                lf.write(f"file '{escaped}'\n")

        output_path = os.path.join(workdir, f"{os.path.splitext(os.path.basename(file_path))[0]}.cut.mkv")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        try:
            os.replace(output_path, file_path)
        except Exception:
            shutil.copy(output_path, file_path)

        try:
            os.remove(list_path)
        except Exception:
            pass
        for pth in parts:
            try: os.remove(pth)
            except Exception: pass

        cp["comskip"] = {
            "status": "completed",
            "edl": os.path.basename(edl_path),
            "segments_kept": len(parts),
            "commercials": len(commercials),
        }
        if selected_ini:
            cp["comskip"]["ini_path"] = selected_ini
        _persist_custom_properties()
        _ws('completed', {"commercials": len(commercials), "segments_kept": len(parts)})
        return "ok"
    except Exception as e:
        cp["comskip"] = {"status": "error", "reason": str(e)}
        _persist_custom_properties()
        _ws('error', {"reason": str(e)})
        return f"error:{e}"
def _resolve_poster_for_program(channel_name, program):
    """Internal helper that attempts to resolve a poster URL and/or Logo id.
    Returns (poster_logo_id, poster_url) where either may be None.
    """
    poster_logo_id = None
    poster_url = None

    # Try EPG Program images first
    try:
        from apps.epg.models import ProgramData
        prog_id = program.get("id") if isinstance(program, dict) else None
        if prog_id:
            epg_program = ProgramData.objects.filter(id=prog_id).only("custom_properties").first()
            if epg_program and epg_program.custom_properties:
                epg_props = epg_program.custom_properties or {}

                def pick_best_image_from_epg_props(epg_props):
                    images = epg_props.get("images") or []
                    if not isinstance(images, list):
                        return None
                    size_order = {"xxl": 6, "xl": 5, "l": 4, "m": 3, "s": 2, "xs": 1}
                    def score(img):
                        t = (img.get("type") or "").lower()
                        size = (img.get("size") or "").lower()
                        return (2 if t in ("poster", "cover") else 1, size_order.get(size, 0))
                    best = None
                    for im in images:
                        if not isinstance(im, dict):
                            continue
                        url = im.get("url")
                        if not url:
                            continue
                        if best is None or score(im) > score(best):
                            best = im
                    return best.get("url") if best else None

                poster_url = pick_best_image_from_epg_props(epg_props)
                if not poster_url:
                    icon = epg_props.get("icon")
                    if isinstance(icon, str) and icon:
                        poster_url = icon
    except Exception:
        pass

    # VOD logo fallback by title
    if not poster_url and not poster_logo_id:
        try:
            from apps.vod.models import Movie, Series
            title = (program.get("title") if isinstance(program, dict) else None) or channel_name
            vod_logo = None
            movie = Movie.objects.filter(name__iexact=title).select_related("logo").first()
            if movie and movie.logo:
                vod_logo = movie.logo
            if not vod_logo:
                series = Series.objects.filter(name__iexact=title).select_related("logo").first()
                if series and series.logo:
                    vod_logo = series.logo
            if vod_logo:
                poster_logo_id = vod_logo.id
        except Exception:
            pass

    # Keyless providers (TVMaze & iTunes)
    if not poster_url and not poster_logo_id:
        try:
            title = (program.get('title') if isinstance(program, dict) else None) or channel_name
            if title:
                # TVMaze
                try:
                    url = f"https://api.tvmaze.com/singlesearch/shows?q={quote(title)}"
                    resp = requests.get(url, timeout=5)
                    if resp.ok:
                        data = resp.json() or {}
                        img = (data.get('image') or {})
                        p = img.get('original') or img.get('medium')
                        if p:
                            poster_url = p
                except Exception:
                    pass
                # iTunes
                if not poster_url:
                    try:
                        for media in ('movie', 'tvShow'):
                            url = f"https://itunes.apple.com/search?term={quote(title)}&media={media}&limit=1"
                            resp = requests.get(url, timeout=5)
                            if resp.ok:
                                data = resp.json() or {}
                                results = data.get('results') or []
                                if results:
                                    art = results[0].get('artworkUrl100')
                                    if art:
                                        poster_url = art.replace('100x100', '600x600')
                                        break
                    except Exception:
                        pass
        except Exception:
            pass

    # Fallback: search existing Logo entries by name if we still have nothing
    if not poster_logo_id and not poster_url:
        try:
            from .models import Logo
            title = (program.get("title") if isinstance(program, dict) else None) or channel_name
            existing = Logo.objects.filter(name__iexact=title).first()
            if existing:
                poster_logo_id = existing.id
                poster_url = existing.url
        except Exception:
            pass

    # Save to Logo if URL available
    if not poster_logo_id and poster_url and len(poster_url) <= 1000:
        try:
            from .models import Logo
            logo, _ = Logo.objects.get_or_create(url=poster_url, defaults={"name": (program.get("title") if isinstance(program, dict) else None) or channel_name})
            poster_logo_id = logo.id
        except Exception:
            pass

    return poster_logo_id, poster_url


@shared_task
def prefetch_recording_artwork(recording_id):
    """Prefetch poster info for a scheduled recording so the UI can show art in Upcoming."""
    try:
        from .models import Recording
        rec = Recording.objects.get(id=recording_id)
        cp = rec.custom_properties or {}
        program = cp.get("program") or {}
        poster_logo_id, poster_url = _resolve_poster_for_program(rec.channel.name, program)
        updated = False
        if poster_logo_id and cp.get("poster_logo_id") != poster_logo_id:
            cp["poster_logo_id"] = poster_logo_id
            updated = True
        if poster_url and cp.get("poster_url") != poster_url:
            cp["poster_url"] = poster_url
            updated = True
        # Enrich with rating if available from ProgramData.custom_properties
        try:
            from apps.epg.models import ProgramData
            prog_id = program.get("id") if isinstance(program, dict) else None
            if prog_id:
                epg_program = ProgramData.objects.filter(id=prog_id).only("custom_properties").first()
                if epg_program and isinstance(epg_program.custom_properties, dict):
                    rating_val = epg_program.custom_properties.get("rating")
                    rating_sys = epg_program.custom_properties.get("rating_system")
                    season_val = epg_program.custom_properties.get("season")
                    episode_val = epg_program.custom_properties.get("episode")
                    onscreen = epg_program.custom_properties.get("onscreen_episode")
                    if rating_val and cp.get("rating") != rating_val:
                        cp["rating"] = rating_val
                        updated = True
                    if rating_sys and cp.get("rating_system") != rating_sys:
                        cp["rating_system"] = rating_sys
                        updated = True
                    if season_val is not None and cp.get("season") != season_val:
                        cp["season"] = season_val
                        updated = True
                    if episode_val is not None and cp.get("episode") != episode_val:
                        cp["episode"] = episode_val
                        updated = True
                    if onscreen and cp.get("onscreen_episode") != onscreen:
                        cp["onscreen_episode"] = onscreen
                        updated = True
        except Exception:
            pass

        if updated:
            rec.custom_properties = cp
            rec.save(update_fields=["custom_properties"])
            try:
                from core.utils import send_websocket_update
                send_websocket_update('updates', 'update', {"success": True, "type": "recording_updated", "recording_id": rec.id})
            except Exception:
                pass
        return "ok"
    except Exception as e:
        logger.debug(f"prefetch_recording_artwork failed: {e}")
        return f"error: {e}"


@shared_task(bind=True)
def bulk_create_channels_from_streams(self, stream_ids, channel_profile_ids=None, starting_channel_number=None):
    """
    Asynchronously create channels from a list of stream IDs.
    Provides progress updates via WebSocket.

    Args:
        stream_ids: List of stream IDs to create channels from
        channel_profile_ids: Optional list of channel profile IDs to assign channels to
        starting_channel_number: Optional starting channel number behavior:
            - None: Use provider channel numbers, then auto-assign from 1
            - 0: Start with lowest available number and increment by 1
            - Other number: Use as starting number for auto-assignment
    """
    from apps.channels.models import Stream, Channel, ChannelGroup, ChannelProfile, ChannelProfileMembership, Logo
    from apps.epg.models import EPGData
    from django.db import transaction
    from django.shortcuts import get_object_or_404
    from core.utils import send_websocket_update

    task_id = self.request.id
    total_streams = len(stream_ids)
    created_channels = []
    errors = []

    try:
        # Send initial progress update
        send_websocket_update('updates', 'update', {
            'type': 'bulk_channel_creation_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_streams,
            'status': 'starting',
            'message': f'Starting bulk creation of {total_streams} channels...'
        })

        # Gather current used numbers once
        used_numbers = set(Channel.objects.all().values_list("channel_number", flat=True))

        # Initialize next_number based on starting_channel_number mode
        if starting_channel_number is None:
            # Mode 1: Use provider numbers when available, auto-assign when not
            next_number = 1
        elif starting_channel_number == 0:
            # Mode 2: Start from lowest available number
            next_number = 1
        else:
            # Mode 3: Start from specified number
            next_number = starting_channel_number

        def get_auto_number():
            nonlocal next_number
            while next_number in used_numbers:
                next_number += 1
            used_numbers.add(next_number)
            return next_number

        logos_to_create = []
        channels_to_create = []
        streams_map = []
        logo_map = []
        profile_map = []

        # Process streams in batches to avoid memory issues
        batch_size = 100
        processed = 0

        for i in range(0, total_streams, batch_size):
            batch_stream_ids = stream_ids[i:i + batch_size]
            # Fetch streams and preserve the order from batch_stream_ids
            batch_streams_dict = {stream.id: stream for stream in Stream.objects.filter(id__in=batch_stream_ids)}
            batch_streams = [batch_streams_dict[stream_id] for stream_id in batch_stream_ids if stream_id in batch_streams_dict]

            # Send progress update
            send_websocket_update('updates', 'update', {
                'type': 'bulk_channel_creation_progress',
                'task_id': task_id,
                'progress': processed,
                'total': total_streams,
                'status': 'processing',
                'message': f'Processing streams {processed + 1}-{min(processed + batch_size, total_streams)} of {total_streams}...'
            })

            for stream in batch_streams:
                try:
                    name = stream.name
                    channel_group = stream.channel_group
                    stream_custom_props = stream.custom_properties or {}

                    # Determine channel number based on starting_channel_number mode
                    channel_number = None

                    if starting_channel_number is None:
                        # Mode 1: Use provider numbers when available
                        if "tvg-chno" in stream_custom_props:
                            channel_number = float(stream_custom_props["tvg-chno"])
                        elif "channel-number" in stream_custom_props:
                            channel_number = float(stream_custom_props["channel-number"])
                        elif "num" in stream_custom_props:
                            channel_number = float(stream_custom_props["num"])

                    # For modes 2 and 3 (starting_channel_number == 0 or specific number),
                    # ignore provider numbers and use sequential assignment

                    # Get TVC guide station ID
                    tvc_guide_stationid = None
                    if "tvc-guide-stationid" in stream_custom_props:
                        tvc_guide_stationid = stream_custom_props["tvc-guide-stationid"]

                    # Check if the determined/provider number is available
                    if channel_number is not None and (
                        channel_number in used_numbers
                        or Channel.objects.filter(channel_number=channel_number).exists()
                    ):
                        # Provider number is taken, use auto-assignment
                        channel_number = get_auto_number()
                    elif channel_number is not None:
                        # Provider number is available, use it
                        used_numbers.add(channel_number)
                    else:
                        # No provider number or ignoring provider numbers, use auto-assignment
                        channel_number = get_auto_number()

                    channel_data = {
                        "channel_number": channel_number,
                        "name": name,
                        "tvc_guide_stationid": tvc_guide_stationid,
                        "tvg_id": stream.tvg_id,
                    }

                    # Only add channel_group_id if the stream has a channel group
                    if channel_group:
                        channel_data["channel_group_id"] = channel_group.id

                    # Attempt to find existing EPGs with the same tvg-id
                    epgs = EPGData.objects.filter(tvg_id=stream.tvg_id)
                    if epgs:
                        channel_data["epg_data_id"] = epgs.first().id

                    channel = Channel(**channel_data)
                    channels_to_create.append(channel)
                    streams_map.append([stream.id])

                    # Store profile IDs for this channel
                    profile_map.append(channel_profile_ids)

                    # Handle logo - validate URL length to avoid PostgreSQL btree index errors
                    validated_logo_url = validate_logo_url(stream.logo_url) if stream.logo_url else None
                    if validated_logo_url:
                        logos_to_create.append(
                            Logo(
                                url=validated_logo_url,
                                name=stream.name or stream.tvg_id,
                            )
                        )
                        logo_map.append(validated_logo_url)
                    else:
                        logo_map.append(None)

                    processed += 1

                except Exception as e:
                    errors.append({
                        'stream_id': stream.id if 'stream' in locals() else 'unknown',
                        'error': str(e)
                    })
                    processed += 1

        # Create logos first
        if logos_to_create:
            send_websocket_update('updates', 'update', {
                'type': 'bulk_channel_creation_progress',
                'task_id': task_id,
                'progress': processed,
                'total': total_streams,
                'status': 'creating_logos',
                'message': f'Creating {len(logos_to_create)} logos...'
            })
            Logo.objects.bulk_create(logos_to_create, ignore_conflicts=True)

        # Get logo objects for association
        channel_logos = {
            logo.url: logo
            for logo in Logo.objects.filter(
                url__in=[url for url in logo_map if url is not None]
            )
        }

        # Create channels in database
        if channels_to_create:
            send_websocket_update('updates', 'update', {
                'type': 'bulk_channel_creation_progress',
                'task_id': task_id,
                'progress': processed,
                'total': total_streams,
                'status': 'creating_channels',
                'message': f'Creating {len(channels_to_create)} channels in database...'
            })

            with transaction.atomic():
                created_channels = Channel.objects.bulk_create(channels_to_create)

                # Update channels with logos and create stream associations
                update = []
                channel_stream_associations = []
                channel_profile_memberships = []

                for channel, stream_ids, logo_url, profile_ids in zip(
                    created_channels, streams_map, logo_map, profile_map
                ):
                    if logo_url:
                        channel.logo = channel_logos[logo_url]
                        update.append(channel)

                    # Create stream associations
                    for stream_id in stream_ids:
                        from apps.channels.models import ChannelStream
                        channel_stream_associations.append(
                            ChannelStream(channel=channel, stream_id=stream_id, order=0)
                        )

                    # Handle channel profile membership
                    if profile_ids:
                        try:
                            specific_profiles = ChannelProfile.objects.filter(id__in=profile_ids)
                            channel_profile_memberships.extend([
                                ChannelProfileMembership(
                                    channel_profile=profile,
                                    channel=channel,
                                    enabled=True
                                )
                                for profile in specific_profiles
                            ])
                        except Exception as e:
                            errors.append({
                                'channel_id': channel.id,
                                'error': f'Failed to add to profiles: {str(e)}'
                            })
                    else:
                        # Add to all profiles by default
                        all_profiles = ChannelProfile.objects.all()
                        channel_profile_memberships.extend([
                            ChannelProfileMembership(
                                channel_profile=profile,
                                channel=channel,
                                enabled=True
                            )
                            for profile in all_profiles
                        ])

                # Bulk update channels with logos
                if update:
                    Channel.objects.bulk_update(update, ["logo"])

                # Bulk create channel-stream associations
                if channel_stream_associations:
                    from apps.channels.models import ChannelStream
                    ChannelStream.objects.bulk_create(channel_stream_associations, ignore_conflicts=True)

                # Bulk create profile memberships
                if channel_profile_memberships:
                    ChannelProfileMembership.objects.bulk_create(channel_profile_memberships, ignore_conflicts=True)

        # Send completion update
        send_websocket_update('updates', 'update', {
            'type': 'bulk_channel_creation_progress',
            'task_id': task_id,
            'progress': total_streams,
            'total': total_streams,
            'status': 'completed',
            'message': f'Successfully created {len(created_channels)} channels',
            'created_count': len(created_channels),
            'error_count': len(errors),
            'errors': errors[:10]  # Send first 10 errors only
        })

        # Send general channel update notification
        send_websocket_update('updates', 'update', {
            'type': 'channels_created',
            'count': len(created_channels)
        })

        return {
            'status': 'completed',
            'created_count': len(created_channels),
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"Bulk channel creation failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'bulk_channel_creation_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_streams,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise


@shared_task(bind=True)
def set_channels_names_from_epg(self, channel_ids):
    """
    Celery task to set channel names from EPG data for multiple channels
    """
    from core.utils import send_websocket_update

    task_id = self.request.id
    total_channels = len(channel_ids)
    updated_count = 0
    errors = []

    try:
        logger.info(f"Starting EPG name setting task for {total_channels} channels")

        # Send initial progress
        send_websocket_update('updates', 'update', {
            'type': 'epg_name_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'running',
            'message': 'Starting EPG name setting...'
        })

        batch_size = 100
        for i in range(0, total_channels, batch_size):
            batch_ids = channel_ids[i:i + batch_size]
            batch_updates = []

            # Get channels and their EPG data
            channels = Channel.objects.filter(id__in=batch_ids).select_related('epg_data')

            for channel in channels:
                try:
                    if channel.epg_data and channel.epg_data.name:
                        if channel.name != channel.epg_data.name:
                            channel.name = channel.epg_data.name
                            batch_updates.append(channel)
                            updated_count += 1
                except Exception as e:
                    errors.append(f"Channel {channel.id}: {str(e)}")
                    logger.error(f"Error processing channel {channel.id}: {e}")

            # Bulk update the batch
            if batch_updates:
                Channel.objects.bulk_update(batch_updates, ['name'])

            # Send progress update
            progress = min(i + batch_size, total_channels)
            send_websocket_update('updates', 'update', {
                'type': 'epg_name_setting_progress',
                'task_id': task_id,
                'progress': progress,
                'total': total_channels,
                'status': 'running',
                'message': f'Updated {updated_count} channel names...',
                'updated_count': updated_count
            })

        # Send completion notification
        send_websocket_update('updates', 'update', {
            'type': 'epg_name_setting_progress',
            'task_id': task_id,
            'progress': total_channels,
            'total': total_channels,
            'status': 'completed',
            'message': f'Successfully updated {updated_count} channel names from EPG data',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        })

        logger.info(f"EPG name setting task completed. Updated {updated_count} channels")
        return {
            'status': 'completed',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"EPG name setting task failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'epg_name_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise


@shared_task(bind=True)
def set_channels_logos_from_epg(self, channel_ids):
    """
    Celery task to set channel logos from EPG data for multiple channels
    Creates logos from EPG icon URLs if they don't exist
    """
    from .models import Logo
    from core.utils import send_websocket_update
    import requests
    from urllib.parse import urlparse

    task_id = self.request.id
    total_channels = len(channel_ids)
    updated_count = 0
    created_logos_count = 0
    errors = []

    try:
        logger.info(f"Starting EPG logo setting task for {total_channels} channels")

        # Send initial progress
        send_websocket_update('updates', 'update', {
            'type': 'epg_logo_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'running',
            'message': 'Starting EPG logo setting...'
        })

        batch_size = 50  # Smaller batch for logo processing
        for i in range(0, total_channels, batch_size):
            batch_ids = channel_ids[i:i + batch_size]
            batch_updates = []

            # Get channels and their EPG data
            channels = Channel.objects.filter(id__in=batch_ids).select_related('epg_data', 'logo')

            for channel in channels:
                try:
                    if channel.epg_data and channel.epg_data.icon_url:
                        icon_url = channel.epg_data.icon_url.strip()

                        # Try to find existing logo with this URL
                        try:
                            logo = Logo.objects.get(url=icon_url)
                        except Logo.DoesNotExist:
                            # Create new logo from EPG icon URL
                            try:
                                # Generate a name for the logo
                                logo_name = channel.epg_data.name or f"Logo for {channel.epg_data.tvg_id}"

                                # Create the logo record
                                logo = Logo.objects.create(
                                    name=logo_name,
                                    url=icon_url
                                )
                                created_logos_count += 1
                                logger.info(f"Created new logo from EPG: {logo_name} - {icon_url}")

                            except Exception as create_error:
                                errors.append(f"Channel {channel.id}: Failed to create logo from {icon_url}: {str(create_error)}")
                                logger.error(f"Failed to create logo for channel {channel.id}: {create_error}")
                                continue

                        # Update channel logo if different
                        if channel.logo != logo:
                            channel.logo = logo
                            batch_updates.append(channel)
                            updated_count += 1

                except Exception as e:
                    errors.append(f"Channel {channel.id}: {str(e)}")
                    logger.error(f"Error processing channel {channel.id}: {e}")

            # Bulk update the batch
            if batch_updates:
                Channel.objects.bulk_update(batch_updates, ['logo'])

            # Send progress update
            progress = min(i + batch_size, total_channels)
            send_websocket_update('updates', 'update', {
                'type': 'epg_logo_setting_progress',
                'task_id': task_id,
                'progress': progress,
                'total': total_channels,
                'status': 'running',
                'message': f'Updated {updated_count} channel logos, created {created_logos_count} new logos...',
                'updated_count': updated_count,
                'created_logos_count': created_logos_count
            })

        # Send completion notification
        send_websocket_update('updates', 'update', {
            'type': 'epg_logo_setting_progress',
            'task_id': task_id,
            'progress': total_channels,
            'total': total_channels,
            'status': 'completed',
            'message': f'Successfully updated {updated_count} channel logos and created {created_logos_count} new logos from EPG data',
            'updated_count': updated_count,
            'created_logos_count': created_logos_count,
            'error_count': len(errors),
            'errors': errors
        })

        logger.info(f"EPG logo setting task completed. Updated {updated_count} channels, created {created_logos_count} logos")
        return {
            'status': 'completed',
            'updated_count': updated_count,
            'created_logos_count': created_logos_count,
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"EPG logo setting task failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'epg_logo_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise


@shared_task(bind=True)
def set_channels_tvg_ids_from_epg(self, channel_ids):
    """
    Celery task to set channel TVG-IDs from EPG data for multiple channels
    """
    from core.utils import send_websocket_update

    task_id = self.request.id
    total_channels = len(channel_ids)
    updated_count = 0
    errors = []

    try:
        logger.info(f"Starting EPG TVG-ID setting task for {total_channels} channels")

        # Send initial progress
        send_websocket_update('updates', 'update', {
            'type': 'epg_tvg_id_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'running',
            'message': 'Starting EPG TVG-ID setting...'
        })

        batch_size = 100
        for i in range(0, total_channels, batch_size):
            batch_ids = channel_ids[i:i + batch_size]
            batch_updates = []

            # Get channels and their EPG data
            channels = Channel.objects.filter(id__in=batch_ids).select_related('epg_data')

            for channel in channels:
                try:
                    if channel.epg_data and channel.epg_data.tvg_id:
                        if channel.tvg_id != channel.epg_data.tvg_id:
                            channel.tvg_id = channel.epg_data.tvg_id
                            batch_updates.append(channel)
                            updated_count += 1
                except Exception as e:
                    errors.append(f"Channel {channel.id}: {str(e)}")
                    logger.error(f"Error processing channel {channel.id}: {e}")

            # Bulk update the batch
            if batch_updates:
                Channel.objects.bulk_update(batch_updates, ['tvg_id'])

            # Send progress update
            progress = min(i + batch_size, total_channels)
            send_websocket_update('updates', 'update', {
                'type': 'epg_tvg_id_setting_progress',
                'task_id': task_id,
                'progress': progress,
                'total': total_channels,
                'status': 'running',
                'message': f'Updated {updated_count} channel TVG-IDs...',
                'updated_count': updated_count
            })

        # Send completion notification
        send_websocket_update('updates', 'update', {
            'type': 'epg_tvg_id_setting_progress',
            'task_id': task_id,
            'progress': total_channels,
            'total': total_channels,
            'status': 'completed',
            'message': f'Successfully updated {updated_count} channel TVG-IDs from EPG data',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        })

        logger.info(f"EPG TVG-ID setting task completed. Updated {updated_count} channels")
        return {
            'status': 'completed',
            'updated_count': updated_count,
            'error_count': len(errors),
            'errors': errors
        }

    except Exception as e:
        logger.error(f"EPG TVG-ID setting task failed: {e}")
        send_websocket_update('updates', 'update', {
            'type': 'epg_tvg_id_setting_progress',
            'task_id': task_id,
            'progress': 0,
            'total': total_channels,
            'status': 'failed',
            'message': f'Task failed: {str(e)}',
            'error': str(e)
        })
        raise
