"""Read-only Library details, with provider payloads separate from title edits."""

import math

from django.db.models import Count, F
from django.http import Http404

from . import library
from .models import M3UEpisodeRelation
from .provider_metadata import normalize, source_priority_key, source_value


def source_images(source, kind, content_id, request):
    from .image_proxy import (
        format_vod_image_url,
        get_relation_artwork,
        is_proxyable_image_url,
        vod_image_url_parts,
    )

    artwork = get_relation_artwork(source.custom_properties)
    index, backdrop = next(
        (
            (index, url)
            for index, url in enumerate(artwork["backdrop_path"])
            if is_proxyable_image_url(url)
        ),
        (0, ""),
    )
    prefix, suffix = vod_image_url_parts(request, kind)
    return {
        field: (
            format_vod_image_url(
                prefix,
                suffix,
                content_id,
                image_kind,
                index=image_index,
                source_url=url,
                m3u_account_id=source.m3u_account_id,
                relation_id=source.pk,
            )
            if is_proxyable_image_url(url)
            else ""
        )
        for field, image_kind, url, image_index in (
            ("poster_url", "movie_image", artwork["movie_image"], 0),
            ("backdrop_url", "backdrop", backdrop, index),
        )
    }


def video_facts(video):
    video = video if isinstance(video, dict) else {}
    try:
        height = int(video.get("height") or 0)
    except (ValueError, TypeError, OverflowError):
        height = 0
    codec = video.get("codec_name")
    return {
        "resolution": f"{height}p" if 0 < height <= 20000 else "",
        "video_codec": codec[:100] if isinstance(codec, str) else "",
    }


def media_tracks(values):
    result = {}
    for field, keys in (
        (
            "video",
            (
                "codec_name",
                "codec_long_name",
                "profile",
                "width",
                "height",
                "bit_rate",
                "r_frame_rate",
                "avg_frame_rate",
                "display_aspect_ratio",
            ),
        ),
        (
            "audio",
            (
                "codec_name",
                "codec_long_name",
                "profile",
                "channel_layout",
                "channels",
                "sample_rate",
                "bit_rate",
            ),
        ),
    ):
        raw = values.get(field)
        result[field] = {
            key: value
            for key, value in (raw.items() if isinstance(raw, dict) else [])
            if key in keys and isinstance(value, (str, int, float))
        }
    return result


def provider_document(source, request=None):
    """Project only display fields, never account credentials or direct URLs."""
    from .tasks import extract_duration_from_data

    fields = {
        "description": ("plot", "description", "overview"),
        "year": ("year", "release_date", "releasedate", "first_air_date"),
        "release_date": ("release_date", "releasedate", "first_air_date"),
        "genre": ("genre",),
        "rating": ("rating", "vote_average"),
        "director": ("director",),
        "actors": ("actors", "cast"),
        "crew": ("crew",),
        "country": ("country", "production_country", "origin_country"),
        "age_rating": ("age", "age_rating", "rating_mpaa"),
        "tmdb_id": ("tmdb_id", "tmdb"),
        "imdb_id": ("imdb_id", "imdb"),
        "youtube_trailer": ("youtube_trailer", "trailer"),
    }
    values = {
        field: normalize(field, source_value(source, aliases))
        for field, aliases in fields.items()
    }
    kind = "movie" if hasattr(source, "movie_id") else "series"
    values.update(source_images(source, kind, getattr(source, f"{kind}_id"), request))
    values["name"] = library.source_title(source, getattr(source, kind))
    values["duration_secs"] = extract_duration_from_data(
        {
            "duration_secs": source_value(source, ("duration_secs",)),
            "duration": source_value(source, ("duration",)),
        }
    )
    values["technical"] = {
        "bitrate": normalize("bitrate", source_value(source, ("bitrate",)))
    }
    try:
        size = float(source_value(source, ("file_size_bytes", "filesize", "size")) or 0)
    except (ValueError, TypeError, OverflowError):
        size = 0
    values["technical"]["file_size_bytes"] = (
        size if math.isfinite(size) and size > 0 else None
    )
    values["technical"].update(
        media_tracks(
            {field: source_value(source, (field,)) for field in ("video", "audio")}
        )
    )
    values["details_loaded"] = bool(
        (source.custom_properties or {}).get("detailed_fetched")
    )
    return values


def episode_page(source, *, season=None, page=1, page_size=25, request=None):
    from .tasks import extract_duration_from_data

    # A single account can expose several variants of the same series. Do not
    # mix their episodes or fall back to another variant's stream identifier.
    queryset = M3UEpisodeRelation.objects.filter(
        series_relation=source,
        m3u_account_id=source.m3u_account_id,
        episode__series_id=source.series_id,
    )
    seasons = list(
        queryset.order_by("episode__season_number")
        .values("episode__season_number")
        .annotate(count=Count("pk"))
    )
    seasons = [
        {"number": row["episode__season_number"], "count": row["count"]}
        for row in seasons
    ]
    available = [row["number"] if row["number"] is not None else -1 for row in seasons]
    if season not in available:
        season = available[0] if available else None
    if season is not None:
        queryset = queryset.filter(
            episode__season_number=None if season == -1 else season
        )
    count = queryset.count()
    page = min(page, max(1, (count + page_size - 1) // page_size))
    result = []
    for relation in queryset.select_related("episode").order_by(
        "episode__season_number", "episode__episode_number", "pk"
    )[(page - 1) * page_size : page * page_size]:
        episode = relation.episode
        properties = relation.custom_properties or {}
        info = properties.get("info")
        if not isinstance(info, dict):
            info = properties
        details = info.get("info")
        if not isinstance(details, dict):
            details = info
        duration = extract_duration_from_data(details)
        result.append(
            {
                "id": relation.pk,
                "content_id": episode.pk,
                "uuid": str(episode.uuid),
                "name": str(info.get("title") or episode.name),
                "season_number": episode.season_number,
                "episode_number": episode.episode_number,
                "description": str(details.get("plot") or episode.description or ""),
                "duration_secs": (
                    duration if duration is not None else episode.duration_secs
                ),
                "air_date": episode.air_date,
                "rating": normalize("rating", details.get("rating"))
                or episode.rating
                or "",
                "imdb_id": str(details.get("imdb_id") or episode.imdb_id or ""),
                "tmdb_id": str(details.get("tmdb_id") or episode.tmdb_id or ""),
                "stream_id": relation.stream_id,
                "account_id": relation.m3u_account_id,
                "container_extension": relation.container_extension or "",
                "genre": normalize("genre", details.get("genre")) or "",
                "director": normalize("director", details.get("director")) or "",
                "actors": normalize(
                    "actors", details.get("actors") or details.get("cast")
                )
                or "",
                "technical": {
                    "bitrate": normalize("bitrate", details.get("bitrate")),
                    **media_tracks(details),
                },
                "poster_url": source_images(relation, "episode", episode.pk, request)[
                    "poster_url"
                ],
                **video_facts(details.get("video")),
            }
        )
    return {
        "seasons": seasons,
        "selected_season": season,
        "episodes": result,
        "episode_count": count,
        "episode_page": page,
        "episode_page_size": page_size,
    }


def series_video_facts(sources):
    paths = [
        f"custom_properties__{prefix}video" for prefix in ("info__info__", "info__", "")
    ]
    fields = [
        f"{path}__{field}" for path in paths for field in ("height", "codec_name")
    ]
    rows = (
        M3UEpisodeRelation.objects.filter(
            series_relation_id__in=[source.pk for source in sources],
            m3u_account_id=F("series_relation__m3u_account_id"),
            episode__series_id=F("series_relation__series_id"),
        )
        .order_by()
        .values_list("series_relation_id", *fields)
        .distinct()
    )
    result = {}
    for source_id, *values in rows:
        facts = {}
        for index in range(0, len(values), 2):
            candidate = video_facts(
                {"height": values[index], "codec_name": values[index + 1]}
            )
            for field, value in candidate.items():
                if value and not facts.get(field):
                    facts[field] = value
        entry = result.setdefault(
            source_id, {"episode_resolutions": set(), "episode_video_codecs": set()}
        )
        for target, field in (
            ("episode_resolutions", "resolution"),
            ("episode_video_codecs", "video_codec"),
        ):
            if facts.get(field):
                entry[target].add(facts[field])
    return {
        source_id: {field: sorted(values) for field, values in entry.items()}
        for source_id, entry in result.items()
    }


def detail_document(data, request, *, hide_adult=False):
    from .selection import resolve_content

    kind, pk = data["content_type"], data["id"]
    content, _ = resolve_content(kind, pk)
    if content is None or (content.library_blocked and request.user.user_level < 10):
        raise Http404("This title is not available.")
    pk = content.pk
    filters = {"content_id": pk, "_hide_adult": hide_adult}
    sources = list(
        library.relation_queryset(kind, filters).select_related(
            "m3u_account", "category", kind, f"{kind}__logo"
        )
    )
    if not sources:
        raise Http404("This title has no available source.")
    sources.sort(key=source_priority_key)
    selected = next(
        (source for source in sources if source.pk == data.get("source_id")),
        None,
    )
    if data.get("source_id") and selected is None:
        raise Http404("The selected source does not belong to this title.")
    selected = selected or next(
        (
            source
            for source in sources
            if source.m3u_account_id == data.get("preferred_account")
        ),
        sources[0],
    )
    canonical = library.page_documents(
        [{"id": pk, "content_id": pk, "content_type": kind}], request
    )[0]
    rows = library.page_documents(
        [
            {"id": source.pk, "content_id": pk, "content_type": kind}
            for source in sources
        ],
        request,
        sources=True,
    )
    by_id = {row["source_id"]: row for row in rows}
    documents = []
    series_facts = series_video_facts(sources) if kind == "series" else {}
    for source in sources:
        row = by_id[source.pk]
        provider = provider_document(source, request)
        provider["technical"].update(series_facts.get(source.pk, {}))
        documents.append(
            {
                **{
                    key: row[key]
                    for key in (
                        "source_id",
                        "content_id",
                        "content_type",
                        "provider_name",
                        "account",
                        "category",
                        "provider_id",
                        "container_extension",
                        "effective_metadata",
                        "manual_metadata",
                        "locked_fields",
                    )
                },
                "provider": provider,
            }
        )
    from .image_proxy import (
        get_relation_artwork,
        is_proxyable_image_url,
        rewrite_single_image_url,
    )

    settings = library.library_settings()
    if settings["prefer_artwork"] and content.tmdb_backdrop_url:
        canonical["backdrop_url"] = rewrite_single_image_url(
            request, kind, pk, "tmdb_backdrop", content.tmdb_backdrop_url
        )
    else:
        canonical["backdrop_url"] = documents[0]["provider"]["backdrop_url"]
        if not canonical["backdrop_url"]:
            backdrop = next(
                (
                    url
                    for url in get_relation_artwork(content.custom_properties)[
                        "backdrop_path"
                    ]
                    if is_proxyable_image_url(url)
                ),
                "",
            )
            canonical["backdrop_url"] = (
                rewrite_single_image_url(request, kind, pk, "backdrop", backdrop)
                if backdrop
                else ""
            )
    canonical["metadata"] = {
        **canonical["metadata"],
        "poster_url": canonical["poster_url"],
        "backdrop_url": canonical["backdrop_url"],
    }
    episodes = (
        episode_page(
            selected,
            season=data.get("season"),
            page=data["page"],
            page_size=data["page_size"],
            request=request,
        )
        if kind == "series"
        else {}
    )
    return {
        "canonical": canonical,
        "sources": documents,
        "selected_source_id": selected.pk,
        **episodes,
    }
