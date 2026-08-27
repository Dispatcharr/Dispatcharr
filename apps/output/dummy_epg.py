"""On-demand dummy EPG program generation.

Custom regex-based dummy EPG, standard humorous filler, and fallback
templates. Used by XMLTV export, XC EPG, and the web grid API.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from urllib.parse import quote

import pytz
import regex
from django.utils import timezone as django_timezone

logger = logging.getLogger(__name__)

# Humorous descriptions for channels with no EPG assigned. Values use {channel}.
_STANDARD_DUMMY_TIME_DESCRIPTIONS: dict[tuple[int, int], list[str]] = {
    (0, 4): [
        "Late Night with {channel} - Where insomniacs unite!",
        "The 'Why Am I Still Awake?' Show on {channel}",
        "Counting Sheep - A {channel} production for the sleepless",
    ],
    (4, 8): [
        "Dawn Patrol - Rise and shine with {channel}!",
        "Early Bird Special - Coffee not included",
        "Morning Zombies - Before coffee viewing on {channel}",
    ],
    (8, 12): [
        "Mid-Morning Meetings - Pretend you're paying attention while watching {channel}",
        "The 'I Should Be Working' Hour on {channel}",
        "Productivity Killer - {channel}'s daytime programming",
    ],
    (12, 16): [
        "Lunchtime Laziness with {channel}",
        "The Afternoon Slump - Brought to you by {channel}",
        "Post-Lunch Food Coma Theater on {channel}",
    ],
    (16, 20): [
        "Rush Hour - {channel}'s alternative to traffic",
        "The 'What's For Dinner?' Debate on {channel}",
        "Evening Escapism - {channel}'s remedy for reality",
    ],
    (20, 24): [
        "Prime Time Placeholder - {channel}'s finest not-programming",
        "The 'Netflix Was Too Complicated' Show on {channel}",
        "Family Argument Avoider - Courtesy of {channel}",
    ],
}


def programme_overlaps_export_window(start_time, end_time, lookback_cutoff, cutoff_date):
    if end_time < lookback_cutoff:
        return False
    if cutoff_date is not None and start_time >= cutoff_date:
        return False
    return True


def ceil_to_half_hour(dt):
    """Round a datetime up to the next :00 or :30 boundary."""
    original = dt.replace(microsecond=0)
    aligned = dt.replace(second=0, microsecond=0)
    remainder = aligned.minute % 30
    if remainder != 0:
        aligned += timedelta(minutes=30 - remainder)
    if aligned < original:
        aligned += timedelta(minutes=30)
    return aligned


def _convert_js_named_groups(pattern: str) -> str:
    return regex.sub(r'\(\?<(?![=!])([^>]+)>', r'(?P<\1>', pattern)


def _format_template(template: str, groups: dict, *, url_encode: bool = False) -> str:
    if not template:
        return ''
    result = template
    for key, value in groups.items():
        if url_encode and value:
            result = result.replace(f'{{{key}}}', quote(str(value), safe=''))
        else:
            result = result.replace(f'{{{key}}}', str(value) if value else '')
    return result


def _add_normalized_group_aliases(groups: dict) -> None:
    for key, value in list(groups.items()):
        if value:
            normalized = regex.sub(r'[^a-zA-Z0-9\s]', '', str(value))
            normalized = regex.sub(r'\s+', '', normalized).lower()
            groups[f'{key}_normalize'] = normalized


def _match_title_groups(channel_name: str, title_pattern: str) -> dict | None:
    if not title_pattern:
        return None
    try:
        title_regex = regex.compile(_convert_js_named_groups(title_pattern))
        title_match = title_regex.search(channel_name)
        if not title_match:
            return None
        groups = title_match.groupdict()
        _add_normalized_group_aliases(groups)
        return groups
    except Exception:
        return None


def build_channel_logo_url(parse_name: str, custom_properties: dict) -> str | None:
    """Build a channel logo URL from custom dummy regex groups matched in parse_name."""
    template = custom_properties.get('channel_logo_url', '')
    if not template:
        return None
    groups = _match_title_groups(parse_name, custom_properties.get('title_pattern', ''))
    if not groups:
        return None
    return _format_template(template, groups, url_encode=True) or None


def _standard_dummy_description(channel_name: str, hour: int, day: int) -> str:
    for (start_range, end_range), descriptions in _STANDARD_DUMMY_TIME_DESCRIPTIONS.items():
        if start_range <= hour < end_range:
            return descriptions[(hour + day) % len(descriptions)].format(channel=channel_name)
    return f"Placeholder program for {channel_name} - EPG data went on vacation"


def _export_window_bounds(now, num_days, export_lookback, export_cutoff):
    lookback = export_lookback if export_lookback is not None else now
    window_end = (
        export_cutoff
        if export_cutoff is not None
        else now + timedelta(days=num_days if num_days > 0 else 3)
    )
    return lookback, window_end


@dataclass
class _EventLabels:
    main_title: str
    main_subtitle: str | None
    main_description: str
    upcoming_title: str
    upcoming_description: str
    ended_title: str
    ended_description: str


@dataclass
class _FillerOpts:
    channel_id: str
    duration_minutes: int
    include_date: bool
    source_tz: tzinfo
    program_poster_url: str | None
    channel_logo_url: str | None
    categories: list[str]
    include_live: bool
    include_new: bool


def _build_filler_program(
    program_start_utc,
    program_end_utc,
    title,
    description,
    opts: _FillerOpts,
    *,
    sub_title=None,
    custom_properties_extra=None,
):
    program_custom_properties = dict(custom_properties_extra or {})
    if opts.include_date:
        local_time = program_start_utc.astimezone(opts.source_tz)
        program_custom_properties['date'] = local_time.strftime('%Y-%m-%d')
    if opts.program_poster_url:
        program_custom_properties['icon'] = opts.program_poster_url
    return {
        "channel_id": opts.channel_id,
        "start_time": program_start_utc,
        "end_time": program_end_utc,
        "title": title,
        "sub_title": sub_title,
        "description": description,
        "custom_properties": program_custom_properties,
        "channel_logo_url": opts.channel_logo_url,
    }


def _append_filler_programs(
    programs,
    range_start,
    range_end,
    title,
    description,
    opts: _FillerOpts,
):
    current_time = range_start
    while current_time < range_end:
        program_end_utc = min(
            current_time + timedelta(minutes=opts.duration_minutes),
            range_end,
        )
        programs.append(
            _build_filler_program(
                current_time,
                program_end_utc,
                title,
                description,
                opts,
            )
        )
        current_time += timedelta(minutes=opts.duration_minutes)


def _default_main_title(channel_name, all_groups) -> str:
    title_parts = []
    if all_groups.get('league'):
        title_parts.append(all_groups['league'])
    if all_groups.get('team1') and all_groups.get('team2'):
        title_parts.append(f"{all_groups['team1']} vs {all_groups['team2']}")
    elif all_groups.get('title'):
        title_parts.append(all_groups['title'])
    return ' - '.join(title_parts) if title_parts else channel_name


def _resolve_event_labels(
    channel_name,
    all_groups,
    *,
    title_template,
    subtitle_template,
    description_template,
    upcoming_title_template,
    upcoming_description_template,
    ended_title_template,
    ended_description_template,
) -> _EventLabels:
    main_title = (
        _format_template(title_template, all_groups)
        if title_template
        else _default_main_title(channel_name, all_groups)
    )
    main_subtitle = (
        _format_template(subtitle_template, all_groups) if subtitle_template else None
    )
    main_description = (
        _format_template(description_template, all_groups)
        if description_template
        else main_title
    )
    upcoming_title = (
        _format_template(upcoming_title_template, all_groups)
        if upcoming_title_template
        else main_title
    )
    upcoming_description = (
        _format_template(upcoming_description_template, all_groups)
        if upcoming_description_template
        else f"Upcoming: {main_description}"
    )
    ended_title = (
        _format_template(ended_title_template, all_groups)
        if ended_title_template
        else main_title
    )
    ended_description = (
        _format_template(ended_description_template, all_groups)
        if ended_description_template
        else f"Ended: {main_description}"
    )
    return _EventLabels(
        main_title=main_title,
        main_subtitle=main_subtitle,
        main_description=main_description,
        upcoming_title=upcoming_title,
        upcoming_description=upcoming_description,
        ended_title=ended_title,
        ended_description=ended_description,
    )


def _localize_event_start(source_tz, current_date, time_info):
    event_start_naive = datetime.combine(
        current_date,
        datetime.min.time().replace(
            hour=time_info['hour'],
            minute=time_info['minute'],
        ),
    )
    try:
        return source_tz.localize(event_start_naive).astimezone(pytz.utc)
    except Exception as e:
        logger.error("Error localizing time to %s: %s", source_tz, e)
        return django_timezone.make_aware(event_start_naive, pytz.utc)


def _append_main_event(programs, event_start_utc, event_end_utc, labels: _EventLabels, opts: _FillerOpts):
    main_props = {}
    if opts.categories:
        main_props['categories'] = opts.categories
    if opts.include_live:
        main_props['live'] = True
    if opts.include_new:
        main_props['new'] = True
    programs.append(
        _build_filler_program(
            event_start_utc,
            event_end_utc,
            labels.main_title,
            labels.main_description,
            opts,
            sub_title=labels.main_subtitle,
            custom_properties_extra=main_props,
        )
    )


def _generate_dated_event_timeline(
    programs,
    *,
    now,
    num_days,
    time_info,
    date_info,
    source_tz,
    labels: _EventLabels,
    opts: _FillerOpts,
    export_lookback,
    export_cutoff,
):
    current_date = datetime(
        date_info['year'],
        date_info['month'],
        date_info['day'],
    ).date()
    event_start_utc = _localize_event_start(source_tz, current_date, time_info)
    event_end_utc = event_start_utc + timedelta(minutes=opts.duration_minutes)
    lookback, window_end = _export_window_bounds(
        now, num_days, export_lookback, export_cutoff
    )
    event_overlaps = programme_overlaps_export_window(
        event_start_utc, event_end_utc, lookback, export_cutoff
    )

    if lookback >= window_end:
        return

    if event_start_utc > now:
        upcoming_start = ceil_to_half_hour(max(lookback, now))
        upcoming_end = min(event_start_utc, window_end)
        if upcoming_start < upcoming_end:
            _append_filler_programs(
                programs,
                upcoming_start,
                upcoming_end,
                labels.upcoming_title,
                labels.upcoming_description,
                opts,
            )

    if event_overlaps:
        _append_main_event(programs, event_start_utc, event_end_utc, labels, opts)

    if event_end_utc < lookback and not event_overlaps:
        _append_filler_programs(
            programs,
            ceil_to_half_hour(lookback),
            window_end,
            labels.ended_title,
            labels.ended_description,
            opts,
        )
    elif event_end_utc < window_end:
        ended_start = max(event_end_utc, lookback)
        if ended_start < window_end:
            _append_filler_programs(
                programs,
                ended_start,
                window_end,
                labels.ended_title,
                labels.ended_description,
                opts,
            )


def _generate_recurring_time_programs(
    programs,
    *,
    now,
    num_days,
    time_info,
    source_tz,
    labels: _EventLabels,
    opts: _FillerOpts,
    export_lookback,
    export_cutoff,
):
    lookback = export_lookback if export_lookback is not None else now
    event_happened = False

    for day in range(num_days):
        day_start = now + timedelta(days=day)
        day_end = day_start + timedelta(days=1)
        if export_lookback is not None:
            day_start = max(day_start, export_lookback)
        if export_cutoff is not None:
            day_end = min(day_end, export_cutoff)
        if day_start >= day_end:
            continue

        now_in_source_tz = now.astimezone(source_tz)
        current_date = (now_in_source_tz + timedelta(days=day)).date()
        event_start_utc = _localize_event_start(source_tz, current_date, time_info)
        event_end_utc = event_start_utc + timedelta(minutes=opts.duration_minutes)

        if not programme_overlaps_export_window(
            event_start_utc, event_end_utc, lookback, export_cutoff
        ):
            continue

        is_event_day = day == 0
        if is_event_day and not event_happened:
            if event_start_utc > day_start:
                _append_filler_programs(
                    programs,
                    day_start,
                    min(event_start_utc, day_end),
                    labels.upcoming_title,
                    labels.upcoming_description,
                    opts,
                )
            _append_main_event(programs, event_start_utc, event_end_utc, labels, opts)
            event_happened = True
            ended_start = max(event_end_utc, day_start)
            if ended_start < day_end:
                _append_filler_programs(
                    programs,
                    ended_start,
                    day_end,
                    labels.ended_title,
                    labels.ended_description,
                    opts,
                )
        else:
            title = labels.ended_title if event_happened else labels.upcoming_title
            description = (
                labels.ended_description if event_happened else labels.upcoming_description
            )
            _append_filler_programs(
                programs, day_start, day_end, title, description, opts
            )


def _generate_no_time_programs(
    programs,
    *,
    now,
    num_days,
    all_groups,
    channel_name,
    opts: _FillerOpts,
    export_lookback,
    export_cutoff,
    title_template,
    subtitle_template,
    description_template,
):
    # Titles and metadata depend only on the matched groups, so resolve them once
    # instead of per programme block.
    title = (
        _format_template(title_template, all_groups)
        if title_template
        else _default_main_title(channel_name, all_groups)
    )
    subtitle = (
        _format_template(subtitle_template, all_groups) if subtitle_template else None
    )
    description = (
        _format_template(description_template, all_groups)
        if description_template
        else title
    )
    extra = {}
    if opts.categories:
        extra['categories'] = opts.categories
    if opts.include_live:
        extra['live'] = True
    if opts.include_new:
        extra['new'] = True

    programs_per_day = max(1, int(24 / (opts.duration_minutes / 60)))

    for day in range(num_days):
        day_start = now + timedelta(days=day)
        day_end = day_start + timedelta(days=1)
        if export_lookback is not None:
            day_start = max(day_start, export_lookback)
        if export_cutoff is not None:
            day_end = min(day_end, export_cutoff)
        if day_start >= day_end:
            continue

        for program_num in range(programs_per_day):
            program_start_utc = day_start + timedelta(
                minutes=program_num * opts.duration_minutes
            )
            program_end_utc = program_start_utc + timedelta(minutes=opts.duration_minutes)
            if not programme_overlaps_export_window(
                program_start_utc, program_end_utc, day_start, day_end
            ):
                continue
            programs.append(
                _build_filler_program(
                    program_start_utc,
                    program_end_utc,
                    title,
                    description,
                    opts,
                    sub_title=subtitle,
                    custom_properties_extra=extra,
                )
            )


def generate_fallback_programs(
    channel_id,
    channel_name,
    now,
    num_days,
    program_length_hours,
    fallback_title,
    fallback_description,
    export_lookback=None,
    export_cutoff=None,
):
    title = fallback_title if fallback_title else channel_name
    description = (
        fallback_description
        if fallback_description
        else f"EPG information is currently unavailable for {channel_name}"
    )
    programs = []
    for day in range(num_days):
        day_start = now + timedelta(days=day)
        for hour_offset in range(0, 24, program_length_hours):
            start_time = day_start + timedelta(hours=hour_offset)
            end_time = start_time + timedelta(hours=program_length_hours)
            if export_lookback and end_time <= export_lookback:
                continue
            if export_cutoff and start_time >= export_cutoff:
                continue
            programs.append({
                "channel_id": channel_id,
                "start_time": start_time,
                "end_time": end_time,
                "title": title,
                "description": description,
            })
    return programs


def generate_standard_dummy_programs(
    channel_id,
    channel_name,
    now,
    num_days=1,
    program_length_hours=4,
    export_lookback=None,
    export_cutoff=None,
):
    programs = []
    for day in range(num_days):
        day_start = now + timedelta(days=day)
        for hour_offset in range(0, 24, program_length_hours):
            start_time = day_start + timedelta(hours=hour_offset)
            end_time = start_time + timedelta(hours=program_length_hours)
            if export_lookback and end_time <= export_lookback:
                continue
            if export_cutoff and start_time >= export_cutoff:
                continue
            hour = start_time.hour
            programs.append({
                "channel_id": channel_id,
                "start_time": start_time,
                "end_time": end_time,
                "title": channel_name,
                "description": _standard_dummy_description(channel_name, hour, day),
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
    logger.debug("Generating custom dummy programs for channel: %s", channel_name)

    title_pattern = custom_properties.get('title_pattern', '')
    time_pattern = custom_properties.get('time_pattern', '')
    date_pattern = custom_properties.get('date_pattern', '')
    timezone_value = custom_properties.get('timezone', 'UTC')
    output_timezone_value = custom_properties.get('output_timezone', '')
    program_duration = custom_properties.get('program_duration', 180)
    title_template = custom_properties.get('title_template', '')
    subtitle_template = custom_properties.get('subtitle_template', '')
    description_template = custom_properties.get('description_template', '')
    upcoming_title_template = custom_properties.get('upcoming_title_template', '')
    upcoming_description_template = custom_properties.get('upcoming_description_template', '')
    ended_title_template = custom_properties.get('ended_title_template', '')
    ended_description_template = custom_properties.get('ended_description_template', '')
    channel_logo_url_template = custom_properties.get('channel_logo_url', '')
    program_poster_url_template = custom_properties.get('program_poster_url', '')
    category_string = custom_properties.get('category', '')
    categories = (
        [cat.strip() for cat in category_string.split(',') if cat.strip()]
        if category_string
        else []
    )
    include_date = custom_properties.get('include_date', True)
    include_live = custom_properties.get('include_live', False)
    include_new = custom_properties.get('include_new', False)

    if not title_pattern:
        logger.warning("No title_pattern in custom_properties, falling back to default")
        return None

    try:
        source_tz = pytz.timezone(timezone_value)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning("Unknown timezone: %s, defaulting to UTC", timezone_value)
        source_tz = pytz.utc

    output_tz = None
    if output_timezone_value:
        try:
            output_tz = pytz.timezone(output_timezone_value)
        except pytz.exceptions.UnknownTimeZoneError:
            logger.warning(
                "Unknown output timezone: %s, will use source timezone",
                output_timezone_value,
            )

    title_pattern = _convert_js_named_groups(title_pattern)
    try:
        title_regex = regex.compile(title_pattern)
    except Exception as e:
        logger.error(
            "Invalid title regex pattern after conversion: %s (pattern: %r)",
            e,
            title_pattern,
        )
        return None

    time_regex = None
    if time_pattern:
        time_pattern = _convert_js_named_groups(time_pattern)
        try:
            time_regex = regex.compile(time_pattern)
        except Exception as e:
            logger.warning(
                "Invalid time regex pattern after conversion: %s (pattern: %r)",
                e,
                time_pattern,
            )

    date_regex = None
    if date_pattern:
        date_pattern = _convert_js_named_groups(date_pattern)
        try:
            date_regex = regex.compile(date_pattern)
        except Exception as e:
            logger.warning(
                "Invalid date regex pattern after conversion: %s (pattern: %r)",
                e,
                date_pattern,
            )

    title_match = title_regex.search(channel_name)
    if not title_match:
        logger.debug(
            "Channel name '%s' doesn't match title pattern %r", channel_name, title_pattern
        )
        return None

    groups = title_match.groupdict()
    logger.debug("Title pattern matched '%s'. Groups: %s", channel_name, groups)

    time_info = None
    time_groups = {}
    if time_regex:
        time_match = time_regex.search(channel_name)
        if time_match:
            time_groups = time_match.groupdict()
            try:
                hour = int(time_groups.get('hour'))
                minute_value = time_groups.get('minute')
                minute = int(minute_value) if minute_value is not None else 0
                ampm = time_groups.get('ampm')
                ampm = ampm.lower() if ampm else None
                if ampm in ('am', 'pm'):
                    if ampm == 'pm' and hour != 12:
                        hour += 12
                    elif ampm == 'am' and hour == 12:
                        hour = 0
                elif hour > 23:
                    logger.warning("Invalid 24-hour time: %s. Must be 0-23.", hour)
                    hour = hour % 24
                time_info = {'hour': hour, 'minute': minute}
                logger.debug("Extracted time %02d:%02d from '%s'", hour, minute, channel_name)
            except (ValueError, TypeError) as e:
                logger.warning("Error parsing time from '%s': %s", channel_name, e)

    date_info = None
    date_groups = {}
    if date_regex:
        date_match = date_regex.search(channel_name)
        if date_match:
            date_groups = date_match.groupdict()
            try:
                month_str = date_groups.get('month', '')
                day_str = date_groups.get('day', '')
                year_str = date_groups.get('year', '')
                day = int(day_str) if day_str else now.day
                year = int(year_str) if year_str else now.year
                month = None
                if month_str:
                    if month_str.isdigit():
                        month = int(month_str)
                    else:
                        month_str_lower = month_str.lower()
                        for i, month_name in enumerate(calendar.month_name):
                            if month_name.lower() == month_str_lower:
                                month = i
                                break
                        if month is None:
                            for i, month_abbr in enumerate(calendar.month_abbr):
                                if month_abbr.lower() == month_str_lower:
                                    month = i
                                    break
                if month is None:
                    month = now.month
                if month and 1 <= month <= 12 and 1 <= day <= 31:
                    date_info = {'year': year, 'month': month, 'day': day}
                    logger.debug("Extracted date %s from '%s'", date_info, channel_name)
                else:
                    logger.warning(
                        "Invalid date values parsed from '%s': year=%s month=%s day=%s",
                        channel_name,
                        year,
                        month,
                        day,
                    )
            except (ValueError, TypeError) as e:
                logger.warning("Error parsing date from '%s': %s", channel_name, e)

    all_groups = {**groups, **time_groups, **date_groups}
    _add_normalized_group_aliases(all_groups)

    channel_logo_url = (
        _format_template(channel_logo_url_template, all_groups, url_encode=True)
        if channel_logo_url_template
        else None
    )
    program_poster_url = (
        _format_template(program_poster_url_template, all_groups, url_encode=True)
        if program_poster_url_template
        else None
    )

    if time_info:
        hour_24 = time_info['hour']
        minute = time_info['minute']
        if date_info:
            base_date = datetime(date_info['year'], date_info['month'], date_info['day'])
        else:
            base_date = datetime.now()

        if output_tz:
            temp_date = source_tz.localize(
                base_date.replace(hour=hour_24, minute=minute, second=0, microsecond=0)
            )
            temp_date_output = temp_date.astimezone(output_tz)
            hour_24 = temp_date_output.hour
            minute = temp_date_output.minute
            all_groups['date'] = temp_date_output.strftime('%Y-%m-%d')
            all_groups['month'] = str(temp_date_output.month)
            all_groups['day'] = str(temp_date_output.day)
            all_groups['year'] = str(temp_date_output.year)
        else:
            temp_date_source = source_tz.localize(
                base_date.replace(hour=hour_24, minute=minute, second=0, microsecond=0)
            )
            all_groups['date'] = temp_date_source.strftime('%Y-%m-%d')
            all_groups['month'] = str(temp_date_source.month)
            all_groups['day'] = str(temp_date_source.day)
            all_groups['year'] = str(temp_date_source.year)

        ampm = 'AM' if hour_24 < 12 else 'PM'
        hour_12 = 12 if hour_24 == 0 else (hour_24 - 12 if hour_24 > 12 else hour_24)
        all_groups['starttime24'] = (
            f"{hour_24}:{minute:02d}" if minute > 0 else f"{hour_24:02d}:00"
        )
        all_groups['starttime'] = (
            f"{hour_12}:{minute:02d} {ampm}" if minute > 0 else f"{hour_12} {ampm}"
        )
        all_groups['starttime_long'] = f"{hour_12}:{minute:02d} {ampm}"

        temp_start = datetime.now(source_tz).replace(
            hour=hour_24, minute=minute, second=0, microsecond=0
        )
        temp_end = temp_start + timedelta(minutes=program_duration)
        end_hour_24 = temp_end.hour
        end_minute = temp_end.minute
        end_ampm = 'AM' if end_hour_24 < 12 else 'PM'
        end_hour_12 = (
            12 if end_hour_24 == 0 else (end_hour_24 - 12 if end_hour_24 > 12 else end_hour_24)
        )
        all_groups['endtime24'] = (
            f"{end_hour_24}:{end_minute:02d}" if end_minute > 0 else f"{end_hour_24:02d}:00"
        )
        all_groups['endtime'] = (
            f"{end_hour_12}:{end_minute:02d} {end_ampm}"
            if end_minute > 0
            else f"{end_hour_12} {end_ampm}"
        )
        all_groups['endtime_long'] = f"{end_hour_12}:{end_minute:02d} {end_ampm}"

    labels = _resolve_event_labels(
        channel_name,
        all_groups,
        title_template=title_template,
        subtitle_template=subtitle_template,
        description_template=description_template,
        upcoming_title_template=upcoming_title_template,
        upcoming_description_template=upcoming_description_template,
        ended_title_template=ended_title_template,
        ended_description_template=ended_description_template,
    )
    opts = _FillerOpts(
        channel_id=channel_id,
        duration_minutes=program_duration,
        include_date=include_date,
        source_tz=source_tz,
        program_poster_url=program_poster_url,
        channel_logo_url=channel_logo_url,
        categories=categories,
        include_live=include_live,
        include_new=include_new,
    )

    programs: list[dict] = []
    if date_info and time_info:
        _generate_dated_event_timeline(
            programs,
            now=now,
            num_days=num_days,
            time_info=time_info,
            date_info=date_info,
            source_tz=source_tz,
            labels=labels,
            opts=opts,
            export_lookback=export_lookback,
            export_cutoff=export_cutoff,
        )
    elif time_info:
        _generate_recurring_time_programs(
            programs,
            now=now,
            num_days=num_days,
            time_info=time_info,
            source_tz=source_tz,
            labels=labels,
            opts=opts,
            export_lookback=export_lookback,
            export_cutoff=export_cutoff,
        )
    else:
        _generate_no_time_programs(
            programs,
            now=now,
            num_days=num_days,
            all_groups=all_groups,
            channel_name=channel_name,
            opts=opts,
            export_lookback=export_lookback,
            export_cutoff=export_cutoff,
            title_template=title_template,
            subtitle_template=subtitle_template,
            description_template=description_template,
        )

    logger.debug("Generated %s custom dummy programs for %s", len(programs), channel_name)
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
    now = django_timezone.now().replace(minute=0, second=0, microsecond=0)

    if epg_source and epg_source.source_type == 'dummy' and epg_source.custom_properties:
        custom_programs = generate_custom_dummy_programs(
            channel_id,
            channel_name,
            now,
            num_days,
            epg_source.custom_properties,
            export_lookback=export_lookback,
            export_cutoff=export_cutoff,
        )
        if custom_programs is not None:
            return custom_programs

        custom_props = epg_source.custom_properties
        fallback_title = custom_props.get('fallback_title_template', '').strip()
        fallback_description = custom_props.get('fallback_description_template', '').strip()
        if fallback_title or fallback_description:
            return generate_fallback_programs(
                channel_id,
                channel_name,
                now,
                num_days,
                program_length_hours,
                fallback_title,
                fallback_description,
                export_lookback=export_lookback,
                export_cutoff=export_cutoff,
            )

    return generate_standard_dummy_programs(
        channel_id,
        channel_name,
        now,
        num_days=num_days,
        program_length_hours=program_length_hours,
        export_lookback=export_lookback,
        export_cutoff=export_cutoff,
    )


def _ordered_channel_streams(channel):
    """Return a channel's streams ordered by channelstream join order.

    Reuses a prefetched `streams` cache when the caller supplied one so bulk
    exports do not issue a query per channel.
    """
    prefetched = getattr(channel, '_prefetched_objects_cache', {}).get('streams')
    if prefetched is not None:
        return list(prefetched)
    return list(channel.streams.all().order_by('channelstream__order'))


def resolve_pattern_match_name(channel, fallback_name, custom_props):
    """Name used for custom dummy EPG regex matching (channel or stream title).

    Returns (name, stream_lookup_failed). stream_lookup_failed is True only when
    name_source is 'stream' but the configured index is missing or out of range.
    """
    if custom_props.get('name_source') != 'stream':
        return fallback_name, False
    stream_index = custom_props.get('stream_index', 1) - 1
    streams = _ordered_channel_streams(channel)
    if 0 <= stream_index < len(streams):
        return streams[stream_index].name, False
    return fallback_name, True


def resolve_channel_parse_name(channel, epg_source, *, fallback_name=None):
    """Return the channel or stream title used for custom dummy regex parsing."""
    display_name = (
        fallback_name
        if fallback_name is not None
        else getattr(channel, 'effective_name', channel.name)
    )
    custom_props = epg_source.custom_properties if epg_source else None
    if not custom_props:
        return display_name
    name, stream_lookup_failed = resolve_pattern_match_name(
        channel, display_name, custom_props
    )
    if stream_lookup_failed:
        logger.warning(
            "Stream index %s not found for channel %s, falling back to channel name",
            custom_props.get('stream_index', 1) - 1,
            display_name,
        )
    return name


def dummy_program_to_api_dict(channel, program, *, dummy_tvg_id, program_id_prefix='dummy'):
    """Convert a generated dummy program dict to EPG grid API format."""
    prog_custom = program.get('custom_properties') or {}
    start = program['start_time']
    display_name = getattr(channel, 'effective_name', channel.name)
    return {
        "id": f"{program_id_prefix}-{channel.id}-{start.hour}-{start.minute}",
        "epg": {"tvg_id": dummy_tvg_id, "name": display_name},
        "start_time": start.isoformat(),
        "end_time": program['end_time'].isoformat(),
        "title": program['title'],
        "description": program['description'],
        "tvg_id": dummy_tvg_id,
        "sub_title": program.get('sub_title'),
        "custom_properties": prog_custom if prog_custom else None,
        "season": None,
        "episode": None,
        "is_new": bool(prog_custom.get('new')),
        "is_live": bool(prog_custom.get('live')),
        "is_premiere": False,
        "is_finale": False,
    }
