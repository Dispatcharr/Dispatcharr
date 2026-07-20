"""
Schedules Direct API helpers: headers, error codes, and rate-limit lockouts.

See https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.utils import dispatcharr_http_headers

logger = logging.getLogger(__name__)

# SD JSON error codes we must honor to avoid account blocks.
SD_CODE_INVALID_DEBUG = 2055
SD_CODE_IMAGE_NOT_FOUND = 5000
SD_CODE_MAX_IMAGE_DOWNLOADS = 5002
SD_CODE_MAX_IMAGE_DOWNLOADS_TRIAL = 5003

SD_IMAGE_LIMIT_CODES = frozenset({
    SD_CODE_MAX_IMAGE_DOWNLOADS,
    SD_CODE_MAX_IMAGE_DOWNLOADS_TRIAL,
})


def sd_next_midnight_utc():
    """Return the next Schedules Direct counter reset (00:00Z)."""
    now = timezone.now()
    return (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
        tzinfo=dt_timezone.utc,
    )


def sd_headers_for_source(source, *, token=None, content_type='application/json'):
    """
    Build outbound headers for Schedules Direct requests for this source.

    When Extra Schedules Direct Debugging is enabled, adds RouteTo: debug so the
    SD load balancer can steer traffic to their debug server (support-coordinated).
    """
    cp = source.custom_properties or {} if source is not None else {}
    route_to = 'debug' if cp.get('sd_extra_debugging') else None
    return dispatcharr_http_headers(
        token=token,
        content_type=content_type,
        route_to=route_to,
    )


def sd_disable_extra_debugging(source):
    """Clear the user-facing debug toggle after SD returns code 2055."""
    if source is None:
        return False
    cp = dict(source.custom_properties or {})
    if not cp.get('sd_extra_debugging'):
        return False
    cp['sd_extra_debugging'] = False
    source.custom_properties = cp
    source.save(update_fields=['custom_properties'])
    logger.warning(
        "SD source %s: received code 2055 (unexpected debug connection). "
        "Disabled Extra Schedules Direct Debugging.",
        source.id,
    )
    return True


def sd_handle_2055(source, data):
    """
    If data is an SD JSON error with code 2055, disable debug routing.

    Returns True when 2055 was handled.
    """
    if not isinstance(data, dict):
        return False
    if data.get('code') != SD_CODE_INVALID_DEBUG:
        return False
    sd_disable_extra_debugging(source)
    return True


def sd_parse_response_payload(response):
    """Return (code, data_dict_or_None) for an SD HTTP response body."""
    if response is None:
        return None, None

    content_type = (response.headers.get('Content-Type') or '').lower()
    body = response.content or b''
    looks_json = (
        'json' in content_type
        or body.lstrip()[:1] in (b'{', b'[')
    )
    if not looks_json:
        return None, None

    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        return None, None

    if not isinstance(data, dict):
        return None, None
    code = data.get('code')
    return (code if isinstance(code, int) else None), data


def sd_image_limit_active(source):
    """
    Return (active: bool, reason: str|None) for a persisted image download lockout.

    Clears the lockout automatically once the next midnight UTC has passed.
    """
    if source is None:
        return False, None

    cp = source.custom_properties or {}
    if not cp.get('sd_image_limit_hit'):
        return False, None

    reset_at_str = cp.get('sd_image_limit_reset_at')
    reset_at = parse_datetime(reset_at_str) if reset_at_str else None
    if reset_at and timezone.now() >= reset_at:
        sd_clear_image_limit_lockout(source)
        return False, None

    reason = cp.get('sd_image_limit_reason') or (
        'Daily image download limit reached'
    )
    return True, reason


def sd_save_image_limit_lockout(source, code):
    """
    Persist a source-wide image download lockout until next 00:00Z.

    Used for SD codes 5002 (subscriber) and 5003 (trial).
    """
    if source is None:
        return

    reset_at = sd_next_midnight_utc()
    reason = (
        f'Daily image download limit reached (SD error {code})'
        if code
        else 'Daily image download limit reached'
    )
    cp = dict(source.custom_properties or {})
    cp['sd_image_limit_hit'] = True
    cp['sd_image_limit_reset_at'] = reset_at.isoformat()
    cp['sd_image_limit_reason'] = reason
    source.custom_properties = cp
    source.save(update_fields=['custom_properties'])
    logger.warning(
        "SD source %s: image download limit (code %s). Lockout until %s.",
        source.id,
        code,
        reset_at.isoformat(),
    )


def sd_clear_image_limit_lockout(source):
    """Clear a persisted image download lockout after midnight UTC."""
    if source is None:
        return
    cp = dict(source.custom_properties or {})
    changed = False
    for key in (
        'sd_image_limit_hit',
        'sd_image_limit_reset_at',
        'sd_image_limit_reason',
    ):
        if key in cp:
            cp.pop(key, None)
            changed = True
    if changed:
        source.custom_properties = cp
        source.save(update_fields=['custom_properties'])


def sd_mark_icon_missing(program):
    """
    Clear a bad image URI so we never re-request it (SD code 5000).

    Continues requesting the same missing URI can accumulate toward code 5004
    and get the account blocked.
    """
    if program is None:
        return
    cp = dict(program.custom_properties or {})
    if 'sd_icon' not in cp and cp.get('sd_icon_missing'):
        return
    cp.pop('sd_icon', None)
    cp['sd_icon_missing'] = True
    program.custom_properties = cp
    program.save(update_fields=['custom_properties'])
    logger.info(
        "SD program %s: IMAGE_NOT_FOUND (5000). Cleared sd_icon to avoid retries.",
        program.id,
    )
