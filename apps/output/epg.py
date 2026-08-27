"""XMLTV (EPG) output generation.

Consolidates the EPG export logic that backs the `/epg` endpoint and the XC
XMLTV endpoint: real programme streaming, dummy/custom dummy program
generation, and the streaming XMLTV builder. HTTP endpoints live in views.py
and call into this module; Redis chunk caching lives in streaming_chunk_cache.py.
"""

import html
import logging
from datetime import timedelta

from django.db.models import Prefetch
from django.http import Http404
from django.urls import reverse
from django.utils import timezone as django_timezone

from apps.channels.models import Channel, ChannelProfile, Stream
from apps.channels.utils import format_channel_number
from apps.epg.models import ProgramData
from apps.epg.utils import sd_poster_proxy_path
from apps.output.dummy_epg import (
    build_channel_logo_url,
    generate_dummy_programs,
    resolve_pattern_match_name,
)
from apps.output.streaming_chunk_cache import stream_cached_response
from core.utils import build_absolute_uri_with_port, log_system_event

logger = logging.getLogger(__name__)

_EPG_CHANNEL_XML_BATCH_SIZE = 200
_EPG_PROGRAM_YIELD_BATCH_SIZE = 1000
_EPG_PROGRAM_DB_CHUNK_SIZE = 20000


def _epg_export_teardown():
    from core.utils import spawn_memory_trim

    spawn_memory_trim(close_connections=True)


def generate_epg(request, profile_name=None, user=None, *, xc_catchup_prev_days=False):
    """
    Dynamically generate an XMLTV (EPG) file using a streaming response.
    Since the EPG data is stored independently of Channels, we group programmes
    by their associated EPGData record.
    """
    user_custom = (user.custom_properties or {}) if user else {}
    try:
        num_days = int(request.GET.get('days', user_custom.get('epg_days', 0)))
        num_days = max(0, min(num_days, 365))
    except (ValueError, TypeError):
        num_days = 0
    if xc_catchup_prev_days:
        from apps.channels.utils import resolve_xc_epg_prev_days

        prev_days = resolve_xc_epg_prev_days(request, user)
    else:
        try:
            prev_days = int(request.GET.get('prev_days', user_custom.get('epg_prev_days', 0)))
            prev_days = max(0, min(prev_days, 30))
        except (ValueError, TypeError):
            prev_days = 0
    use_cached_logos = request.GET.get('cachedlogos', 'true').lower() != 'false'
    tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

    request_origin = build_absolute_uri_with_port(request, "")
    cache_params = (
        f"{profile_name or 'all'}:{user.username if user else 'anonymous'}"
        f":d={num_days}:p={prev_days}:logos={use_cached_logos}:tvgid={tvg_id_source}"
        f":origin={request_origin}"
    )
    content_cache_key = f"epg_content:{cache_params}"

    def epg_generator():
        """Generator function that yields EPG data with keep-alives during processing."""

        yield '<?xml version="1.0" encoding="UTF-8"?>\n'
        yield (
            '<tv generator-info-name="Dispatcharr" '
            'generator-info-url="https://github.com/Dispatcharr/Dispatcharr">\n'
        )

        # Get channels based on user/profile
        if user is not None:
            if user.user_level < 10:
                user_profile_count = user.channel_profiles.count()

                # If user has ALL profiles or NO profiles, give unrestricted access
                if user_profile_count == 0:
                    # No profile filtering - user sees all channels based on user_level
                    filters = {"user_level__lte": user.user_level}
                    # Hide adult content if user preference is set
                    if (user.custom_properties or {}).get('hide_adult_content', False):
                        filters["is_adult"] = False
                    base_qs = Channel.objects.filter(**filters).select_related('logo', 'epg_data__epg_source')
                else:
                    # User has specific limited profiles assigned
                    filters = {
                        "channelprofilemembership__enabled": True,
                        "user_level__lte": user.user_level,
                        "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
                    }
                    # Hide adult content if user preference is set
                    if (user.custom_properties or {}).get('hide_adult_content', False):
                        filters["is_adult"] = False
                    base_qs = Channel.objects.filter(**filters).select_related('logo', 'epg_data__epg_source').distinct()
            else:
                base_qs = Channel.objects.filter(user_level__lte=user.user_level).select_related('logo', 'epg_data__epg_source')
        else:
            if profile_name is not None:
                try:
                    channel_profile = ChannelProfile.objects.get(name=profile_name)
                except ChannelProfile.DoesNotExist:
                    logger.warning("Requested channel profile (%s) during epg generation does not exist", profile_name)
                    raise Http404(f"Channel profile '{profile_name}' not found")
                base_qs = Channel.objects.filter(
                    channelprofilemembership__channel_profile=channel_profile,
                    channelprofilemembership__enabled=True,
                ).select_related('logo', 'epg_data__epg_source')
            else:
                base_qs = Channel.objects.all().select_related('logo', 'epg_data__epg_source')

        # Resolve effective values at SQL level and exclude hidden channels
        # so output ordering/display honors user overrides.
        from apps.channels.managers import with_effective_values
        channels = list(
            with_effective_values(base_qs, select_related_fks=True)
            .exclude(hidden_from_output=True)
            .order_by("effective_channel_number")
            .prefetch_related(
                Prefetch('streams', queryset=Stream.objects.only('id', 'name').order_by('channelstream__order'))
            )
        )
        channel_count = len(channels)

        # For dummy EPG, use either the specified value or default to 3 days
        dummy_days = num_days if num_days > 0 else 3

        # Calculate cutoff dates for EPG data filtering
        now = django_timezone.now()
        cutoff_date = now + timedelta(days=num_days) if num_days > 0 else None
        lookback_cutoff = now - timedelta(days=prev_days)

        # Build collision-free channel number mapping for XC clients (if user is authenticated)
        # XC clients require integer channel numbers, so we need to ensure no conflicts
        channel_num_map = {}
        if user is not None:
            used_numbers = set()
            deferred_channels = []

            for channel in channels:
                effective_num = channel.effective_channel_number
                if effective_num is None:
                    deferred_channels.append((channel.id, None))
                elif effective_num == int(effective_num):
                    num = int(effective_num)
                    channel_num_map[channel.id] = num
                    used_numbers.add(num)
                else:
                    deferred_channels.append((channel.id, effective_num))

            for channel_id, effective_num in deferred_channels:
                candidate = 1 if effective_num is None else int(effective_num)
                while candidate in used_numbers:
                    candidate += 1
                channel_num_map[channel_id] = candidate
                used_numbers.add(candidate)

        # Host/port/scheme are constant per request; precompute logo URL prefix once.
        _base_url = request_origin
        _sample_logo_path = reverse("api:channels:logo-cache", args=[0])
        _logo_prefix_raw, _, _logo_suffix_raw = _sample_logo_path.partition("/0/")
        _logo_url_prefix = _base_url + _logo_prefix_raw + "/"
        _logo_url_suffix = "/" + _logo_suffix_raw

        dummy_program_list = []
        real_epg_map = {}
        channel_xml_batch = []

        for channel in channels:
            effective_name = channel.effective_name
            effective_epg_data = channel.effective_epg_data_obj
            effective_epg_data_id = channel.effective_epg_data_id
            effective_logo = channel.effective_logo_obj
            effective_number = channel.effective_channel_number

            # user is set only for XC clients, which require integer channel numbers
            if user is not None:
                formatted_channel_number = channel_num_map[channel.id]
            else:
                formatted_channel_number = format_channel_number(effective_number)

            # Determine the channel ID based on the selected source
            if tvg_id_source == 'tvg_id' and channel.effective_tvg_id:
                channel_id = channel.effective_tvg_id
            elif tvg_id_source == 'gracenote' and channel.effective_tvc_guide_stationid:
                channel_id = channel.effective_tvc_guide_stationid
            else:
                channel_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

            tvg_logo = ""
            pattern_match_name = effective_name
            stream_lookup_failed = False
            custom_props = None
            if effective_epg_data and effective_epg_data.epg_source:
                epg_source = effective_epg_data.epg_source
                custom_props = epg_source.custom_properties or None
                if custom_props:
                    pattern_match_name, stream_lookup_failed = resolve_pattern_match_name(
                        channel, effective_name, custom_props
                    )
                    if (
                        custom_props.get('name_source') == 'stream'
                        and not stream_lookup_failed
                        and pattern_match_name != effective_name
                    ):
                        stream_index = custom_props.get('stream_index', 1) - 1
                        logger.debug(
                            "Using stream name for parsing: %s (stream index: %s)",
                            pattern_match_name,
                            stream_index,
                        )
                    elif stream_lookup_failed:
                        stream_index = custom_props.get('stream_index', 1) - 1
                        logger.warning(
                            "Stream index %s not found for channel %s, falling back to channel name",
                            stream_index,
                            effective_name,
                        )

            if (
                effective_epg_data
                and effective_epg_data.epg_source
                and effective_epg_data.epg_source.source_type == 'dummy'
                and custom_props
            ):
                try:
                    tvg_logo = build_channel_logo_url(pattern_match_name, custom_props) or ""
                    if tvg_logo:
                        logger.debug("Built channel logo URL from template: %s", tvg_logo)
                except Exception as e:
                    logger.warning(
                        "Failed to build channel logo URL for %s: %s", effective_name, e
                    )

            # If no custom dummy logo, use regular logo logic
            if not tvg_logo and effective_logo:
                if use_cached_logos:
                    tvg_logo = f"{_logo_url_prefix}{effective_logo.id}{_logo_url_suffix}"
                else:
                    # Use direct URL if available, otherwise fall back to cached version
                    direct_logo = effective_logo.url if effective_logo.url.startswith(('http://', 'https://')) else None
                    if direct_logo:
                        tvg_logo = direct_logo
                    else:
                        tvg_logo = f"{_logo_url_prefix}{effective_logo.id}{_logo_url_suffix}"
            channel_xml_batch.append(f'  <channel id="{html.escape(channel_id)}">')
            channel_xml_batch.append(f'    <display-name>{html.escape(effective_name)}</display-name>')
            channel_xml_batch.append(f'    <icon src="{html.escape(tvg_logo)}" />')
            channel_xml_batch.append("  </channel>")

            if len(channel_xml_batch) >= _EPG_CHANNEL_XML_BATCH_SIZE * 4:
                yield '\n'.join(channel_xml_batch) + '\n'
                channel_xml_batch = []

            if not effective_epg_data:
                dummy_program_list.append((channel_id, pattern_match_name, None))
            elif effective_epg_data.epg_source and effective_epg_data.epg_source.source_type == 'dummy':
                dummy_program_list.append((channel_id, pattern_match_name, effective_epg_data.epg_source))
            else:
                real_epg_map.setdefault(effective_epg_data_id, []).append(channel_id)

        if channel_xml_batch:
            yield '\n'.join(channel_xml_batch) + '\n'

        del channels
        del channel_num_map

        batch_size = _EPG_PROGRAM_YIELD_BATCH_SIZE

        all_epg_ids = list(real_epg_map.keys())
        if all_epg_ids:
            if num_days > 0:
                programs_qs = ProgramData.objects.filter(
                    epg_id__in=all_epg_ids,
                    end_time__gte=lookback_cutoff,
                    start_time__lt=cutoff_date,
                )
            else:
                programs_qs = ProgramData.objects.filter(
                    epg_id__in=all_epg_ids,
                    end_time__gte=lookback_cutoff,
                )

            programs_base_qs = programs_qs.order_by('epg_id', 'id').values(
                'id', 'epg_id', 'start_time', 'end_time', 'title', 'sub_title',
                'description', 'custom_properties',
            )

            current_epg_id = None
            channel_ids_for_epg = None
            escaped_primary_cid = None
            pending = []
            program_batch = []
            chunk_size = _EPG_PROGRAM_DB_CHUNK_SIZE
            last_epg_id = 0
            last_id = 0
            _poster_site_origin = request_origin

            def flush_pending():
                nonlocal program_batch, pending
                if not pending:
                    return
                pending.sort(key=lambda row: (row[0], row[1]))
                escaped_primary = (
                    escaped_primary_cid if len(channel_ids_for_epg) > 1 else None
                )
                for _, _, xml_text in pending:
                    program_batch.append(xml_text)
                    if escaped_primary:
                        for cid in channel_ids_for_epg[1:]:
                            program_batch.append(xml_text.replace(
                                f'channel="{escaped_primary}"',
                                f'channel="{html.escape(cid)}"',
                                1,
                            ))
                    if len(program_batch) >= batch_size:
                        yield '\n'.join(program_batch) + '\n'
                        program_batch = []
                pending.clear()

            while True:
                program_chunk = list(
                    programs_base_qs.filter(epg_id__gte=last_epg_id)
                    .exclude(epg_id=last_epg_id, id__lte=last_id)[:chunk_size]
                )
                if not program_chunk:
                    break

                last_row = program_chunk[-1]
                last_epg_id = last_row['epg_id']
                last_id = last_row['id']

                for prog in program_chunk:
                    epg_id = prog['epg_id']

                    if epg_id != current_epg_id:
                        yield from flush_pending()
                        current_epg_id = epg_id
                        channel_ids_for_epg = real_epg_map[epg_id]
                        escaped_primary_cid = html.escape(channel_ids_for_epg[0])

                    # DB datetimes are UTC (USE_TZ=True, TIME_ZONE=UTC); format
                    # directly instead of strftime("%Y%m%d%H%M%S %z"), which is
                    # ~10x slower and dominates XML build over 750k rows.
                    st = prog['start_time']
                    et = prog['end_time']
                    start_str = f"{st.year:04d}{st.month:02d}{st.day:02d}{st.hour:02d}{st.minute:02d}{st.second:02d} +0000"
                    stop_str = f"{et.year:04d}{et.month:02d}{et.day:02d}{et.hour:02d}{et.minute:02d}{et.second:02d} +0000"

                    program_xml = [f'  <programme start="{start_str}" stop="{stop_str}" channel="{escaped_primary_cid}">']
                    program_xml.append(f'    <title>{html.escape(prog["title"])}</title>')

                    if prog['sub_title']:
                        program_xml.append(f"    <sub-title>{html.escape(prog['sub_title'])}</sub-title>")

                    if prog['description']:
                        program_xml.append(f"    <desc>{html.escape(prog['description'])}</desc>")

                    custom_data = prog['custom_properties'] or {}
                    if custom_data:

                        if "categories" in custom_data and custom_data["categories"]:
                            for category in custom_data["categories"]:
                                program_xml.append(f"    <category>{html.escape(category)}</category>")

                        if "keywords" in custom_data and custom_data["keywords"]:
                            for keyword in custom_data["keywords"]:
                                program_xml.append(f"    <keyword>{html.escape(keyword)}</keyword>")

                        # onscreen_episode takes priority over episode for the onscreen system
                        if "onscreen_episode" in custom_data:
                            program_xml.append(f'    <episode-num system="onscreen">{html.escape(custom_data["onscreen_episode"])}</episode-num>')
                        elif "episode" in custom_data:
                            program_xml.append(f'    <episode-num system="onscreen">E{custom_data["episode"]}</episode-num>')

                        # Handle dd_progid format
                        if 'dd_progid' in custom_data:
                            program_xml.append(f'    <episode-num system="dd_progid">{html.escape(custom_data["dd_progid"])}</episode-num>')

                        # Handle external database IDs
                        for system in ['thetvdb.com', 'themoviedb.org', 'imdb.com']:
                            if f'{system}_id' in custom_data:
                                program_xml.append(f'    <episode-num system="{system}">{html.escape(custom_data[f"{system}_id"])}</episode-num>')

                        # Add season and episode numbers in xmltv_ns format if available
                        if "season" in custom_data and "episode" in custom_data:
                            season = (
                                int(custom_data["season"]) - 1
                                if str(custom_data["season"]).isdigit()
                                else 0
                            )
                            episode = (
                                int(custom_data["episode"]) - 1
                                if str(custom_data["episode"]).isdigit()
                                else 0
                            )
                            program_xml.append(f'    <episode-num system="xmltv_ns">{season}.{episode}.</episode-num>')

                        if "language" in custom_data:
                            program_xml.append(f'    <language>{html.escape(custom_data["language"])}</language>')

                        if "original_language" in custom_data:
                            program_xml.append(f'    <orig-language>{html.escape(custom_data["original_language"])}</orig-language>')

                        if "length" in custom_data and isinstance(custom_data["length"], dict):
                            length_value = custom_data["length"].get("value", "")
                            length_units = custom_data["length"].get("units", "minutes")
                            program_xml.append(f'    <length units="{html.escape(length_units)}">{html.escape(str(length_value))}</length>')

                        if "video" in custom_data and isinstance(custom_data["video"], dict):
                            program_xml.append("    <video>")
                            for attr in ['present', 'colour', 'aspect', 'quality']:
                                if attr in custom_data["video"]:
                                    program_xml.append(f"      <{attr}>{html.escape(custom_data['video'][attr])}</{attr}>")
                            program_xml.append("    </video>")

                        if "audio" in custom_data and isinstance(custom_data["audio"], dict):
                            program_xml.append("    <audio>")
                            for attr in ['present', 'stereo']:
                                if attr in custom_data["audio"]:
                                    program_xml.append(f"      <{attr}>{html.escape(custom_data['audio'][attr])}</{attr}>")
                            program_xml.append("    </audio>")

                        if "subtitles" in custom_data and isinstance(custom_data["subtitles"], list):
                            for subtitle in custom_data["subtitles"]:
                                if isinstance(subtitle, dict):
                                    subtitle_type = subtitle.get("type", "")
                                    type_attr = f' type="{html.escape(subtitle_type)}"' if subtitle_type else ""
                                    program_xml.append(f"    <subtitles{type_attr}>")
                                    if "language" in subtitle:
                                        program_xml.append(f"      <language>{html.escape(subtitle['language'])}</language>")
                                    program_xml.append("    </subtitles>")

                        if "rating" in custom_data:
                            rating_system = custom_data.get("rating_system", "TV Parental Guidelines")
                            program_xml.append(f'    <rating system="{html.escape(rating_system)}">')
                            program_xml.append(f'      <value>{html.escape(custom_data["rating"])}</value>')
                            program_xml.append(f"    </rating>")

                        if "star_ratings" in custom_data and isinstance(custom_data["star_ratings"], list):
                            for star_rating in custom_data["star_ratings"]:
                                if isinstance(star_rating, dict) and "value" in star_rating:
                                    system_attr = f' system="{html.escape(star_rating["system"])}"' if "system" in star_rating else ""
                                    program_xml.append(f"    <star-rating{system_attr}>")
                                    program_xml.append(f"      <value>{html.escape(star_rating['value'])}</value>")
                                    program_xml.append("    </star-rating>")

                        if "reviews" in custom_data and isinstance(custom_data["reviews"], list):
                            for review in custom_data["reviews"]:
                                if isinstance(review, dict) and "content" in review:
                                    review_type = review.get("type", "text")
                                    attrs = [f'type="{html.escape(review_type)}"']
                                    if "source" in review:
                                        attrs.append(f'source="{html.escape(review["source"])}"')
                                    if "reviewer" in review:
                                        attrs.append(f'reviewer="{html.escape(review["reviewer"])}"')
                                    attr_str = " ".join(attrs)
                                    program_xml.append(f'    <review {attr_str}>{html.escape(review["content"])}</review>')

                        if "images" in custom_data and isinstance(custom_data["images"], list):
                            for image in custom_data["images"]:
                                if isinstance(image, dict) and "url" in image:
                                    attrs = []
                                    for attr in ['type', 'size', 'orient', 'system']:
                                        if attr in image:
                                            attrs.append(f'{attr}="{html.escape(image[attr])}"')
                                    attr_str = " " + " ".join(attrs) if attrs else ""
                                    program_xml.append(f'    <image{attr_str}>{html.escape(image["url"])}</image>')

                        # Add enhanced credits handling
                        if "credits" in custom_data:
                            program_xml.append("    <credits>")
                            credits = custom_data["credits"]

                            for role in ['director', 'writer', 'adapter', 'producer', 'composer', 'editor', 'presenter', 'commentator', 'guest']:
                                if role in credits:
                                    people = credits[role]
                                    if isinstance(people, list):
                                        for person in people:
                                            program_xml.append(f"      <{role}>{html.escape(person)}</{role}>")
                                    else:
                                        program_xml.append(f"      <{role}>{html.escape(people)}</{role}>")

                            # Handle actors separately to include role and guest attributes
                            if "actor" in credits:
                                actors = credits["actor"]
                                if isinstance(actors, list):
                                    for actor in actors:
                                        if isinstance(actor, dict):
                                            name = actor.get("name", "")
                                            role_attr = f' role="{html.escape(actor["role"])}"' if "role" in actor else ""
                                            guest_attr = ' guest="yes"' if actor.get("guest") else ""
                                            program_xml.append(f"      <actor{role_attr}{guest_attr}>{html.escape(name)}</actor>")
                                        else:
                                            program_xml.append(f"      <actor>{html.escape(actor)}</actor>")
                                else:
                                    program_xml.append(f"      <actor>{html.escape(actors)}</actor>")

                            program_xml.append("    </credits>")

                        if "date" in custom_data:
                            program_xml.append(f'    <date>{html.escape(custom_data["date"])}</date>')

                        if "country" in custom_data:
                            program_xml.append(f'    <country>{html.escape(custom_data["country"])}</country>')

                        if "icon" in custom_data:
                            program_xml.append(f'    <icon src="{html.escape(custom_data["icon"])}" />')
                        elif "sd_icon" in custom_data:
                            poster_src = (
                                f'{_poster_site_origin}'
                                f'{sd_poster_proxy_path(prog["id"], custom_data["sd_icon"])}'
                            )
                            program_xml.append(
                                f'    <icon src="{html.escape(poster_src)}" />'
                            )

                        # Add special flags as proper tags with enhanced handling
                        if custom_data.get("previously_shown", False):
                            prev_shown_details = custom_data.get("previously_shown_details", {})
                            attrs = []
                            if "start" in prev_shown_details:
                                attrs.append(f'start="{html.escape(prev_shown_details["start"])}"')
                            if "channel" in prev_shown_details:
                                attrs.append(f'channel="{html.escape(prev_shown_details["channel"])}"')
                            attr_str = " " + " ".join(attrs) if attrs else ""
                            program_xml.append(f"    <previously-shown{attr_str} />")

                        if custom_data.get("premiere", False):
                            premiere_text = custom_data.get("premiere_text", "")
                            if premiere_text:
                                program_xml.append(f"    <premiere>{html.escape(premiere_text)}</premiere>")
                            else:
                                program_xml.append("    <premiere />")

                        if custom_data.get("last_chance", False):
                            last_chance_text = custom_data.get("last_chance_text", "")
                            if last_chance_text:
                                program_xml.append(f"    <last-chance>{html.escape(last_chance_text)}</last-chance>")
                            else:
                                program_xml.append("    <last-chance />")

                        if custom_data.get("new", False):
                            program_xml.append("    <new />")

                        if custom_data.get('live', False):
                            program_xml.append('    <live />')

                    program_xml.append("  </programme>")

                    xml_text = '\n'.join(program_xml)
                    pending.append((prog['start_time'], prog['id'], xml_text))

                del program_chunk

            yield from flush_pending()

            if program_batch:
                yield '\n'.join(program_batch) + '\n'

        del real_epg_map

        for channel_id, pattern_match_name, epg_source in dummy_program_list:
            program_length_hours = 4
            dummy_programs = generate_dummy_programs(
                channel_id, pattern_match_name,
                num_days=dummy_days,
                program_length_hours=program_length_hours,
                epg_source=epg_source,
                export_lookback=lookback_cutoff,
                export_cutoff=cutoff_date,
            )
            if not dummy_programs:
                continue
            dummy_batch = []
            for program in dummy_programs:
                start_str = program['start_time'].strftime("%Y%m%d%H%M%S %z")
                stop_str = program['end_time'].strftime("%Y%m%d%H%M%S %z")
                lines = [
                    f'  <programme start="{start_str}" stop="{stop_str}" channel="{html.escape(channel_id)}">',
                    f"    <title>{html.escape(program['title'])}</title>",
                ]
                if program.get('sub_title'):
                    lines.append(f"    <sub-title>{html.escape(program['sub_title'])}</sub-title>")
                lines.append(f"    <desc>{html.escape(program['description'])}</desc>")
                custom_data = program.get('custom_properties', {})
                if 'categories' in custom_data:
                    for cat in custom_data['categories']:
                        lines.append(f"    <category>{html.escape(cat)}</category>")
                if 'date' in custom_data:
                    lines.append(f"    <date>{html.escape(custom_data['date'])}</date>")
                if custom_data.get('live', False):
                    lines.append("    <live />")
                if custom_data.get('new', False):
                    lines.append("    <new />")
                if 'icon' in custom_data:
                    lines.append(f'    <icon src="{html.escape(custom_data["icon"])}" />')
                lines.append("  </programme>")
                dummy_batch.append('\n'.join(lines))
                if len(dummy_batch) >= batch_size:
                    yield '\n'.join(dummy_batch) + '\n'
                    dummy_batch = []
            del dummy_programs
            if dummy_batch:
                yield '\n'.join(dummy_batch) + '\n'

        del dummy_program_list

        yield "</tv>\n"

        from apps.output.views import get_client_identifier

        client_id, client_ip, user_agent = get_client_identifier(request)
        event_cache_key = f"epg_download:{user.username if user else 'anonymous'}:{profile_name or 'all'}:{client_id}"

        def _log_epg_download():
            from django.core.cache import cache as event_cache

            if not event_cache.get(event_cache_key):
                log_system_event(
                    event_type='epg_download',
                    profile=profile_name or 'all',
                    user=user.username if user else 'anonymous',
                    channels=channel_count,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
                event_cache.set(event_cache_key, True, 2)

        try:
            from core.utils import _is_gevent_monkey_patched

            if _is_gevent_monkey_patched():
                import gevent

                gevent.spawn(_log_epg_download)
            else:
                _log_epg_download()
        except Exception:
            _log_epg_download()

    def build_epg_stream():
        try:
            yield from epg_generator()
        finally:
            _epg_export_teardown()

    return stream_cached_response(
        content_cache_key,
        build_epg_stream,
        content_type="application/xml",
        filename="Dispatcharr.xml",
    )
