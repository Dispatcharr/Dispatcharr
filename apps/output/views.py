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
from django.utils import timezone as django_timezone
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
import regex
from core.utils import log_system_event
import hashlib

logger = logging.getLogger(__name__)

def get_client_identifier(request):
    """Get client information including IP, user agent, and a unique hash identifier

    Returns:
        tuple: (client_id_hash, client_ip, user_agent)
    """
    # Get client IP (handle proxies)
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        client_ip = x_forwarded_for.split(',')[0].strip()
    else:
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')

    # Get user agent
    user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')

    # Create a hash for a shorter cache key
    client_str = f"{client_ip}:{user_agent}"
    client_id_hash = hashlib.md5(client_str.encode()).hexdigest()[:12]

    return client_id_hash, client_ip, user_agent

def m3u_endpoint(request, profile_name=None, user=None):
    logger.debug("m3u_endpoint called: method=%s, profile=%s", request.method, profile_name)
    if not network_access_allowed(request, "M3U_EPG"):
        # Log blocked M3U download
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='m3u_blocked',
            profile=profile_name or 'all',
            reason='Network access denied',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({"error": "Forbidden"}, status=403)

    # Handle HEAD requests efficiently without generating content
    if request.method == "HEAD":
        logger.debug("Handling HEAD request for M3U")
        response = HttpResponse(content_type="audio/x-mpegurl")
        response["Content-Disposition"] = 'attachment; filename="channels.m3u"'
        return response

    return generate_m3u(request, profile_name, user)

def epg_endpoint(request, profile_name=None, user=None):
    logger.debug("epg_endpoint called: method=%s, profile=%s", request.method, profile_name)
    if not network_access_allowed(request, "M3U_EPG"):
        # Log blocked EPG download
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='epg_blocked',
            profile=profile_name or 'all',
            reason='Network access denied',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({"error": "Forbidden"}, status=403)

    # Handle HEAD requests efficiently without generating content
    if request.method == "HEAD":
        logger.debug("Handling HEAD request for EPG")
        response = HttpResponse(content_type="application/xml")
        response["Content-Disposition"] = 'attachment; filename="Dispatcharr.xml"'
        response["Cache-Control"] = "no-cache"
        return response

    return generate_epg(request, profile_name, user)

@csrf_exempt
@require_http_methods(["GET", "POST", "HEAD"])
def generate_m3u(request, profile_name=None, user=None):
    """
    Dynamically generate an M3U file from channels.
    The stream URL now points to the new stream_view that uses StreamProfile.
    Supports both GET and POST methods for compatibility with IPTVSmarters.
    """
    # Check if this is a POST request and the body is not empty (which we don't want to allow)
    logger.debug("Generating M3U for profile: %s, user: %s, method: %s", profile_name, user.username if user else "Anonymous", request.method)

    # Check cache for recent identical request (helps with double-GET from browsers)
    from django.core.cache import cache
    cache_params = f"{profile_name or 'all'}:{user.username if user else 'anonymous'}:{request.GET.urlencode()}"
    content_cache_key = f"m3u_content:{cache_params}"

    cached_content = cache.get(content_cache_key)
    if cached_content:
        logger.debug("Serving M3U from cache")
        response = HttpResponse(cached_content, content_type="audio/x-mpegurl")
        response["Content-Disposition"] = 'attachment; filename="channels.m3u"'
        return response
    # Check if this is a POST request with data (which we don't want to allow)
    if request.method == "POST" and request.body:
        if request.body.decode() != '{}':
            return HttpResponseForbidden("POST requests with body are not allowed, body is: {}".format(request.body.decode()))

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
            try:
                channel_profile = ChannelProfile.objects.get(name=profile_name)
            except ChannelProfile.DoesNotExist:
                logger.warning("Requested channel profile (%s) during m3u generation does not exist", profile_name)
                raise Http404(f"Channel profile '{profile_name}' not found")
            channels = Channel.objects.filter(
                channelprofilemembership__channel_profile=channel_profile,
                channelprofilemembership__enabled=True
            ).order_by('channel_number')
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

    # Cache the generated content for 2 seconds to handle double-GET requests
    cache.set(content_cache_key, m3u_content, 2)

    # Log system event for M3U download (with deduplication based on client)
    client_id, client_ip, user_agent = get_client_identifier(request)
    event_cache_key = f"m3u_download:{user.username if user else 'anonymous'}:{profile_name or 'all'}:{client_id}"
    if not cache.get(event_cache_key):
        log_system_event(
            event_type='m3u_download',
            profile=profile_name or 'all',
            user=user.username if user else 'anonymous',
            channels=channels.count(),
            client_ip=client_ip,
            user_agent=user_agent,
        )
        cache.set(event_cache_key, True, 2)  # Prevent duplicate events for 2 seconds

    response = HttpResponse(m3u_content, content_type="audio/x-mpegurl")
    response["Content-Disposition"] = 'attachment; filename="channels.m3u"'
    return response


def generate_fallback_programs(channel_id, channel_name, now, num_days, program_length_hours, fallback_title, fallback_description):
    """
    Generate dummy programs using custom fallback templates when patterns don't match.

    Args:
        channel_id: Channel ID for the programs
        channel_name: Channel name to use as fallback in templates
        now: Current datetime (in UTC)
        num_days: Number of days to generate programs for
        program_length_hours: Length of each program in hours
        fallback_title: Custom fallback title template (empty string if not provided)
        fallback_description: Custom fallback description template (empty string if not provided)

    Returns:
        List of program dictionaries
    """
    programs = []

    # Use custom fallback title or channel name as default
    title = fallback_title if fallback_title else channel_name

    # Use custom fallback description or a simple default message
    if fallback_description:
        description = fallback_description
    else:
        description = f"EPG information is currently unavailable for {channel_name}"

    # Create programs for each day
    for day in range(num_days):
        day_start = now + timedelta(days=day)

        # Create programs with specified length throughout the day
        for hour_offset in range(0, 24, program_length_hours):
            # Calculate program start and end times
            start_time = day_start + timedelta(hours=hour_offset)
            end_time = start_time + timedelta(hours=program_length_hours)

            programs.append({
                "channel_id": channel_id,
                "start_time": start_time,
                "end_time": end_time,
                "title": title,
                "description": description,
            })

    return programs


def generate_dummy_programs(channel_id, channel_name, num_days=1, program_length_hours=4, epg_source=None):
    """
    Generate dummy EPG programs for channels.

    If epg_source is provided and it's a custom dummy EPG with patterns,
    use those patterns to generate programs from the channel title.
    Otherwise, generate default dummy programs.

    Args:
        channel_id: Channel ID for the programs
        channel_name: Channel title/name
        num_days: Number of days to generate programs for
        program_length_hours: Length of each program in hours
        epg_source: Optional EPGSource for custom dummy EPG with patterns

    Returns:
        List of program dictionaries
    """
    # Get current time rounded to hour
    now = django_timezone.now()
    now = now.replace(minute=0, second=0, microsecond=0)

    # Check if this is a custom dummy EPG with regex patterns
    if epg_source and epg_source.source_type == 'dummy' and epg_source.custom_properties:
        custom_programs = generate_custom_dummy_programs(
            channel_id, channel_name, now, num_days,
            epg_source.custom_properties
        )
        # If custom generation succeeded, return those programs
        # If it returned empty (pattern didn't match), check for custom fallback templates
        if custom_programs:
            return custom_programs
        else:
            logger.info(f"Custom pattern didn't match for '{channel_name}', checking for custom fallback templates")

            # Check if custom fallback templates are provided
            custom_props = epg_source.custom_properties
            fallback_title = custom_props.get('fallback_title_template', '').strip()
            fallback_description = custom_props.get('fallback_description_template', '').strip()

            # If custom fallback templates exist, use them instead of default
            if fallback_title or fallback_description:
                logger.info(f"Using custom fallback templates for '{channel_name}'")
                return generate_fallback_programs(
                    channel_id, channel_name, now, num_days,
                    program_length_hours, fallback_title, fallback_description
                )
            else:
                logger.info(f"No custom fallback templates found, using default dummy EPG")

    # Default humorous program descriptions based on time of day
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


def generate_custom_dummy_programs(channel_id, channel_name, now, num_days, custom_properties):
    """
    Generate programs using custom dummy EPG regex patterns.

    Extracts information from channel title using regex patterns and generates
    programs based on the extracted data.

    TIMEZONE HANDLING:
    ------------------
    The timezone parameter specifies the timezone of the event times in your channel
    titles using standard timezone names (e.g., 'US/Eastern', 'US/Pacific', 'Europe/London').
    DST (Daylight Saving Time) is handled automatically by pytz.

    Examples:
    - Channel: "NHL 01: Bruins VS Maple Leafs @ 8:00PM ET"
    - Set timezone = "US/Eastern"
    - In October (DST): 8:00PM EDT → 12:00AM UTC (automatically uses UTC-4)
    - In January (no DST): 8:00PM EST → 1:00AM UTC (automatically uses UTC-5)

    Args:
        channel_id: Channel ID for the programs
        channel_name: Channel title to parse
        now: Current datetime (in UTC)
        num_days: Number of days to generate programs for
        custom_properties: Dict with title_pattern, time_pattern, templates, etc.
            - timezone: Timezone name (e.g., 'US/Eastern')

    Returns:
        List of program dictionaries with start_time/end_time in UTC
    """
    import pytz

    logger.info(f"Generating custom dummy programs for channel: {channel_name}")

    # Extract patterns from custom properties
    title_pattern = custom_properties.get('title_pattern', '')
    time_pattern = custom_properties.get('time_pattern', '')
    date_pattern = custom_properties.get('date_pattern', '')

    # Get timezone name (e.g., 'US/Eastern', 'US/Pacific', 'Europe/London')
    timezone_value = custom_properties.get('timezone', 'UTC')
    output_timezone_value = custom_properties.get('output_timezone', '')  # Optional: display times in different timezone
    program_duration = custom_properties.get('program_duration', 180)  # Minutes
    title_template = custom_properties.get('title_template', '')
    description_template = custom_properties.get('description_template', '')

    # Templates for upcoming/ended programs
    upcoming_title_template = custom_properties.get('upcoming_title_template', '')
    upcoming_description_template = custom_properties.get('upcoming_description_template', '')
    ended_title_template = custom_properties.get('ended_title_template', '')
    ended_description_template = custom_properties.get('ended_description_template', '')

    # Image URL templates
    channel_logo_url_template = custom_properties.get('channel_logo_url', '')
    program_poster_url_template = custom_properties.get('program_poster_url', '')

    # EPG metadata options
    category_string = custom_properties.get('category', '')
    # Split comma-separated categories and strip whitespace, filter out empty strings
    categories = [cat.strip() for cat in category_string.split(',') if cat.strip()] if category_string else []
    include_date = custom_properties.get('include_date', True)
    include_live = custom_properties.get('include_live', False)
    include_new = custom_properties.get('include_new', False)

    # Parse timezone name
    try:
        source_tz = pytz.timezone(timezone_value)
        logger.debug(f"Using timezone: {timezone_value} (DST will be handled automatically)")
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone: {timezone_value}, defaulting to UTC")
        source_tz = pytz.utc

    # Parse output timezone if provided (for display purposes)
    output_tz = None
    if output_timezone_value:
        try:
            output_tz = pytz.timezone(output_timezone_value)
            logger.debug(f"Using output timezone for display: {output_timezone_value}")
        except pytz.exceptions.UnknownTimeZoneError:
            logger.warning(f"Unknown output timezone: {output_timezone_value}, will use source timezone")
            output_tz = None

    if not title_pattern:
        logger.warning(f"No title_pattern in custom_properties, falling back to default")
        return []  # Return empty, will use default

    logger.debug(f"Title pattern from DB: {repr(title_pattern)}")

    # Convert PCRE/JavaScript named groups (?<name>) to Python format (?P<name>)
    # This handles patterns created with JavaScript regex syntax
    # Use negative lookahead to avoid matching lookbehind (?<=) and negative lookbehind (?<!)
    title_pattern = regex.sub(r'\(\?<(?![=!])([^>]+)>', r'(?P<\1>', title_pattern)
    logger.debug(f"Converted title pattern: {repr(title_pattern)}")

    # Compile regex patterns using the enhanced regex module
    # (supports variable-width lookbehinds like JavaScript)
    try:
        title_regex = regex.compile(title_pattern)
    except Exception as e:
        logger.error(f"Invalid title regex pattern after conversion: {e}")
        logger.error(f"Pattern was: {repr(title_pattern)}")
        return []

    time_regex = None
    if time_pattern:
        # Convert PCRE/JavaScript named groups to Python format
        # Use negative lookahead to avoid matching lookbehind (?<=) and negative lookbehind (?<!)
        time_pattern = regex.sub(r'\(\?<(?![=!])([^>]+)>', r'(?P<\1>', time_pattern)
        logger.debug(f"Converted time pattern: {repr(time_pattern)}")
        try:
            time_regex = regex.compile(time_pattern)
        except Exception as e:
            logger.warning(f"Invalid time regex pattern after conversion: {e}")
            logger.warning(f"Pattern was: {repr(time_pattern)}")

    # Compile date regex if provided
    date_regex = None
    if date_pattern:
        # Convert PCRE/JavaScript named groups to Python format
        # Use negative lookahead to avoid matching lookbehind (?<=) and negative lookbehind (?<!)
        date_pattern = regex.sub(r'\(\?<(?![=!])([^>]+)>', r'(?P<\1>', date_pattern)
        logger.debug(f"Converted date pattern: {repr(date_pattern)}")
        try:
            date_regex = regex.compile(date_pattern)
        except Exception as e:
            logger.warning(f"Invalid date regex pattern after conversion: {e}")
            logger.warning(f"Pattern was: {repr(date_pattern)}")

    # Try to match the channel name with the title pattern
    # Use search() instead of match() to match JavaScript behavior where .match() searches anywhere in the string
    title_match = title_regex.search(channel_name)
    if not title_match:
        logger.debug(f"Channel name '{channel_name}' doesn't match title pattern")
        return []  # Return empty, will use default

    groups = title_match.groupdict()
    logger.debug(f"Title pattern matched. Groups: {groups}")

    # Helper function to format template with matched groups
    def format_template(template, groups, url_encode=False):
        """Replace {groupname} placeholders with matched group values

        Args:
            template: Template string with {groupname} placeholders
            groups: Dict of group names to values
            url_encode: If True, URL encode the group values for safe use in URLs
        """
        if not template:
            return ''
        result = template
        for key, value in groups.items():
            if url_encode and value:
                # URL encode the value to handle spaces and special characters
                from urllib.parse import quote
                encoded_value = quote(str(value), safe='')
                result = result.replace(f'{{{key}}}', encoded_value)
            else:
                result = result.replace(f'{{{key}}}', str(value) if value else '')
        return result

    # Extract time from title if time pattern exists
    time_info = None
    time_groups = {}
    if time_regex:
        time_match = time_regex.search(channel_name)
        if time_match:
            time_groups = time_match.groupdict()
            try:
                hour = int(time_groups.get('hour'))
                # Handle optional minute group - could be None if not captured
                minute_value = time_groups.get('minute')
                minute = int(minute_value) if minute_value is not None else 0
                ampm = time_groups.get('ampm')
                ampm = ampm.lower() if ampm else None

                # Determine if this is 12-hour or 24-hour format
                if ampm in ('am', 'pm'):
                    # 12-hour format: convert to 24-hour
                    if ampm == 'pm' and hour != 12:
                        hour += 12
                    elif ampm == 'am' and hour == 12:
                        hour = 0
                    logger.debug(f"Extracted time (12-hour): {hour}:{minute:02d} {ampm}")
                else:
                    # 24-hour format: hour is already in 24-hour format
                    # Validate that it's actually a 24-hour time (0-23)
                    if hour > 23:
                        logger.warning(f"Invalid 24-hour time: {hour}. Must be 0-23.")
                        hour = hour % 24  # Wrap around just in case
                    logger.debug(f"Extracted time (24-hour): {hour}:{minute:02d}")

                time_info = {'hour': hour, 'minute': minute}
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing time: {e}")

    # Extract date from title if date pattern exists
    date_info = None
    date_groups = {}
    if date_regex:
        date_match = date_regex.search(channel_name)
        if date_match:
            date_groups = date_match.groupdict()
            try:
                # Support various date group names: month, day, year
                month_str = date_groups.get('month', '')
                day_str = date_groups.get('day', '')
                year_str = date_groups.get('year', '')

                # Parse day - default to current day if empty or invalid
                day = int(day_str) if day_str else now.day

                # Parse year - default to current year if empty or invalid (matches frontend behavior)
                year = int(year_str) if year_str else now.year

                # Parse month - can be numeric (1-12) or text (Jan, January, etc.)
                month = None
                if month_str:
                    if month_str.isdigit():
                        month = int(month_str)
                    else:
                        # Try to parse text month names
                        import calendar
                        month_str_lower = month_str.lower()
                        # Check full month names
                        for i, month_name in enumerate(calendar.month_name):
                            if month_name.lower() == month_str_lower:
                                month = i
                                break
                        # Check abbreviated month names if not found
                        if month is None:
                            for i, month_abbr in enumerate(calendar.month_abbr):
                                if month_abbr.lower() == month_str_lower:
                                    month = i
                                    break

                # Default to current month if not extracted or invalid
                if month is None:
                    month = now.month

                if month and 1 <= month <= 12 and 1 <= day <= 31:
                    date_info = {'year': year, 'month': month, 'day': day}
                    logger.debug(f"Extracted date: {year}-{month:02d}-{day:02d}")
                else:
                    logger.warning(f"Invalid date values: month={month}, day={day}, year={year}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing date: {e}")

    # Merge title groups, time groups, and date groups for template formatting
    all_groups = {**groups, **time_groups, **date_groups}

    # Add normalized versions of all groups for cleaner URLs
    # These remove all non-alphanumeric characters and convert to lowercase
    for key, value in list(all_groups.items()):
        if value:
            # Remove all non-alphanumeric characters (except spaces temporarily)
            # then replace spaces with nothing, and convert to lowercase
            normalized = regex.sub(r'[^a-zA-Z0-9\s]', '', str(value))
            normalized = regex.sub(r'\s+', '', normalized).lower()
            all_groups[f'{key}_normalize'] = normalized

    # Format channel logo URL if template provided (with URL encoding)
    channel_logo_url = None
    if channel_logo_url_template:
        channel_logo_url = format_template(channel_logo_url_template, all_groups, url_encode=True)
        logger.debug(f"Formatted channel logo URL: {channel_logo_url}")

    # Format program poster URL if template provided (with URL encoding)
    program_poster_url = None
    if program_poster_url_template:
        program_poster_url = format_template(program_poster_url_template, all_groups, url_encode=True)
        logger.debug(f"Formatted program poster URL: {program_poster_url}")

    # Add formatted time strings for better display (handles minutes intelligently)
    if time_info:
        hour_24 = time_info['hour']
        minute = time_info['minute']

        # Determine the base date to use for placeholders
        # If date was extracted, use it; otherwise use current date
        if date_info:
            base_date = datetime(date_info['year'], date_info['month'], date_info['day'])
        else:
            base_date = datetime.now()

        # If output_timezone is specified, convert the display time to that timezone
        if output_tz:
            # Create a datetime in the source timezone using the base date
            temp_date = source_tz.localize(base_date.replace(hour=hour_24, minute=minute, second=0, microsecond=0))
            # Convert to output timezone
            temp_date_output = temp_date.astimezone(output_tz)
            # Extract converted hour and minute for display
            hour_24 = temp_date_output.hour
            minute = temp_date_output.minute
            logger.debug(f"Converted display time from {source_tz} to {output_tz}: {hour_24}:{minute:02d}")

            # Add date placeholders based on the OUTPUT timezone
            # This ensures {date}, {month}, {day}, {year} reflect the converted timezone
            all_groups['date'] = temp_date_output.strftime('%Y-%m-%d')
            all_groups['month'] = str(temp_date_output.month)
            all_groups['day'] = str(temp_date_output.day)
            all_groups['year'] = str(temp_date_output.year)
            logger.debug(f"Converted date placeholders to {output_tz}: {all_groups['date']}")
        else:
            # No output timezone conversion - use source timezone for date
            # Create temp date to get proper date in source timezone using the base date
            temp_date_source = source_tz.localize(base_date.replace(hour=hour_24, minute=minute, second=0, microsecond=0))
            all_groups['date'] = temp_date_source.strftime('%Y-%m-%d')
            all_groups['month'] = str(temp_date_source.month)
            all_groups['day'] = str(temp_date_source.day)
            all_groups['year'] = str(temp_date_source.year)

        # Format 24-hour start time string - only include minutes if non-zero
        if minute > 0:
            all_groups['starttime24'] = f"{hour_24}:{minute:02d}"
        else:
            all_groups['starttime24'] = f"{hour_24:02d}:00"

        # Convert 24-hour to 12-hour format for {starttime} placeholder
        # Note: hour_24 is ALWAYS in 24-hour format at this point (converted earlier if needed)
        ampm = 'AM' if hour_24 < 12 else 'PM'
        hour_12 = hour_24
        if hour_24 == 0:
            hour_12 = 12
        elif hour_24 > 12:
            hour_12 = hour_24 - 12

        # Format 12-hour start time string - only include minutes if non-zero
        if minute > 0:
            all_groups['starttime'] = f"{hour_12}:{minute:02d} {ampm}"
        else:
            all_groups['starttime'] = f"{hour_12} {ampm}"

        # Format long version that always includes minutes (e.g., "9:00 PM" instead of "9 PM")
        all_groups['starttime_long'] = f"{hour_12}:{minute:02d} {ampm}"

        # Calculate end time based on program duration
        # Create a datetime for calculations
        temp_start = datetime.now(source_tz).replace(hour=hour_24, minute=minute, second=0, microsecond=0)
        temp_end = temp_start + timedelta(minutes=program_duration)

        # Extract end time components (already in correct timezone if output_tz was applied above)
        end_hour_24 = temp_end.hour
        end_minute = temp_end.minute

        # Format 24-hour end time string - only include minutes if non-zero
        if end_minute > 0:
            all_groups['endtime24'] = f"{end_hour_24}:{end_minute:02d}"
        else:
            all_groups['endtime24'] = f"{end_hour_24:02d}:00"

        # Convert 24-hour to 12-hour format for {endtime} placeholder
        end_ampm = 'AM' if end_hour_24 < 12 else 'PM'
        end_hour_12 = end_hour_24
        if end_hour_24 == 0:
            end_hour_12 = 12
        elif end_hour_24 > 12:
            end_hour_12 = end_hour_24 - 12

        # Format 12-hour end time string - only include minutes if non-zero
        if end_minute > 0:
            all_groups['endtime'] = f"{end_hour_12}:{end_minute:02d} {end_ampm}"
        else:
            all_groups['endtime'] = f"{end_hour_12} {end_ampm}"

        # Format long version that always includes minutes (e.g., "9:00 PM" instead of "9 PM")
        all_groups['endtime_long'] = f"{end_hour_12}:{end_minute:02d} {end_ampm}"

    # Generate programs
    programs = []

    # If we have extracted time AND date, the event happens on a SPECIFIC date
    # If we have time but NO date, generate for multiple days (existing behavior)
    # All other days and times show "Upcoming" before or "Ended" after
    event_happened = False

    # Determine how many iterations we need
    if date_info and time_info:
        # Specific date extracted - only generate for that one date
        iterations = 1
        logger.debug(f"Date extracted, generating single event for specific date")
    else:
        # No specific date - use num_days (existing behavior)
        iterations = num_days

    for day in range(iterations):
        # Start from current time (like standard dummy) instead of midnight
        # This ensures programs appear in the guide's current viewing window
        day_start = now + timedelta(days=day)
        day_end = day_start + timedelta(days=1)

        if time_info:
            # We have an extracted event time - this is when the MAIN event starts
            # The extracted time is in the SOURCE timezone (e.g., 8PM ET)
            # We need to convert it to UTC for storage

            # Determine which date to use
            if date_info:
                # Use the extracted date from the channel title
                current_date = datetime(
                    date_info['year'],
                    date_info['month'],
                    date_info['day']
                ).date()
                logger.debug(f"Using extracted date: {current_date}")
            else:
                # No date extracted, use day offset from current time in SOURCE timezone
                # This ensures we calculate "today" in the event's timezone, not UTC
                # For example: 8:30 PM Central (1:30 AM UTC next day) for a 10 PM ET event
                # should use today's date in ET, not tomorrow's date in UTC
                now_in_source_tz = now.astimezone(source_tz)
                current_date = (now_in_source_tz + timedelta(days=day)).date()
                logger.debug(f"No date extracted, using day offset in {source_tz}: {current_date}")

            # Create a naive datetime (no timezone info) representing the event in source timezone
            event_start_naive = datetime.combine(
                current_date,
                datetime.min.time().replace(
                    hour=time_info['hour'],
                    minute=time_info['minute']
                )
            )

            # Use pytz to localize the naive datetime to the source timezone
            # This automatically handles DST!
            try:
                event_start_local = source_tz.localize(event_start_naive)
                # Convert to UTC
                event_start_utc = event_start_local.astimezone(pytz.utc)
                logger.debug(f"Converted {event_start_local} to UTC: {event_start_utc}")
            except Exception as e:
                logger.error(f"Error localizing time to {source_tz}: {e}")
                # Fallback: treat as UTC
                event_start_utc = django_timezone.make_aware(event_start_naive, pytz.utc)

            event_end_utc = event_start_utc + timedelta(minutes=program_duration)

            # Pre-generate the main event title and description for reuse
            if title_template:
                main_event_title = format_template(title_template, all_groups)
            else:
                title_parts = []
                if 'league' in all_groups and all_groups['league']:
                    title_parts.append(all_groups['league'])
                if 'team1' in all_groups and 'team2' in all_groups:
                    title_parts.append(f"{all_groups['team1']} vs {all_groups['team2']}")
                elif 'title' in all_groups and all_groups['title']:
                    title_parts.append(all_groups['title'])
                main_event_title = ' - '.join(title_parts) if title_parts else channel_name

            if description_template:
                main_event_description = format_template(description_template, all_groups)
            else:
                main_event_description = main_event_title



            # Determine if this day is before, during, or after the event
            # Event only happens on day 0 (first day)
            is_event_day = (day == 0)

            if is_event_day and not event_happened:
                # This is THE day the event happens
                # Fill programs BEFORE the event
                current_time = day_start

                while current_time < event_start_utc:
                    program_start_utc = current_time
                    program_end_utc = min(current_time + timedelta(minutes=program_duration), event_start_utc)

                    # Use custom upcoming templates if provided, otherwise use defaults
                    if upcoming_title_template:
                        upcoming_title = format_template(upcoming_title_template, all_groups)
                    else:
                        upcoming_title = main_event_title

                    if upcoming_description_template:
                        upcoming_description = format_template(upcoming_description_template, all_groups)
                    else:
                        upcoming_description = f"Upcoming: {main_event_description}"

                    # Build custom_properties for upcoming programs (only date, no category/live)
                    program_custom_properties = {}

                    # Add date if requested (YYYY-MM-DD format from start time in event timezone)
                    if include_date:
                        # Convert UTC time to event timezone for date calculation
                        local_time = program_start_utc.astimezone(source_tz)
                        date_str = local_time.strftime('%Y-%m-%d')
                        program_custom_properties['date'] = date_str

                    # Add program poster URL if provided
                    if program_poster_url:
                        program_custom_properties['icon'] = program_poster_url

                    programs.append({
                        "channel_id": channel_id,
                        "start_time": program_start_utc,
                        "end_time": program_end_utc,
                        "title": upcoming_title,
                        "description": upcoming_description,
                        "custom_properties": program_custom_properties,
                        "channel_logo_url": channel_logo_url,  # Pass channel logo for EPG generation
                    })

                    current_time += timedelta(minutes=program_duration)

                # Add the MAIN EVENT at the extracted time
                # Build custom_properties for main event (includes category and live)
                main_event_custom_properties = {}

                # Add categories if provided
                if categories:
                    main_event_custom_properties['categories'] = categories

                # Add date if requested (YYYY-MM-DD format from start time in event timezone)
                if include_date:
                    # Convert UTC time to event timezone for date calculation
                    local_time = event_start_utc.astimezone(source_tz)
                    date_str = local_time.strftime('%Y-%m-%d')
                    main_event_custom_properties['date'] = date_str

                # Add live flag if requested
                if include_live:
                    main_event_custom_properties['live'] = True

                # Add new flag if requested
                if include_new:
                    main_event_custom_properties['new'] = True

                # Add program poster URL if provided
                if program_poster_url:
                    main_event_custom_properties['icon'] = program_poster_url

                programs.append({
                    "channel_id": channel_id,
                    "start_time": event_start_utc,
                    "end_time": event_end_utc,
                    "title": main_event_title,
                    "description": main_event_description,
                    "custom_properties": main_event_custom_properties,
                    "channel_logo_url": channel_logo_url,  # Pass channel logo for EPG generation
                })

                event_happened = True

                # Fill programs AFTER the event until end of day
                current_time = event_end_utc

                while current_time < day_end:
                    program_start_utc = current_time
                    program_end_utc = min(current_time + timedelta(minutes=program_duration), day_end)

                    # Use custom ended templates if provided, otherwise use defaults
                    if ended_title_template:
                        ended_title = format_template(ended_title_template, all_groups)
                    else:
                        ended_title = main_event_title

                    if ended_description_template:
                        ended_description = format_template(ended_description_template, all_groups)
                    else:
                        ended_description = f"Ended: {main_event_description}"

                    # Build custom_properties for ended programs (only date, no category/live)
                    program_custom_properties = {}

                    # Add date if requested (YYYY-MM-DD format from start time in event timezone)
                    if include_date:
                        # Convert UTC time to event timezone for date calculation
                        local_time = program_start_utc.astimezone(source_tz)
                        date_str = local_time.strftime('%Y-%m-%d')
                        program_custom_properties['date'] = date_str

                    # Add program poster URL if provided
                    if program_poster_url:
                        program_custom_properties['icon'] = program_poster_url

                    programs.append({
                        "channel_id": channel_id,
                        "start_time": program_start_utc,
                        "end_time": program_end_utc,
                        "title": ended_title,
                        "description": ended_description,
                        "custom_properties": program_custom_properties,
                        "channel_logo_url": channel_logo_url,  # Pass channel logo for EPG generation
                    })

                    current_time += timedelta(minutes=program_duration)
            else:
                # This day is either before the event (future days) or after the event happened
                # Fill entire day with appropriate message
                current_time = day_start

                # If event already happened, all programs show "Ended"
                # If event hasn't happened yet (shouldn't occur with day 0 logic), show "Upcoming"
                is_ended = event_happened

                while current_time < day_end:
                    program_start_utc = current_time
                    program_end_utc = min(current_time + timedelta(minutes=program_duration), day_end)

                    # Use custom templates based on whether event has ended or is upcoming
                    if is_ended:
                        if ended_title_template:
                            program_title = format_template(ended_title_template, all_groups)
                        else:
                            program_title = main_event_title

                        if ended_description_template:
                            program_description = format_template(ended_description_template, all_groups)
                        else:
                            program_description = f"Ended: {main_event_description}"
                    else:
                        if upcoming_title_template:
                            program_title = format_template(upcoming_title_template, all_groups)
                        else:
                            program_title = main_event_title

                        if upcoming_description_template:
                            program_description = format_template(upcoming_description_template, all_groups)
                        else:
                            program_description = f"Upcoming: {main_event_description}"

                    # Build custom_properties (only date for upcoming/ended filler programs)
                    program_custom_properties = {}

                    # Add date if requested (YYYY-MM-DD format from start time in event timezone)
                    if include_date:
                        # Convert UTC time to event timezone for date calculation
                        local_time = program_start_utc.astimezone(source_tz)
                        date_str = local_time.strftime('%Y-%m-%d')
                        program_custom_properties['date'] = date_str

                    # Add program poster URL if provided
                    if program_poster_url:
                        program_custom_properties['icon'] = program_poster_url

                    programs.append({
                        "channel_id": channel_id,
                        "start_time": program_start_utc,
                        "end_time": program_end_utc,
                        "title": program_title,
                        "description": program_description,
                        "custom_properties": program_custom_properties,
                        "channel_logo_url": channel_logo_url,
                    })

                    current_time += timedelta(minutes=program_duration)
        else:
            # No extracted time - fill entire day with regular intervals
            # day_start and day_end are already in UTC, so no conversion needed
            programs_per_day = max(1, int(24 / (program_duration / 60)))

            for program_num in range(programs_per_day):
                program_start_utc = day_start + timedelta(minutes=program_num * program_duration)
                program_end_utc = program_start_utc + timedelta(minutes=program_duration)

                if title_template:
                    title = format_template(title_template, all_groups)
                else:
                    title_parts = []
                    if 'league' in all_groups and all_groups['league']:
                        title_parts.append(all_groups['league'])
                    if 'team1' in all_groups and 'team2' in all_groups:
                        title_parts.append(f"{all_groups['team1']} vs {all_groups['team2']}")
                    elif 'title' in all_groups and all_groups['title']:
                        title_parts.append(all_groups['title'])
                    title = ' - '.join(title_parts) if title_parts else channel_name

                if description_template:
                    description = format_template(description_template, all_groups)
                else:
                    description = title

                # Build custom_properties for this program
                program_custom_properties = {}

                # Add categories if provided
                if categories:
                    program_custom_properties['categories'] = categories

                # Add date if requested (YYYY-MM-DD format from start time in event timezone)
                if include_date:
                    # Convert UTC time to event timezone for date calculation
                    local_time = program_start_utc.astimezone(source_tz)
                    date_str = local_time.strftime('%Y-%m-%d')
                    program_custom_properties['date'] = date_str

                # Add live flag if requested
                if include_live:
                    program_custom_properties['live'] = True

                # Add new flag if requested
                if include_new:
                    program_custom_properties['new'] = True

                # Add program poster URL if provided
                if program_poster_url:
                    program_custom_properties['icon'] = program_poster_url

                programs.append({
                    "channel_id": channel_id,
                    "start_time": program_start_utc,
                    "end_time": program_end_utc,
                    "title": title,
                    "description": description,
                    "custom_properties": program_custom_properties,
                    "channel_logo_url": channel_logo_url,  # Pass channel logo for EPG generation
                })

    logger.info(f"Generated {len(programs)} custom dummy programs for {channel_name}")
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

        # Add custom_properties if present
        custom_data = program.get('custom_properties', {})

        # Categories
        if 'categories' in custom_data:
            for cat in custom_data['categories']:
                xml_lines.append(f"    <category>{html.escape(cat)}</category>")

        # Date tag
        if 'date' in custom_data:
            xml_lines.append(f"    <date>{html.escape(custom_data['date'])}</date>")

        # Live tag
        if custom_data.get('live', False):
            xml_lines.append(f"    <live />")

        # New tag
        if custom_data.get('new', False):
            xml_lines.append(f"    <new />")

        xml_lines.append(f"  </programme>")

    return xml_lines


def generate_epg(request, profile_name=None, user=None):
    """
    Dynamically generate an XMLTV (EPG) file using streaming response to handle keep-alives.
    Since the EPG data is stored independently of Channels, we group programmes
    by their associated EPGData record.
    This version filters data based on the 'days' parameter and sends keep-alives during processing.
    """
    # Check cache for recent identical request (helps with double-GET from browsers)
    from django.core.cache import cache
    cache_params = f"{profile_name or 'all'}:{user.username if user else 'anonymous'}:{request.GET.urlencode()}"
    content_cache_key = f"epg_content:{cache_params}"

    cached_content = cache.get(content_cache_key)
    if cached_content:
        logger.debug("Serving EPG from cache")
        response = HttpResponse(cached_content, content_type="application/xml")
        response["Content-Disposition"] = 'attachment; filename="Dispatcharr.xml"'
        response["Cache-Control"] = "no-cache"
        return response

    def epg_generator():
        """Generator function that yields EPG data with keep-alives during processing"""
        # Send initial HTTP headers as comments (these will be ignored by XML parsers but keep connection alive)

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
                try:
                    channel_profile = ChannelProfile.objects.get(name=profile_name)
                except ChannelProfile.DoesNotExist:
                    logger.warning("Requested channel profile (%s) during epg generation does not exist", profile_name)
                    raise Http404(f"Channel profile '{profile_name}' not found")
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
        now = django_timezone.now()
        cutoff_date = now + timedelta(days=num_days) if num_days > 0 else None

        # Build collision-free channel number mapping for XC clients (if user is authenticated)
        # XC clients require integer channel numbers, so we need to ensure no conflicts
        channel_num_map = {}
        if user is not None:
            # This is an XC client - build collision-free mapping
            used_numbers = set()

            # First pass: assign integers for channels that already have integer numbers
            for channel in channels:
                if channel.channel_number == int(channel.channel_number):
                    num = int(channel.channel_number)
                    channel_num_map[channel.id] = num
                    used_numbers.add(num)

            # Second pass: assign integers for channels with float numbers
            for channel in channels:
                if channel.channel_number != int(channel.channel_number):
                    candidate = int(channel.channel_number)
                    while candidate in used_numbers:
                        candidate += 1
                    channel_num_map[channel.id] = candidate
                    used_numbers.add(candidate)

        # Process channels for the <channel> section
        for channel in channels:
            # For XC clients (user is not None), use collision-free integer mapping
            # For regular clients (user is None), use original formatting logic
            if user is not None:
                # XC client - use collision-free integer
                formatted_channel_number = channel_num_map[channel.id]
            else:
                # Regular client - format channel number as integer if it has no decimal component
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

            # Check if this is a custom dummy EPG with channel logo URL template
            if channel.epg_data and channel.epg_data.epg_source and channel.epg_data.epg_source.source_type == 'dummy':
                epg_source = channel.epg_data.epg_source
                if epg_source.custom_properties:
                    custom_props = epg_source.custom_properties
                    channel_logo_url_template = custom_props.get('channel_logo_url', '')

                    if channel_logo_url_template:
                        # Determine which name to use for pattern matching (same logic as program generation)
                        pattern_match_name = channel.name
                        name_source = custom_props.get('name_source')

                        if name_source == 'stream':
                            stream_index = custom_props.get('stream_index', 1) - 1
                            channel_streams = channel.streams.all().order_by('channelstream__order')

                            if channel_streams.exists() and 0 <= stream_index < channel_streams.count():
                                stream = list(channel_streams)[stream_index]
                                pattern_match_name = stream.name

                        # Try to extract groups from the channel/stream name and build the logo URL
                        title_pattern = custom_props.get('title_pattern', '')
                        if title_pattern:
                            try:
                                # Convert PCRE/JavaScript named groups to Python format
                                title_pattern = regex.sub(r'\(\?<(?![=!])([^>]+)>', r'(?P<\1>', title_pattern)
                                title_regex = regex.compile(title_pattern)
                                title_match = title_regex.search(pattern_match_name)

                                if title_match:
                                    groups = title_match.groupdict()

                                    # Add normalized versions of all groups for cleaner URLs
                                    for key, value in list(groups.items()):
                                        if value:
                                            # Remove all non-alphanumeric characters and convert to lowercase
                                            normalized = regex.sub(r'[^a-zA-Z0-9\s]', '', str(value))
                                            normalized = regex.sub(r'\s+', '', normalized).lower()
                                            groups[f'{key}_normalize'] = normalized

                                    # Format the logo URL template with the matched groups (with URL encoding)
                                    from urllib.parse import quote
                                    for key, value in groups.items():
                                        if value:
                                            encoded_value = quote(str(value), safe='')
                                            channel_logo_url_template = channel_logo_url_template.replace(f'{{{key}}}', encoded_value)
                                        else:
                                            channel_logo_url_template = channel_logo_url_template.replace(f'{{{key}}}', '')
                                    tvg_logo = channel_logo_url_template
                                    logger.debug(f"Built channel logo URL from template: {tvg_logo}")
                            except Exception as e:
                                logger.warning(f"Failed to build channel logo URL for {channel.name}: {e}")

            # If no custom dummy logo, use regular logo logic
            if not tvg_logo and channel.logo:
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
        channel_xml = '\n'.join(xml_lines) + '\n'
        yield channel_xml
        xml_lines = []  # Clear to save memory

        # Process programs for each channel
        for channel in channels:

            # Use the same channel ID determination for program entries
            if tvg_id_source == 'tvg_id' and channel.tvg_id:
                channel_id = channel.tvg_id
            elif tvg_id_source == 'gracenote' and channel.tvc_guide_stationid:
                channel_id = channel.tvc_guide_stationid
            else:
                # For XC clients (user is not None), use collision-free integer mapping
                # For regular clients (user is None), use original formatting logic
                if user is not None:
                    # XC client - use collision-free integer from map
                    formatted_channel_number = channel_num_map[channel.id]
                else:
                    # Regular client - format channel number as before
                    if channel.channel_number is not None:
                        if channel.channel_number == int(channel.channel_number):
                            formatted_channel_number = int(channel.channel_number)
                        else:
                            formatted_channel_number = channel.channel_number
                    else:
                        formatted_channel_number = ""
                # Default to channel number
                channel_id = str(formatted_channel_number) if formatted_channel_number != "" else str(channel.id)

            # Use EPG data name for display, but channel name for pattern matching
            display_name = channel.epg_data.name if channel.epg_data else channel.name
            # For dummy EPG pattern matching, determine which name to use
            pattern_match_name = channel.name

            # Check if we should use stream name instead of channel name
            if channel.epg_data and channel.epg_data.epg_source:
                epg_source = channel.epg_data.epg_source
                if epg_source.custom_properties:
                    custom_props = epg_source.custom_properties
                    name_source = custom_props.get('name_source')

                    if name_source == 'stream':
                        stream_index = custom_props.get('stream_index', 1) - 1
                        channel_streams = channel.streams.all().order_by('channelstream__order')

                        if channel_streams.exists() and 0 <= stream_index < channel_streams.count():
                            stream = list(channel_streams)[stream_index]
                            pattern_match_name = stream.name
                            logger.debug(f"Using stream name for parsing: {pattern_match_name} (stream index: {stream_index})")
                        else:
                            logger.warning(f"Stream index {stream_index} not found for channel {channel.name}, falling back to channel name")

            if not channel.epg_data:
                # Use the enhanced dummy EPG generation function with defaults
                program_length_hours = 4  # Default to 4-hour program blocks
                dummy_programs = generate_dummy_programs(
                    channel_id, pattern_match_name,
                    num_days=dummy_days,
                    program_length_hours=program_length_hours,
                    epg_source=None
                )

                for program in dummy_programs:
                    # Format times in XMLTV format
                    start_str = program['start_time'].strftime("%Y%m%d%H%M%S %z")
                    stop_str = program['end_time'].strftime("%Y%m%d%H%M%S %z")

                    # Create program entry with escaped channel name
                    yield f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">\n'
                    yield f"    <title>{html.escape(program['title'])}</title>\n"
                    yield f"    <desc>{html.escape(program['description'])}</desc>\n"

                    # Add custom_properties if present
                    custom_data = program.get('custom_properties', {})

                    # Categories
                    if 'categories' in custom_data:
                        for cat in custom_data['categories']:
                            yield f"    <category>{html.escape(cat)}</category>\n"

                    # Date tag
                    if 'date' in custom_data:
                        yield f"    <date>{html.escape(custom_data['date'])}</date>\n"

                    # Live tag
                    if custom_data.get('live', False):
                        yield f"    <live />\n"

                    # New tag
                    if custom_data.get('new', False):
                        yield f"    <new />\n"

                    # Icon/poster URL
                    if 'icon' in custom_data:
                        yield f"    <icon src=\"{html.escape(custom_data['icon'])}\" />\n"

                    yield f"  </programme>\n"

            else:
                # Check if this is a dummy EPG with no programs (generate on-demand)
                if channel.epg_data.epg_source and channel.epg_data.epg_source.source_type == 'dummy':
                    # This is a custom dummy EPG - check if it has programs
                    if not channel.epg_data.programs.exists():
                        # No programs stored, generate on-demand using custom patterns
                        # Use actual channel name for pattern matching
                        program_length_hours = 4
                        dummy_programs = generate_dummy_programs(
                            channel_id, pattern_match_name,
                            num_days=dummy_days,
                            program_length_hours=program_length_hours,
                            epg_source=channel.epg_data.epg_source
                        )

                        for program in dummy_programs:
                            start_str = program['start_time'].strftime("%Y%m%d%H%M%S %z")
                            stop_str = program['end_time'].strftime("%Y%m%d%H%M%S %z")

                            yield f'  <programme start="{start_str}" stop="{stop_str}" channel="{channel_id}">\n'
                            yield f"    <title>{html.escape(program['title'])}</title>\n"
                            yield f"    <desc>{html.escape(program['description'])}</desc>\n"

                            # Add custom_properties if present
                            custom_data = program.get('custom_properties', {})

                            # Categories
                            if 'categories' in custom_data:
                                for cat in custom_data['categories']:
                                    yield f"    <category>{html.escape(cat)}</category>\n"

                            # Date tag
                            if 'date' in custom_data:
                                yield f"    <date>{html.escape(custom_data['date'])}</date>\n"

                            # Live tag
                            if custom_data.get('live', False):
                                yield f"    <live />\n"

                            # New tag
                            if custom_data.get('new', False):
                                yield f"    <new />\n"

                            # Icon/poster URL
                            if 'icon' in custom_data:
                                yield f"    <icon src=\"{html.escape(custom_data['icon'])}\" />\n"

                            yield f"  </programme>\n"

                        continue  # Skip to next channel

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
                            batch_xml = '\n'.join(program_batch) + '\n'
                            yield batch_xml
                            program_batch = []

                    # Move to next chunk
                    offset += chunk_size

                # Send remaining programs in batch
                if program_batch:
                    batch_xml = '\n'.join(program_batch) + '\n'
                    yield batch_xml

        # Send final closing tag and completion message
        yield "</tv>\n"

        # Log system event for EPG download after streaming completes (with deduplication based on client)
        client_id, client_ip, user_agent = get_client_identifier(request)
        event_cache_key = f"epg_download:{user.username if user else 'anonymous'}:{profile_name or 'all'}:{client_id}"
        if not cache.get(event_cache_key):
            log_system_event(
                event_type='epg_download',
                profile=profile_name or 'all',
                user=user.username if user else 'anonymous',
                channels=channels.count(),
                client_ip=client_ip,
                user_agent=user_agent,
            )
            cache.set(event_cache_key, True, 2)  # Prevent duplicate events for 2 seconds

    # Wrapper generator that collects content for caching
    def caching_generator():
        collected_content = []
        for chunk in epg_generator():
            collected_content.append(chunk)
            yield chunk
        # After streaming completes, cache the full content
        full_content = ''.join(collected_content)
        cache.set(content_cache_key, full_content, 300)
        logger.debug("Cached EPG content (%d bytes)", len(full_content))

    # Return streaming response
    response = StreamingHttpResponse(
        streaming_content=caching_generator(),
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

    if action == "get_live_categories":
        return JsonResponse(xc_get_live_categories(user), safe=False)
    elif action == "get_live_streams":
        return JsonResponse(xc_get_live_streams(request, user, request.GET.get("category_id")), safe=False)
    elif action == "get_short_epg":
        return JsonResponse(xc_get_epg(request, user, short=True), safe=False)
    elif action == "get_simple_data_table":
        return JsonResponse(xc_get_epg(request, user, short=False), safe=False)
    elif action == "get_vod_categories":
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
        # For any other action (including get_account_info or unknown actions),
        # return server_info/account_info to match provider behavior
        server_info = xc_get_info(request)
        return JsonResponse(server_info, safe=False)


def xc_panel_api(request):
    if not network_access_allowed(request, 'XC_API'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    user = xc_get_user(request)

    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return JsonResponse(xc_get_info(request, True))


def xc_get(request):
    if not network_access_allowed(request, 'XC_API'):
        # Log blocked M3U download
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='m3u_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Network access denied (XC API)',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Forbidden'}, status=403)

    action = request.GET.get("action")
    user = xc_get_user(request)

    if user is None:
        # Log blocked M3U download due to invalid credentials
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='m3u_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Invalid XC credentials',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return generate_m3u(request, None, user)


def xc_xmltv(request):
    if not network_access_allowed(request, 'XC_API'):
        # Log blocked EPG download
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='epg_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Network access denied (XC API)',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Forbidden'}, status=403)

    user = xc_get_user(request)

    if user is None:
        # Log blocked EPG download due to invalid credentials
        from core.utils import log_system_event
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        log_system_event(
            event_type='epg_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Invalid XC credentials',
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    return generate_epg(request, None, user)


def xc_get_live_categories(user):
    from django.db.models import Min
    response = []

    if user.user_level == 0:
        user_profile_count = user.channel_profiles.count()

        # If user has ALL profiles or NO profiles, give unrestricted access
        if user_profile_count == 0:
            # No profile filtering - user sees all channel groups
            channel_groups = ChannelGroup.objects.filter(
                channels__isnull=False, channels__user_level__lte=user.user_level
            ).distinct().annotate(min_channel_number=Min('channels__channel_number')).order_by('min_channel_number')
        else:
            # User has specific limited profiles assigned
            filters = {
                "channels__channelprofilemembership__enabled": True,
                "channels__user_level": 0,
                "channels__channelprofilemembership__channel_profile__in": user.channel_profiles.all()
            }
            channel_groups = ChannelGroup.objects.filter(**filters).distinct().annotate(min_channel_number=Min('channels__channel_number')).order_by('min_channel_number')
    else:
        channel_groups = ChannelGroup.objects.filter(
            channels__isnull=False, channels__user_level__lte=user.user_level
        ).distinct().annotate(min_channel_number=Min('channels__channel_number')).order_by('min_channel_number')

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

    # Build collision-free mapping for XC clients (which require integers)
    # This ensures channels with float numbers don't conflict with existing integers
    channel_num_map = {}  # Maps channel.id -> integer channel number for XC
    used_numbers = set()  # Track all assigned integer channel numbers

    # First pass: assign integers for channels that already have integer numbers
    for channel in channels:
        if channel.channel_number == int(channel.channel_number):
            # Already an integer, use it directly
            num = int(channel.channel_number)
            channel_num_map[channel.id] = num
            used_numbers.add(num)

    # Second pass: assign integers for channels with float numbers
    # Find next available number to avoid collisions
    for channel in channels:
        if channel.channel_number != int(channel.channel_number):
            # Has decimal component, need to find available integer
            # Start from truncated value and increment until we find an unused number
            candidate = int(channel.channel_number)
            while candidate in used_numbers:
                candidate += 1
            channel_num_map[channel.id] = candidate
            used_numbers.add(candidate)

    # Build the streams list with the collision-free channel numbers
    for channel in channels:
        channel_num_int = channel_num_map[channel.id]

        streams.append(
            {
                "num": channel_num_int,
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
                "epg_channel_id": str(channel_num_int),
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

    # Calculate the collision-free integer channel number for this channel
    # This must match the logic in xc_get_live_streams to ensure consistency
    # Get all channels in the same category for collision detection
    category_channels = Channel.objects.filter(
        channel_group=channel.channel_group
    ).order_by("channel_number")

    channel_num_map = {}
    used_numbers = set()

    # First pass: assign integers for channels that already have integer numbers
    for ch in category_channels:
        if ch.channel_number == int(ch.channel_number):
            num = int(ch.channel_number)
            channel_num_map[ch.id] = num
            used_numbers.add(num)

    # Second pass: assign integers for channels with float numbers
    for ch in category_channels:
        if ch.channel_number != int(ch.channel_number):
            candidate = int(ch.channel_number)
            while candidate in used_numbers:
                candidate += 1
            channel_num_map[ch.id] = candidate
            used_numbers.add(candidate)

    # Get the mapped integer for this specific channel
    channel_num_int = channel_num_map.get(channel.id, int(channel.channel_number))

    limit = request.GET.get('limit', 4)
    if channel.epg_data:
        # Check if this is a dummy EPG that generates on-demand
        if channel.epg_data.epg_source and channel.epg_data.epg_source.source_type == 'dummy':
            if not channel.epg_data.programs.exists():
                # Generate on-demand using custom patterns
                programs = generate_dummy_programs(
                    channel_id=channel_id,
                    channel_name=channel.name,
                    epg_source=channel.epg_data.epg_source
                )
            else:
                # Has stored programs, use them
                if short == False:
                    programs = channel.epg_data.programs.filter(
                        start_time__gte=django_timezone.now()
                    ).order_by('start_time')
                else:
                    programs = channel.epg_data.programs.all().order_by('start_time')[:limit]
        else:
            # Regular EPG with stored programs
            if short == False:
                programs = channel.epg_data.programs.filter(
                    start_time__gte=django_timezone.now()
                ).order_by('start_time')
            else:
                programs = channel.epg_data.programs.all().order_by('start_time')[:limit]
    else:
        # No EPG data assigned, generate default dummy
        programs = generate_dummy_programs(channel_id=channel_id, channel_name=channel.name, epg_source=None)

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
            "title": base64.b64encode((title or "").encode()).decode(),
            "lang": "",
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
            "description": base64.b64encode((description or "").encode()).decode(),
            "channel_id": str(channel_num_int),
            "start_timestamp": str(int(start.timestamp())),
            "stop_timestamp": str(int(end.timestamp())),
            "stream_id": f"{channel_id}",
        }

        if short == False:
            program_output["now_playing"] = 1 if start <= django_timezone.now() <= end else 0
            program_output["has_archive"] = 0

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
                    reverse("api:vod:vodlogo-cache", args=[movie.logo.id])
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
                    reverse("api:vod:vodlogo-cache", args=[series.logo.id])
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
            series_relation.last_episode_refresh < django_timezone.now() - timedelta(hours=24)
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

    # Get unique episodes for this series that have relations from any active M3U account
    # We query episodes directly to avoid duplicates when multiple relations exist
    # (e.g., same episode in different languages/qualities)
    from apps.vod.models import Episode
    episodes = Episode.objects.filter(
        series=series,
        m3u_relations__m3u_account__is_active=True
    ).distinct().order_by('season_number', 'episode_number')

    # Group episodes by season
    seasons = {}
    for episode in episodes:
        season_num = episode.season_number or 1
        if season_num not in seasons:
            seasons[season_num] = []

        # Get the highest priority relation for this episode (for container_extension, video/audio/bitrate)
        from apps.vod.models import M3UEpisodeRelation
        best_relation = M3UEpisodeRelation.objects.filter(
            episode=episode,
            m3u_account__is_active=True
        ).select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

        video = audio = bitrate = None
        container_extension = "mp4"
        added_timestamp = str(int(episode.created_at.timestamp()))

        if best_relation:
            container_extension = best_relation.container_extension or "mp4"
            added_timestamp = str(int(best_relation.created_at.timestamp()))
            if best_relation.custom_properties:
                info = best_relation.custom_properties.get('info')
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
            "container_extension": container_extension,
            "added": added_timestamp,
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
                    reverse("api:vod:vodlogo-cache", args=[series.logo.id])
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
                    reverse("api:vod:vodlogo-cache", args=[movie.logo.id])
                )
            ),
            "movie_image": (
                None if not movie.logo
                else build_absolute_uri_with_port(
                    request,
                    reverse("api:vod:vodlogo-cache", args=[movie.logo.id])
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
        episode_relation = M3UEpisodeRelation.objects.select_related('episode').filter(**filters).order_by('-m3u_account__priority', 'id').first()
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
    - Returns None for port if using standard ports (80/443) to omit from URLs.
    - In dev, uses 5656 as a guess if port cannot be determined.
    """
    # Determine the scheme first - needed for standard port detection
    scheme = request.META.get("HTTP_X_FORWARDED_PROTO", request.scheme)
    standard_port = "443" if scheme == "https" else "80"

    # 1. Try X-Forwarded-Host (may include port) - set by our nginx
    xfh = request.META.get("HTTP_X_FORWARDED_HOST")
    if xfh:
        if ":" in xfh:
            host, port = xfh.split(":", 1)
            # Omit standard ports from URLs, or omit if port doesn't match standard for scheme
            # (e.g., HTTPS but port is 9191 = behind external reverse proxy)
            if port == standard_port:
                return host, None
            # If port doesn't match standard and X-Forwarded-Proto is set, likely behind external RP
            if request.META.get("HTTP_X_FORWARDED_PROTO"):
                host = xfh.split(":")[0]  # Strip port, will check for proper port below
            else:
                return host, port
        else:
            host = xfh

        # Check for X-Forwarded-Port header (if we didn't already find a valid port)
        port = request.META.get("HTTP_X_FORWARDED_PORT")
        if port:
            # Omit standard ports from URLs
            return host, None if port == standard_port else port
        # If X-Forwarded-Proto is set but no valid port, assume standard
        if request.META.get("HTTP_X_FORWARDED_PROTO"):
            return host, None

    # 2. Try Host header
    raw_host = request.get_host()
    if ":" in raw_host:
        host, port = raw_host.split(":", 1)
        # Omit standard ports from URLs
        return host, None if port == standard_port else port
    else:
        host = raw_host

    # 3. Check if we're behind a reverse proxy (X-Forwarded-Proto or X-Forwarded-For present)
    # If so, assume standard port for the scheme (don't trust SERVER_PORT in this case)
    if request.META.get("HTTP_X_FORWARDED_PROTO") or request.META.get("HTTP_X_FORWARDED_FOR"):
        return host, None

    # 4. Try SERVER_PORT from META (only if NOT behind reverse proxy)
    port = request.META.get("SERVER_PORT")
    if port:
        # Omit standard ports from URLs
        return host, None if port == standard_port else port

    # 5. Dev fallback: guess port 5656
    if os.environ.get("DISPATCHARR_ENV") == "dev" or host in ("localhost", "127.0.0.1"):
        return host, "5656"

    # 6. Final fallback: assume standard port for scheme (omit from URL)
    return host, None

def build_absolute_uri_with_port(request, path):
    """
    Build an absolute URI with optional port.
    Port is omitted from URL if None (standard port for scheme).
    """
    host, port = get_host_and_port(request)
    scheme = request.META.get("HTTP_X_FORWARDED_PROTO", request.scheme)

    if port:
        return f"{scheme}://{host}:{port}{path}"
    else:
        return f"{scheme}://{host}{path}"

def format_duration_hms(seconds):
    """
    Format a duration in seconds as HH:MM:SS zero-padded string.
    """
    seconds = int(seconds or 0)
    return f"{seconds//3600:02}:{(seconds%3600)//60:02}:{seconds%60:02}"
