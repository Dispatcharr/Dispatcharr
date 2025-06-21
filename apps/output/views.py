import ipaddress
from django.http import HttpResponse, JsonResponse, Http404, HttpResponseForbidden
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
import re
import html  # Add this import for XML escaping
from tzlocal import get_localzone
import time
import json
from urllib.parse import urlparse
import base64
import os # For HLS views
from django.http import FileResponse # For HLS views

# HLS Specific Imports
from apps.proxy.hls_output.manager import HLSOutputManager
from apps.proxy.hls_output.constants import HLSChannelState
# from apps.proxy.hls_output.redis_keys import HLSRedisKeys # May not be directly needed
from apps.proxy.hls_output.config import get_hls_setting
from apps.channels.models import Channel # Already imported
from core.models import StreamProfile, UserAgent # UserAgent for default

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
    # Check if this is a POST request with data (which we don't want to allow)
    if request.method == "POST" and request.body:
        return HttpResponseForbidden("POST requests with content are not allowed")

    if user is not None:
        if user.user_level == 0:
            filters = {
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
            }

            if user.channel_profiles.count() != 0:
                channel_profiles = user.channel_profiles.all()
                filters["channelprofilemembership__channel_profile__in"] = (
                    channel_profiles
                )

            channels = Channel.objects.filter(**filters).order_by("channel_number")
        else:
            channels = Channel.objects.filter(user_level__lte=user.user_level).order_by(
                "channel_number"
            )


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
    output_format = request.GET.get('format', 'ts').lower() # New parameter for format

    # Get the source to use for tvg-id value
    # Options: 'channel_number' (default), 'tvg_id', 'gracenote'
    tvg_id_source = request.GET.get('tvg_id_source', 'channel_number').lower()

    m3u_content = "#EXTM3U\n"
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
                tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))
            else:
                # Try to find direct logo URL from channel's streams
                direct_logo = channel.logo.url if channel.logo.url.startswith(('http://', 'https://')) else None
                # If direct logo found, use it; otherwise fall back to cached version
                if direct_logo:
                    tvg_logo = direct_logo
                else:
                    tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))

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

        # Determine the stream URL based on the direct parameter and format
        if output_format == 'hls':
            # HLS format requested
            # Note: use_direct_urls is ignored for HLS as HLS is always served via Dispatcharr
            try:
                stream_url = request.build_absolute_uri(
                    reverse('output:hls_playlist', kwargs={'channel_uuid': channel.uuid, 'playlist_name': 'master.m3u8'})
                )
            except Exception as e:
                logger.error(f"Error reversing HLS URL for channel {channel.uuid}: {e}", exc_info=True)
                stream_url = "#ERROR_GENERATING_HLS_URL"
        elif use_direct_urls: # TS format, direct URL requested
            first_stream = channel.streams.filter(enabled=True, is_backup=False).order_by('priority').first()
            if not first_stream or not first_stream.url:
                 first_stream = channel.streams.filter(enabled=True, is_backup=True).order_by('priority').first()

            if first_stream and first_stream.url:
                stream_url = first_stream.url
            else:
                # Fall back to TS proxy URL if no direct URL available
                base_url = request.build_absolute_uri('/')[:-1] # Remove trailing slash
                # Assuming the TS proxy URL is still desired as a fallback for direct=true
                ts_proxy_path = reverse('output:stream', kwargs={'channel_uuid': channel.uuid})
                stream_url = f"{base_url}{ts_proxy_path}"
        else: # TS format, proxy URL requested (default behavior)
            base_url = request.build_absolute_uri('/')[:-1] # Remove trailing slash
            ts_proxy_path = reverse('output:stream', kwargs={'channel_uuid': channel.uuid})
            stream_url = f"{base_url}{ts_proxy_path}"
            # Old way: stream_url = f"{base_url}/proxy/ts/stream/{channel.uuid}" - ensure reverse matches this structure if kept

        m3u_content += extinf_line + stream_url + "\n"

    content_type = "application/vnd.apple.mpegurl" if output_format == 'hls' else "audio/x-mpegurl"
    response = HttpResponse(m3u_content, content_type=content_type)
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
            f'  <programme start="{start_str}" stop="{stop_str}" channel="{program['channel_id']}">'
        )
        xml_lines.append(f"    <title>{html.escape(program['title'])}</title>")
        xml_lines.append(f"    <desc>{html.escape(program['description'])}</desc>")
        xml_lines.append(f"  </programme>")

    return xml_lines


def generate_epg(request, profile_name=None, user=None):
    """
    Dynamically generate an XMLTV (EPG) file using the new EPGData/ProgramData models.
    Since the EPG data is stored independently of Channels, we group programmes
    by their associated EPGData record.
    This version filters data based on the 'days' parameter.
    """
    xml_lines = []
    xml_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml_lines.append(
        '<tv generator-info-name="Dispatcharr" generator-info-url="https://github.com/Dispatcharr/Dispatcharr">'
    )

    if user is not None:
        if user.user_level == 0:
            filters = {
                "channelprofilemembership__enabled": True,
                "user_level__lte": user.user_level,
            }

            if user.channel_profiles.count() != 0:
                channel_profiles = user.channel_profiles.all()
                filters["channelprofilemembership__channel_profile__in"] = (
                    channel_profiles
                )

            channels = Channel.objects.filter(**filters).order_by("channel_number")
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
            )
        else:
            channels = Channel.objects.all()

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

    # Retrieve all active channels
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
                tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))
            else:
                # Try to find direct logo URL from channel's streams
                direct_logo = channel.logo.url if channel.logo.url.startswith(('http://', 'https://')) else None
                # If direct logo found, use it; otherwise fall back to cached version
                if direct_logo:
                    tvg_logo = direct_logo
                else:
                    tvg_logo = request.build_absolute_uri(reverse('api:channels:logo-cache', args=[channel.logo.id]))
        display_name = channel.epg_data.name if channel.epg_data else channel.name
        xml_lines.append(f'  <channel id="{channel_id}">')
        xml_lines.append(f'    <display-name>{html.escape(display_name)}</display-name>')
        xml_lines.append(f'    <icon src="{html.escape(tvg_logo)}" />')

        xml_lines.append("  </channel>")

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
            generate_dummy_epg(
                channel_id,
                display_name,
                xml_lines,
                num_days=dummy_days,  # Use dummy_days (3 days by default)
                program_length_hours=program_length_hours
            )
        else:
            # For real EPG data - filter only if days parameter was specified
            if num_days > 0:
                programs = channel.epg_data.programs.filter(
                    start_time__gte=now,
                    start_time__lt=cutoff_date
                )
            else:
                # Return all programs if days=0 or not specified
                programs = channel.epg_data.programs.all()

            for prog in programs:
                start_str = prog.start_time.strftime("%Y%m%d%H%M%S %z")
                stop_str = prog.end_time.strftime("%Y%m%d%H%M%S %z")
                xml_lines.append(f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">')
                xml_lines.append(f'    <title>{html.escape(prog.title)}</title>')

                # Add subtitle if available
                if prog.sub_title:
                    xml_lines.append(
                        f"    <sub-title>{html.escape(prog.sub_title)}</sub-title>"
                    )

                # Add description if available
                if prog.description:
                    xml_lines.append(
                        f"    <desc>{html.escape(prog.description)}</desc>"
                    )

                # Process custom properties if available
                if prog.custom_properties:
                    try:
                        import json

                        custom_data = json.loads(prog.custom_properties)

                        # Add categories if available
                        if "categories" in custom_data and custom_data["categories"]:
                            for category in custom_data["categories"]:
                                xml_lines.append(
                                    f"    <category>{html.escape(category)}</category>"
                                )

                        # Handle episode numbering - multiple formats supported
                        # Standard episode number if available
                        if "episode" in custom_data:
                            xml_lines.append(
                                f'    <episode-num system="onscreen">E{custom_data["episode"]}</episode-num>'
                            )

                        # Handle onscreen episode format (like S06E128)
                        if "onscreen_episode" in custom_data:
                            xml_lines.append(
                                f'    <episode-num system="onscreen">{html.escape(custom_data["onscreen_episode"])}</episode-num>'
                            )

                        # Handle dd_progid format
                        if 'dd_progid' in custom_data:
                            xml_lines.append(f'    <episode-num system="dd_progid">{html.escape(custom_data["dd_progid"])}</episode-num>')

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
                            xml_lines.append(
                                f'    <episode-num system="xmltv_ns">{season}.{episode}.</episode-num>'
                            )

                        # Add rating if available
                        if "rating" in custom_data:
                            rating_system = custom_data.get(
                                "rating_system", "TV Parental Guidelines"
                            )
                            xml_lines.append(
                                f'    <rating system="{html.escape(rating_system)}">'
                            )
                            xml_lines.append(
                                f'      <value>{html.escape(custom_data["rating"])}</value>'
                            )
                            xml_lines.append(f"    </rating>")

                        # Add actors/directors/writers if available
                        if "credits" in custom_data:
                            xml_lines.append(f"    <credits>")
                            for role, people in custom_data["credits"].items():
                                if isinstance(people, list):
                                    for person in people:
                                        xml_lines.append(
                                            f"      <{role}>{html.escape(person)}</{role}>"
                                        )
                                else:
                                    xml_lines.append(
                                        f"      <{role}>{html.escape(people)}</{role}>"
                                    )
                            xml_lines.append(f"    </credits>")

                        # Add program date/year if available
                        if "year" in custom_data:
                            xml_lines.append(
                                f'    <date>{html.escape(custom_data["year"])}</date>'
                            )

                        # Add country if available
                        if "country" in custom_data:
                            xml_lines.append(
                                f'    <country>{html.escape(custom_data["country"])}</country>'
                            )

                        # Add icon if available
                        if "icon" in custom_data:
                            xml_lines.append(
                                f'    <icon src="{html.escape(custom_data["icon"])}" />'
                            )

                        # Add special flags as proper tags
                        if custom_data.get("previously_shown", False):
                            xml_lines.append(f"    <previously-shown />")

                        if custom_data.get("premiere", False):
                            xml_lines.append(f"    <premiere />")

                        if custom_data.get("new", False):
                            xml_lines.append(f"    <new />")

                        if custom_data.get('live', False):
                            xml_lines.append(f'    <live />')

                    except Exception as e:
                        xml_lines.append(
                            f"    <!-- Error parsing custom properties: {html.escape(str(e))} -->"
                        )

                xml_lines.append("  </programme>")

    xml_lines.append("</tv>")
    xml_content = "\n".join(xml_lines)

    response = HttpResponse(xml_content, content_type="application/xml")
    response["Content-Disposition"] = 'attachment; filename="epg.xml"'
    return response


def xc_get_user(request):
    username = request.GET.get("username")
    password = request.GET.get("password")

    if not username or not password:
        return None

    user = get_object_or_404(User, username=username)
    custom_properties = (
        json.loads(user.custom_properties) if user.custom_properties else {}
    )

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
            "message": "",
            "auth": 1,
            "status": "Active",
            "exp_date": "1715062090",
            "max_connections": "99",
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
        filters = {
            "channels__channelprofilemembership__enabled": True,
            "channels__user_level": 0,
        }

        if user.channel_profiles.count() != 0:
            # Only get data from active profile
            channel_profiles = user.channel_profiles.all()
            filters["channels__channelprofilemembership__channel_profile__in"] = (
                channel_profiles
            )

        channel_groups = ChannelGroup.objects.filter(**filters).distinct()
    else:
        channel_groups = ChannelGroup.objects.filter(
            channels__isnull=False, channels__user_level__lte=user.user_level
        ).distinct()

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
        filters = {
            "channelprofilemembership__enabled": True,
            "user_level__lte": user.user_level,
        }

        if user.channel_profiles.count() > 0:
            # Only get data from active profile
            channel_profiles = user.channel_profiles.all()
            filters["channelprofilemembership__channel_profile__in"] = channel_profiles

        if category_id is not None:
            filters["channel_group__id"] = category_id

        channels = Channel.objects.filter(**filters).order_by("channel_number")
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
                    else request.build_absolute_uri(
                        reverse("api:channels:logo-cache", args=[channel.logo.id])
                    )
                ),
                "epg_channel_id": str(int(channel.channel_number)) if channel.channel_number.is_integer() else str(channel.channel_number),
                "added": int(time.time()),  # @TODO: make this the actual created date
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
        filters = {
            "id": channel_id,
            "channelprofilemembership__enabled": True,
            "user_level__lte": user.user_level,
        }

        if user.channel_profiles.count() > 0:
            channel_profiles = user.channel_profiles.all()
            filters["channelprofilemembership__channel_profile__in"] = channel_profiles

        channel = get_object_or_404(Channel, **filters)
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


# --- HLS Views ---

@csrf_exempt
@require_http_methods(["GET"])
def hls_manifest_view(request, channel_uuid, playlist_name="master.m3u8"): # Default changed to master.m3u8
    if not network_access_allowed(request, NETWORK_ACCESS.PROXY_STREAMING): # Assuming same access level as other streams
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        channel = get_object_or_404(Channel, uuid=channel_uuid)
    except Http404:
        return JsonResponse({"error": "Channel not found"}, status=404)

    manager = HLSOutputManager.get_instance()
    hls_base_path = get_hls_setting('hls_segment_path')

    # Security: Normalize and validate playlist_name path
    channel_hls_root = os.path.abspath(os.path.join(hls_base_path, str(channel_uuid)))
    requested_manifest_full_path = os.path.abspath(os.path.join(channel_hls_root, playlist_name))

    if not requested_manifest_full_path.startswith(channel_hls_root):
        logger.warning(f"Path traversal attempt for HLS manifest: channel_uuid={channel_uuid}, playlist_name='{playlist_name}'")
        return JsonResponse({"error": "Invalid playlist path"}, status=400)

    # Check if the playlist_name itself contains suspicious parts after join, though abspath should handle most.
    # This is an additional check on the playlist_name component itself.
    if ".." in playlist_name.replace("\\", "/").split("/") or playlist_name.startswith("/"):
         logger.warning(f"Invalid characters in playlist_name component: '{playlist_name}'")
         return JsonResponse({"error": "Invalid playlist name format"}, status=400)

    manifest_file_path = requested_manifest_full_path # Use the validated, absolute path

    # Check HLS status and auto-start
    current_state = None
    metadata = None
    redis_client = RedisClient().get_client() # Direct Redis client for metadata check
    metadata_key = f"hls:channel:{str(channel_uuid)}:metadata" # Using f-string as HLSRedisKeys not imported directly

    try:
        metadata_str = redis_client.get(metadata_key)
        if metadata_str:
            metadata = json.loads(metadata_str)
            current_state = metadata.get("state")
    except Exception as e:
        # Log this error, but proceed as if no metadata found
        # logger.error(f"Error fetching/parsing HLS metadata for {channel_uuid}: {e}")
        pass # Fall through to auto-start logic

    # Auto-start if not active/generating or no metadata
    # (Simplified: doesn't check for ERROR state specifically to retry, manager should handle that)
    if current_state not in [HLSChannelState.ACTIVE, HLSChannelState.GENERATING_HLS] or not metadata:
        first_stream = channel.streams.filter(enabled=True, is_backup=False).order_by('priority').first()
        if not first_stream or not first_stream.url:
             # Check for backup streams if no primary active stream
            first_stream = channel.streams.filter(enabled=True, is_backup=True).order_by('priority').first()
            if not first_stream or not first_stream.url:
                return JsonResponse({"error": "Channel has no active source streams"}, status=500)

        source_stream_url = first_stream.url

        try:
            # Assuming "HLS Proxy" is the designated profile name for HLS tasks
            hls_proxy_profile = StreamProfile.objects.get(name="HLS Proxy", command="ffmpeg")
        except StreamProfile.DoesNotExist:
            return JsonResponse({"error": "HLS Proxy stream profile not found"}, status=500)

        # Get a default User-Agent string
        default_ua_string = "Dispatcharr/1.0 HLS" # Fallback
        try:
            default_user_agent_obj = UserAgent.objects.filter(is_default=True).first()
            if default_user_agent_obj:
                default_ua_string = default_user_agent_obj.user_agent_string
            else: # Fallback to system setting if no default UserAgent object
                default_ua_string = CoreSettings.get_setting("default_user_agent", default_ua_string)
        except Exception:
            # logger.warning("Could not fetch default UserAgent from DB/CoreSettings for HLS init.")
            pass


        if not manager.initialize_channel_hls(str(channel_uuid), source_stream_url, hls_proxy_profile.id, default_ua_string):
            # If init fails, manager logs errors. We return a generic failure.
            # It's possible another worker picked it up, so check manifest existence anyway.
            # For now, we'll just proceed to check manifest. A better flow might involve manager.get_channel_state()
            pass # Proceed to check manifest existence

        # Brief pause to allow FFmpeg to start and potentially create the manifest
        # In a production system, a more robust polling or notification mechanism would be better.
        time.sleep(2) # Adjust as needed, or remove if client-side retry is preferred

    # Serve Manifest
    if os.path.exists(manifest_file_path):
        try:
            return FileResponse(open(manifest_file_path, 'rb'), content_type='application/vnd.apple.mpegurl')
        except Exception as e:
            # logger.error(f"Error serving HLS manifest {manifest_file_path}: {e}")
            return JsonResponse({"error": "Error serving manifest"}, status=500)
    else:
        # Could be starting, or failed.
        # Check state again after init attempt
        try:
            metadata_str_after_init = redis_client.get(metadata_key)
            if metadata_str_after_init:
                current_state_after_init = json.loads(metadata_str_after_init).get("state")
                if current_state_after_init == HLSChannelState.GENERATING_HLS:
                    return JsonResponse({"status": "starting_hls", "message": "HLS generation in progress, manifest not yet available. Please retry shortly."}, status=202) # Accepted
                elif current_state_after_init == HLSChannelState.ERROR:
                     return JsonResponse({"error": "HLS generation failed for this channel."}, status=500)
        except: # Ignore errors reading state after init, just fall through to 404
            pass
        return JsonResponse({"error": "HLS manifest not found or not yet ready."}, status=404)


@csrf_exempt
@require_http_methods(["GET"])
def hls_segment_view(request, channel_uuid, segment_path_in_channel_dir): # Parameter name changed
    if not network_access_allowed(request, NETWORK_ACCESS.PROXY_STREAMING): # Assuming same access level
        return JsonResponse({"error": "Forbidden"}, status=403)

    hls_base_path = get_hls_setting('hls_segment_path')

    # Security: Normalize and validate segment_path_in_channel_dir
    channel_hls_root = os.path.abspath(os.path.join(hls_base_path, str(channel_uuid)))
    requested_segment_full_path = os.path.abspath(os.path.join(channel_hls_root, segment_path_in_channel_dir))

    if not requested_segment_full_path.startswith(channel_hls_root):
        logger.warning(f"Path traversal attempt for HLS segment: channel_uuid={channel_uuid}, segment_path='{segment_path_in_channel_dir}'")
        return JsonResponse({"error": "Invalid segment path"}, status=400)

    # Additional check on the segment_path_in_channel_dir component itself
    # Ensure it doesn't contain '..' and is a .ts file (or other expected segment extension)
    path_parts = segment_path_in_channel_dir.replace("\\", "/").split("/")
    segment_filename = path_parts[-1]
    if ".." in path_parts or not segment_filename.endswith(('.ts', '.aac', '.mp4', '.vtt')): # Common segment/subtitle extensions
        logger.warning(f"Invalid characters or extension in segment path component: '{segment_path_in_channel_dir}'")
        return JsonResponse({"error": "Invalid segment name format or extension"}, status=400)

    # Check if rendition part is "safe" - simple alphanumeric check for directory names
    if len(path_parts) > 1: # Means there's a rendition directory part
        rendition_name_part = path_parts[0]
        if not rendition_name_part.isalnum() and '_' not in rendition_name_part and '-' not in rendition_name_part : # Allow alphanumeric, underscore, hyphen
             logger.warning(f"Invalid rendition name format in segment path: '{rendition_name_part}'")
             return JsonResponse({"error": "Invalid rendition name in path"}, status=400)


    segment_file_path = requested_segment_full_path # Use the validated, absolute path

    if os.path.exists(segment_file_path):
        try:
            return FileResponse(open(segment_file_path, 'rb'), content_type='video/MP2T') # MP2T is common for .ts
        except Exception as e:
            logger.error(f"Error serving HLS segment {segment_file_path}: {e}", exc_info=True)
            return JsonResponse({"error": "Error serving segment"}, status=500)
    else:
        # Could log that segment was not found if needed for debugging active streams
        # logger.info(f"HLS segment not found: {segment_file_path}")
        return JsonResponse({"error": "HLS segment not found"}, status=404)
