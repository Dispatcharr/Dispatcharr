# apps/channels/tasks.py
import logging
import os
import re

from celery import shared_task
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer, util
from django.conf import settings
from django.db import transaction

from apps.channels.models import Channel
from apps.epg.models import EPGData, EPGSource
from core.models import CoreSettings
from apps.epg.tasks import parse_programs_for_tvg_id  # <-- we import our new helper

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

# Load the sentence-transformers model once at the module level
SENTENCE_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_PATH = os.path.join(settings.MEDIA_ROOT, "models", "all-MiniLM-L6-v2")
os.makedirs(MODEL_PATH, exist_ok=True)

# If not present locally, download:
if not os.path.exists(os.path.join(MODEL_PATH, "config.json")):
    logger.info(f"Local model not found in {MODEL_PATH}; downloading from {SENTENCE_MODEL_NAME}...")
    st_model = SentenceTransformer(SENTENCE_MODEL_NAME, cache_folder=MODEL_PATH)
else:
    logger.info(f"Loading local model from {MODEL_PATH}")
    st_model = SentenceTransformer(MODEL_PATH)

# Thresholds
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
      4) If a match is found, we set channel.tvg_id and also parse its programs
         from the cached EPG file (parse_programs_for_tvg_id).
      5) Summarize and log results.
    """
    logger.info("Starting EPG matching logic...")

    # Attempt to retrieve a "preferred-region" if configured
    try:
        region_obj = CoreSettings.objects.get(key="preferred-region")
        region_code = region_obj.value.strip().lower()
    except CoreSettings.DoesNotExist:
        region_code = None

    # Gather EPGData rows so we can do fuzzy matching in memory
    all_epg = {e.id: e for e in EPGData.objects.all()}

    epg_rows = []
    for e in list(all_epg.values()):
        epg_rows.append({
            "epg_id": e.id,
            "tvg_id": e.tvg_id or "",
            "raw_name": e.name,
            "norm_name": normalize_name(e.name),
        })

    epg_embeddings = None
    if any(row["norm_name"] for row in epg_rows):
        epg_embeddings = st_model.encode(
            [row["norm_name"] for row in epg_rows],
            convert_to_tensor=True
        )

    matched_channels = []

    source = EPGSource.objects.filter(is_active=True).first()
    epg_file_path = getattr(source, 'file_path', None) if source else None

    with transaction.atomic():
        for chan in Channel.objects.all():

            # A) Skip if channel.tvg_id is already valid
            if chan.tvg_id and EPGData.objects.filter(tvg_id=chan.tvg_id).exists():
                continue

            # B) If channel has a tvg_id that doesn't exist in EPGData, do direct check
            if chan.tvg_id:
                epg_match = EPGData.objects.filter(tvg_id=chan.tvg_id).first()
                if epg_match:
                    logger.info(f"Channel {chan.id} '{chan.name}' => EPG found by tvg_id={chan.tvg_id}")
                    continue

            # C) Perform name-based fuzzy matching
            fallback_name = chan.epg_data.name.strip() if chan.epg_data else chan.name
            norm_chan = normalize_name(fallback_name)
            if not norm_chan:
                logger.info(f"Channel {chan.id} '{chan.name}' => empty after normalization, skipping")
                continue

            best_score = 0
            best_epg = None
            for row in epg_rows:
                if not row["norm_name"]:
                    continue
                base_score = fuzz.ratio(norm_chan, row["norm_name"])
                bonus = 0
                # Region-based bonus/penalty
                combined_text = row["tvg_id"].lower() + " " + row["raw_name"].lower()
                dot_regions = re.findall(r'\.([a-z]{2})', combined_text)
                if region_code:
                    if dot_regions:
                        if region_code in dot_regions:
                            bonus = 30  # bigger bonus if .us or .ca matches
                        else:
                            bonus = -15
                    elif region_code in combined_text:
                        bonus = 15
                score = base_score + bonus

                logger.debug(
                    f"Channel {chan.id} '{fallback_name}' => EPG row {row['epg_id']}: "
                    f"raw_name='{row['raw_name']}', norm_name='{row['norm_name']}', "
                    f"combined_text='{combined_text}', dot_regions={dot_regions}, "
                    f"base_score={base_score}, bonus={bonus}, total_score={score}"
                )

                if score > best_score:
                    best_score = score
                    best_epg = row

            # If no best match was found, skip
            if not best_epg:
                logger.info(f"Channel {chan.id} '{fallback_name}' => no EPG match at all.")
                continue

            # If best_score is above BEST_FUZZY_THRESHOLD => direct accept
            if best_score >= BEST_FUZZY_THRESHOLD:
                chan.epg_data = all_epg[best_epg["epg_id"]]
                chan.save()

                # Attempt to parse program data for this channel
                if epg_file_path:
                    parse_programs_for_tvg_id(epg_file_path, all_epg[best_epg["epg_id"]])
                    logger.info(f"Loaded program data for tvg_id={best_epg['tvg_id']}")

                matched_channels.append((chan.id, fallback_name, best_epg["tvg_id"]))
                logger.info(
                    f"Channel {chan.id} '{fallback_name}' => matched tvg_id={best_epg['tvg_id']} "
                    f"(score={best_score})"
                )

            # If best_score is in the “middle range,” do embedding check
            elif best_score >= LOWER_FUZZY_THRESHOLD and epg_embeddings is not None:
                chan_embedding = st_model.encode(norm_chan, convert_to_tensor=True)
                sim_scores = util.cos_sim(chan_embedding, epg_embeddings)[0]
                top_index = int(sim_scores.argmax())
                top_value = float(sim_scores[top_index])
                if top_value >= EMBED_SIM_THRESHOLD:
                    matched_epg = epg_rows[top_index]
                    chan.epg_data = all_epg[matched_epg["epg_id"]]
                    chan.save()

                    if epg_file_path:
                        parse_programs_for_tvg_id(epg_file_path, all_epg[matched_epg["epg_id"]])
                        logger.info(f"Loaded program data for tvg_id={matched_epg['tvg_id']}")

                    matched_channels.append((chan.id, fallback_name, matched_epg["tvg_id"]))
                    logger.info(
                        f"Channel {chan.id} '{fallback_name}' => matched EPG tvg_id={matched_epg['tvg_id']} "
                        f"(fuzzy={best_score}, cos-sim={top_value:.2f})"
                    )
                else:
                    logger.info(
                        f"Channel {chan.id} '{fallback_name}' => fuzzy={best_score}, "
                        f"cos-sim={top_value:.2f} < {EMBED_SIM_THRESHOLD}, skipping"
                    )
            else:
                logger.info(
                    f"Channel {chan.id} '{fallback_name}' => fuzzy={best_score} < "
                    f"{LOWER_FUZZY_THRESHOLD}, skipping"
                )

    total_matched = len(matched_channels)
    if total_matched:
        logger.info(f"Match Summary: {total_matched} channel(s) matched.")
        for (cid, cname, tvg) in matched_channels:
            logger.info(f"  - Channel ID={cid}, Name='{cname}' => tvg_id='{tvg}'")
    else:
        logger.info("No new channels were matched.")

    logger.info("Finished EPG matching logic.")

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'updates',
        {
            'type': 'update',
            "data": {"success": True, "type": "epg_match"}
        }
    )

    return f"Done. Matched {total_matched} channel(s)."
