import ipaddress
from django.http import HttpResponse, JsonResponse, Http404, HttpResponseForbidden, StreamingHttpResponse
from rest_framework.response import Response
from django.urls import reverse
from apps.channels.models import Channel, ChannelProfile, ChannelGroup
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from apps.epg.models import ProgramData
from apps.accounts.models import User
from core.models import CoreSettings, NETWORK_ACCESS
from dispatcharr.utils import network_access_allowed
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import datetime, timedelta
import html  # Add this import for XML escaping
import json  # Add this import for JSON parsing
import time  # Add this import for keep-alive delays
from tzlocal import get_localzone
from urllib.parse import urlparse
import base64
import logging
from django.db.models.functions import Lower
import os
from apps.m3u.utils import calculate_tuner_count

logger = logging.getLogger(__name__)

def m3u_endpoint(request, profile_name=None, user=None):
    if not network_access_allowed(request, "M3U_EPG"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    return generate_m3u(request, profile_name, user)

def epg_endpoint(request, profile_name=None, user=None):
    if not network_access_allowed(request, "M3U_EPG"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    return generate_epg(request, profile_name, user)

@csrf_exempt
@require_http_methods(["GET", "POST"])
def generate_m3u(request, profile_name=None, user=None):
    """
    Dynamically generate an M3U file from channels.
    The stream URL now points to the new stream_view that uses StreamProfile.
    Supports both GET and POST methods for compatibility with IPTVSmarters.
    """
    logger.debug("Generating M3U for profile: %s, user: %s", profile_name, user.username if user else "Anonymous")
    # Check if this is a POST request with data (which we don't want to allow)
    if request.method == "POST" and request.body:
        return HttpResponseForbidden("POST requests with content are not allowed")

    if user is not None:
        if user.user_level == 0:
            user_profile_count = user.channel_profiles.count()

            # If user has ALL profiles or NO profiles, give unrestricted access
            if user_profile_count == 0:
                # No profile filtering - user sees all channels based on user_level
                channels = Channel.objects.filter(user_level__lte=user.user_level).order_by("channel_number")
            else:
                # User has specific limited profiles assigned
                filters = {
                    "channelprofilemembership__enabled": True,
                    "user_level__lte": user.user_level,
                    "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
                }
                channels = Channel.objects.filter(**filters).distinct().order_by("channel_number")
        else:
            channels = Channel.objects.filter(user_level__lte=user.user_level).order_by(
                "channel_number"
            )

    else:
        if profile_name is not None:
            channel_profile = ChannelProfile.objects.get(name=profile_name)
            channels = Channel.objects.filter(
                channelprofilemembership__channel_profile=channel_profile,
                channelprofilemembership__enabled=True
            ).order_by('channel_number')
        else:
            if profile_name is not None:
                channel_profile = ChannelProfile.objects.get(name=profile_name)
                channels = Channel.objects.filter(
                    channelprofilemembership__channel_profile=channel_profile,
                    channelprofilemembership__enabled=True,
                ).order_by("channel_number")
            else:
                channels = Channel.objects.order_by("channel_number")

    # Check if the request wants to use direct logo URLs instead of cache
    use_cached_logos = request.GET.get('cachedlogos', 'true').lower() != 'false'

    # Check if direct stream URLs should be used instead of proxy
    use_direct_urls = request.GET.get('direct', 'false').lower() == 'true'

    # Get the source to use for tvg-id value
    # Options: 'channel_number' (default), 'tvg_id', 'gracenote'
    tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

    # Build EPG URL with query parameters if needed
    epg_base_url = build_absolute_uri_with_port(request, reverse('output:epg_endpoint', args=[profile_name]) if profile_name else reverse('output:epg_endpoint'))

    # Optionally preserve certain query parameters
    preserved_params = ['tvg_id_source', 'cachedlogos', 'days']
    query_params = {k: v for k, v in request.GET.items() if k in preserved_params}
    if query_params:
        from urllib.parse import urlencode
        epg_url = f"{epg_base_url}?{urlencode(query_params)}"
    else:
        epg_url = epg_base_url

    # Add x-tvg-url and url-tvg attribute for EPG URL
    m3u_content = f'#EXTM3U x-tvg-url="{epg_url}" url-tvg="{epg_url}"\n'

    # Start building M3U content
    for channel in channels:
        group_title = channel.channel_group.name if channel.channel_group else "Default"

        # Format channel number as integer if it has no decimal component
        if channel.channel_number is not None:
            if channel.channel_number == int(channel.channel_number):
                formatted_channel_number = int(channel.channel_number)
            else:
                formatted_channel_number = channel.channel_number
        else:
            formatted_channel_number = ""

        # Determine the tvg-id based on the selected source
        if tvg_id_source == 'tvg_id' and channel.tvg_id:
            tvg_id = channel.tvg_id
        elif tvg_id_source == 'gracenote' and channel.tvc_guide_stationid:
            tvg_id = channel.tvc_guide_stationid
        else:
            # Default to channel number (original behavior)
            tvg_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

        tvg_name = channel.name

        tvg_logo = ""
        if channel.logo:
            if use_cached_logos:
                # Use cached logo as before
                tvg_logo = build_absolute_uri_with_port(request, reverse('api:channels:logo-cache', args=[channel.logo.id]))
            else:
                # Try to find direct logo URL from channel's streams
                direct_logo = channel.logo.url if channel.logo.url.startswith(('http://', 'https://')) else None
                # If direct logo found, use it; otherwise fall back to cached version
                if direct_logo:
                    tvg_logo = direct_logo
                else:
                    tvg_logo = build_absolute_uri_with_port(request, reverse('api:channels:logo-cache', args=[channel.logo.id]))

        # create possible gracenote id insertion
        tvc_guide_stationid = ""
        if channel.tvc_guide_stationid:
            tvc_guide_stationid = (
                f'tvc-guide-stationid="{channel.tvc_guide_stationid}" '
            )

        extinf_line = (
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" '
            f'tvg-chno="{formatted_channel_number}" {tvc_guide_stationid}group-title="{group_title}",{channel.name}\n'
        )

        # Determine the stream URL based on the direct parameter
        if use_direct_urls:
            # Try to get the first stream's direct URL
            first_stream = channel.streams.order_by('channelstream__order').first()
            if first_stream and first_stream.url:
                # Use the direct stream URL
                stream_url = first_stream.url
            else:
                # Fall back to proxy URL if no direct URL available
                base_url = request.build_absolute_uri('/')[:-1]
                stream_url = f"{base_url}/proxy/ts/stream/{channel.uuid}"
        else:
            # Standard behavior - use proxy URL
            base_url = request.build_absolute_uri('/')[:-1]
            stream_url = f"{base_url}/proxy/ts/stream/{channel.uuid}"

        m3u_content += extinf_line + stream_url + "\n"

    response = HttpResponse(m3u_content, content_type="audio/x-mpegurl")
    response["Content-Disposition"] = 'attachment; filename="channels.m3u"'
    return response


def generate_dummy_programs(channel_id, channel_name, num_days=1, program_length_hours=4):
    # Get current time rounded to hour
    now = timezone.now()
    now = now.replace(minute=0, second=0, microsecond=0)

    # Humorous program descriptions based on time of day
    time_descriptions = {
        (0, 4): [
            f"Late Night with {channel_name} - Where insomniacs unite!",
            f"The 'Why Am I Still Awake?' Show on {channel_name}",
            f"Counting Sheep - A {channel_name} production for the sleepless",
        ],
        (4, 8): [
            f"Dawn Patrol - Rise and shine with {channel_name}!",
            f"Early Bird Special - Coffee not included",
            f"Morning Zombies - Before coffee viewing on {channel_name}",
        ],
        (8, 12): [
            f"Mid-Morning Meetings - Pretend you're paying attention while watching {channel_name}",
            f"The 'I Should Be Working' Hour on {channel_name}",
            f"Productivity Killer - {channel_name}'s daytime programming",
        ],
        (12, 16): [
            f"Lunchtime Laziness with {channel_name}",
            f"The Afternoon Slump - Brought to you by {channel_name}",
            f"Post-Lunch Food Coma Theater on {channel_name}",
        ],
        (16, 20): [
            f"Rush Hour - {channel_name}'s alternative to traffic",
            f"The 'What's For Dinner?' Debate on {channel_name}",
            f"Evening Escapism - {channel_name}'s remedy for reality",
        ],
        (20, 24): [
            f"Prime Time Placeholder - {channel_name}'s finest not-programming",
            f"The 'Netflix Was Too Complicated' Show on {channel_name}",
            f"Family Argument Avoider - Courtesy of {channel_name}",
        ],
    }

    programs = []

    # Create programs for each day
    for day in range(num_days):
        day_start = now + timedelta(days=day)

        # Create programs with specified length throughout the day
        for hour_offset in range(0, 24, program_length_hours):
            # Calculate program start and end times
            start_time = day_start + timedelta(hours=hour_offset)
            end_time = start_time + timedelta(hours=program_length_hours)

            # Get the hour for selecting a description
            hour = start_time.hour

            # Find the appropriate time slot for description
            for time_range, descriptions in time_descriptions.items():
                start_range, end_range = time_range
                if start_range <= hour < end_range:
                    # Pick a description using the sum of the hour and day as seed
                    # This makes it somewhat random but consistent for the same timeslot
                    description = descriptions[(hour + day) % len(descriptions)]
                    break
            else:
                # Fallback description if somehow no range matches
                description = f"Placeholder program for {channel_name} - EPG data went on vacation"

            programs.append({
                "channel_id": channel_id,
                "start_time": start_time,
                "end_time": end_time,
                "title": channel_name,
                "description": description,
            })

    return programs


def generate_dummy_epg(
    channel_id, channel_name, xml_lines=None, num_days=1, program_length_hours=4
):
    """
    Generate dummy EPG programs for channels without EPG data.
    Creates program blocks for a specified number of days.

    Args:
        channel_id: The channel ID to use in the program entries
        channel_name: The name of the channel to use in program titles
        xml_lines: Optional list to append lines to, otherwise returns new list
        num_days: Number of days to generate EPG data for (default: 1)
        program_length_hours: Length of each program block in hours (default: 4)

    Returns:
        List of XML lines for the dummy EPG entries
    """
    if xml_lines is None:
        xml_lines = []

    for program in generate_dummy_programs(channel_id, channel_name, num_days=1, program_length_hours=4):
        # Format times in XMLTV format
        start_str = program['start_time'].strftime("%Y%m%d%H%M%S %z")
        stop_str = program['end_time'].strftime("%Y%m%d%H%M%S %z")

        # Create program entry with escaped channel name
        xml_lines.append(
            f'  <programme start="{start_str}" stop="{stop_str}" channel="{program["channel_id"]}">'
        )
        xml_lines.append(f"    <title>{html.escape(program['title'])}</title>")
        xml_lines.append(f"    <desc>{html.escape(program['description'])}</desc>")
        xml_lines.append(f"  </programme>")

    return xml_lines


def generate_epg(request, profile_name=None, user=None):
    """
    Dynamically generate an XMLTV (EPG) file using streaming response to handle keep-alives.
    Since the EPG data is stored independently of Channels, we group programmes
    by their associated EPGData record.
    This version filters data based on the 'days' parameter and sends keep-alives during processing.
    """
    def epg_generator():
        """Generator function that yields EPG data with keep-alives during processing"""        # Send initial HTTP headers as comments (these will be ignored by XML parsers but keep connection alive)

        xml_lines = []
        xml_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        xml_lines.append(
            '<tv generator-info-name="Dispatcharr" generator-info-url="https://github.com/Dispatcharr/Dispatcharr">'
        )

        # Get channels based on user/profile
        if user is not None:
            if user.user_level == 0:
                user_profile_count = user.channel_profiles.count()

                # If user has ALL profiles or NO profiles, give unrestricted access
                if user_profile_count == 0:
                    # No profile filtering - user sees all channels based on user_level
                    channels = Channel.objects.filter(user_level__lte=user.user_level).order_by("channel_number")
                else:
                    # User has specific limited profiles assigned
                    filters = {
                        "channelprofilemembership__enabled": True,
                        "user_level__lte": user.user_level,
                        "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
                    }
                    channels = Channel.objects.filter(**filters).distinct().order_by("channel_number")
            else:
                channels = Channel.objects.filter(user_level__lte=user.user_level).order_by(
                    "channel_number"
                )
        else:
            if profile_name is not None:
                channel_profile = ChannelProfile.objects.get(name=profile_name)
                channels = Channel.objects.filter(
                    channelprofilemembership__channel_profile=channel_profile,
                    channelprofilemembership__enabled=True,
                ).order_by("channel_number")
            else:
                channels = Channel.objects.all().order_by("channel_number")

        # Check if the request wants to use direct logo URLs instead of cache
        use_cached_logos = request.GET.get('cachedlogos', 'true').lower() != 'false'

        # Get the source to use for tvg-id value
        # Options: 'channel_number' (default), 'tvg_id', 'gracenote'
        tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

        # Get the number of days for EPG data
        try:
            # Default to 0 days (everything) for real EPG if not specified
            days_param = request.GET.get('days', '0')
            num_days = int(days_param)
            # Set reasonable limits
            num_days = max(0, min(num_days, 365))  # Between 0 and 365 days
        except ValueError:
            num_days = 0  # Default to all data if invalid value

        # For dummy EPG, use either the specified value or default to 3 days
        dummy_days = num_days if num_days > 0 else 3

        # Calculate cutoff date for EPG data filtering (only if days > 0)
        now = timezone.now()
        cutoff_date = now + timedelta(days=num_days) if num_days > 0 else None

        # Process channels for the <channel> section
        for channel in channels:
            # Format channel number as integer if it has no decimal component - same as M3U generation
            if channel.channel_number is not None:
                if channel.channel_number == int(channel.channel_number):
                    formatted_channel_number = int(channel.channel_number)
                else:
                    formatted_channel_number = channel.channel_number
            else:
                formatted_channel_number = ""

            # Determine the channel ID based on the selected source
            if tvg_id_source == 'tvg_id' and channel.tvg_id:
                channel_id = channel.tvg_id
            elif tvg_id_source == 'gracenote' and channel.tvc_guide_stationid:
                channel_id = channel.tvc_guide_stationid
            else:
                # Default to channel number (original behavior)
                channel_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

            # Add channel logo if available
            tvg_logo = ""
            if channel.logo:
                if use_cached_logos:
                    # Use cached logo as before
                    tvg_logo = build_absolute_uri_with_port(request, reverse('api:channels:logo-cache', args=[channel.logo.id]))
                else:
                    # Try to find direct logo URL from channel's streams
                    direct_logo = channel.logo.url if channel.logo.url.startswith(('http://', 'https://')) else None
                    # If direct logo found, use it; otherwise fall back to cached version
                    if direct_logo:
                        tvg_logo = direct_logo
                    else:
                        tvg_logo = build_absolute_uri_with_port(request, reverse('api:channels:logo-cache', args=[channel.logo.id]))
            display_name = channel.name
            xml_lines.append(f'  <channel id="{channel_id}">')
            xml_lines.append(f'    <display-name>{html.escape(display_name)}</display-name>')
            xml_lines.append(f'    <icon src="{html.escape(tvg_logo)}" />')
            xml_lines.append("  </channel>")

        # Send all channel definitions
        yield '\n'.join(xml_lines) + '\n'
        xml_lines = []  # Clear to save memory

        # Process programs for each channel
        for channel in channels:

            # Use the same channel ID determination for program entries
            if tvg_id_source == 'tvg_id' and channel.tvg_id:
                channel_id = channel.tvg_id
            elif tvg_id_source == 'gracenote' and channel.tvc_guide_stationid:
                channel_id = channel.tvc_guide_stationid
            else:
                # Get formatted channel number
                if channel.channel_number is not None:
                    if channel.channel_number == int(channel.channel_number):
                        formatted_channel_number = int(channel.channel_number)
                    else:
                        formatted_channel_number = channel.channel_number
                else:
                    formatted_channel_number = ""
                # Default to channel number
                channel_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

            display_name = channel.epg_data.name if channel.epg_data else channel.name

            if not channel.epg_data:
                # Use the enhanced dummy EPG generation function with defaults
                program_length_hours = 4  # Default to 4-hour program blocks
                dummy_programs = generate_dummy_programs(channel_id, display_name, num_days=dummy_days, program_length_hours=program_length_hours)

                for program in dummy_programs:
                    # Format times in XMLTV format
                    start_str = program['start_time'].strftime("%Y%m%d%H%M%S %z")
                    stop_str = program['end_time'].strftime("%Y%m%d%H%M%S %z")

                    # Create program entry with escaped channel name
                    yield f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">\n'
                    yield f"    <title>{html.escape(program['title'])}</title>\n"
                    yield f"    <desc>{html.escape(program['description'])}</desc>\n"
                    yield f"  </programme>\n"

            else:
                # For real EPG data - filter only if days parameter was specified
                if num_days > 0:
                    programs_qs = channel.epg_data.programs.filter(
                        start_time__gte=now,
                        start_time__lt=cutoff_date
                    ).order_by('id')  # Explicit ordering for consistent chunking
                else:
                    # Return all programs if days=0 or not specified
                    programs_qs = channel.epg_data.programs.all().order_by('id')

                # Process programs in chunks to avoid cursor timeout issues
                program_batch = []
                batch_size = 250
                chunk_size = 1000  # Fetch 1000 programs at a time from DB

                # Fetch chunks until no more results (avoids count() query)
                offset = 0
                while True:
                    # Fetch a chunk of programs - this closes the cursor after fetching
                    program_chunk = list(programs_qs[offset:offset + chunk_size])

                    # Break if no more programs
                    if not program_chunk:
                        break

                    # Process each program in the chunk
                    for prog in program_chunk:
                        start_str = prog.start_time.strftime("%Y%m%d%H%M%S %z")
                        stop_str = prog.end_time.strftime("%Y%m%d%H%M%S %z")

                        program_xml = [f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">']
                        program_xml.append(f'    <title>{html.escape(prog.title)}</title>')

                        # Add subtitle if available
                        if prog.sub_title:
                            program_xml.append(f"    <sub-title>{html.escape(prog.sub_title)}</sub-title>")

                        # Add description if available
                        if prog.description:
                            program_xml.append(f"    <desc>{html.escape(prog.description)}</desc>")

                        # Process custom properties if available
                        if prog.custom_properties:
                            custom_data = prog.custom_properties or {}

                            # Add categories if available
                            if "categories" in custom_data and custom_data["categories"]:
                                for category in custom_data["categories"]:
                                    program_xml.append(f"    <category>{html.escape(category)}</category>")

                            # Add keywords if available
                            if "keywords" in custom_data and custom_data["keywords"]:
                                for keyword in custom_data["keywords"]:
                                    program_xml.append(f"    <keyword>{html.escape(keyword)}</keyword>")

                            # Handle episode numbering - multiple formats supported
                            # Prioritize onscreen_episode over standalone episode for onscreen system
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

                            # Add language information
                            if "language" in custom_data:
                                program_xml.append(f'    <language>{html.escape(custom_data["language"])}</language>')

                            if "original_language" in custom_data:
                                program_xml.append(f'    <orig-language>{html.escape(custom_data["original_language"])}</orig-language>')

                            # Add length information
                            if "length" in custom_data and isinstance(custom_data["length"], dict):
                                length_value = custom_data["length"].get("value", "")
                                length_units = custom_data["length"].get("units", "minutes")
                                program_xml.append(f'    <length units="{html.escape(length_units)}">{html.escape(str(length_value))}</length>')

                            # Add video information
                            if "video" in custom_data and isinstance(custom_data["video"], dict):
                                program_xml.append("    <video>")
                                for attr in ['present', 'colour', 'aspect', 'quality']:
                                    if attr in custom_data["video"]:
                                        program_xml.append(f"      <{attr}>{html.escape(custom_data['video'][attr])}</{attr}>")
                                program_xml.append("    </video>")

                            # Add audio information
                            if "audio" in custom_data and isinstance(custom_data["audio"], dict):
                                program_xml.append("    <audio>")
                                for attr in ['present', 'stereo']:
                                    if attr in custom_data["audio"]:
                                        program_xml.append(f"      <{attr}>{html.escape(custom_data['audio'][attr])}</{attr}>")
                                program_xml.append("    </audio>")

                            # Add subtitles information
                            if "subtitles" in custom_data and isinstance(custom_data["subtitles"], list):
                                for subtitle in custom_data["subtitles"]:
                                    if isinstance(subtitle, dict):
                                        subtitle_type = subtitle.get("type", "")
                                        type_attr = f' type="{html.escape(subtitle_type)}"' if subtitle_type else ""
                                        program_xml.append(f"    <subtitles{type_attr}>")
                                        if "language" in subtitle:
                                            program_xml.append(f"      <language>{html.escape(subtitle['language'])}</language>")
                                        program_xml.append("    </subtitles>")

                            # Add rating if available
                            if "rating" in custom_data:
                                rating_system = custom_data.get("rating_system", "TV Parental Guidelines")
                                program_xml.append(f'    <rating system="{html.escape(rating_system)}">')
                                program_xml.append(f'      <value>{html.escape(custom_data["rating"])}</value>')
                                program_xml.append(f"    </rating>")

                            # Add star ratings
                            if "star_ratings" in custom_data and isinstance(custom_data["star_ratings"], list):
                                for star_rating in custom_data["star_ratings"]:
                                    if isinstance(star_rating, dict) and "value" in star_rating:
                                        system_attr = f' system="{html.escape(star_rating["system"])}"' if "system" in star_rating else ""
                                        program_xml.append(f"    <star-rating{system_attr}>")
                                        program_xml.append(f"      <value>{html.escape(star_rating['value'])}</value>")
                                        program_xml.append("    </star-rating>")

                            # Add reviews
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

                            # Add images
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

                                # Handle different credit types
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

                            # Add program date if available (full date, not just year)
                            if "date" in custom_data:
                                program_xml.append(f'    <date>{html.escape(custom_data["date"])}</date>')

                            # Add country if available
                            if "country" in custom_data:
                                program_xml.append(f'    <country>{html.escape(custom_data["country"])}</country>')

                            # Add icon if available
                            if "icon" in custom_data:
                                program_xml.append(f'    <icon src="{html.escape(custom_data["icon"])}" />')

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

                        # Add to batch
                        program_batch.extend(program_xml)

                        # Send batch when full or send keep-alive
                        if len(program_batch) >= batch_size:
                            yield '\n'.join(program_batch) + '\n'
                            program_batch = []

                    # Move to next chunk
                    offset += chunk_size

                # Send remaining programs in batch
                if program_batch:
                    yield '\n'.join(program_batch) + '\n'

        # Send final closing tag and completion message
        yield "</tv>\n"    # Return streaming response
    response = StreamingHttpResponse(
        streaming_content=epg_generator(),
        content_type="application/xml"
    )
    response["Content-Disposition"] = 'attachment; filename="Dispatcharr.xml"'
    response["Cache-Control"] = "no-cache"
    return response


def xc_get_user(request):
    username = request.GET.get("username")
    password = request.GET.get("password")

    if not username or not password:
        return None

    user = get_object_or_404(User, username=username)
    custom_properties = user.custom_properties or {}

    if "xc_password" not in custom_properties:
        return None

    if custom_properties["xc_password"] != password:
        return None

    return user


def xc_get_info(request, full=False):
    if not network_access_allowed(request, 'XC_API'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    raw_host = request.get_host()
    if ":" in raw_host:
        hostname, port = raw_host.split(":", 1)
    else:
        hostname = raw_host
        port = "443" if request.is_secure() else "80"

    info = {
        "user_info": {
            "username": request.GET.get("username"),
            "password": request.GET.get("password"),
            "message": "Dispatcharr XC API",
            "auth": 1,
            "status": "Active",
            "exp_date": str(int(time.time()) + (90 * 24 * 60 * 60)),
            "max_connections": str(calculate_tuner_count(minimum=1, unlimited_default=50)),
            "allowed_output_formats": [
                "ts",
            ],
        },
        "server_info": {
            "url": hostname,
            "server_protocol": request.scheme,
            "port": port,
            "timezone": get_localzone().key,
            "timestamp_now": int(time.time()),
            "time_now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "process": True,
        },
    }

    if full == True:
        info['categories'] = {
            "series": [],
            "movie": [],
            "live": xc_get_live_categories(user),
        }
        info['available_channels'] = {channel["stream_id"]: channel for channel in xc_get_live_streams(request, user, request.GET.get("category_id"))}

    return info


def xc_player_api(request, full=False):
    if not network_access_allowed(request, 'XC_API'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    action = request.GET.get("action")
    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    server_info = xc_get_info(request)

    if not action:
        return JsonResponse(server_info)

    if action == "get_live_categories":
        return JsonResponse(xc_get_live_categories(user), safe=False)
    if action == "get_live_streams":
        return JsonResponse(xc_get_live_streams(request, user, request.GET.get("category_id")), safe=False)
    if action == "get_short_epg":
        return JsonResponse(xc_get_epg(request, user, short=True), safe=False)
    if action == "get_simple_data_table":
        return JsonResponse(xc_get_epg(request, user, short=False), safe=False)

    # Endpoints not implemented, but still provide a response
    if action in [
        "get_vod_categories",
        "get_vod_streams",
        "get_series",
        "get_series_categories",
        "get_series_info",
        "get_vod_info",
    ]:
        if action == "get_vod_categories":
            return JsonResponse(xc_get_vod_categories(user), safe=False)
        elif action == "get_vod_streams":
            return JsonResponse(xc_get_vod_streams(request, user, request.GET.get("category_id")), safe=False)
        elif action == "get_series_categories":
            return JsonResponse(xc_get_series_categories(user), safe=False)
        elif action == "get_series":
            return JsonResponse(xc_get_series(request, user, request.GET.get("category_id")), safe=False)
        elif action == "get_series_info":
            return JsonResponse(xc_get_series_info(request, user, request.GET.get("series_id")), safe=False)
        elif action == "get_vod_info":
            return JsonResponse(xc_get_vod_info(request, user, request.GET.get("vod_id")), safe=False)
        else:
            return JsonResponse([], safe=False)

    raise Http404()


def xc_panel_api(request):
    if not network_access_allowed(request, 'XC_API'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return JsonResponse(xc_get_info(request, True))


def xc_get(request):
    if not network_access_allowed(request, 'XC_API'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    action = request.GET.get("action")
    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return generate_m3u(request, None, user)


def xc_xmltv(request):
    if not network_access_allowed(request, 'XC_API'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return generate_epg(request, None, user)


def xc_get_live_categories(user):
    response = []

    if user.user_level == 0:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channel groups
            channel_groups = ChannelGroup.objects.filter(
                channels__isnull=False, channels__user_level__lte=user.user_level
            ).distinct().order_by(Lower("name"))
        else:
            # User has specific limited profiles assigned
            filters = {
                "channels__channelprofilemembership__enabled": True,
                "channels__user_level": 0,
                "channels__channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            channel_groups = ChannelGroup.objects.filter(**filters).distinct().order_by(Lower("name"))
    else:
        channel_groups = ChannelGroup.objects.filter(
            channels__isnull=False, channels__user_level__lte=user.user_level
        ).distinct().order_by(Lower("name"))

    for group in channel_groups:
        response.append(
            {
                "category_id": str(group.id),
                "category_name": group.name,
                "parent_id": 0,
            }
        )

    return response


def xc_get_live_streams(request, user, category_id=None):
    streams = []

    if user.user_level == 0:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channels based on user_level
            filters = {"user_level__lte": user.user_level}
            if category_id is not None:
                filters["channel_group__id"] = category_id
            channels = Channel.objects.filter(**filters).order_by("channel_number")
        else:
            # User has specific limited profiles assigned
            filters = {
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
                "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            if category_id is not None:
                filters["channel_group__id"] = category_id
            channels = Channel.objects.filter(**filters).distinct().order_by("channel_number")
    else:
        if not category_id:
            channels = Channel.objects.filter(user_level__lte=user.user_level).order_by("channel_number")
        else:
            channels = Channel.objects.filter(
                channel_group__id=category_id, user_level__lte=user.user_level
            ).order_by("channel_number")

    for channel in channels:
        streams.append(
            {
                "num": int(channel.channel_number) if channel.channel_number.is_integer() else channel.channel_number,
                "name": channel.name,
                "stream_type": "live",
                "stream_id": channel.id,
                "stream_icon": (
                    None
                    if not channel.logo
                    else build_absolute_uri_with_port(
                        request,
                        reverse("api:channels:logo-cache", args=[channel.logo.id])
                    )
                ),
                "epg_channel_id": str(int(channel.channel_number)) if channel.channel_number.is_integer() else str(channel.channel_number),
                "added": int(channel.created_at.timestamp()),
                "is_adult": 0,
                "category_id": str(channel.channel_group.id),
                "category_ids": [channel.channel_group.id],
                "custom_sid": None,
                "tv_archive": 0,
                "direct_source": "",
                "tv_archive_duration": 0,
            }
        )

    return streams


def xc_get_epg(request, user, short=False):
    channel_id = request.GET.get('stream_id')
    if not channel_id:
        raise Http404()

    channel = None
    if user.user_level < 10:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channels based on user_level
            channel = Channel.objects.filter(
                id=channel_id,
                user_level__lte=user.user_level
            ).first()
        else:
            # User has specific limited profiles assigned
            filters = {
                "id": channel_id,
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
                "channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            channel = Channel.objects.filter(**filters).distinct().first()

        if not channel:
            raise Http404()
    else:
        channel = get_object_or_404(Channel, id=channel_id)

    if not channel:
        raise Http404()

    limit = request.GET.get('limit', 4)
    if channel.epg_data:
        if short == False:
            programs = channel.epg_data.programs.filter(
                start_time__gte=timezone.now()
            ).order_by('start_time')
        else:
            programs = channel.epg_data.programs.all().order_by('start_time')[:limit]
    else:
        programs = generate_dummy_programs(channel_id=channel_id, channel_name=channel.name)

    output = {"epg_listings": []}
    for program in programs:
        id = "0"
        epg_id = "0"
        title = program['title'] if isinstance(program, dict) else program.title
        description = program['description'] if isinstance(program, dict) else program.description

        start = program["start_time"] if isinstance(program, dict) else program.start_time
        end = program["end_time"] if isinstance(program, dict) else program.end_time

        program_output = {
            "id": f"{id}",
            "epg_id": f"{epg_id}",
            "title": base64.b64encode(title.encode()).decode(),
            "lang": "",
            "start": start.strftime("%Y%m%d%H%M%S"),
            "end": end.strftime("%Y%m%d%H%M%S"),
            "description": base64.b64encode(description.encode()).decode(),
            "channel_id": int(channel.channel_number) if channel.channel_number.is_integer() else channel.channel_number,
            "start_timestamp": int(start.timestamp()),
            "stop_timestamp": int(end.timestamp()),
            "stream_id": f"{channel_id}",
        }

        if short == False:
            program_output["now_playing"] = 1 if start <= timezone.now() <= end else 0
            program_output["has_archive"] = "0"

        output['epg_listings'].append(program_output)

    return output


def xc_get_vod_categories(user):
    """Get VOD categories for XtreamCodes API"""
    from apps.vod.models import VODCategory, M3UMovieRelation

    response = []

    # All authenticated users get access to VOD from all active M3U accounts
    categories = VODCategory.objects.filter(
        category_type='movie',
        m3umovierelation__m3u_account__is_active=True
    ).distinct().order_by(Lower("name"))

    for category in categories:
        response.append({
            "category_id": str(category.id),
            "category_name": category.name,
            "parent_id": 0,
        })

    return response


def xc_get_vod_streams(request, user, category_id=None):
    """Get VOD streams (movies) for XtreamCodes API"""
    from apps.vod.models import Movie, M3UMovieRelation
    from django.db.models import Prefetch

    streams = []

    # All authenticated users get access to VOD from all active M3U accounts
    filters = {"m3u_relations__m3u_account__is_active": True}

    if category_id:
        filters["m3u_relations__category_id"] = category_id

    # Optimize with prefetch_related to eliminate N+1 queries
    # This loads all relations in a single query instead of one per movie
    movies = Movie.objects.filter(**filters).select_related('logo').prefetch_related(
        Prefetch(
            'm3u_relations',
            queryset=M3UMovieRelation.objects.filter(
                m3u_account__is_active=True
            ).select_related('m3u_account', 'category').order_by('-m3u_account__priority', 'id'),
            to_attr='active_relations'
        )
    ).distinct()

    for movie in movies:
        # Get the first (highest priority) relation from prefetched data
        # This avoids the N+1 query problem entirely
        if hasattr(movie, 'active_relations') and movie.active_relations:
            relation = movie.active_relations[0]
        else:
            # Fallback - should rarely be needed with proper prefetching
            continue

        streams.append({
            "num": movie.id,
            "name": movie.name,
            "stream_type": "movie",
            "stream_id": movie.id,
            "stream_icon": (
                None if not movie.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:channels:logo-cache", args=[movie.logo.id])
                )
            ),
            #'stream_icon': movie.logo.url if movie.logo else '',
            "rating": movie.rating or "0",
            "rating_5based": round(float(movie.rating or 0) / 2, 2) if movie.rating else 0,
            "added": str(int(movie.created_at.timestamp())),
            "is_adult": 0,
            "tmdb_id": movie.tmdb_id or "",
            "imdb_id": movie.imdb_id or "",
            "trailer": (movie.custom_properties or {}).get('trailer') or "",
            "category_id": str(relation.category.id) if relation.category else "0",
            "category_ids": [int(relation.category.id)] if relation.category else [],
            "container_extension": relation.container_extension or "mp4",
            "custom_sid": None,
            "direct_source": "",
        })

    return streams


def xc_get_series_categories(user):
    """Get series categories for XtreamCodes API"""
    from apps.vod.models import VODCategory, M3USeriesRelation

    response = []

    # All authenticated users get access to series from all active M3U accounts
    categories = VODCategory.objects.filter(
        category_type='series',
        m3useriesrelation__m3u_account__is_active=True
    ).distinct().order_by(Lower("name"))

    for category in categories:
        response.append({
            "category_id": str(category.id),
            "category_name": category.name,
            "parent_id": 0,
        })

    return response


def xc_get_series(request, user, category_id=None):
    """Get series list for XtreamCodes API"""
    from apps.vod.models import M3USeriesRelation

    series_list = []

    # All authenticated users get access to series from all active M3U accounts
    filters = {"m3u_account__is_active": True}

    if category_id:
        filters["category_id"] = category_id

    # Get series relations instead of series directly
    series_relations = M3USeriesRelation.objects.filter(**filters).select_related(
        'series', 'series__logo', 'category', 'm3u_account'
    )

    for relation in series_relations:
        series = relation.series
        series_list.append({
            "num": relation.id,  # Use relation ID
            "name": series.name,
            "series_id": relation.id,  # Use relation ID
            "cover": (
                None if not series.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:channels:logo-cache", args=[series.logo.id])
                )
            ),
            "plot": series.description or "",
            "cast": series.custom_properties.get('cast', '') if series.custom_properties else "",
            "director": series.custom_properties.get('director', '') if series.custom_properties else "",
            "genre": series.genre or "",
            "release_date": series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else ""),
            "releaseDate": series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else ""),
            "last_modified": str(int(relation.updated_at.timestamp())),
            "rating": str(series.rating or "0"),
            "rating_5based": str(round(float(series.rating or 0) / 2, 2)) if series.rating else "0",
            "backdrop_path": series.custom_properties.get('backdrop_path', []) if series.custom_properties else [],
            "youtube_trailer": series.custom_properties.get('youtube_trailer', '') if series.custom_properties else "",
            "episode_run_time": series.custom_properties.get('episode_run_time', '') if series.custom_properties else "",
            "category_id": str(relation.category.id) if relation.category else "0",
            "category_ids": [int(relation.category.id)] if relation.category else [],
        })

    return series_list


def xc_get_series_info(request, user, series_id):
    """Get detailed series information including episodes"""
    from apps.vod.models import M3USeriesRelation, M3UEpisodeRelation

    if not series_id:
        raise Http404()

    # All authenticated users get access to series from all active M3U accounts
    filters = {"id": series_id, "m3u_account__is_active": True}

    try:
        series_relation = M3USeriesRelation.objects.select_related('series', 'series__logo').get(**filters)
        series = series_relation.series
    except M3USeriesRelation.DoesNotExist:
        raise Http404()

    # Check if we need to refresh detailed info (similar to vod api_views pattern)
    try:
        should_refresh = (
            not series_relation.last_episode_refresh or
            series_relation.last_episode_refresh < timezone.now() - timedelta(hours=24)
        )

        # Check if detailed data has been fetched
        custom_props = series_relation.custom_properties or {}
        episodes_fetched = custom_props.get('episodes_fetched', False)
        detailed_fetched = custom_props.get('detailed_fetched', False)

        # Force refresh if episodes/details have never been fetched or time interval exceeded
        if not episodes_fetched or not detailed_fetched or should_refresh:
            from apps.vod.tasks import refresh_series_episodes
            account = series_relation.m3u_account
            if account and account.is_active:
                refresh_series_episodes(account, series, series_relation.external_series_id)
                # Refresh objects from database after task completion
                series.refresh_from_db()
                series_relation.refresh_from_db()

    except Exception as e:
        logger.error(f"Error refreshing series data for relation {series_relation.id}: {str(e)}")

    # Get episodes for this series from the same M3U account
    episode_relations = M3UEpisodeRelation.objects.filter(
        episode__series=series,
        m3u_account=series_relation.m3u_account
    ).select_related('episode').order_by('episode__season_number', 'episode__episode_number')

    # Group episodes by season
    seasons = {}
    for relation in episode_relations:
        episode = relation.episode
        season_num = episode.season_number or 1
        if season_num not in seasons:
            seasons[season_num] = []

        # Try to get the highest priority related M3UEpisodeRelation for this episode (for video/audio/bitrate)
        from apps.vod.models import M3UEpisodeRelation
        first_relation = M3UEpisodeRelation.objects.filter(
            episode=episode
        ).select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()
        video = audio = bitrate = None
        if first_relation and first_relation.custom_properties:
            info = first_relation.custom_properties.get('info')
            if info and isinstance(info, dict):
                info_info = info.get('info')
                if info_info and isinstance(info_info, dict):
                    video = info_info.get('video', {})
                    audio = info_info.get('audio', {})
                    bitrate = info_info.get('bitrate', 0)
        if video is None:
            video = episode.custom_properties.get('video', {}) if episode.custom_properties else {}
        if audio is None:
            audio = episode.custom_properties.get('audio', {}) if episode.custom_properties else {}
        if bitrate is None:
            bitrate = episode.custom_properties.get('bitrate', 0) if episode.custom_properties else 0

        seasons[season_num].append({
            "id": episode.id,
            "season": season_num,
            "episode_num": episode.episode_number or 0,
            "title": episode.name,
            "container_extension": relation.container_extension or "mp4",
            "added": str(int(relation.created_at.timestamp())),
            "custom_sid": None,
            "direct_source": "",
            "info": {
                "id": int(episode.id),
                "name": episode.name,
                "overview": episode.description or "",
                "crew": str(episode.custom_properties.get('crew', "") if episode.custom_properties else ""),
                "directed_by": episode.custom_properties.get('director', '') if episode.custom_properties else "",
                "imdb_id": episode.imdb_id or "",
                "air_date": f"{episode.air_date}" if episode.air_date else "",
                "backdrop_path": episode.custom_properties.get('backdrop_path', []) if episode.custom_properties else [],
                "movie_image": episode.custom_properties.get('movie_image', '') if episode.custom_properties else "",
                "rating": float(episode.rating or 0),
                "release_date": f"{episode.air_date}" if episode.air_date else "",
                "duration_secs": (episode.duration_secs or 0),
                "duration": format_duration_hms(episode.duration_secs),
                "video": video,
                "audio": audio,
                "bitrate": bitrate,
            }
        })

    # Build response using potentially refreshed data
    series_data = {
        'name': series.name,
        'description': series.description or '',
        'year': series.year,
        'genre': series.genre or '',
        'rating': series.rating or '0',
        'cast': '',
        'director': '',
        'youtube_trailer': '',
        'episode_run_time': '',
        'backdrop_path': [],
    }

    # Add detailed info from custom_properties if available
    try:
        if series.custom_properties:
            custom_data = series.custom_properties
            series_data.update({
                'cast': custom_data.get('cast', ''),
                'director': custom_data.get('director', ''),
                'youtube_trailer': custom_data.get('youtube_trailer', ''),
                'episode_run_time': custom_data.get('episode_run_time', ''),
                'backdrop_path': custom_data.get('backdrop_path', []),
            })

        # Check relation custom_properties for detailed_info
        if series_relation.custom_properties and 'detailed_info' in series_relation.custom_properties:
            detailed_info = series_relation.custom_properties['detailed_info']

            # Override with detailed_info values where available
            for key in ['name', 'description', 'year', 'genre', 'rating']:
                if detailed_info.get(key):
                    series_data[key] = detailed_info[key]

            # Handle plot vs description
            if detailed_info.get('plot'):
                series_data['description'] = detailed_info['plot']
            elif detailed_info.get('description'):
                series_data['description'] = detailed_info['description']

            # Update additional fields from detailed info
            series_data.update({
                'cast': detailed_info.get('cast', series_data['cast']),
                'director': detailed_info.get('director', series_data['director']),
                'youtube_trailer': detailed_info.get('youtube_trailer', series_data['youtube_trailer']),
                'episode_run_time': detailed_info.get('episode_run_time', series_data['episode_run_time']),
                'backdrop_path': detailed_info.get('backdrop_path', series_data['backdrop_path']),
            })

    except Exception as e:
        logger.error(f"Error parsing series custom_properties: {str(e)}")

    seasons_list = [
        {"season_number": int(season_num), "name": f"Season {season_num}"}
        for season_num in sorted(seasons.keys(), key=lambda x: int(x))
    ]

    info = {
        'seasons': seasons_list,
        "info": {
            "name": series_data['name'],
            "cover": (
                None if not series.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:channels:logo-cache", args=[series.logo.id])
                )
            ),
            "plot": series_data['description'],
            "cast": series_data['cast'],
            "director": series_data['director'],
            "genre": series_data['genre'],
            "release_date": series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else ""),
            "releaseDate": series.custom_properties.get('release_date', str(series.year) if series.year else "") if series.custom_properties else (str(series.year) if series.year else ""),
            "added": str(int(series_relation.created_at.timestamp())),
            "last_modified": str(int(series_relation.updated_at.timestamp())),
            "rating": str(series_data['rating']),
            "rating_5based": str(round(float(series_data['rating'] or 0) / 2, 2)) if series_data['rating'] else "0",
            "backdrop_path": series_data['backdrop_path'],
            "youtube_trailer": series_data['youtube_trailer'],
            "imdb": str(series.imdb_id) if series.imdb_id else "",
            "tmdb": str(series.tmdb_id) if series.tmdb_id else "",
            "episode_run_time": str(series_data['episode_run_time']),
            "category_id": str(series_relation.category.id) if series_relation.category else "0",
            "category_ids": [int(series_relation.category.id)] if series_relation.category else [],
        },
        "episodes": dict(seasons)
    }
    return info


def xc_get_vod_info(request, user, vod_id):
    """Get detailed VOD (movie) information"""
    from apps.vod.models import M3UMovieRelation
    from django.utils import timezone
    from datetime import timedelta

    if not vod_id:
        raise Http404()

    # All authenticated users get access to VOD from all active M3U accounts
    filters = {"movie_id": vod_id, "m3u_account__is_active": True}

    try:
        # Order by account priority to get the best relation when multiple exist
        movie_relation = M3UMovieRelation.objects.select_related('movie', 'movie__logo').filter(**filters).order_by('-m3u_account__priority', 'id').first()
        if not movie_relation:
            raise Http404()
        movie = movie_relation.movie
    except (M3UMovieRelation.DoesNotExist, M3UMovieRelation.MultipleObjectsReturned):
        raise Http404()

    # Initialize basic movie data first
    movie_data = {
        'name': movie.name,
        'description': movie.description or '',
        'year': movie.year,
        'genre': movie.genre or '',
        'rating': movie.rating or 0,
        'tmdb_id': movie.tmdb_id or '',
        'imdb_id': movie.imdb_id or '',
        'director': '',
        'actors': '',
        'country': '',
        'release_date': '',
        'youtube_trailer': '',
        'backdrop_path': [],
        'cover_big': '',
        'bitrate': 0,
        'video': {},
        'audio': {},
    }

    # Duplicate the provider_info logic for detailed information
    try:
        # Check if we need to refresh detailed info (same logic as provider_info)
        should_refresh = (
            not movie_relation.last_advanced_refresh or
            movie_relation.last_advanced_refresh < timezone.now() - timedelta(hours=24)
        )

        if should_refresh:
            # Trigger refresh of detailed info
            from apps.vod.tasks import refresh_movie_advanced_data
            refresh_movie_advanced_data(movie_relation.id)
            # Refresh objects from database after task completion
            movie.refresh_from_db()
            movie_relation.refresh_from_db()

        # Add detailed info from custom_properties if available
        if movie.custom_properties:
            custom_data = movie.custom_properties or {}

            # Extract detailed info
            #detailed_info = custom_data.get('detailed_info', {})
            detailed_info = movie_relation.custom_properties.get('detailed_info', {})
            # Update movie_data with detailed info
            movie_data.update({
                'director': custom_data.get('director') or detailed_info.get('director', ''),
                'actors': custom_data.get('actors') or detailed_info.get('actors', ''),
                'country': custom_data.get('country') or detailed_info.get('country', ''),
                'release_date': custom_data.get('release_date') or detailed_info.get('release_date') or detailed_info.get('releasedate', ''),
                'youtube_trailer': custom_data.get('youtube_trailer') or detailed_info.get('youtube_trailer') or detailed_info.get('trailer', ''),
                'backdrop_path': custom_data.get('backdrop_path') or detailed_info.get('backdrop_path', []),
                'cover_big': detailed_info.get('cover_big', ''),
                'bitrate': detailed_info.get('bitrate', 0),
                'video': detailed_info.get('video', {}),
                'audio': detailed_info.get('audio', {}),
            })

            # Override with detailed_info values where available
            for key in ['name', 'description', 'year', 'genre', 'rating', 'tmdb_id', 'imdb_id']:
                if detailed_info.get(key):
                    movie_data[key] = detailed_info[key]

            # Handle plot vs description
            if detailed_info.get('plot'):
                movie_data['description'] = detailed_info['plot']
            elif detailed_info.get('description'):
                movie_data['description'] = detailed_info['description']

    except Exception as e:
        logger.error(f"Failed to process movie data: {e}")

    # Transform API response to XtreamCodes format
    info = {
        "info": {
            "name": movie_data.get('name', movie.name),
            "o_name": movie_data.get('name', movie.name),
            "cover_big": (
                None if not movie.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:channels:logo-cache", args=[movie.logo.id])
                )
            ),
            "movie_image": (
                None if not movie.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:channels:logo-cache", args=[movie.logo.id])
                )
            ),
            'description': movie_data.get('description', ''),
            'plot': movie_data.get('description', ''),
            'year': movie_data.get('year', ''),
            'release_date': movie_data.get('release_date', ''),
            'genre': movie_data.get('genre', ''),
            'director': movie_data.get('director', ''),
            'actors': movie_data.get('actors', ''),
            'cast': movie_data.get('actors', ''),
            'country': movie_data.get('country', ''),
            'rating': movie_data.get('rating', 0),
            'imdb_id': movie_data.get('imdb_id', ''),
            "tmdb_id": movie_data.get('tmdb_id', ''),
            'youtube_trailer': movie_data.get('youtube_trailer', ''),
            'backdrop_path': movie_data.get('backdrop_path', []),
            'cover': movie_data.get('cover_big', ''),
            'bitrate': movie_data.get('bitrate', 0),
            'video': movie_data.get('video', {}),
            'audio': movie_data.get('audio', {}),
        },
        "movie_data": {
            "stream_id": movie.id,
            "name": movie.name,
            "added": int(movie_relation.created_at.timestamp()),
            "category_id": str(movie_relation.category.id) if movie_relation.category else "0",
            "category_ids": [int(movie_relation.category.id)] if movie_relation.category else [],
            "container_extension": movie_relation.container_extension or "mp4",
            "custom_sid": None,
            "direct_source": "",
        }
    }

    return info


def xc_movie_stream(request, username, password, stream_id, extension):
    """Handle XtreamCodes movie streaming requests"""
    from apps.vod.models import M3UMovieRelation

    user = get_object_or_404(User, username=username)

    custom_properties = user.custom_properties or {}

    if "xc_password" not in custom_properties:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    if custom_properties["xc_password"] != password:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    # All authenticated users get access to VOD from all active M3U accounts
    filters = {"movie_id": stream_id, "m3u_account__is_active": True}

    try:
        # Order by account priority to get the best relation when multiple exist
        movie_relation = M3UMovieRelation.objects.select_related('movie').filter(**filters).order_by('-m3u_account__priority', 'id').first()
        if not movie_relation:
            return JsonResponse({"error": "Movie not found"}, status=404)
    except (M3UMovieRelation.DoesNotExist, M3UMovieRelation.MultipleObjectsReturned):
        return JsonResponse({"error": "Movie not found"}, status=404)

    # Redirect to the VOD proxy endpoint
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    vod_url = reverse('proxy:vod_proxy:vod_stream', kwargs={
        'content_type': 'movie',
        'content_id': movie_relation.movie.uuid
    })

    return HttpResponseRedirect(vod_url)


def xc_series_stream(request, username, password, stream_id, extension):
    """Handle XtreamCodes series/episode streaming requests"""
    from apps.vod.models import M3UEpisodeRelation

    user = get_object_or_404(User, username=username)

    custom_properties = user.custom_properties or {}

    if "xc_password" not in custom_properties:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    if custom_properties["xc_password"] != password:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    # All authenticated users get access to series/episodes from all active M3U accounts
    filters = {"episode_id": stream_id, "m3u_account__is_active": True}

    try:
        episode_relation = M3UEpisodeRelation.objects.select_related('episode').get(**filters)
    except M3UEpisodeRelation.DoesNotExist:
        return JsonResponse({"error": "Episode not found"}, status=404)

    # Redirect to the VOD proxy endpoint
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    vod_url = reverse('proxy:vod_proxy:vod_stream', kwargs={
        'content_type': 'episode',
        'content_id': episode_relation.episode.uuid
    })

    return HttpResponseRedirect(vod_url)


def get_host_and_port(request):
    """
    Returns (host, port) for building absolute URIs.
    - Prefers X-Forwarded-Host/X-Forwarded-Port (nginx).
    - Falls back to Host header.
    - In dev, if missing, uses 5656 or 8000 as a guess.
    """
    # 1. Try X-Forwarded-Host (may include port)
    xfh = request.META.get("HTTP_X_FORWARDED_HOST")
    if xfh:
        if ":" in xfh:
            host, port = xfh.split(":", 1)
        else:
            host = xfh
            port = request.META.get("HTTP_X_FORWARDED_PORT")
        if port:
            return host, port

    # 2. Try Host header
    raw_host = request.get_host()
    if ":" in raw_host:
        host, port = raw_host.split(":", 1)
        return host, port
    else:
        host = raw_host

    # 3. Try X-Forwarded-Port
    port = request.META.get("HTTP_X_FORWARDED_PORT")
    if port:
        return host, port

    # 4. Dev fallback: guess port
    if os.environ.get("DISPATCHARR_ENV") == "dev" or host in ("localhost", "127.0.0.1"):
       guess = "5656"
       return host, guess

    # 5. Fallback to scheme default
    port = "443" if request.is_secure() else "9191"
    return host, port

def build_absolute_uri_with_port(request, path):
    host, port = get_host_and_port(request)
    scheme = request.scheme
    return f"{scheme}://{host}:{port}{path}"

def format_duration_hms(seconds):
    """
    Format a duration in seconds as HH:MM:SS zero-padded string.
    """
    seconds = int(seconds or 0)
    return f"{seconds//3600:02}:{(seconds%3600)//60:02}:{seconds%60:02}"
