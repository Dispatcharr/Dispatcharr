"""Relation-owned VOD metadata and field-level precedence helpers."""

import re
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from .models import (
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
)


RELATION_CONFIG = {
    M3UMovieRelation: ("movie", "stream_id"),
    M3USeriesRelation: ("series", "external_series_id"),
    M3UEpisodeRelation: ("episode", "stream_id"),
}

MANUALLY_EDITABLE_SOURCE_METADATA_FIELDS = frozenset(
    {
        "audio_languages",
        "subtitle_languages",
        "resolution",
        "video_features",
    }
)


LANGUAGE_ALIASES = {
    "de": "ger",
    "deu": "ger",
    "ger": "ger",
    "german": "ger",
    "deutsch": "ger",
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    "englisch": "eng",
    "fr": "fre",
    "fra": "fre",
    "fre": "fre",
    "french": "fre",
    "français": "fre",
    "es": "spa",
    "spa": "spa",
    "spanish": "spa",
    "español": "spa",
    "it": "ita",
    "ita": "ita",
    "italian": "ita",
    "nl": "dut",
    "nld": "dut",
    "dut": "dut",
    "dutch": "dut",
}

# Dispatcharr exposes the bibliographic ISO-639-2 codes used by common IPTV
# clients (for example ``ger`` rather than the terminology code ``deu``).
# Keeping the allow-list here makes every write path validate the same values
# instead of letting arbitrary free text leak into policy matching.
ISO_639_2B_CODES = frozenset(
    """
    aar abk ace ach ada ady afa afh afr ain aka akk alb ale alg alt amh ang anp
    apa ara arc arg arm arn arp art arw asm ast ath aus ava ave awa aym aze bad
    bai bak bal bam ban baq bas bat bej bel bem ben ber bho bih bik bin bis bla
    bnt bod bos bra bre btk bua bug bul bur byn cad cai car cat cau ceb cel cha
    chb che chg chi chk chm chn cho chp chr chu chv chy cmc cnr cop cor cos cpe
    cpf cpp cre crh crp csb cus cze dak dan dar day del den dgr din div doi dra
    dsb dua dum dut dyu dzo efi egy eka elx eng enm epo est ewe ewo fan fao fat
    fij fil fin fiu fon fre frm fro frr frs fry ful fur gaa gay gba gem geo ger
    gez gil gla gle glg glv gmh goh gon gor got grb grc gre grn gsw guj gwi hai
    hat hau haw heb her hil him hin hit hmn hmo hrv hsb hun hup iba ibo ice ido
    iii ijo iku ile ilo ina inc ind ine inh ipk ira iro ita jav jbo jpn jpr jrb
    kaa kab kac kal kam kan kar kas kau kaw kaz kbd kha khi khm kho kik kin kir
    kmb kok kom kon kor kos kpe krc krl kro kru kua kum kur kut lad lah lam lao
    lat lav lez lim lin lit lol loz ltz lua lub lug lui lun luo lus mac mad mag
    mah mai mak mal man mao map mar mas may mdf mdr men mga mic min mis mkh mlg
    mlt mnc mni mno moh mon mos mul mun mus mwl mwr myn myv nah nai nap nau nav
    nbl nde ndo nds nep new nia nic niu nno nob nog non nor nqo nso nub nwc nya
    nym nyn nyo nzi oci oji ori orm osa oss ota oto paa pag pal pam pan pap pau
    peo per phi phn pli pol pon por pra pro pus que raj rap rar roa roh rom rum
    run rup rus sad sag sah sai sal sam san sas sat scn sco sel sem sga sgn shn
    sid sin sio sit sla slo slv sma sme smi smj smn smo sms sna snd snk sog som
    son sot spa srd srn srp srr ssa ssw suk sun sus sux swa swe syc syr tah tai
    tam tat tel tem ter tet tgk tgl tha tib tig tir tiv tkl tlh tli tmh tog ton
    tpi tsi tsn tso tuk tum tup tur tut tvl twi tyv udm uga uig ukr umb und urd
    uzb vai ven vie vol vot wak wal war was wel wen wln wol xal yao yap yid yor
    ypk zap zbl zen zgh zha znd zul zun zxx
    """.split()
)


VIDEO_FEATURE_ALIASES = {
    "3d": "3d",
    "sbs": "3d",
    "hsbs": "3d",
    "side-by-side": "3d",
    "side by side": "3d",
    "3d_sbs": "3d",
    "tab": "3d",
    "hou": "3d",
    "over-under": "3d",
    "top-and-bottom": "3d",
    "top and bottom": "3d",
    "3d_tab": "3d",
    "hdr": "hdr",
    "hdr10": "hdr",
    "hdr10+": "hdr",
    "hdr10_plus": "hdr",
    "hlg": "hdr",
    "dv": "dv",
    "dovi": "dv",
    "dolby vision": "dv",
    "dolby_vision": "dv",
}

VIDEO_FEATURES = frozenset({"3d", "hdr", "dv"})

IMAGE_VIDEO_CODECS = frozenset(
    {"apng", "bmp", "gif", "jpeg", "jpg", "mjpeg", "png", "tiff", "webp"}
)


def normalize_language_code(value):
    """Return Dispatcharr's English ISO-639-2/B language code."""
    code = str(value or "").strip().lower()
    return LANGUAGE_ALIASES.get(code, code)


def normalize_language_list(value):
    if isinstance(value, str):
        value = [part.strip() for part in value.replace(";", ",").split(",")]
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(
        dict.fromkeys(
            normalized
            for normalized in (normalize_language_code(item) for item in value)
            if normalized
        )
    )


def invalid_language_codes(value):
    """Return normalized values which are not ISO-639-2/B codes."""
    return [
        code
        for code in normalize_language_list(value)
        if code not in ISO_639_2B_CODES
    ]


def normalize_video_features(value):
    """Return stable built-in or explicitly namespaced custom feature tags."""
    if isinstance(value, str):
        value = [part.strip() for part in value.replace(";", ",").split(",")]
    if not isinstance(value, (list, tuple, set)):
        return []
    normalized = []
    for item in value:
        raw = str(item or "").strip().lower()
        if not raw:
            continue
        feature = VIDEO_FEATURE_ALIASES.get(raw)
        if not feature:
            custom = raw.removeprefix("custom:")
            custom = re.sub(r"[^a-z0-9._-]+", "-", custom).strip("-._")
            feature = f"custom:{custom}" if custom else ""
        if feature and feature not in normalized:
            normalized.append(feature)
    return normalized


def compatible_video_features(value):
    """Return concrete stored values matched by one UI/profile feature."""
    normalized = normalize_video_features([value])
    if not normalized:
        return []
    feature = normalized[0]
    return [feature]


def detect_video_features(*values):
    """Infer conservative 3D/HDR flags from provider names and video details."""
    text = " ".join(str(value or "") for value in values).lower()
    detected = []
    if re.search(r"(?:^|[\s._|\-])(?:h?sbs|side[\s._-]*by[\s._-]*side)(?:$|[\s._|\-])", text):
        detected.append("3d")
    elif re.search(r"(?:^|[\s._|\-])(?:h?ou|tab|top[\s._-]*and[\s._-]*bottom|over[\s._-]*under)(?:$|[\s._|\-])", text):
        detected.append("3d")
    elif re.search(r"(?:^|[\s._|\-])3d(?:$|[\s._|\-])", text):
        detected.append("3d")

    if re.search(r"\b(?:dolby[\s._-]*vision|dovi|dvhe|dvh1)\b", text):
        detected.append("dv")
    elif re.search(r"\bhdr10(?:\+(?!\w)|[\s._-]*plus\b)", text):
        detected.append("hdr")
    elif re.search(r"\bhdr10\b", text):
        detected.append("hdr")
    elif re.search(r"\b(?:hdr|smpte2084|smpte2086|pq)\b", text):
        detected.append("hdr")
    if re.search(r"\b(?:hlg|arib[\s._-]*std[\s._-]*b67)\b", text):
        detected.append("hdr")
    return list(dict.fromkeys(detected))


def validate_source_metadata(metadata):
    """Normalize source metadata and reject invalid language identifiers."""
    normalized = normalize_source_metadata(metadata)
    invalid = {}
    for field in ("audio_languages", "subtitle_languages", "languages"):
        bad = invalid_language_codes(normalized.get(field, []))
        if bad:
            invalid[field] = bad
    if invalid:
        details = "; ".join(
            f"{field}: {', '.join(values)}" for field, values in invalid.items()
        )
        raise ValueError(f"Use ISO-639-2/B language codes ({details})")
    return normalized


def validate_configurable_source_metadata(metadata):
    """Validate metadata that operators may assign to categories/sources."""
    if not isinstance(metadata, dict):
        raise ValueError("Source metadata must be an object")
    unsupported = sorted(
        set(metadata) - MANUALLY_EDITABLE_SOURCE_METADATA_FIELDS
    )
    if unsupported:
        raise ValueError(
            "Unsupported source metadata fields: " + ", ".join(unsupported)
        )
    return validate_source_metadata(metadata)


def normalize_source_metadata(metadata):
    """Normalize metadata at every API/provider/telemetry boundary."""
    normalized = dict(metadata or {})
    for field in ("audio_languages", "subtitle_languages", "languages"):
        if field in normalized:
            normalized[field] = normalize_language_list(normalized[field])
    if "video_features" in normalized:
        normalized["video_features"] = normalize_video_features(
            normalized["video_features"]
        )
    bitrate = normalize_bitrate_kbps(
        normalized.get("bitrate_kbps", normalized.get("bitrate"))
    )
    if bitrate:
        normalized["bitrate_kbps"] = bitrate
    file_size = normalize_file_size_bytes(
        normalized.get("file_size_bytes", normalized.get("file_size"))
    )
    if file_size:
        normalized["file_size_bytes"] = file_size
    return normalized


def _positive_int(value):
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _resolution_tier(width, height):
    """Return the conventional vertical resolution class for video dimensions."""
    for min_width, min_height, label in (
        (7680, 4320, "4320p"),
        (3840, 2160, "2160p"),
        (2560, 1440, "1440p"),
        (1920, 1080, "1080p"),
        (1280, 720, "720p"),
        (1024, 576, "576p"),
        (854, 480, "480p"),
        (640, 360, "360p"),
    ):
        # Width keeps cropped cinematic video such as 1920x960 in its
        # conventional 1080p class instead of inventing a 960p tier.
        if width >= min_width or height >= min_height:
            return label
    return ""


def _episode_provider_video_metadata(relation):
    """Extract trustworthy video facts from one provider episode payload.

    Some XC panels put the episode poster into the ``video`` slot.  Require a
    real, non-image codec and sane dimensions so those rows fall back to the
    operator's category resolution instead of becoming source metadata.
    """
    if not isinstance(relation, M3UEpisodeRelation):
        return {}
    properties = relation.custom_properties or {}
    episode_payload = properties.get("info") or {}
    if not isinstance(episode_payload, dict):
        return {}
    episode_info = episode_payload.get("info") or {}
    if not isinstance(episode_info, dict):
        episode_info = {}
    video = episode_info.get("video") or episode_payload.get("video") or {}
    if not isinstance(video, dict):
        return {}

    codec = str(video.get("codec_name") or video.get("codec") or "").strip().lower()
    disposition = video.get("disposition") or {}
    attached_picture = (
        disposition.get("attached_pic") if isinstance(disposition, dict) else False
    )
    if (
        not codec
        or codec in IMAGE_VIDEO_CODECS
        or str(attached_picture).strip().lower() in {"1", "true", "yes"}
    ):
        return {}

    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))
    if not (160 <= width <= 16384 and 120 <= height <= 8640):
        return {}
    resolution = _resolution_tier(width, height)
    if not resolution:
        return {}
    return {
        "resolution": resolution,
        "video_codec": codec,
    }


def summarize_episode_provider_video_metadata(relations):
    """Summarize valid provider video facts without flattening mixed episodes."""
    resolutions = set()
    video_codecs = set()
    for relation in relations:
        metadata = _episode_provider_video_metadata(relation)
        if metadata.get("resolution"):
            resolutions.add(metadata["resolution"])
        if metadata.get("video_codec"):
            video_codecs.add(metadata["video_codec"])
    return {
        "episode_resolutions": sorted(
            resolutions,
            key=lambda value: _positive_int(str(value).rstrip("p")),
        ),
        "episode_video_codecs": sorted(video_codecs),
    }


def merge_episode_provider_video_metadata(metadata, relations):
    """Add trustworthy episode video facts to one series-source payload."""
    summary = summarize_episode_provider_video_metadata(relations)
    values = dict(metadata.get("values") or {})
    provenance = dict(metadata.get("provenance") or {})
    for field, items in summary.items():
        if items:
            values[field] = items
            provenance[field] = "episode_provider"
    return {"values": values, "provenance": provenance}


def _positive_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    number = float(match.group(0).replace(",", "."))
    return number if number > 0 else None


def normalize_bitrate_kbps(value, *, bits_per_second=False):
    """Return a positive bitrate in kbps from common XC/ffprobe shapes."""
    number = _positive_number(value)
    if number is None:
        return None
    text = str(value or "").lower()
    if "mbit" in text or "mbps" in text:
        number *= 1000
    elif bits_per_second or (
        ("bit" in text or "bps" in text)
        and "kbit" not in text
        and "kbps" not in text
    ):
        number /= 1000
    return round(number, 2)


def normalize_file_size_bytes(value):
    """Return a positive byte count when a provider exposes file size."""
    number = _positive_number(value)
    if number is None:
        return None
    text = str(value or "").strip().lower()
    unit_match = re.search(r"(?:^|\d)\s*(kib|mib|gib|tib|kb|mb|gb|tb|b)\s*$", text)
    unit = unit_match.group(1) if unit_match else "b"
    multipliers = {
        "b": 1,
        "kb": 1000,
        "mb": 1000 ** 2,
        "gb": 1000 ** 3,
        "tb": 1000 ** 4,
        "kib": 1024,
        "mib": 1024 ** 2,
        "gib": 1024 ** 3,
        "tib": 1024 ** 4,
    }
    return int(number * multipliers[unit])


@transaction.atomic
def initialize_relation_metadata(relation):
    """Populate the stored metadata snapshot for one provider relation."""
    return sync_relation_declared_metadata(relation, notify_profile_change=False)


@transaction.atomic
def initialize_relations_metadata(relations):
    """Populate stored metadata snapshots and return concrete source keys."""
    ids_by_model = defaultdict(set)
    for relation in relations:
        ids_by_model[type(relation)].add(relation.pk)

    source_keys = set()
    for model, relation_ids in ids_by_model.items():
        queryset = model.objects.select_for_update(of=("self",)).select_related(
            "m3u_account"
        )
        if model is M3UEpisodeRelation:
            queryset = queryset.select_related("series_relation")
        locked = list(queryset.filter(pk__in=relation_ids).order_by("pk"))
        changed = []
        for relation in locked:
            declared = normalize_source_metadata(
                {
                    **category_defaults_for_relation(relation),
                    **relation_declared_metadata(relation),
                }
            )
            if declared != (relation.declared_metadata or {}):
                relation.declared_metadata = declared
                changed.append(relation)
            source_keys.add((RELATION_CONFIG[model][0], relation.pk))
        if changed:
            model.objects.bulk_update(
                changed, ["declared_metadata", "updated_at"], batch_size=1000
            )
    return source_keys


@transaction.atomic
def sync_category_relation_metadata(category_relation, *, batch_size=1000):
    """Copy one category's defaults onto all of its concrete source rows."""
    return sync_category_relations_metadata(
        [category_relation], batch_size=batch_size
    )


@transaction.atomic
def sync_category_relations_metadata(category_relations, *, batch_size=1000):
    """Copy category defaults onto all matching concrete source rows.

    Category settings are the import-time default, not something XC output
    should derive repeatedly. Re-syncing here also removes values that were
    removed from the category while retaining safe provider-owned scalars
    such as container and file size.
    """
    defaults_by_key = {
        (relation.m3u_account_id, relation.category_id): normalize_source_metadata(
            relation.metadata_defaults or {}
        )
        for relation in category_relations
    }
    if not defaults_by_key:
        return 0
    account_ids = {key[0] for key in defaults_by_key}
    category_ids = {key[1] for key in defaults_by_key}
    relation_specs = (
        (
            M3UMovieRelation,
            {
                "m3u_account_id__in": account_ids,
                "category_id__in": category_ids,
            },
            lambda relation: relation.category_id,
        ),
        (
            M3USeriesRelation,
            {
                "m3u_account_id__in": account_ids,
                "category_id__in": category_ids,
            },
            lambda relation: relation.category_id,
        ),
        (
            M3UEpisodeRelation,
            {
                "m3u_account_id__in": account_ids,
                "series_relation__category_id__in": category_ids,
            },
            lambda relation: relation.series_relation.category_id,
        ),
    )
    updated_count = 0
    now = timezone.now()
    for model, filters, category_id_getter in relation_specs:
        changed = []
        queryset = model.objects.filter(**filters)
        if model is M3UEpisodeRelation:
            queryset = queryset.select_related("series_relation")
        for relation in queryset.iterator(
            chunk_size=batch_size
        ):
            defaults = defaults_by_key.get(
                (relation.m3u_account_id, category_id_getter(relation))
            )
            if defaults is None:
                continue
            declared = {**defaults, **relation_declared_metadata(relation)}
            if declared == (relation.declared_metadata or {}):
                continue
            relation.declared_metadata = declared
            relation.updated_at = now
            changed.append(relation)
            if len(changed) == batch_size:
                model.objects.bulk_update(
                    changed,
                    ["declared_metadata", "updated_at"],
                    batch_size=batch_size,
                )
                updated_count += len(changed)
                changed = []
        if changed:
            model.objects.bulk_update(
                changed,
                ["declared_metadata", "updated_at"],
                batch_size=batch_size,
            )
            updated_count += len(changed)
    return updated_count


def category_defaults_for_relation(relation):
    category_id = getattr(relation, "category_id", None)
    if category_id is None:
        series_relation = getattr(relation, "series_relation", None)
        category_id = getattr(series_relation, "category_id", None)
    if not category_id:
        return {}
    category_relation = M3UVODCategoryRelation.objects.filter(
        m3u_account=relation.m3u_account,
        category_id=category_id,
    ).only("metadata_defaults").first()
    return category_relation.metadata_defaults if category_relation else {}


def relation_declared_metadata(relation):
    """Return only safe provider-owned scalar metadata.

    XC providers commonly expose one arbitrary audio stream, omit subtitles,
    and can report an attached cover as the video stream. DUB, SUB and
    features therefore come from category defaults, manual edits, or observed
    playback metadata. Episode resolution and video codec are accepted only
    when the provider payload identifies a real video stream; image streams
    are ignored so category resolution remains the fallback.
    """
    props = relation.custom_properties or {}
    detailed = props.get("detailed_info") or {}
    if not isinstance(detailed, dict):
        detailed = {}
    result = {}
    result.update(_episode_provider_video_metadata(relation))
    for key in ("bitrate", "container_extension"):
        value = detailed.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    # Movie/episode container extensions are already stored on the relation by
    # the fast catalog import.  They do not require an advanced provider fetch
    # and should therefore be visible in the effective source metadata.
    container_extension = getattr(relation, "container_extension", None)
    if not container_extension:
        for payload_name in ("movie_data", "basic_data"):
            payload = props.get(payload_name) or {}
            if isinstance(payload, dict) and payload.get("container_extension"):
                container_extension = payload["container_extension"]
                break
    if container_extension:
        result["container_extension"] = str(container_extension).lower()
    bitrate = normalize_bitrate_kbps(result.get("bitrate"))
    if bitrate:
        result["bitrate_kbps"] = bitrate
    for payload in (
        detailed,
        props.get("movie_data") or {},
        props.get("basic_data") or {},
    ):
        if not isinstance(payload, dict):
            continue
        raw_size = next(
            (
                payload.get(key)
                for key in ("file_size_bytes", "file_size", "filesize", "size")
                if payload.get(key) not in (None, "")
            ),
            None,
        )
        file_size = normalize_file_size_bytes(raw_size)
        if file_size:
            result["file_size_bytes"] = file_size
            break
    return normalize_source_metadata(result)


def sync_relation_declared_metadata(relation, *, notify_profile_change=True):
    """Persist category defaults and safe provider scalars on one relation."""
    declared = normalize_source_metadata(
        {
            **category_defaults_for_relation(relation),
            **relation_declared_metadata(relation),
        }
    )
    if declared != (relation.declared_metadata or {}):
        relation.declared_metadata = declared
        if notify_profile_change:
            relation.save(update_fields=["declared_metadata", "updated_at"])
        else:
            relation.__class__.objects.filter(pk=relation.pk).update(
                declared_metadata=declared,
                updated_at=timezone.now(),
            )
    return relation


def effective_relation_metadata(relation):
    return relation.effective_metadata(
        category_defaults=category_defaults_for_relation(relation),
        relation_declared=relation_declared_metadata(relation),
    )


def summarize_relation_metadata(relations, category_mapping=None):
    """Return a compact union of metadata across enabled source relations.

    The category mapping is cached globally, so this helper never performs a
    query per VOD row.
    """
    if category_mapping is None:
        from .policies import enabled_category_map

        category_mapping = enabled_category_map()

    audio_languages = set()
    subtitle_languages = set()
    resolutions = set()
    containers = set()
    video_features = set()
    source_count = 0
    for relation in relations:
        category_id = getattr(relation, "category_id", None)
        if category_id is None:
            series_relation = getattr(relation, "series_relation", None)
            category_id = getattr(series_relation, "category_id", None)
        defaults = category_mapping.get(
            (relation.m3u_account_id, category_id)
        )
        if defaults is None:
            continue
        declared = relation_declared_metadata(relation)
        metadata = relation.effective_metadata(
            category_defaults=defaults,
            relation_declared=declared,
        )["values"]
        audio_languages.update(
            normalize_language_list(
                metadata.get("audio_languages") or metadata.get("languages")
            )
        )
        subtitle_languages.update(
            normalize_language_list(metadata.get("subtitle_languages"))
        )
        resolution = metadata.get("resolution") or metadata.get("height")
        if resolution not in (None, "", [], {}):
            resolutions.add(str(resolution))
        container = metadata.get("container_extension")
        if container:
            containers.add(str(container).lower())
        video_features.update(normalize_video_features(metadata.get("video_features")))
        source_count += 1

    return {
        "audio_languages": sorted(audio_languages),
        "subtitle_languages": sorted(subtitle_languages),
        "resolutions": sorted(resolutions),
        "container_extensions": sorted(containers),
        "video_features": sorted(video_features),
        "source_count": source_count,
    }


def summarize_series_relation_metadata(
    series_relations,
    episode_relations,
    category_mapping=None,
):
    """Summarize series editions without double-counting their episodes.

    A category resolution is the default for one series source. Once that
    source exposes trustworthy episode video dimensions, the episode values
    replace its default. Other series sources without episode details retain
    their own defaults.
    """
    series_relations = list(series_relations)
    episode_relations = list(episode_relations)
    summary = summarize_relation_metadata(series_relations, category_mapping)
    episodes_by_source = defaultdict(list)
    for relation in episode_relations:
        episodes_by_source[relation.series_relation_id].append(relation)

    resolutions = set()
    for relation in series_relations:
        provider_video = summarize_episode_provider_video_metadata(
            episodes_by_source.get(relation.id, [])
        )
        if provider_video["episode_resolutions"]:
            resolutions.update(provider_video["episode_resolutions"])
            continue
        relation_summary = summarize_relation_metadata(
            [relation],
            category_mapping,
        )
        resolutions.update(relation_summary["resolutions"])

    # Legacy rows without a parent relation cannot replace one exact source,
    # but their valid video dimensions are still useful library information.
    orphan_video = summarize_episode_provider_video_metadata(
        episodes_by_source.get(None, [])
    )
    resolutions.update(orphan_video["episode_resolutions"])
    summary["resolutions"] = sorted(
        resolutions,
        key=lambda value: _positive_int(str(value).rstrip("p")),
    )

    episode_summary = summarize_relation_metadata(
        episode_relations,
        category_mapping,
    )
    if episode_summary["container_extensions"]:
        summary["container_extensions"] = episode_summary[
            "container_extensions"
        ]
    return summary
