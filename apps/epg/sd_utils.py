"""
Schedules Direct API helpers: headers, error codes, and rate-limit lockouts.

See https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import timedelta, timezone as dt_timezone

import requests
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.utils import dispatcharr_http_headers

logger = logging.getLogger(__name__)

SD_BASE_URL = 'https://json.schedulesdirect.org/20141201'

# SD JSON error codes we must honor to avoid account blocks.
SD_CODE_INVALID_DEBUG = 2055
SD_CODE_SERVICE_OFFLINE = 3000
SD_CODE_SERVICE_BUSY = 3001
SD_CODE_ACCOUNT_EXPIRED = 4001
SD_CODE_INVALID_PASSWORD_HASH = 4002
SD_CODE_INVALID_USER_OR_PASSWORD = 4003
SD_CODE_ACCOUNT_LOCKED = 4004
SD_CODE_JSON_DISABLED = 4005
SD_CODE_APP_NOT_AUTHORIZED = 4007
SD_CODE_ACCOUNT_INACTIVE = 4008
SD_CODE_TOO_MANY_LOGINS = 4009
SD_CODE_TOO_MANY_UNIQUE_IPS = 4010
SD_CODE_IMAGE_NOT_FOUND = 5000
SD_CODE_MAX_IMAGE_DOWNLOADS = 5002
SD_CODE_MAX_IMAGE_DOWNLOADS_TRIAL = 5003

SD_IMAGE_LIMIT_CODES = frozenset({
    SD_CODE_MAX_IMAGE_DOWNLOADS,
    SD_CODE_MAX_IMAGE_DOWNLOADS_TRIAL,
})

# Soft /token failures: stop and retry later (idle), not a hard account error.
SD_AUTH_SOFT_CODES = frozenset({
    SD_CODE_SERVICE_OFFLINE,
    SD_CODE_SERVICE_BUSY,
})

# Wrong username/password (or hash): clear early when credentials change.
SD_AUTH_CREDENTIAL_LOCKOUT_CODES = frozenset({
    SD_CODE_INVALID_PASSWORD_HASH,
    SD_CODE_INVALID_USER_OR_PASSWORD,
})

# All /token codes we must not hammer. Includes soft codes (shorter cooldown).
SD_AUTH_LOCKOUT_CODES = frozenset({
    SD_CODE_SERVICE_OFFLINE,
    SD_CODE_SERVICE_BUSY,
    SD_CODE_ACCOUNT_EXPIRED,
    SD_CODE_INVALID_PASSWORD_HASH,
    SD_CODE_INVALID_USER_OR_PASSWORD,
    SD_CODE_ACCOUNT_LOCKED,
    SD_CODE_JSON_DISABLED,
    SD_CODE_APP_NOT_AUTHORIZED,
    SD_CODE_ACCOUNT_INACTIVE,
    SD_CODE_TOO_MANY_LOGINS,
    SD_CODE_TOO_MANY_UNIQUE_IPS,
})

SD_AUTH_LOCKOUT_SECONDS = 24 * 3600
SD_AUTH_LOCKOUT_SECONDS_SOFT = 3600
SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK = 15 * 60


def sd_auth_lockout_seconds_for_code(code):
    """Cooldown length for a /token error code."""
    if code == SD_CODE_ACCOUNT_LOCKED:
        return SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK
    if code in SD_AUTH_SOFT_CODES:
        return SD_AUTH_LOCKOUT_SECONDS_SOFT
    return SD_AUTH_LOCKOUT_SECONDS


def sd_auth_lockout_retry_message():
    """Suffix explaining how to clear an auth lockout."""
    return (
        "Not retrying Schedules Direct authentication until the username or "
        "password is updated, or the cooldown expires."
    )


# Shared across uWSGI workers via Django's Redis cache.
_SD_TOKEN_CACHE_PREFIX = 'sd:token:'
# Expire a bit early so we re-auth before SD rejects an almost-expired token.
_SD_TOKEN_CACHE_SKEW_SECONDS = 60
_SD_TOKEN_DEFAULT_TTL_SECONDS = 86400


def sd_token_cache_key(source_id):
    return f'{_SD_TOKEN_CACHE_PREFIX}{source_id}'


def sd_credential_fingerprint(username, password):
    """
    Stable fingerprint of SD credentials for lockout and token-cache matching.

    Used so a persisted auth lockout or cached token clears automatically when
    the user changes username or password.
    """
    raw = f'{(username or "").strip()}\0{(password or "").strip()}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def sd_get_cached_token(source_id, username=None, password=None):
    """
    Return a cached SD token string for this source, or None.

    Requires ``username`` / ``password`` so a cached session is only reused when
    credentials still match (avoids using account A's token after switching to B).
    On Redis failure, returns None so the caller re-authenticates.
    """
    if source_id is None:
        return None
    current_fp = sd_credential_fingerprint(username, password)
    try:
        payload = cache.get(sd_token_cache_key(source_id))
    except Exception as exc:
        logger.warning(
            "SD token cache get failed for source %s (%s); re-authenticating",
            source_id,
            type(exc).__name__,
        )
        return None
    if not isinstance(payload, dict):
        return None
    token = payload.get('token')
    expires = payload.get('expires')
    if not token or not isinstance(expires, (int, float)):
        return None
    if payload.get('fp') != current_fp:
        sd_clear_cached_token(source_id)
        return None
    if time.time() >= float(expires) - _SD_TOKEN_CACHE_SKEW_SECONDS:
        return None
    return token


def sd_set_cached_token(source_id, token, expires=None, username=None, password=None):
    """
    Cache an SD token for this source until near tokenExpires.

    ``expires`` is a UNIX epoch seconds value from SD's tokenExpires field.
    Stores a credential fingerprint so callers must still match to reuse it.
    """
    if source_id is None or not token:
        return False
    now = time.time()
    if expires is None:
        expires = now + _SD_TOKEN_DEFAULT_TTL_SECONDS
    try:
        expires = float(expires)
    except (TypeError, ValueError):
        expires = now + _SD_TOKEN_DEFAULT_TTL_SECONDS
    ttl = int(expires - now - _SD_TOKEN_CACHE_SKEW_SECONDS)
    if ttl < 1:
        return False
    try:
        cache.set(
            sd_token_cache_key(source_id),
            {
                'token': token,
                'expires': expires,
                'fp': sd_credential_fingerprint(username, password),
            },
            timeout=ttl,
        )
        return True
    except Exception as exc:
        logger.warning(
            "SD token cache set failed for source %s (%s)",
            source_id,
            type(exc).__name__,
        )
        return False


def sd_clear_cached_token(source_id):
    """Drop a cached SD token (e.g. after 401/403 from an image request)."""
    if source_id is None:
        return False
    try:
        cache.delete(sd_token_cache_key(source_id))
        return True
    except Exception as exc:
        logger.warning(
            "SD token cache delete failed for source %s (%s)",
            source_id,
            type(exc).__name__,
        )
        return False


def sd_auth_failure_message(code, sd_message=None):
    """Human-readable message for a Schedules Direct /token error code."""
    if code == SD_CODE_SERVICE_OFFLINE:
        return (
            "Schedules Direct is offline for maintenance. "
            "Do not retry for at least 1 hour."
        )
    if code == SD_CODE_SERVICE_BUSY:
        return "Schedules Direct is busy. Stop requesting and retry later."
    if code == SD_CODE_ACCOUNT_EXPIRED:
        return (
            "Schedules Direct: account has expired. Please renew your "
            "subscription at schedulesdirect.org."
        )
    if code == SD_CODE_INVALID_PASSWORD_HASH:
        return (
            "Schedules Direct: invalid password hash. Check that credentials "
            "are stored correctly."
        )
    if code == SD_CODE_INVALID_USER_OR_PASSWORD:
        return "Schedules Direct: invalid username or password."
    if code == SD_CODE_ACCOUNT_LOCKED:
        return (
            "Schedules Direct: account locked due to too many failed login "
            "attempts. Try again in 15 minutes."
        )
    if code == SD_CODE_JSON_DISABLED:
        return (
            "Schedules Direct: JSON API access is disabled for this account. "
            "Contact Schedules Direct support."
        )
    if code == SD_CODE_APP_NOT_AUTHORIZED:
        return (
            "Schedules Direct: this application is not authorized. Please "
            "contact the Dispatcharr maintainers."
        )
    if code == SD_CODE_ACCOUNT_INACTIVE:
        return (
            "Schedules Direct: account is inactive. Please log in to "
            "schedulesdirect.org to reactivate."
        )
    if code == SD_CODE_TOO_MANY_LOGINS:
        return (
            "Schedules Direct: too many login attempts in 24 hours. Token is "
            "valid for 24 hours. Check for misconfiguration."
        )
    if code == SD_CODE_TOO_MANY_UNIQUE_IPS:
        return (
            "Schedules Direct: too many unique IP addresses in 24 hours. "
            "Avoid VPNs or multiple locations, or contact SD support to raise "
            "the limit."
        )
    if sd_message:
        return f"Schedules Direct authentication failed (code {code}): {sd_message}"
    return f"Schedules Direct authentication failed (code {code})."


def sd_token_response_code(auth_data):
    """Return integer SD ``code`` from a /token JSON body, or 0."""
    if not isinstance(auth_data, dict):
        return 0
    code = auth_data.get('code', 0)
    return code if isinstance(code, int) else 0


def sd_auth_lockout_active(source, username=None, password=None):
    """
    Return (active, reason, code) for a persisted auth lockout.

    Cleared when username/password changed, or sd_auth_lockout_until has passed.
    """
    if source is None:
        return False, None, None

    cp = source.custom_properties or {}
    if not cp.get('sd_auth_lockout'):
        return False, None, None

    until_str = cp.get('sd_auth_lockout_until')
    until = parse_datetime(until_str) if until_str else None
    if until is None or timezone.now() >= until:
        sd_clear_auth_lockout(source)
        return False, None, None

    if username is None:
        username = source.username
    if password is None:
        password = source.password

    stored_fp = cp.get('sd_auth_lockout_credential_fp')
    current_fp = sd_credential_fingerprint(username, password)
    if not stored_fp or stored_fp != current_fp:
        sd_clear_auth_lockout(source)
        return False, None, None

    code = cp.get('sd_auth_lockout_code')
    reason = cp.get('sd_auth_lockout_reason') or (
        'Schedules Direct authentication is temporarily blocked.'
    )
    return True, reason, code if isinstance(code, int) else None


def sd_save_auth_lockout(source, code, username=None, password=None, reason=None):
    """
    Persist an auth lockout so we stop calling /token for a cooldown period.

    Duration depends on the code (15m for 4004, 1h for offline/busy, else 24h).
    Cleared early if username/password change.
    """
    if source is None:
        return
    if code not in SD_AUTH_LOCKOUT_CODES:
        return

    if username is None:
        username = source.username
    if password is None:
        password = source.password

    if reason is None:
        reason = sd_auth_failure_message(code)

    seconds = sd_auth_lockout_seconds_for_code(code)
    until = timezone.now() + timedelta(seconds=seconds)
    cp = dict(source.custom_properties or {})
    cp['sd_auth_lockout'] = True
    cp['sd_auth_lockout_code'] = code
    cp['sd_auth_lockout_reason'] = reason
    cp['sd_auth_lockout_until'] = until.isoformat()
    cp['sd_auth_lockout_credential_fp'] = sd_credential_fingerprint(
        username, password
    )
    source.custom_properties = cp
    source.save(update_fields=['custom_properties'])
    sd_clear_cached_token(source.id)
    logger.warning(
        "SD source %s: auth lockout (code %s). Not calling /token until "
        "username or password changes, or after %s.",
        source.id,
        code,
        until.isoformat(),
    )


def sd_clear_auth_lockout(source):
    """Clear a persisted auth lockout (success, credentials changed, or expired)."""
    if source is None:
        return
    cp = dict(source.custom_properties or {})
    changed = False
    for key in (
        'sd_auth_lockout',
        'sd_auth_lockout_code',
        'sd_auth_lockout_reason',
        'sd_auth_lockout_until',
        'sd_auth_lockout_credential_fp',
    ):
        if key in cp:
            cp.pop(key, None)
            changed = True
    if changed:
        source.custom_properties = cp
        source.save(update_fields=['custom_properties'])


@dataclass(frozen=True)
class SDTokenAuthResult:
    """Outcome of POST /token (or a short-circuit from a persisted lockout)."""

    ok: bool
    token: str | None = None
    token_expires: float | None = None
    code: int | None = None
    message: str = ''
    soft: bool = False
    debug_rejected: bool = False
    lockout: bool = False


_DEBUG_REJECTED_MESSAGE = (
    "Schedules Direct rejected the debug routing header (code 2055). "
    "Extra Schedules Direct Debugging has been turned off. Retry without it "
    "unless Schedules Direct support asked you to enable it."
)


def sd_obtain_token(source, username=None, password=None, *, timeout=30):
    """
    Return a Schedules Direct session token, reusing a cached one when valid.

    Shared by refresh, lineup/form auth, and the poster proxy. Checks Redis for
    an unexpired token bound to the current credentials before POSTing /token.
    Honors persisted lockouts, reads JSON ``code`` before HTTP status, and
    persists cooldowns for codes that must not be retried until cleared.
    """
    if source is None:
        return SDTokenAuthResult(
            ok=False,
            message='Schedules Direct source is required.',
        )

    if username is None:
        username = (source.username or '').strip()
    else:
        username = (username or '').strip()
    if password is None:
        password = (source.password or '').strip()
    else:
        password = (password or '').strip()

    if not username or not password:
        return SDTokenAuthResult(
            ok=False,
            message='Username and password are required.',
        )

    active, reason, lockout_code = sd_auth_lockout_active(
        source, username, password
    )
    if active:
        msg = f"{reason} {sd_auth_lockout_retry_message()}"
        return SDTokenAuthResult(
            ok=False,
            code=lockout_code,
            message=msg,
            soft=lockout_code in SD_AUTH_SOFT_CODES if lockout_code else False,
            lockout=True,
        )

    cached = sd_get_cached_token(source.id, username=username, password=password)
    if cached:
        return SDTokenAuthResult(
            ok=True,
            token=cached,
            code=0,
        )

    sha1_password = hashlib.sha1(password.encode('utf-8')).hexdigest()
    try:
        response = requests.post(
            f"{SD_BASE_URL}/token",
            json={'username': username, 'password': sha1_password},
            headers=sd_headers_for_source(source),
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        return SDTokenAuthResult(
            ok=False,
            message=f'Network error authenticating with Schedules Direct: {exc}',
        )

    try:
        auth_data = response.json()
    except ValueError:
        auth_data = {}

    if sd_handle_2055(source, auth_data):
        return SDTokenAuthResult(
            ok=False,
            code=SD_CODE_INVALID_DEBUG,
            message=_DEBUG_REJECTED_MESSAGE,
            debug_rejected=True,
        )

    # Honor JSON ``code`` before raise_for_status. SD error semantics are in
    # the body; HTTP status alone is not reliable for auth failures.
    auth_code = sd_token_response_code(auth_data)
    if auth_code != 0:
        msg = sd_auth_failure_message(
            auth_code, auth_data.get('message', 'Unknown error')
        )
        soft = auth_code in SD_AUTH_SOFT_CODES
        locked = False
        if auth_code in SD_AUTH_LOCKOUT_CODES:
            sd_save_auth_lockout(
                source, auth_code, username, password, reason=msg
            )
            msg = f"{msg} {sd_auth_lockout_retry_message()}"
            locked = True
        return SDTokenAuthResult(
            ok=False,
            code=auth_code,
            message=msg,
            soft=soft,
            lockout=locked,
        )

    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return SDTokenAuthResult(
            ok=False,
            message=f'Network error authenticating with Schedules Direct: {exc}',
        )

    token = auth_data.get('token') if isinstance(auth_data, dict) else None
    if not token:
        return SDTokenAuthResult(
            ok=False,
            message='Schedules Direct returned no token.',
        )

    sd_clear_auth_lockout(source)
    expires = None
    if isinstance(auth_data, dict):
        expires = auth_data.get('tokenExpires')
    if not isinstance(expires, (int, float)):
        expires = time.time() + _SD_TOKEN_DEFAULT_TTL_SECONDS
    expires = float(expires)
    sd_set_cached_token(
        source.id, token, expires, username=username, password=password
    )
    return SDTokenAuthResult(
        ok=True,
        token=token,
        token_expires=expires,
        code=0,
    )


def sd_authorized_request(
    method,
    url,
    *,
    source,
    token,
    username=None,
    password=None,
    timeout=30,
    content_type='application/json',
    **kwargs,
):
    """
    Perform an authenticated Schedules Direct HTTP request.

    On HTTP 401/403 (SD documents TOKEN_EXPIRED as 403 + code 4006), clears the
    Redis token cache, obtains a fresh token, and retries the request once.

    Returns ``(response, token)`` where ``token`` may have been refreshed.
    """
    method_upper = (method or 'GET').upper()
    http_fn = {
        'GET': requests.get,
        'POST': requests.post,
        'PUT': requests.put,
        'DELETE': requests.delete,
        'HEAD': requests.head,
        'PATCH': requests.patch,
    }.get(method_upper)

    def _once(current_token):
        headers = sd_headers_for_source(
            source,
            token=current_token,
            content_type=content_type,
        )
        if http_fn is not None:
            return http_fn(url, headers=headers, timeout=timeout, **kwargs)
        return requests.request(
            method_upper, url, headers=headers, timeout=timeout, **kwargs
        )

    response = _once(token)
    if response.status_code not in (401, 403):
        return response, token

    logger.warning(
        "SD source %s: %s %s returned %s; clearing cached token and retrying once",
        getattr(source, 'id', None),
        method_upper,
        url,
        response.status_code,
    )
    sd_clear_cached_token(getattr(source, 'id', None))
    auth_timeout = timeout if isinstance(timeout, (int, float)) else 30
    auth = sd_obtain_token(
        source,
        username=username,
        password=password,
        timeout=min(int(auth_timeout), 30) if auth_timeout else 30,
    )
    if not auth.ok or not auth.token:
        return response, token

    retry_response = _once(auth.token)
    return retry_response, auth.token


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
