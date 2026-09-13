# apps/m3u/utils.py
import regex
import threading
import logging
from django.db import models

lock = threading.Lock()
# Dictionary to track usage: {m3u_account_id: current_usage}
active_streams_map = {}
logger = logging.getLogger(__name__)


def convert_js_numbered_backreferences(replacement):
    """Translate JS-style ``$1``/``$2`` backreferences to Python ``\\1``/``\\2``.

    Auto-sync replace patterns are authored in JS regex syntax, but Python's
    regex engines honor backslash backreferences, not ``$1``. The live rename
    and the UI preview must convert identically, so both call this single
    helper and cannot drift apart (otherwise the preview promises an output
    the sync would never produce).
    """
    return regex.sub(r"\$(\d+)", r"\\\1", replacement)


def parse_is_adult(value):
    """Return True when a provider adult flag is 1 or \"1\".

    XC providers send is_adult as an int or string. Invalid values
    (None, \"None\", empty) are treated as non-adult.
    """
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return False


def normalize_stream_url(url):
    """
    Normalize stream URLs for compatibility with FFmpeg.

    Handles VLC-specific syntax like udp://@239.0.0.1:1234 by removing the @ symbol.
    FFmpeg doesn't recognize the @ prefix for multicast addresses.

    Args:
        url (str): The stream URL to normalize

    Returns:
        str: The normalized URL
    """
    if not url:
        return url

    # Handle VLC-style UDP multicast URLs: udp://@239.0.0.1:1234 -> udp://239.0.0.1:1234
    # The @ symbol in VLC means "listen on all interfaces" but FFmpeg doesn't use this syntax
    if url.startswith('udp://@'):
        normalized = url.replace('udp://@', 'udp://', 1)
        logger.debug(f"Normalized VLC-style UDP URL: {url} -> {normalized}")
        return normalized

    # Could add other normalizations here in the future (rtp://@, etc.)
    return url


def increment_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        current_usage += 1
        active_streams_map[account.id] = current_usage
        account.active_streams = current_usage
        account.save(update_fields=['active_streams'])

def decrement_stream_count(account):
    with lock:
        current_usage = active_streams_map.get(account.id, 0)
        if current_usage > 0:
            current_usage -= 1
            if current_usage == 0:
                del active_streams_map[account.id]
            else:
                active_streams_map[account.id] = current_usage
            account.active_streams = current_usage
            account.save(update_fields=['active_streams'])


def calculate_tuner_count(minimum=1, unlimited_default=10):
    """
    Calculate tuner/connection count from active M3U profiles and custom streams.
    This is the centralized function used by both HDHR and XtreamCodes APIs.

    Args:
        minimum (int): Minimum number to return (default: 1)
        unlimited_default (int): Default value when unlimited profiles exist (default: 10)

    Returns:
        int: Calculated tuner/connection count
    """
    try:
        from apps.m3u.models import M3UAccountProfile
        from apps.channels.models import Stream

        # Calculate tuner count from active profiles from active M3U accounts (excluding default "custom Default" profile)
        profiles = M3UAccountProfile.objects.filter(
            is_active=True,
            m3u_account__is_active=True,  # Only include profiles from enabled M3U accounts
        ).exclude(id=1)

        # 1. Check if any profile has unlimited streams (max_streams=0)
        has_unlimited = profiles.filter(max_streams=0).exists()

        # 2. Calculate tuner count from limited profiles
        limited_tuners = 0
        if not has_unlimited:
            limited_tuners = (
                profiles.filter(max_streams__gt=0)
                .aggregate(total=models.Sum("max_streams"))
                .get("total", 0)
                or 0
            )

        # 3. Add custom stream count to tuner count
        custom_stream_count = Stream.objects.filter(is_custom=True).count()
        logger.debug(f"Found {custom_stream_count} custom streams")

        # 4. Calculate final tuner count
        if has_unlimited:
            # If there are unlimited profiles, start with unlimited_default plus custom streams
            tuner_count = unlimited_default + custom_stream_count
        else:
            # Otherwise use the limited profile sum plus custom streams
            tuner_count = limited_tuners + custom_stream_count

        # 5. Ensure minimum number
        tuner_count = max(minimum, tuner_count)

        logger.debug(
            f"Calculated tuner count: {tuner_count} (limited profiles: {limited_tuners}, custom streams: {custom_stream_count}, unlimited: {has_unlimited})"
        )

        return tuner_count

    except Exception as e:
        logger.error(f"Error calculating tuner count: {e}")
        return minimum  # Fallback to minimum value


ALLOWED_M3U_PROFILE_IDS_KEY = "allowed_m3u_profile_ids"


def get_allowed_m3u_profiles(user):
    """Return active allowed profiles by account, or None when unrestricted.

    Tri-state on ``custom_properties.allowed_m3u_profile_ids`` (same shape as
    channel-creation profile targeting):

    - key absent: unrestricted (all profiles)
    - key present with ``[]``: allow none
    - key present with ``[ids]``: only those active profiles
    """
    from apps.m3u.models import M3UAccountProfile

    custom_properties = getattr(user, "custom_properties", None)
    if not isinstance(custom_properties, dict):
        return None

    if ALLOWED_M3U_PROFILE_IDS_KEY not in custom_properties:
        return None

    profile_ids = custom_properties.get(ALLOWED_M3U_PROFILE_IDS_KEY)
    # Stale null (e.g. create payload before key scrub) means unrestricted.
    if profile_ids is None:
        return None
    if not isinstance(profile_ids, list):
        # Malformed value: fail closed (explicit allowlist, nothing usable).
        return {}

    if not profile_ids:
        return {}

    profiles = (
        M3UAccountProfile.objects.select_related("m3u_account__user_agent")
        .filter(
            id__in=profile_ids,
            is_active=True,
            m3u_account__is_active=True,
        )
        .order_by("m3u_account_id", "-is_default", "id")
    )
    profiles_by_account = {}
    for profile in profiles:
        profiles_by_account.setdefault(profile.m3u_account_id, []).append(profile)
    return profiles_by_account


def scrub_allowed_m3u_profile_id(profile_id):
    """Remove ``profile_id`` from every user's allowlist.

    Keeps the key when the list becomes empty so the user stays restricted
    (NONE) instead of becoming unrestricted (ALL).
    """
    from apps.accounts.models import User

    users = User.objects.exclude(custom_properties=None).filter(
        custom_properties__has_key=ALLOWED_M3U_PROFILE_IDS_KEY
    )
    for user in users.iterator():
        custom = user.custom_properties
        if not isinstance(custom, dict):
            continue
        ids = custom.get(ALLOWED_M3U_PROFILE_IDS_KEY)
        if not isinstance(ids, list) or profile_id not in ids:
            continue
        custom[ALLOWED_M3U_PROFILE_IDS_KEY] = [
            item for item in ids if item != profile_id
        ]
        user.custom_properties = custom
        user.save(update_fields=["custom_properties"])
