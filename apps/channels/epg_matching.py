"""
EPG channel matching: fuzzy scoring, optional ML validation, and UI notifications.

Celery tasks in tasks.py call into this module; keep orchestration here and
task wiring thin so matching logic stays testable without a worker.
"""
import gc
import heapq
import logging
import os
import re

from rapidfuzz import fuzz

from apps.epg.models import EPGData
from core.models import CoreSettings
from core.utils import send_websocket_update

logger = logging.getLogger(__name__)

_ml_model_cache = {'sentence_transformer': None}
_normalize_settings_cache = None

ML_CANDIDATE_LIMIT = 20
SINGLE_CHANNEL_MATCH_TIMEOUT_MS = 180_000

COMMON_EXTRANEOUS_WORDS = [
    "tv", "channel", "network", "television",
    "east", "west", "hd", "uhd", "24/7",
    "1080p", "720p", "540p", "480p",
    "film", "movie", "movies",
]


def release_ml_models():
    """Unload sentence transformer and encourage PyTorch to release memory."""
    if _ml_model_cache['sentence_transformer'] is None:
        return
    logger.info("Cleaning up ML models from memory")
    model = _ml_model_cache['sentence_transformer']
    _ml_model_cache['sentence_transformer'] = None
    del model
    try:
        import torch
        if hasattr(torch, 'cuda') and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    gc.collect()


def clear_normalize_settings_cache():
    """Reset cached normalization settings after a matching run."""
    global _normalize_settings_cache
    _normalize_settings_cache = None


def cleanup_after_matching():
    """Release ML models and normalization cache after a matching run."""
    release_ml_models()
    clear_normalize_settings_cache()


def get_sentence_transformer():
    """Lazy load the sentence transformer model only when needed."""
    if _ml_model_cache['sentence_transformer'] is None:
        try:
            from sentence_transformers import SentenceTransformer
            from sentence_transformers import util

            model_name = "sentence-transformers/all-MiniLM-L6-v2"
            cache_dir = "/data/models"
            disable_downloads = os.environ.get('DISABLE_ML_DOWNLOADS', 'false').lower() == 'true'

            if disable_downloads:
                hf_model_path = os.path.join(cache_dir, f"models--{model_name.replace('/', '--')}")
                if not os.path.exists(hf_model_path):
                    logger.warning(
                        "ML model not found and downloads disabled (DISABLE_ML_DOWNLOADS=true). "
                        "Skipping ML matching."
                    )
                    return None, None

            os.makedirs(cache_dir, exist_ok=True)
            logger.info(f"Loading sentence transformer model (cache: {cache_dir})")
            _ml_model_cache['sentence_transformer'] = SentenceTransformer(
                model_name,
                cache_folder=cache_dir,
            )
            return _ml_model_cache['sentence_transformer'], util
        except ImportError:
            logger.warning("sentence-transformers not available - ML-enhanced matching disabled")
            return None, None
        except Exception as e:
            logger.error(f"Failed to load sentence transformer: {e}")
            return None, None

    from sentence_transformers import util
    return _ml_model_cache['sentence_transformer'], util


def normalize_name(name: str) -> str:
    """Normalize a channel/EPG name for fuzzy matching."""
    if not name:
        return ""

    global _normalize_settings_cache
    if _normalize_settings_cache is None:
        prefixes = []
        suffixes = []
        custom_strings = []
        try:
            settings = CoreSettings.get_epg_settings()
            mode = settings.get("epg_match_mode", "default")
            if mode == "advanced":
                prefixes = settings.get("epg_match_ignore_prefixes", [])
                suffixes = settings.get("epg_match_ignore_suffixes", [])
                custom_strings = settings.get("epg_match_ignore_custom", [])
                if not isinstance(prefixes, list):
                    prefixes = []
                if not isinstance(suffixes, list):
                    suffixes = []
                if not isinstance(custom_strings, list):
                    custom_strings = []
        except Exception as e:
            logger.debug(f"Could not load EPG matching settings: {e}")
        _normalize_settings_cache = (prefixes, suffixes, custom_strings)

    prefixes, suffixes, custom_strings = _normalize_settings_cache
    result = name

    for prefix in prefixes:
        if not prefix or not isinstance(prefix, str):
            continue
        if result.startswith(prefix):
            result = result[len(prefix):]
            break

    for suffix in suffixes:
        if not suffix or not isinstance(suffix, str):
            continue
        if result.endswith(suffix):
            result = result[:-len(suffix)]
            break

    for custom in custom_strings:
        if not custom or not isinstance(custom, str):
            continue
        try:
            result = result.replace(custom, "")
        except Exception as e:
            logger.debug(f"Failed to remove custom string '{custom}': {e}")

    norm = result.lower()
    norm = re.sub(r"\[.*?\]", "", norm)

    call_sign_match = re.search(r"\(([A-Z]{3,5})\)", name)
    preserved_call_sign = ""
    if call_sign_match:
        preserved_call_sign = " " + call_sign_match.group(1).lower()

    norm = re.sub(r"\(.*?\)", "", norm)
    norm = norm + preserved_call_sign
    norm = re.sub(r"[^\w\s]", "", norm)
    tokens = [t for t in norm.split() if t not in COMMON_EXTRANEOUS_WORDS]
    return " ".join(tokens).strip()


def send_epg_matching_progress(total_channels, matched_channels, current_channel_name="", stage="matching"):
    """Send bulk EPG matching progress via WebSocket."""
    matched_count = (
        len(matched_channels) if isinstance(matched_channels, list) else matched_channels
    )
    send_websocket_update(
        'updates',
        'update',
        {
            'type': 'epg_matching_progress',
            'total': total_channels,
            'matched': matched_count,
            'remaining': total_channels - matched_count,
            'current_channel': current_channel_name,
            'stage': stage,
            'progress_percent': round(matched_count / total_channels * 100, 1) if total_channels > 0 else 0,
        },
    )


def send_single_channel_epg_match_result(channel_id, matched, message, channel=None, epg_data=None):
    """Notify the UI that a single-channel EPG match attempt has finished."""
    try:
        from apps.channels.serializers import ChannelSerializer

        payload = {
            "type": "single_channel_epg_match",
            "channel_id": channel_id,
            "matched": matched,
            "message": message,
        }
        if channel is not None:
            payload["channel"] = ChannelSerializer(channel).data
        if epg_data is not None:
            payload["epg_id"] = epg_data.id
            payload["epg_name"] = epg_data.name

        send_websocket_update('updates', 'update', payload)
    except Exception as e:
        logger.warning(f"Failed to send single channel EPG match result: {e}")


def _compute_fuzzy_score(chan_norm, row, region_code=None):
    """Compute fuzzy match score with optional region bonus/penalty."""
    if not row.get("norm_name"):
        return 0
    base_score = fuzz.ratio(chan_norm, row["norm_name"])
    bonus = 0
    if region_code and row.get("tvg_id"):
        combined_text = row["tvg_id"].lower() + " " + row["name"].lower()
        dot_regions = re.findall(r'\.([a-z]{2})', combined_text)
        if dot_regions:
            bonus = 15 if region_code in dot_regions else -15
        elif region_code in combined_text:
            bonus = 10
    return base_score + bonus


def _ml_cosine_similarities(st_model, util, query_text, candidate_texts):
    """Encode only the query plus candidate texts (not the full EPG database)."""
    if not candidate_texts:
        return []
    texts = [query_text] + list(candidate_texts)
    embeddings = st_model.encode(texts, convert_to_tensor=True, show_progress_bar=False)
    sim_scores = util.cos_sim(embeddings[0:1], embeddings[1:])[0]
    return [float(s) for s in sim_scores]


def _active_epg_lookup_queryset():
    """Lightweight queryset for exact EPG lookups (includes nameless entries)."""
    return (
        EPGData.objects
        .filter(epg_source__is_active=True)
        .values('id', 'tvg_id', 'name', 'epg_source_id', 'epg_source__priority')
    )


def _active_epg_fuzzy_queryset():
    """Lightweight queryset for fuzzy EPG matching (requires a display name)."""
    return (
        _active_epg_lookup_queryset()
        .filter(name__isnull=False)
        .exclude(name='')
    )


def _row_from_epg_values(values_row):
    tvg_id = values_row.get('tvg_id') or ''
    normalized_tvg_id = tvg_id.strip().lower() if tvg_id else ''
    return {
        'id': values_row['id'],
        'tvg_id': normalized_tvg_id,
        'original_tvg_id': tvg_id,
        'name': values_row['name'],
        'epg_source_id': values_row['epg_source_id'],
        'epg_source_priority': values_row.get('epg_source__priority') or 0,
    }


def lookup_epg_by_tvg_id(tvg_id):
    """Exact tvg_id lookup without loading the full EPG catalog into memory."""
    if not tvg_id:
        return None
    values_row = _active_epg_lookup_queryset().filter(tvg_id__iexact=tvg_id.strip()).first()
    return _row_from_epg_values(values_row) if values_row else None


def build_epg_matching_catalog():
    """
    Build the in-memory EPG catalog for bulk matching using a streaming DB cursor.

    Returns (epg_data, tvg_id_index): the full catalog plus an O(1) in-memory
    tvg_id lookup table (no extra DB queries). The index prefers the first entry
    per tvg_id after priority sorting.
    """
    epg_data = []
    for values_row in _active_epg_fuzzy_queryset().iterator(chunk_size=500):
        row = _row_from_epg_values(values_row)
        row['norm_name'] = normalize_name(row['name'])
        epg_data.append(row)
    epg_data.sort(key=lambda x: x['epg_source_priority'], reverse=True)
    return epg_data, build_epg_tvg_id_index(epg_data)


def build_epg_tvg_id_index(epg_data):
    """
    Build an in-memory tvg_id -> row index from an EPG catalog (no DB queries).
    epg_data must be sorted by source priority (highest first) so the first
    entry wins when multiple sources share the same tvg_id.
    """
    index = {}
    for row in epg_data:
        tvg_id = row.get("tvg_id")
        if tvg_id and tvg_id not in index:
            index[tvg_id] = row
    return index


def _dispatch_program_parse_for_epg_assignments(changed_associations):
    """
    Queue parse_programs once per unique EPG id newly assigned to a channel.

    bulk_update bypasses post_save, so callers must invoke this when epg_data
    actually changes (mirrors the M3U sync path).
    """
    if not changed_associations:
        return 0

    from apps.epg.tasks import parse_programs_for_tvg_id

    epg_ids = {
        assoc["epg_data_id"]
        for assoc in changed_associations
        if assoc.get("epg_data_id")
    }
    if not epg_ids:
        return 0

    dispatched = 0
    for epg in EPGData.objects.filter(id__in=epg_ids).select_related("epg_source"):
        source_type = epg.epg_source.source_type if epg.epg_source else None
        if source_type == "dummy":
            continue
        parse_programs_for_tvg_id.delay(epg.id)
        dispatched += 1
    return dispatched


def _log_unchanged_epg_assignment(chan, epg_id, epg_name, epg_tvg_id, match_method):
    chan_name = chan.get("name") or f"id={chan['id']}"
    chan_tvg = chan.get("original_tvg_id") or chan.get("tvg_id") or ""
    logger.debug(
        f"Channel '{chan_name}' (id={chan['id']}, tvg_id={chan_tvg!r}) "
        f"unchanged - already on EPG '{epg_name or '?'}' "
        f"(id={epg_id}, tvg_id={(epg_tvg_id or '?')!r}, via {match_method})"
    )


def _record_epg_match(
    chan,
    epg_id,
    *,
    epg_name,
    epg_tvg_id,
    match_method,
    channels_to_update,
    matched_channels,
    unchanged_channels,
):
    """Record a match result; skip channels_to_update when assignment is already correct."""
    if chan.get("current_epg_data_id") == epg_id:
        unchanged_channels.append((chan["id"], chan.get("name") or "", epg_tvg_id or ""))
        _log_unchanged_epg_assignment(chan, epg_id, epg_name, epg_tvg_id, match_method)
        return

    chan_name = chan.get("name") or f"id={chan['id']}"
    chan_tvg = chan.get("original_tvg_id") or chan.get("tvg_id") or ""
    fallback_name = chan.get("fallback_name") or chan_name
    chan["epg_data_id"] = epg_id
    channels_to_update.append(chan)
    matched_channels.append((chan["id"], fallback_name, epg_tvg_id or ""))
    logger.info(
        f"Channel '{chan_name}' (id={chan['id']}, tvg_id={chan_tvg!r}) "
        f"=> EPG '{epg_name or '?'}' (id={epg_id}, tvg_id={(epg_tvg_id or '?')!r}, via {match_method})"
    )


def apply_matched_epg_to_channels(channels_to_update_dicts):
    """
    Assign matched EPG rows to channels using two DB queries (channels + EPG).

    Skips channels that already have the matched EPG. Returns association dicts
    for channels whose epg_data assignment actually changed, and dispatches
    program-parse tasks only for those new assignments.
    """
    from apps.channels.models import Channel

    if not channels_to_update_dicts:
        return []

    channel_ids = [d["id"] for d in channels_to_update_dicts]
    epg_mapping = {d["id"]: d["epg_data_id"] for d in channels_to_update_dicts}
    epg_ids = {epg_id for epg_id in epg_mapping.values() if epg_id}

    epg_by_id = {epg.id: epg for epg in EPGData.objects.filter(id__in=epg_ids)}
    channels_list = list(Channel.objects.filter(id__in=channel_ids))

    changed_associations = []
    channels_to_bulk = []
    for channel_obj in channels_list:
        epg_data_id = epg_mapping.get(channel_obj.id)
        if not epg_data_id:
            continue
        if channel_obj.epg_data_id == epg_data_id:
            epg_row = epg_by_id.get(epg_data_id)
            _log_unchanged_epg_assignment(
                {
                    "id": channel_obj.id,
                    "name": channel_obj.name,
                    "original_tvg_id": channel_obj.tvg_id,
                },
                epg_data_id,
                epg_row.name if epg_row else None,
                epg_row.tvg_id if epg_row else None,
                "apply",
            )
            continue
        epg_data_obj = epg_by_id.get(epg_data_id)
        if epg_data_obj:
            channel_obj.epg_data = epg_data_obj
            channels_to_bulk.append(channel_obj)
            changed_associations.append(
                {"channel_id": channel_obj.id, "epg_data_id": epg_data_id}
            )
        else:
            logger.error(f"EPG data {epg_data_id} not found for channel {channel_obj.id}")

    if channels_to_bulk:
        Channel.objects.bulk_update(channels_to_bulk, ["epg_data"])

    parse_dispatched = _dispatch_program_parse_for_epg_assignments(changed_associations)
    if parse_dispatched:
        logger.info(
            f"Dispatched {parse_dispatched} EPG program parse task(s) for changed assignments"
        )

    return changed_associations


def get_preferred_region_code():
    try:
        region_obj = CoreSettings.objects.get(key="preferred-region")
        return region_obj.value.strip().lower()
    except CoreSettings.DoesNotExist:
        return None


def _fuzzy_scan_core(chan_norm, rows, region_code=None, candidate_limit=ML_CANDIDATE_LIMIT):
    """
    Single-pass fuzzy scan: track best match and top-K candidates.
    Rows must already include norm_name when scanning an in-memory catalog.
    """
    best_score = 0
    best_epg = None
    top_heap = []
    seq = 0
    scanned = 0

    for row in rows:
        if not row.get("norm_name"):
            continue

        scanned += 1
        score = _compute_fuzzy_score(chan_norm, row, region_code)
        if score <= 0:
            continue

        if score > 50:
            logger.debug(f"  EPG '{row['name']}' (norm: '{row['norm_name']}') => score: {score}")

        priority = row['epg_source_priority']
        if score > best_score or (
            score == best_score
            and priority > (best_epg.get('epg_source_priority', 0) if best_epg else -1)
        ):
            best_score = score
            best_epg = row

        seq += 1
        if len(top_heap) < candidate_limit:
            heapq.heappush(top_heap, (score, priority, seq, row))
        else:
            smallest_score, smallest_priority, _, _ = top_heap[0]
            if score > smallest_score or (score == smallest_score and priority > smallest_priority):
                heapq.heapreplace(top_heap, (score, priority, seq, row))

    top_candidates = sorted(top_heap, key=lambda item: (item[0], item[1]), reverse=True)
    return best_score, best_epg, [(score, row) for score, _, _, row in top_candidates], scanned


def fuzzy_scan_epg_list(chan_norm, epg_data, region_code=None, candidate_limit=ML_CANDIDATE_LIMIT):
    """Fuzzy scan over a pre-built in-memory EPG catalog (bulk matching)."""
    logger.debug(f"Fuzzy matching '{chan_norm}' against EPG entries...")
    return _fuzzy_scan_core(chan_norm, epg_data, region_code, candidate_limit)


def stream_fuzzy_epg_scan(chan_norm, region_code=None, candidate_limit=ML_CANDIDATE_LIMIT):
    """Stream fuzzy scan over active EPG entries (single-channel matching)."""

    def row_iterator():
        for values_row in _active_epg_fuzzy_queryset().iterator(chunk_size=500):
            row = _row_from_epg_values(values_row)
            row['norm_name'] = normalize_name(row['name'])
            yield row

    logger.debug(f"Fuzzy matching '{chan_norm}' against EPG entries...")
    return _fuzzy_scan_core(chan_norm, row_iterator(), region_code, candidate_limit)


def _get_epg_match_thresholds(is_bulk_matching):
    if is_bulk_matching:
        return {
            'FUZZY_HIGH_CONFIDENCE': 90,
            'FUZZY_SKIP_ML': 80,
            'FUZZY_MEDIUM_CONFIDENCE': 70,
            'ML_HIGH_CONFIDENCE': 0.75,
            'ML_LAST_RESORT': 0.65,
            'FUZZY_LAST_RESORT_MIN': 50,
        }
    return {
        'FUZZY_HIGH_CONFIDENCE': 85,
        'FUZZY_SKIP_ML': 75,
        'FUZZY_MEDIUM_CONFIDENCE': 40,
        'ML_HIGH_CONFIDENCE': 0.65,
        'ML_LAST_RESORT': 0.50,
        'FUZZY_LAST_RESORT_MIN': 20,
    }


def try_epg_name_match(chan, best_score, best_epg, top_candidates, is_bulk_matching,
                       use_ml=True, ml_state=None):
    """
    Apply fuzzy/ML thresholds to a channel's best fuzzy result.
    Returns the matched EPG row dict, or None.
    """
    if not best_epg:
        return None

    thresholds = _get_epg_match_thresholds(is_bulk_matching)
    fuzzy_high = thresholds['FUZZY_HIGH_CONFIDENCE']
    fuzzy_skip_ml = thresholds['FUZZY_SKIP_ML']
    fuzzy_medium = thresholds['FUZZY_MEDIUM_CONFIDENCE']
    ml_high = thresholds['ML_HIGH_CONFIDENCE']
    ml_last_resort = thresholds['ML_LAST_RESORT']
    fuzzy_last_resort_min = thresholds['FUZZY_LAST_RESORT_MIN']

    if best_score >= fuzzy_high:
        logger.info(
            f"Channel {chan['id']} '{chan['name']}' => matched tvg_id={best_epg['tvg_id']} "
            f"(score={best_score})"
        )
        return best_epg

    if best_score >= fuzzy_skip_ml:
        logger.info(
            f"Channel {chan['id']} '{chan['name']}' => matched tvg_id={best_epg['tvg_id']} "
            f"(fuzzy={best_score}, ML skipped)"
        )
        return best_epg

    if ml_state is None:
        ml_state = {}

    st_model = ml_state.get('st_model')
    util = ml_state.get('util')

    if best_score >= fuzzy_medium and use_ml:
        if st_model is None:
            st_model, util = get_sentence_transformer()
            ml_state['st_model'] = st_model
            ml_state['util'] = util

        if st_model:
            try:
                logger.info("Validating fuzzy best match with ML model (single candidate)")
                sims = _ml_cosine_similarities(st_model, util, chan["norm_chan"], [best_epg["norm_name"]])
                top_value = sims[0] if sims else 0.0

                if top_value >= ml_high - 1e-9:
                    logger.info(
                        f"Channel {chan['id']} '{chan['name']}' => matched EPG tvg_id={best_epg['tvg_id']} "
                        f"(fuzzy={best_score}, ML-sim={top_value:.2f})"
                    )
                    return best_epg
                if top_value >= ml_last_resort - 1e-9:
                    logger.info(
                        f"Channel {chan['id']} '{chan['name']}' => LAST RESORT match EPG "
                        f"tvg_id={best_epg['tvg_id']} (fuzzy={best_score}, ML-sim={top_value:.2f})"
                    )
                    return best_epg
                logger.info(
                    f"Channel {chan['id']} '{chan['name']}' => fuzzy={best_score}, "
                    f"ML-sim={top_value:.2f} < {ml_last_resort}, skipping"
                )
            except Exception as e:
                logger.warning(f"ML matching failed for channel {chan['id']}: {e}")
                logger.info(
                    f"Channel {chan['id']} '{chan['name']}' => fuzzy score {best_score} below threshold, skipping"
                )
        return None

    if best_score >= fuzzy_last_resort_min and use_ml:
        if st_model is None:
            st_model, util = get_sentence_transformer()
            ml_state['st_model'] = st_model
            ml_state['util'] = util

        if st_model and top_candidates:
            try:
                logger.info(
                    f"Channel {chan['id']} '{chan['name']}' => trying ML last resort against "
                    f"top {len(top_candidates)} fuzzy candidates (fuzzy={best_score})"
                )
                candidate_rows = [row for _, row in top_candidates]
                sims = _ml_cosine_similarities(
                    st_model,
                    util,
                    chan["norm_chan"],
                    [row["norm_name"] for row in candidate_rows],
                )
                top_index = max(range(len(sims)), key=lambda i: sims[i])
                top_value = sims[top_index]
                matched_epg = candidate_rows[top_index]

                if top_value >= ml_last_resort - 1e-9:
                    logger.info(
                        f"Channel {chan['id']} '{chan['name']}' => DESPERATE LAST RESORT match "
                        f"EPG tvg_id={matched_epg['tvg_id']} (fuzzy={best_score}, ML-sim={top_value:.2f})"
                    )
                    return matched_epg
                logger.info(
                    f"Channel {chan['id']} '{chan['name']}' => desperate last resort "
                    f"ML-sim {top_value:.2f} < {ml_last_resort}, giving up"
                )
            except Exception as e:
                logger.warning(f"Last resort ML matching failed for channel {chan['id']}: {e}")
                logger.info(
                    f"Channel {chan['id']} '{chan['name']}' => best fuzzy score={best_score} "
                    f"< {fuzzy_medium}, giving up"
                )
        return None

    logger.info(
        f"Channel {chan['id']} '{chan['name']}' => best fuzzy score={best_score} "
        f"< {fuzzy_medium}, no ML fallback available"
    )
    return None


def prepare_channel_match_data(channel):
    """Build the channel dict used by matching logic."""
    normalized_tvg_id = channel.tvg_id.strip().lower() if channel.tvg_id else ""
    normalized_gracenote_id = (
        channel.tvc_guide_stationid.strip().lower() if channel.tvc_guide_stationid else ""
    )
    return {
        "id": channel.id,
        "name": channel.name,
        "tvg_id": normalized_tvg_id,
        "original_tvg_id": channel.tvg_id,
        "gracenote_id": normalized_gracenote_id,
        "original_gracenote_id": channel.tvc_guide_stationid,
        "fallback_name": normalized_tvg_id if normalized_tvg_id else channel.name,
        "norm_chan": normalize_name(channel.name),
        "current_epg_data_id": channel.epg_data_id,
    }


def match_channels_to_epg(
    channels_data,
    epg_data,
    region_code=None,
    use_ml=True,
    send_progress=True,
    epg_tvg_id_index=None,
):
    """
    Match channels to EPG rows using exact ID, fuzzy, and optional ML strategies.

    epg_tvg_id_index: optional pre-built tvg_id -> row map from build_epg_matching_catalog().
    """
    channels_to_update = []
    matched_channels = []
    unchanged_channels = []
    total_channels = len(channels_data)

    if send_progress:
        send_epg_matching_progress(total_channels, 0, stage="starting")

    is_bulk_matching = len(channels_data) > 1
    ml_state = {}
    epg_by_tvg_id = epg_tvg_id_index if epg_tvg_id_index is not None else build_epg_tvg_id_index(epg_data)

    if is_bulk_matching:
        logger.info(f"Using conservative thresholds for bulk matching ({total_channels} channels)")
    else:
        logger.info("Using aggressive thresholds for single channel matching")

    for index, chan in enumerate(channels_data):
        normalized_tvg_id = chan.get("tvg_id", "")
        fallback_name = chan["tvg_id"].strip() if chan["tvg_id"] else chan["name"]

        resolved_count = len(matched_channels) + len(unchanged_channels)
        if send_progress and (index < 5 or index % 5 == 0 or index == total_channels - 1):
            send_epg_matching_progress(
                total_channels,
                resolved_count,
                current_channel_name=chan["name"][:50],
                stage="matching",
            )

        if normalized_tvg_id:
            epg_row = epg_by_tvg_id.get(normalized_tvg_id)
            if epg_row:
                _record_epg_match(
                    chan,
                    epg_row["id"],
                    epg_name=epg_row.get("name"),
                    epg_tvg_id=epg_row.get("original_tvg_id") or epg_row.get("tvg_id"),
                    match_method="exact tvg_id",
                    channels_to_update=channels_to_update,
                    matched_channels=matched_channels,
                    unchanged_channels=unchanged_channels,
                )
                continue

        normalized_gracenote_id = chan.get("gracenote_id", "")
        if normalized_gracenote_id:
            epg_by_gracenote_id = epg_by_tvg_id.get(normalized_gracenote_id)
            if epg_by_gracenote_id:
                _record_epg_match(
                    chan,
                    epg_by_gracenote_id["id"],
                    epg_name=epg_by_gracenote_id.get("name"),
                    epg_tvg_id=epg_by_gracenote_id.get("original_tvg_id")
                    or epg_by_gracenote_id.get("tvg_id"),
                    match_method="exact gracenote_id",
                    channels_to_update=channels_to_update,
                    matched_channels=matched_channels,
                    unchanged_channels=unchanged_channels,
                )
                continue

        if not chan["norm_chan"]:
            logger.debug(f"Channel {chan['id']} '{chan['name']}' => empty after normalization, skipping")
            continue

        best_score, best_epg, top_candidates, _scanned = fuzzy_scan_epg_list(
            chan["norm_chan"], epg_data, region_code
        )
        if not best_epg:
            logger.debug(f"Channel {chan['id']} '{chan['name']}' => no EPG entries with valid norm_name found")
            continue

        matched_epg = try_epg_name_match(
            chan,
            best_score,
            best_epg,
            top_candidates,
            is_bulk_matching,
            use_ml=use_ml,
            ml_state=ml_state,
        )
        if matched_epg:
            _record_epg_match(
                chan,
                matched_epg["id"],
                epg_name=matched_epg.get("name"),
                epg_tvg_id=matched_epg.get("original_tvg_id") or matched_epg.get("tvg_id"),
                match_method=f"fuzzy (score={best_score})",
                channels_to_update=channels_to_update,
                matched_channels=matched_channels,
                unchanged_channels=unchanged_channels,
            )

    if send_progress:
        send_epg_matching_progress(
            total_channels,
            len(matched_channels) + len(unchanged_channels),
            stage="completed",
        )

    return {
        "channels_to_update": channels_to_update,
        "matched_channels": matched_channels,
        "unchanged_channels": unchanged_channels,
    }


def run_single_channel_epg_match(channel_id):
    """
    Match one channel to EPG data. Always notifies the UI via WebSocket before returning.
    """
    from apps.channels.models import Channel

    channel = None
    try:
        logger.info(f"Starting integrated single channel EPG matching for channel ID {channel_id}")

        try:
            channel = Channel.objects.get(id=channel_id)
        except Channel.DoesNotExist:
            message = "Channel not found"
            send_single_channel_epg_match_result(channel_id, False, message)
            return {"matched": False, "message": message}

        channel_data = prepare_channel_match_data(channel)
        logger.info(
            f"Channel data prepared: name='{channel.name}', tvg_id='{channel_data['tvg_id']}', "
            f"gracenote_id='{channel_data['gracenote_id']}', norm_chan='{channel_data['norm_chan']}'"
        )

        send_epg_matching_progress(1, 0, current_channel_name=channel.name, stage="matching")
        region_code = get_preferred_region_code()

        fallback_name = channel_data["tvg_id"] if channel_data["tvg_id"] else channel.name
        matched_epg_row = None
        match_via = None

        if channel_data["tvg_id"]:
            matched_epg_row = lookup_epg_by_tvg_id(channel_data["tvg_id"])
            if matched_epg_row:
                match_via = matched_epg_row["tvg_id"]
                logger.info(
                    f"Channel {channel.id} '{fallback_name}' => EPG found by exact tvg_id={match_via}"
                )

        if not matched_epg_row and channel_data["gracenote_id"]:
            matched_epg_row = lookup_epg_by_tvg_id(channel_data["gracenote_id"])
            if matched_epg_row:
                match_via = f"gracenote:{matched_epg_row['tvg_id']}"
                logger.info(
                    f"Channel {channel.id} '{fallback_name}' => EPG found by exact "
                    f"gracenote_id={channel_data['gracenote_id']}"
                )

        if not matched_epg_row and channel_data["norm_chan"]:
            best_score, best_epg, top_candidates, scanned = stream_fuzzy_epg_scan(
                channel_data["norm_chan"], region_code
            )
            logger.info(
                f"Matching single channel '{channel.name}' against {scanned} EPG entries"
            )
            if best_epg:
                logger.info(
                    f"Channel {channel.id} '{channel.name}' => best match: '{best_epg['name']}' "
                    f"(score: {best_score})"
                )
                matched_epg_row = try_epg_name_match(
                    channel_data,
                    best_score,
                    best_epg,
                    top_candidates,
                    is_bulk_matching=False,
                    use_ml=True,
                )
                if matched_epg_row:
                    match_via = matched_epg_row["tvg_id"]
        elif not channel_data["norm_chan"]:
            logger.debug(f"Channel {channel.id} '{channel.name}' => empty after normalization, skipping")

        if not matched_epg_row:
            has_fuzzy_epg = _active_epg_fuzzy_queryset().exists()
            if not has_fuzzy_epg and not channel_data["tvg_id"] and not channel_data["gracenote_id"]:
                message = "No EPG data available for matching (from active sources)"
                send_epg_matching_progress(1, 0, current_channel_name=channel.name, stage="completed")
                send_single_channel_epg_match_result(channel.id, False, message, channel=channel)
                return {"matched": False, "message": message}

        if matched_epg_row:
            try:
                matched_epg_id = matched_epg_row["id"]
                epg_data = (
                    channel.epg_data
                    if channel.epg_data_id == matched_epg_id
                    else EPGData.objects.get(id=matched_epg_id)
                )

                if channel.epg_data_id == matched_epg_id:
                    success_msg = (
                        f"Channel '{channel.name}' already matched with EPG '{epg_data.name}'"
                    )
                    if match_via:
                        success_msg += f" (matched via: {match_via})"
                    logger.info(success_msg)
                    send_epg_matching_progress(1, 1, current_channel_name=channel.name, stage="completed")
                    send_single_channel_epg_match_result(
                        channel.id, True, success_msg, channel=channel, epg_data=epg_data
                    )
                    return {
                        "matched": True,
                        "unchanged": True,
                        "message": success_msg,
                        "epg_name": epg_data.name,
                        "epg_id": epg_data.id,
                    }

                channel.epg_data = epg_data
                channel.save(update_fields=["epg_data"])

                success_msg = f"Channel '{channel.name}' matched with EPG '{epg_data.name}'"
                if match_via:
                    success_msg += f" (matched via: {match_via})"

                logger.info(success_msg)
                send_epg_matching_progress(1, 1, current_channel_name=channel.name, stage="completed")
                channel.refresh_from_db()
                send_single_channel_epg_match_result(
                    channel.id, True, success_msg, channel=channel, epg_data=epg_data
                )
                return {
                    "matched": True,
                    "message": success_msg,
                    "epg_name": epg_data.name,
                    "epg_id": epg_data.id,
                }
            except EPGData.DoesNotExist:
                message = "Matched EPG data not found"
                send_single_channel_epg_match_result(channel.id, False, message, channel=channel)
                return {"matched": False, "message": message}

        send_epg_matching_progress(1, 0, current_channel_name=channel.name, stage="completed")
        message = f"No suitable EPG match found for channel '{channel.name}'"
        send_single_channel_epg_match_result(channel.id, False, message, channel=channel)
        return {"matched": False, "message": message}

    except Exception as e:
        logger.error(f"Error in integrated single channel EPG matching: {e}", exc_info=True)
        message = f"Error during matching: {str(e)}"
        send_single_channel_epg_match_result(
            channel_id,
            False,
            message,
            channel=channel,
        )
        return {"matched": False, "message": message}

    finally:
        cleanup_after_matching()
