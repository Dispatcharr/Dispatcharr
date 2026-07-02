"""XMLTV (EPG) output generation.

Consolidates the EPG export logic that backs the `/epg` endpoint and the XC
XMLTV endpoint: real programme streaming, dummy/custom dummy program
generation, and the streaming XMLTV builder. HTTP endpoints live in views.py
and call into this module; Redis chunk caching lives in streaming_chunk_cache.py.
"""

import html
import logging
from datetime import datetime, timedelta

import regex

from django.db.models import Prefetch
from django.http import Http404
from django.urls import reverse
from django.utils import timezone as django_timezone

from apps.channels.models import Channel, ChannelProfile, Stream
from apps.channels.utils import format_channel_number
from apps.epg.models import ProgramData
from apps.output.streaming_chunk_cache import stream_cached_response
from core.utils import build_absolute_uri_with_port, log_system_event

logger = logging.getLogger(__name__)

_EPG_CHANNEL_XML_BATCH_SIZE = 200
_EPG_PROGRAM_YIELD_BATCH_SIZE = 1000
_EPG_PROGRAM_DB_CHUNK_SIZE = 20000


def _programme_overlaps_export_window(start_time, end_time, lookback_cutoff, cutoff_date):
    if end_time < lookback_cutoff:
        return False
    if cutoff_date is not None and start_time >= cutoff_date:
        return False
    return True


def _ceil_to_half_hour(dt):
    """Round a datetime up to the next :00 or :30 boundary."""
    original = dt.replace(microsecond=0)
    aligned = dt.replace(second=0, microsecond=0)
    remainder = aligned.minute % 30
    if remainder != 0:
        aligned += timedelta(minutes=30 - remainder)
    if aligned < original:
        aligned += timedelta(minutes=30)
    return aligned


def _epg_export_teardown():
    from core.utils import spawn_memory_trim

    spawn_memory_trim(close_connections=True)


def _ordered_channel_streams(channel):
    """Return a channel's streams ordered by channelstream join order."""
    prefetched = getattr(channel, '_prefetched_objects_cache', {}).get('streams')
    if prefetched is not None:
        return list(prefetched)
    return list(channel.streams.all().order_by('channelstream__order'))


def _pattern_match_name_from_custom_props(channel, effective_name, custom_props):
    """Name used for custom dummy EPG regex matching (channel or stream title).

    Returns (name, stream_lookup_failed). stream_lookup_failed is True only when
    name_source is 'stream' but the configured index is missing or out of range.
    """
    if custom_props.get('name_source') != 'stream':
        return effective_name, False
    stream_index = custom_props.get('stream_index', 1) - 1
    streams = _ordered_channel_streams(channel)
    if 0 <= stream_index < len(streams):
        return streams[stream_index].name, False
    return effective_name, True


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


def generate_dummy_programs(
    channel_id,
    channel_name,
    num_days=1,
    program_length_hours=4,
    epg_source=None,
    export_lookback=None,
    export_cutoff=None,
):
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
            epg_source.custom_properties,
            export_lookback=export_lookback,
            export_cutoff=export_cutoff,
        )
        if custom_programs is not None:
            return custom_programs

        logger.info(f"Custom pattern didn't match for '{channel_name}', checking for custom fallback templates")

        custom_props = epg_source.custom_properties
        fallback_title = custom_props.get('fallback_title_template', '').strip()
        fallback_description = custom_props.get('fallback_description_template', '').strip()

        if fallback_title or fallback_description:
            logger.info(f"Using custom fallback templates for '{channel_name}'")
            return generate_fallback_programs(
                channel_id, channel_name, now, num_days,
                program_length_hours, fallback_title, fallback_description
            )
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


def generate_custom_dummy_programs(
    channel_id,
    channel_name,
    now,
    num_days,
    custom_properties,
    export_lookback=None,
    export_cutoff=None,
):
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
    subtitle_template = custom_properties.get('subtitle_template', '')
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
        return None

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
        return None

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
        return None

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
        event_overlaps_window = True
        if date_info and time_info:
            current_date = datetime(
                date_info['year'],
                date_info['month'],
                date_info['day'],
            ).date()
            event_start_naive = datetime.combine(
                current_date,
                datetime.min.time().replace(
                    hour=time_info['hour'],
                    minute=time_info['minute'],
                ),
            )
            try:
                event_start_utc = source_tz.localize(event_start_naive).astimezone(pytz.utc)
            except Exception as e:
                logger.error(f"Error localizing time to {source_tz}: {e}")
                event_start_utc = django_timezone.make_aware(event_start_naive, pytz.utc)
            event_end_utc = event_start_utc + timedelta(minutes=program_duration)

            lookback = export_lookback if export_lookback is not None else now
            event_overlaps_window = _programme_overlaps_export_window(
                event_start_utc, event_end_utc, lookback, export_cutoff
            )
            if not event_overlaps_window:
                logger.debug(
                    "Custom dummy event outside export window; filling window only: %s",
                    channel_name,
                )
                event_happened = event_end_utc < lookback
                day_start = _ceil_to_half_hour(lookback)
                if export_cutoff is not None:
                    day_end = export_cutoff
                else:
                    day_end = now + timedelta(days=num_days if num_days > 0 else 3)
            else:
                day_start = source_tz.localize(
                    datetime.combine(current_date, datetime.min.time())
                ).astimezone(pytz.utc)
                day_end = day_start + timedelta(days=1)
                if export_lookback is not None:
                    day_start = max(day_start, export_lookback)
                if export_cutoff is not None:
                    day_end = min(day_end, export_cutoff)
        else:
            day_start = now + timedelta(days=day)
            day_end = day_start + timedelta(days=1)
            if export_lookback is not None:
                day_start = max(day_start, export_lookback)
            if export_cutoff is not None:
                day_end = min(day_end, export_cutoff)

        if day_start >= day_end:
            continue

        if time_info:
            if not date_info:
                now_in_source_tz = now.astimezone(source_tz)
                current_date = (now_in_source_tz + timedelta(days=day)).date()
                logger.debug(f"No date extracted, using day offset in {source_tz}: {current_date}")

                event_start_naive = datetime.combine(
                    current_date,
                    datetime.min.time().replace(
                        hour=time_info['hour'],
                        minute=time_info['minute'],
                    ),
                )
                try:
                    event_start_local = source_tz.localize(event_start_naive)
                    event_start_utc = event_start_local.astimezone(pytz.utc)
                    logger.debug(f"Converted {event_start_local} to UTC: {event_start_utc}")
                except Exception as e:
                    logger.error(f"Error localizing time to {source_tz}: {e}")
                    event_start_utc = django_timezone.make_aware(event_start_naive, pytz.utc)

                event_end_utc = event_start_utc + timedelta(minutes=program_duration)

                lookback = export_lookback if export_lookback is not None else now
                if not _programme_overlaps_export_window(
                    event_start_utc, event_end_utc, lookback, export_cutoff
                ):
                    continue
            else:
                logger.debug(f"Using extracted date: {current_date}")

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

            if subtitle_template:
                main_event_subtitle = format_template(subtitle_template, all_groups)
            else:
                main_event_subtitle = None

            if description_template:
                main_event_description = format_template(description_template, all_groups)
            else:
                main_event_description = main_event_title



            # Determine if this day is before, during, or after the event
            # Event only happens on day 0 (first day) when it falls inside the window
            is_event_day = (day == 0) and event_overlaps_window

            if is_event_day and not event_happened:
                current_time = day_start

                while current_time < event_start_utc and current_time < day_end:
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
                        "sub_title": None,  # No subtitle for filler programs
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
                    "sub_title": main_event_subtitle,
                    "description": main_event_description,
                    "custom_properties": main_event_custom_properties,
                    "channel_logo_url": channel_logo_url,  # Pass channel logo for EPG generation
                })

                event_happened = True

                # Fill programs AFTER the event until end of export day window
                current_time = max(event_end_utc, day_start)

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
                        "sub_title": None,  # No subtitle for filler programs
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
                        "sub_title": None,  # No subtitle for filler programs
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

                if subtitle_template:
                    subtitle = format_template(subtitle_template, all_groups)
                else:
                    subtitle = None

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
                    "sub_title": subtitle,
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
            f'  <programme start="{start_str}" stop="{stop_str}" channel="{html.escape(program["channel_id"])}">'
        )
        xml_lines.append(f"    <title>{html.escape(program['title'])}</title>")

        # Add subtitle if available
        if program.get('sub_title'):
            xml_lines.append(f"    <sub-title>{html.escape(program['sub_title'])}</sub-title>")

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
    cache_params = (
        f"{profile_name or 'all'}:{user.username if user else 'anonymous'}"
        f":d={num_days}:p={prev_days}:logos={use_cached_logos}:tvgid={tvg_id_source}"
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
            # This is an XC client - build collision-free mapping
            used_numbers = set()

            # First pass: assign integers for channels that already have integer numbers
            for channel in channels:
                effective_num = channel.effective_channel_number
                if effective_num is not None and effective_num == int(effective_num):
                    num = int(effective_num)
                    channel_num_map[channel.id] = num
                    used_numbers.add(num)

            # Second pass: assign integers for channels with float numbers
            for channel in channels:
                effective_num = channel.effective_channel_number
                if effective_num is not None and effective_num != int(effective_num):
                    candidate = int(effective_num)
                    while candidate in used_numbers:
                        candidate += 1
                    channel_num_map[channel.id] = candidate
                    used_numbers.add(candidate)

        # Host/port/scheme are constant per request; precompute logo URL prefix once.
        _base_url = build_absolute_uri_with_port(request, "")
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

            # Check if this is a custom dummy EPG with channel logo URL template
            if effective_epg_data and effective_epg_data.epg_source and effective_epg_data.epg_source.source_type == 'dummy':
                epg_source = effective_epg_data.epg_source
                if epg_source.custom_properties:
                    custom_props = epg_source.custom_properties
                    channel_logo_url_template = custom_props.get('channel_logo_url', '')

                    if channel_logo_url_template:
                        pattern_match_name, _ = _pattern_match_name_from_custom_props(
                            channel, effective_name, custom_props
                        )

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
                                logger.warning(f"Failed to build channel logo URL for {effective_name}: {e}")

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

            pattern_match_name = effective_name
            if effective_epg_data and effective_epg_data.epg_source:
                epg_source = effective_epg_data.epg_source
                if epg_source.custom_properties:
                    custom_props = epg_source.custom_properties
                    pattern_match_name, stream_lookup_failed = _pattern_match_name_from_custom_props(
                        channel, effective_name, custom_props
                    )
                    if (
                        custom_props.get('name_source') == 'stream'
                        and not stream_lookup_failed
                        and pattern_match_name != effective_name
                    ):
                        stream_index = custom_props.get('stream_index', 1) - 1
                        logger.debug(
                            f"Using stream name for parsing: {pattern_match_name} "
                            f"(stream index: {stream_index})"
                        )
                    elif stream_lookup_failed:
                        stream_index = custom_props.get('stream_index', 1) - 1
                        logger.warning(
                            f"Stream index {stream_index} not found for channel "
                            f"{effective_name}, falling back to channel name"
                        )

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
            _poster_url_base = build_absolute_uri_with_port(request, "/api/epg/programs/")

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
                            program_xml.append(f'    <icon src="{html.escape(_poster_url_base)}{prog["id"]}/poster/" />')

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
